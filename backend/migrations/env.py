"""Alembic 迁移运行环境（FayeLong 后端）。

目标库解析（本文件最关键的部分）
================================
两个结构性约束决定了这里必须做「显式注入」：

1. `app/core/config.py` 里的路径全是**模块级常量**（由 `__file__` 推导），
   **不读** `FAYELONG_*` 环境变量 —— 所以「设个环境变量让 alembic 换库」
   这条路根本不通。
2. `app/db.py` 在 **import 时**就 `create_engine(DB_PATH)` 并绑定；而
   `models/entities.py` 通过 `from app.db import Base` 导入它，因此「注册模型」
   必然连带 import `app.db`。

所幸 `create_engine()` 只构造 Engine、**不建立连接**，所以 import `app.db`
不会写真实库。但为了安全，本文件**从不复用** `app.db.engine`：所有 DDL 都落在
下面解析出的目标库上，优先级为

1. ``-x db_path=<路径>``（命令行属性；编程式调用时可用
   ``Config.attributes["x"] = {"db_path": ...}``，见 ``tests/test_migrations.py``）
2. ``app.core.config.DB_PATH``（默认，即项目根 ``data/app.db``）

离线模式（``alembic upgrade head --sql``）只把 SQL 打到 stdout，不连库。

已知坑（给 P3-2 / P4-3 的接手人，务必先读）
============================================
**老库上的 ``--autogenerate`` 会产出假的外键 diff。**

老库的 ``media.category_id`` 是历史上用 ``ALTER TABLE ADD COLUMN ... REFERENCES
categories(id) ON DELETE SET NULL`` 补出来的「列级外键」。SQLite 的反射对这类
列级约束会**丢掉 ondelete 信息**（``Inspector.get_foreign_keys()`` 返回
``options={}``），于是 autogenerate 会报一对假的
``remove_fk (category_id) / add_fk (category_id)``。

对策（按推荐度）：
1. ``alembic revision --autogenerate`` **一律针对「空库 + upgrade head」生成的
   库**（那种库里外键是表级带名约束，反射完整，``alembic check`` 报 0 差异）；
2. 若必须在老库上生成，手工删掉那对 ``remove_fk`` / ``add_fk`` 噪音；
3. 另有一个**真实**差异会一直被报出来：``sentences.marks`` 老库可空、模型
   要求 NOT NULL（详见 ``versions/0001_baseline.py`` 的 docstring），属既定取舍。

⚠️ **不要**图省事用 ``include_object`` 把 ``media.category_id`` 的假 FK diff 过滤掉。
理由：``include_object`` 是按对象类型一刀切，屏蔽外键比较会**静默阉割未来所有真实
外键退化检测**（比如有人漏了 ``ondelete``、或把 CASCADE 改成 NO ACTION，都没人发现）。
正解是将来另起一版迁移，用 batch 模式把老库那条「列级内联 REFERENCES」重建成
「表级命名 FK」，让反射能读到 ``ondelete``；那一版属 P3-2 之后的工作，别在本阶段
用过滤器掩盖。
"""

from __future__ import annotations

import logging
import sys
from logging.config import fileConfig
from pathlib import Path
from typing import Any

# 让 `alembic` 从**任意 cwd** 都能 import 到 `app` 包。
# alembic.ini 的 `prepend_sys_path = .` 是 **cwd 相对**的：在仓库根执行
# `python -m alembic ...` 会 ModuleNotFoundError: No module named 'app'。
# 按 `__file__` 推导 backend/ 并插到 sys.path 最前面，彻底摆脱 cwd 依赖。
_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from alembic import context  # noqa: E402  —— 必须在 sys.path 兜底之后
from sqlalchemy import create_engine, pool  # noqa: E402

from app import models  # noqa: E402,F401  —— 确保 9 张表全部注册到 Base.metadata
from app.core import config as app_config  # noqa: E402
from app.db import Base  # noqa: E402

#: Alembic 的运行时配置（由 alembic.ini + 命令行共同构造）。
config = context.config

#: 目标元数据：与 ORM 模型（9 张表）严格同源，避免手抄 schema。
target_metadata = Base.metadata

#: 本文件的日志器（`alembic` 的子级，CLI 下由 alembic.ini 配成 INFO 输出）。
logger = logging.getLogger("alembic.env")


def _configure_logging() -> None:
    """只在**真实 CLI 调用**时接管日志配置，pytest 内一律不碰。

    为什么需要判据：``logging.config.fileConfig()`` 会清空 root handlers，
    因而会顶掉宿主的日志设施（pytest 的 caplog、应用的 app.core.logging）。
    迁移脚本同样会在 pytest 里被编程式调用，所以这里用「进程里是否已加载
    pytest 模块」作为判据 —— pytest 一定先于迁移被 import。

    Notes:
        副作用是 CLI 下会正常打印 ``INFO [alembic.runtime.migration] ...``，
        不再「静默成功」。没日志的迁移命令是危险的：出错与成功看起来一样。
    """
    if config.config_file_name is None or "pytest" in sys.modules:
        return
    try:
        fileConfig(config.config_file_name, disable_existing_loggers=False)
    except (KeyError, ValueError):
        # ini 里没有 logging 段（用户自备配置）时忽略，不影响迁移本身。
        pass


def _parse_x_pairs(raw: Any) -> dict[str, str]:
    """把 ``-x`` 的原始值统一成 ``{key: value}``。

    Args:
        raw: 可能是 ``None``、``"k=v"``、``["k=v", ...]`` 或 ``{"k": "v"}``。

    Returns:
        键值对字典；不带 ``=`` 的项按 alembic 自身语义记为空串值。
    """
    pairs: dict[str, str] = {}

    if raw is None:
        return pairs
    if isinstance(raw, dict):
        for key, value in raw.items():
            pairs[str(key)] = "" if value is None else str(value)
        return pairs
    if isinstance(raw, str):
        raw = [raw]

    for item in raw:
        text = str(item)
        key, separator, value = text.partition("=")
        if not separator:
            pairs[text.strip()] = ""
            continue
        pairs[key.strip()] = value.strip()
    return pairs


def get_x_arguments() -> dict[str, str]:
    """收集 ``-x`` 属性（等价于 ``context.get_x_argument(as_dictionary=True)``）。

    在 alembic 自带行为之外，额外兼容 ``config.attributes["x"]``：用
    ``alembic.command.upgrade(cfg, "head")`` 编程式调用时没有 argparse 解析出的
    ``-x``，宿主只能通过 attributes 传参。同名键以命令行 ``-x`` 为准。

    Returns:
        ``{属性名: 属性值}``，无属性时为空字典。
    """
    merged: dict[str, str] = {}

    attributes = getattr(config, "attributes", None) or {}
    merged.update(_parse_x_pairs(attributes.get("x")))

    cmd_opts = getattr(config, "cmd_opts", None)
    if cmd_opts is not None:
        merged.update(_parse_x_pairs(getattr(cmd_opts, "x", None)))

    # 兜底：adopt alembic 自己解析出的结果（命令行场景即 cmd_opts.x）。
    try:
        merged.update(context.get_x_argument(as_dictionary=True))
    except (AttributeError, TypeError):
        # cmd_opts 形态异常（例如被注入了一个没有 .x 的对象）时忽略。
        pass
    return merged


def _resolve_database_target() -> tuple[Path, str]:
    """解析目标库：``-x db_path=`` 优先，其次 ``app.core.config.DB_PATH``。

    Returns:
        ``(绝对路径, SQLAlchemy URL)``。

    Notes:
        路径先 ``resolve()`` 绝对化再 ``as_posix()`` 统一成正斜杠 —— Windows
        反斜杠在 URL 里的处理容易踩歧义（``sqlite:///C:\\...`` 在不同调用栈下
        解析结果不一致），正斜杠是最稳的形式。
    """
    x_args = get_x_arguments()
    raw_path = x_args.get("db_path") or str(app_config.DB_PATH)
    resolved = Path(raw_path).expanduser().resolve()
    return resolved, f"sqlite:///{resolved.as_posix()}"


def _announce_target(path: Path, url: str) -> None:
    """把「这次迁移到底打到哪个库」明确喊出来。

    没有这条日志时，迁移是「静默成功」的：路径写错（例如 Git Bash 的
    ``/tmp/x.db`` 被 Python 解析成 ``D:\\tmp\\x.db``）会**悄悄新建一个空库**并
    迁移成功，操作者却以为动的是副本。日志 + 文件不存在告警能立刻暴露这种误判。
    """
    logger.info("迁移目标库：%s", url)
    if not path.exists():
        logger.warning("目标库文件不存在，将按基线新建空库：%s", path)


def _configure_kwargs() -> dict[str, Any]:
    """online / offline 共用的 ``context.configure`` 参数。"""
    return {
        # 关键：复用同一个 metadata 对象
        "target_metadata": target_metadata,
        # SQLite 不支持多数 ALTER TABLE，批处理模式用
        # 「建新表 → 拷数据 → 删旧表 → 改名」实现后续迁移（P3-2 / P4-3）需要的
        # 改列操作。基线本身不需要它，但从第一次迁移起就开，避免以后不一致。
        "render_as_batch": True,
        # 列类型变更也要被 autogenerate 检测出来（否则 VARCHAR 长度变化会被吞掉）。
        "compare_type": True,
    }


def run_migrations_offline() -> None:
    """离线模式（``--sql``）：只产出 SQL 脚本，**不连接数据库**。"""
    path, url = _resolve_database_target()
    # 写回配置，供脚本/工具读取；set_main_option 不建立任何连接。
    config.set_main_option("sqlalchemy.url", url)
    _announce_target(path, url)

    context.configure(
        url=url,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **_configure_kwargs(),
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式：连接目标库并执行迁移。"""
    path, url = _resolve_database_target()
    config.set_main_option("sqlalchemy.url", url)
    _announce_target(path, url)

    # NullPool：迁移是一次性短任务，没必要缓存连接；同时保证连接在 finally
    # 里一定被释放，避免 Windows 上文件被占用（后续 shutil / 删除会失败）。
    connectable = create_engine(url, poolclass=pool.NullPool, future=True)
    try:
        with connectable.connect() as connection:
            context.configure(connection=connection, **_configure_kwargs())
            with context.begin_transaction():
                context.run_migrations()
    finally:
        connectable.dispose()


_configure_logging()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

"""pytest 基础设施：把运行时数据目录整体重定向到临时目录，杜绝触碰真实 data/。

核心难点
--------
`app/core/config.py` 里的 `DATA_DIR / MEDIA_DIR / INBOX_DIR / LIBRARY_DIR /
MODELS_DIR / DICT_DIR / LOG_DIR / DB_PATH` 全是**模块级常量**（由 `__file__`
推导），**不读 `FAYELONG_*` 环境变量**（`Settings` 只把 host/port/model 等做成
可配置）。更麻烦的是 `app/db.py` 在 **import 时就**执行
`create_engine(f"sqlite:///{DB_PATH}")` 并绑定。

因此「覆写 FAYELONG_* 指向 tmp」根本不会重定向数据库。唯一可靠的做法是
**在 import 任何 `app.db` / `app.main` 之前**，把 `app.core.config` 模块对象上
的上述常量**打补丁**重指向临时根目录。由于 `db.py` / `api/*.py` / `services/*.py`
都是 `from app.core.config import <CONSTANT>` 的**一次性绑定**，只要补丁先于它们的
首次 import，下游拿到的就是临时路径。

⚠️ 关于 `tmp_path_factory`：它是 fixture，只有**收集期之后**才可用，而 `app.db`
在**收集期**就已绑定数据库。所以临时根目录必须在 conftest **模块顶层**（import 时）
就创建好——这里用 `tempfile.mkdtemp`，而非 `tmp_path_factory`。
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# 0) 保证 backend/ 在 sys.path 上（pytest.ini 已设 pythonpath=.，此处兜底）。
# ---------------------------------------------------------------------------
_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

# ---------------------------------------------------------------------------
# 1) 【关键】import app.db / app.main 之前，先给 app.core.config 打补丁。
#    此处只 import app.core.config（它本身不 import db），是安全的。
# ---------------------------------------------------------------------------
import app.core.config as config  # noqa: E402  （必须最先，且仅此一个 app 子模块）

#: 需要重定向的目录/文件常量名。
_REDIRECT_DIR_NAMES = (
    "DATA_DIR",
    "MEDIA_DIR",
    "INBOX_DIR",
    "LIBRARY_DIR",
    "MODELS_DIR",
    "DICT_DIR",
    "LOG_DIR",
)

#: 记录真实 data 根，用于护栏断言（补丁前先算出来）。
_REAL_DATA_DIR = (config.ROOT_DIR / "data").resolve()


def _redirect_runtime_dirs(tmp_root: Path) -> None:
    """把 config 模块上的运行时路径常量全部重指向 `tmp_root` 之下。"""
    data_dir = tmp_root / "data"
    mapping = {
        "DATA_DIR": data_dir,
        "MEDIA_DIR": data_dir / "media",
        "INBOX_DIR": data_dir / "media" / "audio",
        "LIBRARY_DIR": data_dir / "media" / "library",
        "MODELS_DIR": data_dir / "models",
        "DICT_DIR": data_dir / "dict",
        "LOG_DIR": data_dir / "logs",
        "DB_PATH": data_dir / "app.db",
    }
    for name, path in mapping.items():
        setattr(config, name, path)

    # ensure_dirs() 会读取被补丁后的常量建目录；这里先建好，保证 db.py 导入时
    # 目录已存在（虽 SQLite 会自建文件，但 media/library 等目录需存在）。
    for name in _REDIRECT_DIR_NAMES:
        getattr(config, name).mkdir(parents=True, exist_ok=True)
    # DB_PATH 的父目录（即 DATA_DIR）随 DATA_DIR 一起建好即可。
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)


#: 会话级临时根目录。在模块顶层创建 —— 必须早于任何 app.db 导入。
_TMP_ROOT = Path(tempfile.mkdtemp(prefix="fayelong-pytest-"))
_redirect_runtime_dirs(_TMP_ROOT)

# ---------------------------------------------------------------------------
# 1.5) 【关键】测试里绝不能让 lifespan 起后台执行线程。
#      `main.lifespan` 会按 `FAYELONG_WEB_INPROC_WORKER` 决定是否在 web 进程内
#      起一个降级 worker。若测试里是 `auto`/`on`，session 级 TestClient 会带起一个
#      真线程池去抢 `jobs` 表里的任务 —— 用例之间会互相偷任务、变成随机失败
#      （而且失败现场还取决于哪个用例先跑）。因此强制 `off`。
#      ⚠️ 这一行必须在 `import app.main` **之前**：`maybe_start_inproc_worker()`
#      读的是 `settings.web_inproc_worker`，但更重要的是别让任何模块级代码提前
#      初始化执行器。
# ---------------------------------------------------------------------------
config.settings.web_inproc_worker = "off"


# ---------------------------------------------------------------------------
# 2) 现在可以安全 import app.db / app.main —— 它们会绑定到临时库。
# ---------------------------------------------------------------------------
from app.db import init_db  # noqa: E402
from app.main import app as fastapi_app  # noqa: E402


# ---------------------------------------------------------------------------
# 3) 护栏：assert 数据库确实指向临时目录，而非真实 data/。
#    若将来有人重构掉重定向逻辑，这里会立即 fail，阻止测试静默写进真实库。
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session", autouse=True)
def _guard_tmp_database() -> None:
    """开跑前断言 DB_PATH 不在真实 data/ 目录下。"""
    db_path = Path(config.DB_PATH).resolve()
    try:
        db_path.relative_to(_REAL_DATA_DIR)
    except ValueError:
        pass  # 不在真实 data/ 下 —— 正常
    else:
        raise AssertionError(
            "测试数据库危险地指向了真实数据目录！\n"
            f"  DB_PATH     = {db_path}\n"
            f"  真实 data/  = {_REAL_DATA_DIR}\n"
            "conftest 的数据目录重定向逻辑可能被破坏，已中止测试。"
        )

    # 进一步：必须落在本次会话的临时根之下。
    try:
        db_path.relative_to(_TMP_ROOT.resolve())
    except ValueError as exc:
        raise AssertionError(
            f"测试数据库未落在临时根目录下：DB_PATH={db_path}, 临时根={_TMP_ROOT}"
        ) from exc


@pytest.fixture(scope="session")
def tmp_runtime_root() -> Path:
    """暴露本次会话使用的临时运行时根目录（供用例读取临时媒体/词典路径）。"""
    return _TMP_ROOT


@pytest.fixture(scope="session")
def app_client():
    """Session 级 `TestClient`（以 context manager 触发 lifespan）。

    lifespan 会执行 `ensure_dirs()` + `init_db()` + `requeue_unfinished()`——
    由于 conftest 已在 import 前完成重定向，这些操作全部作用于**临时库**。
    """
    from fastapi.testclient import TestClient

    with TestClient(fastapi_app) as client:
        yield client


@pytest.fixture()
def client(app_client):
    """Function 级 `TestClient` 别名（同一底层 session 客户端）。

    之所以复用 session 客户端：TestClient 的 lifespan 会跑一次 `init_db()`，
    每个用例各起一次既慢又无必要。测试隔离靠用例自身的清理，而非重建库。
    """
    return app_client


@pytest.fixture()
def clean_db():
    """按需重建临时库（用于需要干净表的用例）。

    仅清理临时库——绝不可能命中真实数据。
    """
    db_path = Path(config.DB_PATH)
    if db_path.exists():
        db_path.unlink()
    init_db()
    return db_path


@pytest.fixture()
def db_session(app_client):
    """提供一个指向**临时库**的 SQLAlchemy 会话（供写库用例）。

    依赖 `app_client` 以触发 lifespan 的 `init_db()` 建好表结构（否则单独跑
    某些只依赖 `db_session` 的用例时会遇到「no such table」）。本 fixture 只负责
    开/关会话；用例自行负责清理其写入的行（或依赖库被丢弃）。
    """
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _make_user(role: str = "user", *, is_active: bool = True) -> int:
    """在临时库直接落库建一个用户，返回其 id（供铸牌 fixture 复用）。

    Args:
        role: `user` / `admin`。
        is_active: 是否可用（False 用于「禁用账号」用例）。

    Notes:
        用户名用随机后缀，避免多个用例共用一个 session 级库时唯一约束冲突。
    """
    import secrets

    from app.db import SessionLocal
    from app.models import User
    from app.services import auth as auth_service

    db = SessionLocal()
    try:
        salt = auth_service.new_salt()
        user = User(
            username=f"t-{role}-{secrets.token_hex(4)}",
            salt=salt,
            iterations=200_000,
            password_hash=auth_service.hash_password("test-password-123", salt, 200_000),
            role=role,
            is_active=is_active,
            token_version=0,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user.id
    finally:
        db.close()


def _mint_session(client, uid: int) -> None:
    """给 `client` 铸一个指向 `uid` 的有效会话 cookie（版本号按 0 签发）。"""
    from app.db import SessionLocal
    from app.services import auth as auth_service

    db = SessionLocal()
    try:
        secret = auth_service.get_secret(db)
        token = auth_service.issue_token(uid, secret, 600, 0)
    finally:
        db.close()
    client.cookies.set(auth_service.COOKIE_NAME, token)


@pytest.fixture()
def authed_uid() -> int:
    """当前「普通用户」的 id（供需要给学习数据落 `user_id` 的用例复用）。"""
    return _make_user("user")


@pytest.fixture()
def authed_client(client, authed_uid):
    """带**有效会话 cookie** 的 `TestClient`（普通用户，用于受登录门禁保护的端点）。

    做法：真实建一行 `role='user'` 的用户，再用 `issue_token` 铸牌塞进 cookie ——
    守卫中间件现在会回查 `User`（校验存在 + `is_active` + `token_version`），
    所以必须落库，不能像旧版那样只签 `uid=1` 不建行。

    Notes:
        用法与 `client` 一致；用例结束后清掉 cookie，避免污染共享的 session 级
        `TestClient`（其它模块的用例会断言「未登录 → 401」）。
        若用例要给学习数据落 `user_id`，请同时依赖 `authed_uid` 拿同一用户 id。
    """
    _mint_session(client, authed_uid)
    try:
        yield client
    finally:
        client.cookies.clear()


@pytest.fixture()
def admin_client(client):
    """带**管理员会话 cookie** 的 `TestClient`（用于仅管理员可写的端点）。"""
    uid = _make_user("admin")
    _mint_session(client, uid)
    try:
        yield client
    finally:
        client.cookies.clear()

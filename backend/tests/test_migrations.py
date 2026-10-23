"""Alembic 迁移（`migrations/`）的自动化验收。

⚠️ **本文件是唯一校验 `migrations/versions/*.py` 的地方**（结构性说明，别搞错）
==============================================================================
`tests/test_jobs.py` 等业务用例全部跑在 `conftest` 的临时库上，而那张库是
`Base.metadata.create_all()` 建出来的 —— **元数据永远是对的**，所以它们对迁移脚本
的任何退化**完全免疫**。实测（QA 独立复核）：删掉 `jobs.worker_id` 一列、或摘掉
`uq_jobs_active` 的 `sqlite_where`，`test_jobs.py` 都是 36/36 全绿，只有本文件会红。

推论：
* 想给「迁移脚本」加保护，**只能**加在这里；加在 `test_jobs.py` 里等于没加
  （`TestSchemaGuards` 守的是 `create_all` 路径，不是迁移）。
* 反过来，本文件**不**覆盖业务行为（认领/回收/fencing 都在 `test_jobs.py` 与
  `test_worker_*.py`），两边职责不重叠。

设计要点
========
* 目标库一律**显式**通过 ``-x db_path=`` 注入（编程式用
  ``Config.attributes["x"]`` / ``Config.cmd_opts``），**不依赖** conftest 对
  ``app.core.config.DB_PATH`` 的重定向副作用 —— 迁移代码必须自己就能被指到
  任意库上，否则「在副本上演练」这条规矩就无从谈起。
* 真实 ``data/app.db`` **只读**：需要「真实库副本」的用例用 ``shutil.copy2``
  拷到 tmp 再操作，并断言操作路径不在 ``data/`` 之下。
* 断言「零结构差异」时严格从 ``Base.metadata`` 推导期望值 —— 基线漏列/漏索引
  会立刻失败，不是恒真式。
* 索引比对**含 `partial` 位**（四元组，不只 `name/columns/unique`）：
  `uq_jobs_active` 一旦退化成普通唯一索引，「入队幂等」会变成「一个媒体一生只能
  跑一次任务」且不报错，而 alembic 的 autogenerate / `check` **不比较** SQLite 的
  部分索引属性。谓词**内容**（`'pending'`/`'running'` 两个字面量）由
  `test_fresh_database_creates_all_indexes` 里的定点断言逐字守着 —— 通用比对刻意
  **不**解析 DDL 文本（排版归一脆且易误伤）。
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.dialects import sqlite as sqlite_dialect
from sqlalchemy.orm import Session

from app import models  # 把全部表注册到 Base.metadata，并供 ORM 冒烟用例构造实体
from app.db import Base

#: 用于把模型侧 `server_default`（如 `func.now()`）编译成 SQLite 方言的文本，
#: 才能与反射侧拿到的 `'CURRENT_TIMESTAMP'` 直接比对。
_SQLITE_DIALECT = sqlite_dialect.dialect()

# ---------------------------------------------------------------------------
# 路径常量
# ---------------------------------------------------------------------------
_BACKEND_DIR: Path = Path(__file__).resolve().parents[1]
_ALEMBIC_INI: Path = _BACKEND_DIR / "alembic.ini"
_MIGRATIONS_DIR: Path = _BACKEND_DIR / "migrations"
_REAL_DATA_DIR: Path = (_BACKEND_DIR.parent / "data").resolve()
_REAL_DB_PATH: Path = _REAL_DATA_DIR / "app.db"

#: 当前 head（P3-1 的基线 `0001` + P3-2 的 `0002_jobs_and_workers.py`
#: + P4-3 的 `0003_ielts.py` + v1.16.2 的 `0004_multiuser.py`）。
#: 语义从「基线」变成「当前 head」—— 保留 `0001` 的断言会阻止任何新迁移。
_HEAD_REVISION = "0004"

#: 基线 `0001` 负责的 9 张业务表（与 `models/entities.py` 硬对齐，手工列出，
#: 避免「metadata 少了某张表 → 期望值也跟着少」这种自我循环的假通过）。
#: ⚠️ 这是**只许加强、不许放宽**的一组：任何一张老表的逐列断言被删掉，
#: 「老库结构不许动」的保护就没了（DD-001 §9 R2）。
_LEGACY_TABLES = frozenset(
    {
        "categories",
        "media",
        "sentences",
        "attempts",
        "notes",
        "vocab",
        "settings",
        "users",
        "translations",
    }
)

#: `0002_jobs_and_workers.py` 新增的 2 张表（P3-2 调度层）。
#: 对它们的断言口径与老表不同：老库升级前**根本没有**这两张表，
#: 因此只能断言「升级后存在 + 列集合与模型一致」，不能整表比对 PRAGMA（会假红）。
_NEW_TABLES = frozenset({"jobs", "workers"})

#: `0003_ielts.py` 新增的 7 张表（P4-3 题库与作答 + P4-4 批改缓存）。
#: 口径与 `_NEW_TABLES` 相同：老库升级前不存在，只断言「升级后存在 + 列集合一致」。
_IELTS_TABLES = frozenset(
    {
        "papers",
        "sections",
        "passages",
        "questions",
        "practice_sessions",
        "responses",
        "writing_grade_cache",
    }
)

#: `0004_multiuser.py` 新增的 1 张表（v1.16.2 个人「易听错」标记）。
#: 口径同上：老库升级前不存在。
_MULTIUSER_TABLES = frozenset({"sentence_marks"})

#: 「老库升级前不存在」的全部表（P3-2 + P4-3 + v1.16.2）。上面几条规则合并后的口径。
_ADDED_TABLES = _NEW_TABLES | _IELTS_TABLES | _MULTIUSER_TABLES

#: 当前 head 应当建出的全部业务表。
_EXPECTED_TABLES = _LEGACY_TABLES | _ADDED_TABLES

#: 基线**刻意**在 DDL 里补、而模型侧没有 `server_default` 的默认值。
#: 见 `0001_baseline.py` 的「关于默认值」段：模型只有 Python 端 `default=""`，
#: 基线额外给 `DEFAULT ''` 是为了裸 SQL 插入也安全。这里是**白名单**：
#: 除了这些，任何「模型上没有、库里却有」的默认值都会被断言打红。
_DDL_ONLY_SERVER_DEFAULTS: dict[tuple[str, str], str] = {
    ("sentences", "marks"): "''",
}


# ---------------------------------------------------------------------------
# 通用助手
# ---------------------------------------------------------------------------
def _guard_path(path: Path) -> Path:
    """断言操作路径**不在**真实 ``data/`` 目录下，返回绝对路径。

    Raises:
        AssertionError: 路径落在真实数据目录内（绝不允许写真实库）。
    """
    resolved = Path(path).expanduser().resolve()
    try:
        resolved.relative_to(_REAL_DATA_DIR)
    except ValueError:
        return resolved
    raise AssertionError(
        "测试拒绝在真实数据目录下创建/操作数据库：\n"
        f"  目标路径    = {resolved}\n"
        f"  真实 data/  = {_REAL_DATA_DIR}"
    )


def _make_config(db_path: Path, *, channel: str = "attributes") -> Config:
    """构造指向 ``db_path`` 的 alembic ``Config``。

    Args:
        db_path: 目标库路径（不允许落在真实 ``data/`` 下）。
        channel: 注入通道 ——
            ``"attributes"`` 模拟编程式调用（``Config.attributes["x"]``）；
            ``"cmd_opts"`` 模拟命令行 ``-x db_path=...``。

    Returns:
        已设置 ``script_location`` 与 ``-x db_path`` 的 Config。
    """
    target = _guard_path(db_path)
    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))

    if channel == "attributes":
        cfg.attributes["x"] = {"db_path": str(target)}
    elif channel == "cmd_opts":
        #: 命令行走的是 argparse.Namespace.x = ["k=v", ...]
        cfg.cmd_opts = argparse.Namespace(x=[f"db_path={target}"])
    else:  # pragma: no cover - 防御性分支
        raise ValueError(f"未知的注入通道：{channel}")
    return cfg


def _upgrade(db_path: Path, revision: str = "head", *, channel: str = "attributes") -> None:
    """对 ``db_path`` 执行 ``alembic upgrade``。"""
    command.upgrade(_make_config(db_path, channel=channel), revision)


def _engine(db_path: Path) -> sa.Engine:
    """打开指向 ``db_path`` 的 Engine（与 env.py 同样的 URL 拼法）。"""
    resolved = Path(db_path).expanduser().resolve()
    return sa.create_engine(f"sqlite:///{resolved.as_posix()}", future=True)


def _alembic_version(db_path: Path) -> str:
    """读取库里的 ``alembic_version.version_num``。"""
    with sqlite3.connect(str(db_path)) as conn:
        rows = conn.execute("SELECT version_num FROM alembic_version").fetchall()
    assert len(rows) == 1, f"alembic_version 应恰有一行，实际 {rows!r}"
    return str(rows[0][0])


def _table_names(db_path: Path) -> set[str]:
    """库中全部表名（直接用 sqlite3，避免反射层缓存干扰）。"""
    with sqlite3.connect(str(db_path)) as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {str(row[0]) for row in rows}


# ---------------------------------------------------------------------------
# 期望值：一律从 ORM 元数据推导（baseline 必须与模型完全一致）
# ---------------------------------------------------------------------------
def _expected_columns(table_name: str) -> list[tuple[str, str, bool]]:
    """模型定义的列：``(列名, 类型字符串, 是否可空)``，保持声明顺序。"""
    table = Base.metadata.tables[table_name]
    return [(column.name, str(column.type), bool(column.nullable)) for column in table.columns]


def _actual_columns(db_path: Path, table_name: str) -> list[tuple[str, str, bool]]:
    """库里的实际列（反射得到），格式同 :func:`_expected_columns`。"""
    engine = _engine(db_path)
    try:
        inspector = sa.inspect(engine)
        return [
            (column["name"], str(column["type"]), bool(column["nullable"]))
            for column in inspector.get_columns(table_name)
        ]
    finally:
        engine.dispose()


def _expected_indexes(table_name: str) -> set[tuple[str, tuple[str, ...], bool, bool]]:
    """模型定义的索引：``(索引名, 列元组, 是否唯一, 是否部分索引)``。

    Notes:
        ★ 第 4 元组（`partial`）是 P3-2 补的**第二道网**。
        P3-2 的 `uq_jobs_active` 是 `CREATE UNIQUE INDEX ... WHERE status IN (...)`；
        一旦它退化成普通唯一索引，「入队幂等」会变成「一个媒体一辈子只能跑一次
        任务」且**不报错**（DD-001 §9 R1）。原先守这条的只有
        `test_fresh_database_creates_all_indexes` 里的两行显式断言，而「结构与模型
        零差异」这条主力用例（`test_fresh_schema_matches_models_exactly`）只比
        `(name, columns, unique)` 三元组，对 `partial` 属性丢失**完全免疫**。
        把 `partial` 纳入通用比对后，主力用例自己就能抓到这类退化。

        为什么这里只比「是不是部分索引」而**不**比谓词文本：
        谓词文本比对要自己从 `sqlite_master.sql` 里切 WHERE、再做空白/引号归一，
        脆且容易误伤（SQLite 回显 DDL 的排版不受我们控制）。谓词**内容**由
        `test_fresh_database_creates_all_indexes` 里的定点断言逐字守着
        （含 `'pending'` / `'running'` 两个字面量，所以「谓词被改窄」也会红）。
    """
    table = Base.metadata.tables[table_name]
    expected: set[tuple[str, tuple[str, ...], bool, bool]] = set()
    for index in table.indexes:
        # SQLAlchemy 把方言参数放在 `dialect_options` 里；未设置该键时直接下标会
        # KeyError，所以先转成普通 dict 再 `.get()`。
        sqlite_options = dict(index.dialect_options["sqlite"])
        expected.add(
            (
                index.name,
                tuple(column.name for column in index.columns),
                bool(index.unique),
                sqlite_options.get("where") is not None,
            )
        )
    return expected


def _actual_indexes(
    db_path: Path, table_name: str
) -> set[tuple[str, tuple[str, ...], bool, bool]]:
    """库里的实际索引，格式同 :func:`_expected_indexes`（含 `partial` 位）。

    过滤 ``sqlite_autoindex_*``：那是非 INTEGER 主键（settings.key /
    translations.key）由 SQLite 自动建的，不属于模型显式声明的索引。

    Notes:
        `partial` 直接读 ``PRAGMA index_list(<table>)`` 的第 5 列（SQLite 3.8.0+
        的 `partial` 位）：这是 SQLite 内核自己算出来的属性，比解析 DDL 文本稳。
    """
    engine = _engine(db_path)
    try:
        inspector = sa.inspect(engine)
        index_rows = [
            index
            for index in inspector.get_indexes(table_name)
            if index["name"] and not str(index["name"]).startswith("sqlite_autoindex")
        ]
    finally:
        engine.dispose()

    with sqlite3.connect(str(db_path)) as conn:
        # 表名来自本文件硬编码的 `_EXPECTED_TABLES`，不是外部输入；PRAGMA 不支持
        # 绑定参数，所以这里用 f-string（不存在注入面）。
        partial_by_name = {
            str(row[1]): bool(row[4])
            for row in conn.execute(f"PRAGMA index_list({table_name})")
        }

    return {
        (
            index["name"],
            tuple(index["column_names"]),
            bool(index["unique"]),
            partial_by_name.get(str(index["name"]), False),
        )
        for index in index_rows
    }


def _normalize_sql_text(text: str) -> str | None:
    """归一化 SQL 文本：压缩空白（DDL 里可能带换行/多空格）、空串转 ``None``。"""
    normalized = " ".join(text.split())
    return normalized or None


def _compile_server_default(value: Any) -> str | None:
    """把模型侧 / 反射侧的 ``server_default`` 归一成同一形态。

    Args:
        value: 模型侧是 ``DefaultClause``（内部 ``arg`` 可能是 ``func.now()``、
            ``TextClause`` 或普通字符串）；反射侧（``Inspector.get_columns()``）
            直接给字符串，例如 ``"CURRENT_TIMESTAMP"``。

    Returns:
        归一化后的 SQL 文本，或 ``None``（无默认值）。

    Notes:
        ``func.now()`` 必须按 **SQLite 方言编译** 才能得到
        ``CURRENT_TIMESTAMP`` —— 直接 ``str(func.now())`` 得到的是 ``now()``，
        与库里反射出来的值不可比。
    """
    if value is None:
        return None
    if isinstance(value, str):
        return _normalize_sql_text(value)

    argument = getattr(value, "arg", None)
    if argument is None:
        return None
    if isinstance(argument, str):
        return _normalize_sql_text(argument)

    compiled = argument.compile(dialect=_SQLITE_DIALECT, compile_kwargs={"literal_binds": True})
    return _normalize_sql_text(str(compiled))


def _expected_server_defaults(table_name: str) -> dict[str, str | None]:
    """模型声明的 ``server_default``：``{列名: 归一化 SQL 文本或 None}``。"""
    return {
        column.name: _compile_server_default(column.server_default)
        for column in Base.metadata.tables[table_name].columns
    }


def _actual_server_defaults(db_path: Path, table_name: str) -> dict[str, str | None]:
    """库里实际的列默认值（反射），格式同 :func:`_expected_server_defaults`。"""
    engine = _engine(db_path)
    try:
        inspector = sa.inspect(engine)
        return {
            column["name"]: _compile_server_default(column["default"])
            for column in inspector.get_columns(table_name)
        }
    finally:
        engine.dispose()


def _expected_foreign_keys(table_name: str) -> set[tuple[tuple[str, ...], str, tuple[str, ...], str]]:
    """模型声明的外键：``(本地列元组, 目标表, 目标列元组, ondelete)``。"""
    expected: set[tuple[tuple[str, ...], str, tuple[str, ...], str]] = set()
    for constraint in Base.metadata.tables[table_name].foreign_key_constraints:
        local_columns = tuple(element.parent.name for element in constraint.elements)
        referred_columns = tuple(element.column.name for element in constraint.elements)
        referred_table = constraint.elements[0].column.table.name
        expected.add((local_columns, referred_table, referred_columns, (constraint.ondelete or "NO ACTION").upper()))
    return expected


def _actual_foreign_keys(db_path: Path, table_name: str) -> set[tuple[tuple[str, ...], str, tuple[str, ...], str]]:
    """库里实际的外键（反射），格式同 :func:`_expected_foreign_keys`。"""
    engine = _engine(db_path)
    try:
        inspector = sa.inspect(engine)
        actual: set[tuple[tuple[str, ...], str, tuple[str, ...], str]] = set()
        for foreign_key in inspector.get_foreign_keys(table_name):
            ondelete = foreign_key.get("options", {}).get("ondelete") or "NO ACTION"
            actual.add(
                (
                    tuple(foreign_key["constrained_columns"]),
                    str(foreign_key["referred_table"]),
                    tuple(foreign_key["referred_columns"]),
                    str(ondelete).upper(),
                )
            )
        return actual
    finally:
        engine.dispose()


def _row_counts(
    db_path: Path, tables: frozenset[str] | set[str] | None = None
) -> dict[str, int]:
    """各业务表的行数（用于「数据没被改动」的断言）。

    Args:
        db_path: 目标库。
        tables: 要统计的表名集合；默认全部 `_EXPECTED_TABLES`。
            「老库副本升级前还没有 jobs/workers」的场景必须传 `_LEGACY_TABLES`，
            否则 `SELECT COUNT(*) FROM jobs` 会直接 OperationalError。
    """
    target = sorted(tables if tables is not None else _EXPECTED_TABLES)
    counts: dict[str, int] = {}
    with sqlite3.connect(str(db_path)) as conn:
        for table_name in target:
            counts[table_name] = int(conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0])
    return counts


def _table_info(
    db_path: Path,
    *,
    readonly: bool = False,
    tables: frozenset[str] | set[str] | None = None,
) -> dict[str, list[tuple[Any, ...]]]:
    """业务表的 ``PRAGMA table_info`` 快照（列名/类型/可空/默认值/主键）。

    Args:
        db_path: 目标库。
        readonly: 以只读 URI 打开（用于校验真实库「一个字节都没变」）。
        tables: 要快照的表名集合；默认全部 `_EXPECTED_TABLES`。
            老库升级前的快照必须传 `_LEGACY_TABLES` —— 那时 `jobs` 还不存在，
            `PRAGMA table_info(jobs)` 返回 `[]`，与升级后的 14 列不等 → 假红。
    """
    target = sorted(tables if tables is not None else _EXPECTED_TABLES)
    snapshot: dict[str, list[tuple[Any, ...]]] = {}
    if readonly:
        uri = f"file:{Path(db_path).as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
    else:
        conn = sqlite3.connect(str(db_path))
    try:
        for table_name in target:
            snapshot[table_name] = [tuple(row) for row in conn.execute(f"PRAGMA table_info({table_name})")]
    finally:
        conn.close()
    return snapshot


# ---------------------------------------------------------------------------
# 1) 空库 → upgrade head：全部业务表 + alembic_version 就位，列集合与模型一致
# ---------------------------------------------------------------------------
def test_fresh_database_creates_baseline_schema(tmp_path: Path) -> None:
    """全新的空库执行 ``upgrade head`` 后，表与列都应与模型严格一致。"""
    fresh_db = tmp_path / "fresh.db"
    assert not fresh_db.exists()

    _upgrade(fresh_db)

    tables = _table_names(fresh_db)
    assert tables == _EXPECTED_TABLES | {"alembic_version"}, f"表集合不符：{tables}"

    # 模型侧也必须有且仅有 `_EXPECTED_TABLES`（防止有人删模型而基线仍「自洽」）。
    assert frozenset(Base.metadata.tables) == _EXPECTED_TABLES, sorted(Base.metadata.tables)

    for table_name in sorted(_EXPECTED_TABLES):
        actual = {column[0] for column in _actual_columns(fresh_db, table_name)}
        expected = {column.name for column in Base.metadata.tables[table_name].columns}
        assert actual == expected, f"{table_name} 列集合不符：多 {actual - expected}，缺 {expected - actual}"

    assert _alembic_version(fresh_db) == _HEAD_REVISION


# ---------------------------------------------------------------------------
# 2) 空库 → 索引全部存在（含 ix_media_category_id 与全部 index=True 索引）
# ---------------------------------------------------------------------------
def test_fresh_database_creates_all_indexes(tmp_path: Path) -> None:
    """基线必须建出模型声明的每一个索引，且唯一性一致。"""
    fresh_db = tmp_path / "indexed.db"
    _upgrade(fresh_db)

    for table_name in sorted(_EXPECTED_TABLES):
        actual = _actual_indexes(fresh_db, table_name)
        expected = _expected_indexes(table_name)
        assert actual == expected, (
            f"{table_name} 索引不符："
            f"多 {sorted(actual - expected)}，缺 {sorted(expected - actual)}"
        )

    # 关键索引显式点名（`_INDEXES` 里的 legacy 补建项，最容易被漏掉）。
    media_indexes = {name for name, _columns, _unique, _partial in _actual_indexes(fresh_db, "media")}
    assert "ix_media_category_id" in media_indexes, sorted(media_indexes)

    # `index=True` 系列（entities.py 里声明）全部就位。
    for index_name in (
        "ix_categories_name",
        "ix_categories_sort_order",
        "ix_sentences_media_id",
        "ix_attempts_sentence_id",
        "ix_notes_sentence_id",
        "ix_vocab_word",
        "ix_users_username",
    ):
        hit = [
            table_name
            for table_name in _EXPECTED_TABLES
            # 括号内换行合法；四元组的第 4 位是「部分索引谓词」（本轮新增）
            if index_name in {
                name
                for name, _columns, _unique, _partial in _actual_indexes(fresh_db, table_name)
            }
        ]
        assert len(hit) == 1, f"索引 {index_name} 未创建或重复：{hit}"

    # ------------------------------------------------------------------
    # P3-2 / DD-001 §9 R1：`uq_jobs_active` 必须是**部分**唯一索引。
    # 只断言 unique=True 是不够的（普通唯一索引也满足），必须看到 WHERE 子句 ——
    # 写成普通唯一索引会让「同一个媒体一辈子只能跑一个任务」且**静默无报错**。
    # ------------------------------------------------------------------
    with sqlite3.connect(str(fresh_db)) as conn:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND name='uq_jobs_active'"
        ).fetchone()
        index_list = {r[1]: r for r in conn.execute("PRAGMA index_list(jobs)")}
        jobs_ddl_row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='jobs'"
        ).fetchone()
    assert row is not None, "uq_jobs_active 未创建"
    ddl = " ".join((row[0] or "").split())
    assert ddl.upper().startswith("CREATE UNIQUE INDEX"), ddl
    assert "WHERE status IN (" in ddl, f"uq_jobs_active 不是部分索引（缺 WHERE）：{ddl}"
    assert "'pending'" in ddl and "'running'" in ddl, ddl
    # PRAGMA index_list 的第 5 列（partial）必须为 1，作为 SQL 文本之外的第二重证据。
    assert index_list["uq_jobs_active"][4] == 1, index_list["uq_jobs_active"]

    # ------------------------------------------------------------------
    # `jobs` 的两个 CHECK 约束只能靠 DDL 文本守：alembic 的 autogenerate/check
    # **不比较 CHECK**（实测：删掉 `ck_jobs_progress` 后 10 个迁移用例全绿），
    # 而 `create_all` 那条路只有 `tests/test_jobs.py::TestSchemaGuards` 兜底 ——
    # 于是「纯 alembic 建库」这条路原本是裸奔的。这里补上第四张网。
    # ------------------------------------------------------------------
    assert jobs_ddl_row is not None, "jobs 表未创建"
    jobs_ddl = " ".join((jobs_ddl_row[0] or "").split())
    assert "ck_jobs_status" in jobs_ddl, f"缺 ck_jobs_status 约束：{jobs_ddl}"
    assert "ck_jobs_progress" in jobs_ddl, f"缺 ck_jobs_progress 约束：{jobs_ddl}"
    # 光有名字不够：谓词本身也必须是预期的（防「改成恒真谓词」这类退化）。
    # ⚠️ SQLite 回显 DDL 时逗号后**没有**空格（`'pending','running'`），断言前先
    #    去掉全部空白再比，避免被排版差异卡住（这条是被自己的首版断言坑过的）。
    jobs_ddl_tight = jobs_ddl.replace(" ", "")
    assert "statusIN('pending','running','done','failed')" in jobs_ddl_tight, jobs_ddl
    assert "progressBETWEEN0AND100" in jobs_ddl_tight, jobs_ddl


# ---------------------------------------------------------------------------
# 3) 模拟老库（表已存在、无 alembic_version）→ upgrade head：不报错、数据不丢
# ---------------------------------------------------------------------------
def test_legacy_database_upgrade_backfills_multiuser(tmp_path: Path) -> None:
    """0001 老库升级到 head：数据不丢 + user_id 回填 + marks 迁移 + 索引切换。

    0004 之前，老库（有表无版本）升级是严格 no-op；0004 起会**演进老表**
    （users/attempts/notes/vocab 加列、sentences.marks 迁到 sentence_marks）。
    本用例验证：这些演进只加列/迁移数据，**不删一行、不改既有列定义**。
    """
    legacy_db = tmp_path / "legacy.db"

    # 用 alembic 0001 建出真正的老库结构（9 表、无 user_id、notes 单列唯一）。
    _upgrade(legacy_db, "0001")
    assert _alembic_version(legacy_db) == "0001"

    # 灌数据：1 个用户 + 素材/句子（带 marks）+ 个人数据。
    engine = _engine(legacy_db)
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(
                "INSERT INTO users (username, password_hash, salt, iterations)"
                " VALUES ('alice', 'deadbeef', 'cafe', 200000)"
            )
            conn.exec_driver_sql("INSERT INTO categories (name, sort_order) VALUES ('第1章', 0)")
            conn.exec_driver_sql(
                "INSERT INTO media (title, type, original_name, file_path, size_bytes,"
                " duration_ms, status, progress, origin, category_id) VALUES"
                " ('老库素材', 'audio', 'old.mp3', 'data/media/library/1/old.mp3',"
                " 1024, 2000, 'done', 100, 'upload', 1)"
            )
            conn.exec_driver_sql(
                "INSERT INTO sentences (media_id, idx, start_ms, end_ms, text_en, text_zh,"
                " is_edited, marks) VALUES (1, 0, 0, 1200, 'Hello there.', '你好。', 0, '[[0,1]]')"
            )
            conn.exec_driver_sql(
                "INSERT INTO attempts (sentence_id, input, accuracy, is_correct)"
                " VALUES (1, 'hello there', 100.0, 1)"
            )
            conn.exec_driver_sql("INSERT INTO notes (sentence_id, content) VALUES (1, '备注')")
            conn.exec_driver_sql("INSERT INTO vocab (word, mastered) VALUES ('hello', 0)")
    finally:
        engine.dispose()

    # 前置：老库没有 user_id 列、notes 的 sentence_id 是唯一索引。
    assert "user_id" not in {c[0] for c in _actual_columns(legacy_db, "attempts")}
    with sqlite3.connect(str(legacy_db)) as conn:
        notes_idx = {r[1]: r for r in conn.execute("PRAGMA index_list(notes)")}
        assert notes_idx["ix_notes_sentence_id"][2] == 1  # 唯一

    _upgrade(legacy_db)  # head：不能抛 "table already exists"

    tables = _table_names(legacy_db)
    assert tables == _EXPECTED_TABLES | {"alembic_version"}, f"表集合不符：{tables}"
    assert _alembic_version(legacy_db) == _HEAD_REVISION

    # 个人数据一行不少（只加列，不增删行）。
    counts = _row_counts(legacy_db)
    assert counts["attempts"] == 1
    assert counts["notes"] == 1
    assert counts["vocab"] == 1
    assert counts["sentences"] == 1
    assert counts["users"] == 1

    with sqlite3.connect(str(legacy_db)) as conn:
        # user_id 回填到老用户（id=1）。
        assert conn.execute("SELECT user_id FROM attempts WHERE id=1").fetchone()[0] == 1
        assert conn.execute("SELECT user_id FROM notes WHERE id=1").fetchone()[0] == 1
        assert conn.execute("SELECT user_id FROM vocab WHERE id=1").fetchone()[0] == 1
        # marks 迁到 sentence_marks，sentences.marks 清空。
        assert conn.execute("SELECT marks FROM sentences WHERE id=1").fetchone()[0] == ""
        row = conn.execute(
            "SELECT user_id, sentence_id, ranges FROM sentence_marks"
        ).fetchone()
        assert row == (1, 1, "[[0,1]]"), row
        # notes 唯一索引切换：单列降级为非唯一，联合唯一索引就位。
        notes_idx = {r[1]: r for r in conn.execute("PRAGMA index_list(notes)")}
        assert notes_idx["ix_notes_sentence_id"][2] == 0  # 非唯一
        assert notes_idx["uq_notes_user_sentence"][2] == 1  # 唯一
        # users 三列就位且默认值正确。
        user_row = conn.execute(
            "SELECT role, is_active, token_version FROM users WHERE id=1"
        ).fetchone()
        assert user_row == ("user", 1, 0), user_row

    # 列集合最终与模型一致。
    for table_name in sorted(_EXPECTED_TABLES):
        actual = {column[0] for column in _actual_columns(legacy_db, table_name)}
        expected = {column.name for column in Base.metadata.tables[table_name].columns}
        assert actual == expected, table_name


# ---------------------------------------------------------------------------
# 4) 幂等：连续两次 upgrade head 均成功（第二次是 no-op）
# ---------------------------------------------------------------------------
def test_repeated_upgrade_is_idempotent(tmp_path: Path) -> None:
    """重复执行 ``upgrade head`` 不应报错，也不应改变结构。"""
    db_path = tmp_path / "idempotent.db"

    _upgrade(db_path)
    first_info = _table_info(db_path)
    first_version = _alembic_version(db_path)

    # 第二次走命令行通道（`cmd_opts.x`），顺带覆盖 env.py 的另一条解析分支。
    _upgrade(db_path, channel="cmd_opts")
    # 第三次走 attributes，确认两条通道可混用。
    _upgrade(db_path)

    assert _alembic_version(db_path) == first_version == _HEAD_REVISION
    assert _table_info(db_path) == first_info
    assert _table_names(db_path) == _EXPECTED_TABLES | {"alembic_version"}


# ---------------------------------------------------------------------------
# 5) 结构零差异：列级 + 索引级全量比对（防基线漏列/漏索引）
# ---------------------------------------------------------------------------
def test_fresh_schema_matches_models_exactly(tmp_path: Path) -> None:
    """空库迁移后的结构与 ``Base.metadata`` 必须零差异（列顺序/类型/可空 + 索引）。

    默认值见 :func:`test_fresh_schema_server_defaults_match_models`，外键见
    :func:`test_fresh_schema_foreign_keys_match_models` —— 刻意拆成三条用例，
    失败时能一眼看出是「列/索引」「默认值」还是「外键」出了问题。
    """
    db_path = tmp_path / "parity.db"
    _upgrade(db_path)

    total_columns = 0
    total_indexes = 0
    for table_name in sorted(_EXPECTED_TABLES):
        expected_columns = _expected_columns(table_name)
        actual_columns = _actual_columns(db_path, table_name)
        assert actual_columns == expected_columns, (
            f"{table_name} 列定义差异：\n  期望 {expected_columns}\n  实际 {actual_columns}"
        )
        total_columns += len(expected_columns)

        expected_indexes = _expected_indexes(table_name)
        actual_indexes = _actual_indexes(db_path, table_name)
        assert actual_indexes == expected_indexes, (
            f"{table_name} 索引差异：\n  期望 {sorted(expected_indexes)}\n  实际 {sorted(actual_indexes)}"
        )
        total_indexes += len(expected_indexes)

    # 防止「空比对」式假通过：数量级必须对得上（19 表 / 142 列 / 28 索引）。
    # 142 = 131（P4-3 时的总量）
    #       + 11（0004：users 3 + attempts/notes/vocab/practice_sessions 各 1 +
    #             sentence_marks 4）
    assert total_columns == 142, f"列总数异常：{total_columns}"
    # 28 = 20（P4-3 时的总量）
    #      + 8（0004：attempts/notes/vocab/practice_sessions 各 +1 个 user_id 索引、
    #            notes 的 uq_notes_user_sentence、sentence_marks 3 个索引）
    assert total_indexes == 28, f"索引总数异常：{total_indexes}"
    assert len(_EXPECTED_TABLES) == 19


# ---------------------------------------------------------------------------
# 6) 真实库副本：upgrade 必须是 no-op（G3-① 的核心验证）
# ---------------------------------------------------------------------------
@pytest.mark.skipif(
    not _REAL_DB_PATH.is_file(),
    reason="本机没有 data/app.db（全新克隆 / CI），跳过真实库副本用例",
)
def test_real_database_copy_upgrade_keeps_everything(tmp_path: Path) -> None:
    """把真实库拷到 tmp 再 upgrade：个人数据不丢 + 0004 加列/回填/迁移。

    0004 会演进老表（users/attempts/notes/vocab 加列、sentences.marks 迁移），
    所以「逐列零改动」只对 0004 **不碰**的 5 张老表成立；对加列的 4 张，只断言
    行数不变、新列就位、user_id 回填。
    """
    copy_db = tmp_path / "app-copy.db"
    shutil.copy2(_REAL_DB_PATH, copy_db)  # 只读源文件，写入目标在 tmp

    # 目标绝不能落在真实 data/ 下（copy2 到 tmp_path 天然满足，这里上锁）。
    _guard_path(copy_db)
    assert copy_db.resolve() != _REAL_DB_PATH.resolve()

    # 0004 会加列的 4 张老表；其余 5 张老表列定义零改动。
    _altered_tables = frozenset({"users", "attempts", "notes", "vocab"})
    _untouched_tables = _LEGACY_TABLES - _altered_tables

    before_counts = _row_counts(copy_db, _LEGACY_TABLES)
    before_info = _table_info(copy_db, tables=_untouched_tables)
    with sqlite3.connect(str(copy_db)) as conn:
        before_marks = conn.execute(
            "SELECT COUNT(*) FROM sentences WHERE marks IS NOT NULL AND marks <> ''"
        ).fetchone()[0]
    # 真实库此时还没有 alembic_version，也还没有任何新增表。
    assert "alembic_version" not in _table_names(copy_db)
    assert not (_ADDED_TABLES & _table_names(copy_db)), sorted(
        _ADDED_TABLES & _table_names(copy_db)
    )

    _upgrade(copy_db)

    assert _alembic_version(copy_db) == _HEAD_REVISION
    # 数据一行不少（0004 只加列，不删行）。
    assert _row_counts(copy_db, _LEGACY_TABLES) == before_counts, "老表数据行数被改动"

    # 0004 不碰的 5 张老表必须逐列零改动（这条断言一个字都不许放宽）。
    after_info = _table_info(copy_db, tables=_untouched_tables)
    assert after_info == before_info, "0004 不应改动 categories/media/sentences/settings/translations 的列定义"

    # 新表必须出现，且列集合与模型一致。
    tables = _table_names(copy_db)
    assert _ADDED_TABLES <= tables, f"新表缺失：{sorted(_ADDED_TABLES - tables)}"
    for table_name in sorted(_ADDED_TABLES):
        actual = {column[0] for column in _actual_columns(copy_db, table_name)}
        expected = {column.name for column in Base.metadata.tables[table_name].columns}
        assert actual == expected, f"{table_name} 列集合不符：多 {actual - expected}，缺 {expected - actual}"

    # marks 全部迁到 sentence_marks，sentences.marks 清空。
    with sqlite3.connect(str(copy_db)) as conn:
        remaining = conn.execute(
            "SELECT COUNT(*) FROM sentences WHERE marks IS NOT NULL AND marks <> ''"
        ).fetchone()[0]
        migrated = conn.execute("SELECT COUNT(*) FROM sentence_marks").fetchone()[0]
        assert remaining == 0, "sentences.marks 未清空"
        assert migrated == before_marks, f"sentence_marks 迁移行数不符：{migrated} != {before_marks}"

    # 真实库本身一行未变（只读校验：它仍然没有 alembic_version / 新表，列也原样）。
    assert "alembic_version" not in _table_names(_REAL_DB_PATH)
    assert not (_ADDED_TABLES & _table_names(_REAL_DB_PATH))
    assert _table_info(_REAL_DB_PATH, readonly=True, tables=_untouched_tables) == before_info


# ---------------------------------------------------------------------------
# 7) downgrade base：可逆（仅本地/CI 演练用途）
# ---------------------------------------------------------------------------
def test_downgrade_base_removes_every_table(tmp_path: Path) -> None:
    """``downgrade base`` 应删掉全部业务表（只留 alembic 自己的版本表）。"""
    db_path = tmp_path / "downgrade.db"
    _upgrade(db_path)
    assert _EXPECTED_TABLES <= _table_names(db_path)

    command.downgrade(_make_config(db_path), "base")

    remaining = _table_names(db_path)
    assert not (_EXPECTED_TABLES & remaining), f"以下表未被删除：{sorted(_EXPECTED_TABLES & remaining)}"
    assert remaining <= {"alembic_version"}, f"存在意外残留表：{sorted(remaining - {'alembic_version'})}"


# ---------------------------------------------------------------------------
# 8) server_default 一致性（QA 变异 C 的盲区：删掉 created_at 的 DEFAULT 也全绿）
# ---------------------------------------------------------------------------
def test_fresh_schema_server_defaults_match_models(tmp_path: Path) -> None:
    """库里的列默认值必须与模型声明的一致，且不得出现未声明的多余默认值。

    为什么单列一条：``server_default`` 缺失既不体现在「列名/类型/可空」比对里，
    ``compare_server_default`` 又必须保持关闭（见 ``0001_baseline.py`` 的
    「关于默认值」段），两条网都会漏。这里补上第三张网。
    """
    db_path = tmp_path / "defaults.db"
    _upgrade(db_path)

    # 白名单必须只有 1 条：防止以后「遇到差异就加白名单」把这条测试泡软。
    assert len(_DDL_ONLY_SERVER_DEFAULTS) == 1, sorted(_DDL_ONLY_SERVER_DEFAULTS)

    checked = 0
    for table_name in sorted(_EXPECTED_TABLES):
        expected = _expected_server_defaults(table_name)
        actual = _actual_server_defaults(db_path, table_name)
        assert set(actual) == set(expected), f"{table_name} 列集合不一致，无法比对默认值"

        for column_name, expected_default in expected.items():
            if (table_name, column_name) in _DDL_ONLY_SERVER_DEFAULTS:
                continue  # 白名单项由下方单独断言
            assert actual[column_name] == expected_default, (
                f"{table_name}.{column_name} 的 server_default 不符："
                f"模型 {expected_default!r}，库里 {actual[column_name]!r}"
            )
            if expected_default is not None:
                checked += 1

        extras = {
            column_name
            for column_name, actual_default in actual.items()
            if actual_default is not None
            and expected.get(column_name) is None
            and (table_name, column_name) not in _DDL_ONLY_SERVER_DEFAULTS
        }
        assert not extras, f"{table_name} 出现模型未声明的默认值：{sorted(extras)}"

    # 6 张老表的 created_at + notes.updated_at = 7 个由模型声明的 server_default；
    # 再加 jobs 的 6 个（status/progress/priority/payload/attempts/created_at）
    # 与 workers 的 5 个（host/mode/pools/started_at/heartbeat_at）= 18；
    # 再加 P4-3 的 3 个（papers.created_at / practice_sessions.started_at /
    # writing_grade_cache.created_at）= 21；
    # 再加 0004 的 4 个（users.role/is_active/token_version +
    # sentence_marks.ranges）= 25。
    # ⚠️ 这个数字是**故意**写成字面量的：它同时兜住「有人给新列随手加了
    #    server_default 却没在迁移里写」与「迁移写了但模型没声明」两侧。
    assert checked == 25, f"declared server_default 数量异常：{checked}"

    # 白名单项（基线刻意补的 DDL 默认值）必须真的存在，且值不变。
    assert _actual_server_defaults(db_path, "sentences")["marks"] == "''"


# ---------------------------------------------------------------------------
# 9) 外键 + ondelete 一致性（此前 0 断言）
# ---------------------------------------------------------------------------
def test_fresh_schema_foreign_keys_match_models(tmp_path: Path) -> None:
    """外键的目标表/列与 ``ondelete`` 语义必须与模型一致。"""
    db_path = tmp_path / "fks.db"
    _upgrade(db_path)

    total = 0
    for table_name in sorted(_EXPECTED_TABLES):
        expected = _expected_foreign_keys(table_name)
        actual = _actual_foreign_keys(db_path, table_name)
        assert actual == expected, (
            f"{table_name} 外键差异：\n  模型 {sorted(expected)}\n  库里 {sorted(actual)}"
        )
        total += len(expected)

    # 老库：media→categories、sentences→media、attempts→sentences、notes→sentences = 4
    # P4-3：sections→papers、passages→sections、questions→sections、
    #       questions→passages、practice_sessions→papers、
    #       responses→practice_sessions、responses→questions = 7
    # 0004：attempts/notes/practice_sessions 的 user_id→users、
    #       sentence_marks 的 user_id→users + sentence_id→sentences = 5
    # 合计 16。**刻意不加外键**的两处（sections.media_id / questions.ref_sentence_id）
    # 与 vocab.user_id 也不在这个总数里 —— 它们必须保持「裸整数」。
    assert total == 16, f"外键总数异常：{total}（vocab / IELTS 对外引用刻意不加外键）"

    # 语义点名：删分类后素材必须回落「未分类」（SET NULL），绝不是级联删除。
    assert (
        ("category_id",),
        "categories",
        ("id",),
        "SET NULL",
    ) in _actual_foreign_keys(db_path, "media")
    for table_name in ("sentences", "attempts", "notes"):
        for local_columns, _referred_table, _referred_columns, ondelete in _actual_foreign_keys(db_path, table_name):
            # user_id 外键（v1.16.2 新增）刻意 NO ACTION：软删除策略下用户不会
            # 被物理删除，且 SQLite 的 ALTER 无法表达 ON DELETE（见 0004 docstring）。
            if local_columns == ("user_id",):
                assert ondelete == "NO ACTION", f"{table_name}.user_id 应为 NO ACTION，实际 {ondelete}"
                continue
            assert ondelete == "CASCADE", f"{table_name}.{local_columns} 应为 ON DELETE CASCADE，实际 {ondelete}"


# ---------------------------------------------------------------------------
# 10) 行为冒烟：迁移后的库必须能被 ORM 真实写入（server_default 的终局验证）
# ---------------------------------------------------------------------------
def test_migrated_schema_accepts_orm_inserts(tmp_path: Path) -> None:
    """空库迁移后，**每张业务表**各插一行必须成功 —— 最贴近故障现场的证据。

    缺 ``DEFAULT CURRENT_TIMESTAMP`` 时，结构比对照样全绿，直到线上第一次
    ``INSERT INTO categories`` 才炸 ``NOT NULL constraint failed``。这里用真实
    ORM 写一遍，并且**不显式给** ``created_at`` / ``updated_at``，逼库自己填。
    """
    db_path = tmp_path / "orm-insert.db"
    _upgrade(db_path)

    engine = _engine(db_path)
    try:
        with Session(engine) as session:
            category = models.Category(name="第1章", sort_order=0)
            session.add(category)
            session.flush()  # 取 id

            media = models.Media(
                title="素材",
                type="audio",
                original_name="a.mp3",
                file_path="data/media/library/1/a.mp3",
                category_id=category.id,
            )
            session.add(media)
            session.flush()

            sentence = models.Sentence(media_id=media.id, idx=0, text_en="Hi.", text_zh="嗨。")
            session.add(sentence)
            session.flush()

            session.add(models.Attempt(sentence_id=sentence.id, input="hi", accuracy=100.0, is_correct=True))
            session.add(models.Note(sentence_id=sentence.id, content="备注"))
            session.add(models.Vocab(word="hello"))
            session.add(models.Setting(key="ui.lang", value="zh"))
            session.add(models.Translation(key="sha1:abc", source_text="a", target_text="b", engine="youdao"))
            user = models.User(username="alice", password_hash="deadbeef", salt="cafe")
            session.add(user)
            session.flush()  # 取 id（sentence_marks 需要外键）
            # v1.16.2 多用户新增：sentence_marks 也要能裸插（ranges 交给库填 DEFAULT）。
            session.add(models.SentenceMark(user_id=user.id, sentence_id=sentence.id))
            # P3-2 新增的两张表：同样只给业务列，逼库自己填 Default。
            session.add(models.Job(kind="media_transcode", ref_id=media.id))
            session.add(models.Worker(id="w" * 32, pid=4321))

            # P4-3 新增的 7 张表：同样**只给业务列**，把 created_at / started_at
            # 交给库填 —— 迁移里漏掉 DEFAULT 的话这里就是 IntegrityError。
            paper = models.Paper(title="C4 Test 1", mode="full_mock", source="Cambridge", tags=["听力"])
            session.add(paper)
            session.flush()
            section = models.Section(
                paper_id=paper.id, kind="listening", ordinal=0, time_limit_sec=1800,
                instructions="听录音答题", media_id=media.id,
            )
            session.add(section)
            session.flush()
            passage = models.Passage(section_id=section.id, ordinal=0, title="Passage 1", body_md="# hi")
            session.add(passage)
            session.flush()
            question = models.Question(
                section_id=section.id, passage_id=passage.id, ordinal=0, type="dictation",
                stem="写下你听到的句子", options=[], answer={"expected_text": "Hi."},
                explanation="原文见句库", ref_sentence_id=sentence.id,
            )
            session.add(question)
            session.flush()
            practice = models.PracticeSession(paper_id=paper.id, status="in_progress", time_spent_sec=0)
            session.add(practice)
            session.flush()
            session.add(
                models.Response(
                    session_id=practice.id, question_id=question.id,
                    user_answer={"text": "hi"}, detail={},
                )
            )
            session.add(
                models.WritingGradeCache(
                    content_hash="f" * 40, question_id=question.id,
                    payload={"score": 6.5, "max_score": 9.0, "correct": False, "detail": {}},
                )
            )

            # 任一 NOT NULL 列缺 server_default 且 ORM 未赋值 → 这里 IntegrityError。
            session.commit()

            # 时间戳必须是**库**填的（ORM 侧没有 Python default）。
            for statement in (
                "SELECT created_at FROM categories",
                "SELECT updated_at FROM notes",
                "SELECT created_at FROM translations",
                "SELECT created_at FROM papers",
                "SELECT started_at FROM practice_sessions",
                "SELECT created_at FROM writing_grade_cache",
            ):
                assert session.execute(sa.text(statement)).scalar() is not None, statement
    finally:
        engine.dispose()

    counts = _row_counts(db_path)
    assert counts == dict.fromkeys(_EXPECTED_TABLES, 1), counts


# ---------------------------------------------------------------------------
# 11) 门禁化：空库迁移后 alembic 自己的 autogenerate 必须报 0 差异
# ---------------------------------------------------------------------------
def test_alembic_check_reports_no_pending_migrations(tmp_path: Path) -> None:
    """``alembic check`` 不得发现任何待迁移项（第三方视角的零差异门禁）。"""
    db_path = tmp_path / "check.db"
    _upgrade(db_path)

    # 有差异时 alembic 抛 AutogenerateDiffsDetected（alembic.util.exc），用例即红。
    command.check(_make_config(db_path))

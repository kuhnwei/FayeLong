"""数据库连接与初始化。"""

import logging
import time
from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import DB_PATH, ensure_dirs

ensure_dirs()

logger = logging.getLogger(__name__)

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    # `timeout=15`：P3-2 起 web 与 worker 是**两个进程**，会同时写同一个 SQLite。
    # SQLite 是单写锁，争抢时默认只等 5s 就抛 `database is locked`（表现为偶发
    # 500 或任务重试）。15s 覆盖「一次进度写 + 一次 claim」的量级（DD-001 §9 R4）。
    connect_args={"check_same_thread": False, "timeout": 15},
    future=True,
)


@event.listens_for(engine, "connect")
def _enable_sqlite_fk(dbapi_connection, _record) -> None:
    """连接级 PRAGMA：开启外键 + 设置写锁等待上限。

    Notes:
        * `foreign_keys=ON`：SQLite 默认关闭外键约束；开启后 `ondelete=CASCADE`
          才会真正生效。
        * `busy_timeout=15000`：与 `connect_args["timeout"]` 同义，但更直接 ——
          `timeout` 只影响 pysqlite 自己的忙等，PRAGMA 是 SQLite 内核级的等待，
          两条一起设才能覆盖「另一个进程正持写锁」的全部路径（DD-001 §9 R4）。
        * ⚠️ **不开 WAL**：`scripts/fingerprint_data.py` 与 `data/backups` 的
          备份/指纹口径按现有 rollback journal 模式工作，改模式属本阶段范围外。
    """
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=15000")
    finally:
        cursor.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


def get_db() -> Iterator[Session]:
    """FastAPI 依赖：提供数据库会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 轻量补列（legacy 兼容层）—— 与 Alembic 的分工
# ---------------------------------------------------------------------------
# 自 v1.16 / P3-1 起，表结构变更的**唯一权威**是 Alembic
# （`backend/migrations/`，基线 `0001` 是 v1.16 现状快照）。
#
# 那这里为什么还留着？因为它服务的是**另一批库**：
#
#   `_ensure_columns()` / `_INDEXES` 只对「**没有 alembic_version 的旧库**」
#   有实际作用 —— 即用户手里那份 v1.16 之前的老 `data/app.db`。
#   而**新库 / 已迁移库**一律以 Alembic 为准（本函数对它们基本是空转）。
#
# 为什么**不能删**：
#   1. 打包版 launcher 启动即调用 `init_db()`（`main.py` 的 lifespan）；
#      用户「只换程序、不碰 data/」时就地覆盖升级，绝不会先跑
#      `alembic upgrade`。此时若这里没有补列逻辑，老库会因缺列直接 500。
#   2. P3-1 明确规定「启动行为零变化」：本阶段不引入启动时自动 upgrade。
#
# 注意：本节只做 `ALTER TABLE ADD COLUMN`（SQLite 能加的只有可空列），
# 所以它补出来的列天然可空、且带 `DEFAULT`；这与基线脚本里按模型意图写出的
# `NOT NULL` 存在差异，属已知历史包袱（详见 `migrations/versions/0001_baseline.py`
# 的 docstring）。要做约束层面的收敛，请另起一版 Alembic 迁移，别在这里加代码。
# ---------------------------------------------------------------------------

# 轻量补列：`create_all` 只会建新表、不会给老表加列。
# 这里按需 ALTER，保证「就地更新」（只换程序不碰 data/）时老库也能直接用。
_ADDED_COLUMNS: dict[str, dict[str, str]] = {
    "sentences": {"marks": "TEXT DEFAULT ''"},
    # 新增（媒体库分类）：老库就地升级时补列。可空、隐式默认 NULL →
    # SQLite 允许 `ALTER TABLE ... ADD COLUMN` 带 REFERENCES（启用 FK 时默认值必须为 NULL）。
    "media": {
        "category_id": "INTEGER REFERENCES categories(id) ON DELETE SET NULL",
    },
    # 多用户（v1.16.2）：users 三列（NOT NULL + 非空常量默认）与 4 张个人表的
    # user_id（可空；vocab 刻意不加外键，理由见 entities.py 的 Vocab docstring）。
    "users": {
        "role": "TEXT NOT NULL DEFAULT 'user'",
        "is_active": "INTEGER NOT NULL DEFAULT 1",
        "token_version": "INTEGER NOT NULL DEFAULT 0",
    },
    "attempts": {"user_id": "INTEGER REFERENCES users(id)"},
    "notes": {"user_id": "INTEGER REFERENCES users(id)"},
    "vocab": {"user_id": "INTEGER"},
    "practice_sessions": {"user_id": "INTEGER REFERENCES users(id)"},
}

# 老库只跑 `ALTER ADD COLUMN`，不会自动补索引，需显式幂等建索引。
# 新库由 `create_all` 建同名索引，`IF NOT EXISTS` 保证两边都不报错。
# （同上：只为「没有 alembic_version 的旧库」兜底，新库/已迁移库以 Alembic 为准。）
_INDEXES: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_media_category_id ON media(category_id)",
    "CREATE INDEX IF NOT EXISTS ix_attempts_user_id ON attempts(user_id)",
    "CREATE INDEX IF NOT EXISTS ix_notes_user_id ON notes(user_id)",
    "CREATE INDEX IF NOT EXISTS ix_vocab_user_id ON vocab(user_id)",
    "CREATE INDEX IF NOT EXISTS ix_practice_sessions_user_id ON practice_sessions(user_id)",
)


def _ensure_columns() -> None:
    """给已存在的表补齐新增列（幂等 + 并发安全）。

    Notes:
        这是**旧库兜底**逻辑，不是迁移框架：只服务「没有 `alembic_version` 的
        v1.16 及更早的库」。新库由 Alembic 基线建全，已迁移库由 Alembic 演进。
        保留原因见本文件 `_ADDED_COLUMNS` 上方的说明（打包版就地覆盖升级）。

        ⚠️ 并发：`PRAGMA table_info` 与 `ALTER TABLE` 之间有一个窗口 —— 另一个
        进程（web / worker）可能恰好在这一刻把列加上了。此时 SQLite 报
        `duplicate column name`，语义上等价于「已经加好了」，吞掉即正确。
        不吞的话，首次安装（两个进程同时启动）会出现**随机**的启动失败。
    """
    with engine.begin() as conn:
        for table, columns in _ADDED_COLUMNS.items():
            rows = conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
            existing = {row[1] for row in rows}
            for name, ddl in columns.items():
                if name not in existing:
                    try:
                        conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
                    except OperationalError as exc:
                        if "duplicate column name" not in str(exc).lower():
                            raise
                        logger.info(
                            "补列 %s.%s 时发现另一进程已加好该列，跳过（并发首启）",
                            table, name,
                        )


def _ensure_indexes() -> None:
    """补齐新增索引（幂等，`IF NOT EXISTS`）。

    Notes:
        与 `_ensure_columns()` 同属**旧库兜底**：只为没有 `alembic_version` 的
        老库补索引。新库/已迁移库的索引以 Alembic 基线为准。
    """
    with engine.begin() as conn:
        for statement in _INDEXES:
            conn.exec_driver_sql(statement)


def _ensure_multiuser_data() -> None:
    """多用户改造的旧库兜底：notes 唯一索引切换 + 个人数据回填 + marks 迁移。

    Notes:
        与 `_ensure_columns()` 同属**旧库兜底**，只为「没有 `alembic_version` 的
        老库」服务。新库 / 已迁移库由 Alembic `0004` 演进，本函数对它们基本是
        空转（回填 `WHERE user_id IS NULL` 无命中、索引判据发现已非唯一则跳过）。

        `notes.sentence_id` 的唯一索引必须降级为 `(user_id, sentence_id)` 联合
        唯一 —— 这是唯一无法用 `ALTER TABLE` 表达、也依赖反射判据的操作，故
        单独成函数而非塞进 `_INDEXES`（那里只有 `IF NOT EXISTS` 幂等建索引，
        无法表达「先 DROP 唯一索引再建非唯一」的切换）。

        ⚠️ 并发：web 与 worker 双进程同时首启会一起跑本函数，`DROP INDEX IF
        EXISTS` + 吞 `already exists` 保证幂等（与 `_create_all_tolerant` 同口径）。
    """
    with engine.begin() as conn:
        # 1. notes 的 sentence_id 唯一索引降级为非唯一。
        #    PRAGMA index_list(notes) 第 3 列是 unique 位（0/1）。
        unique_names = {
            row[1] for row in conn.exec_driver_sql("PRAGMA index_list(notes)").fetchall()
            if row[2]
        }
        if "ix_notes_sentence_id" in unique_names:
            try:
                conn.exec_driver_sql("DROP INDEX IF EXISTS ix_notes_sentence_id")
                conn.exec_driver_sql(
                    "CREATE INDEX ix_notes_sentence_id ON notes(sentence_id)"
                )
            except OperationalError as exc:
                if not _is_already_exists(exc):
                    raise
                logger.info(
                    "notes 索引切换时另一进程已建好同名非唯一索引，跳过（并发首启）"
                )
        # 2. 建联合唯一索引（幂等）。
        conn.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_notes_user_sentence "
            "ON notes(user_id, sentence_id)"
        )

        # 3. 数据回填：老库唯一账号回填到所有个人行；marks 迁到 sentence_marks。
        legacy = conn.exec_driver_sql(
            "SELECT id FROM users ORDER BY id LIMIT 1"
        ).fetchone()
        if legacy is not None:
            legacy_id = int(legacy[0])
            for table in ("attempts", "notes", "vocab", "practice_sessions"):
                conn.exec_driver_sql(
                    f"UPDATE {table} SET user_id = ? WHERE user_id IS NULL",
                    (legacy_id,),
                )
            conn.exec_driver_sql(
                "INSERT INTO sentence_marks(user_id, sentence_id, ranges) "
                "SELECT ?, id, marks FROM sentences "
                "WHERE marks IS NOT NULL AND marks <> '' "
                "AND NOT EXISTS (SELECT 1 FROM sentence_marks sm "
                "WHERE sm.sentence_id = sentences.id)",
                (legacy_id,),
            )
            conn.exec_driver_sql("UPDATE sentences SET marks = ''")


#: `create_all` 并发冲突时的重试次数与间隔（见 `_create_all_tolerant`）。
_CREATE_ALL_ATTEMPTS = 6
_CREATE_ALL_RETRY_SEC = 0.25

#: SQLite 报「这个对象已经存在」的几种文案（大小写不敏感匹配）。
#: 语义：**已经建好了** → 重试时的 `checkfirst` 反射会看到它并跳过。
_ALREADY_EXISTS_MARKERS = (
    "already exists",
    "duplicate column name",
    "index already exists",
)

#: SQLite 在**并发首启**时可能给出的瞬时错误（大小写不敏感匹配）。
#:
#: * `attempt to write a readonly database`：两个进程几乎同一毫秒开始 DDL 时，
#:   后到的那个在 schema 变更窗口里会看到「库暂时不可写」。**它不是权限问题**
#:   —— 同一目录立刻重跑 0.045s 就成功（QA 实测），属可重试的瞬时态。
#: * `database is locked`：SQLite 单写锁。`connect_args["timeout"]=15` 与
#:   `PRAGMA busy_timeout` 已经覆盖大部分场景，但 DDL 阶段仍可能漏出来。
#:
#: ⚠️ 这一组**只放瞬时态**。`disk I/O error`、`no such table`、`unable to open
#: database file`、`database disk image is malformed` 之类要么是真故障、要么
#: 重试也没意义 → 必须立刻抛，不能被这里吞掉（否则把「盘坏了」变成「启动慢」）。
_TRANSIENT_DDL_MARKERS = (
    "readonly database",
    "database is locked",
)


def _is_already_exists(exc: BaseException) -> bool:
    """该异常是否只是「另一个进程已经建好了」这种无害冲突。"""
    message = str(exc).lower()
    return any(marker in message for marker in _ALREADY_EXISTS_MARKERS)


def _is_transient_ddl_error(exc: BaseException) -> bool:
    """该异常是否是并发 DDL 的**瞬时态**（同一个操作重试即可成功）。"""
    message = str(exc).lower()
    return any(marker in message for marker in _TRANSIENT_DDL_MARKERS)


def _is_retryable_ddl_error(exc: BaseException) -> bool:
    """建表阶段值得重试的异常 = 已存在 + 瞬时态。其余一律不重试。"""
    return _is_already_exists(exc) or _is_transient_ddl_error(exc)


def _create_all_tolerant() -> None:
    """建表：容忍「另一个进程正在同时建同一批表」引起的两类冲突。

    Why（机制推断 + 并发实验复现，注意口径）
    ----------------------------------------
    P3-2 之后 **web 与 worker 是两个进程**，两边启动时都会 `init_db()`。
    `create_all(checkfirst=True)` 的做法是「先反射查存在性，再 CREATE TABLE」，
    两步之间**不是原子的**（这是从 SQLAlchemy 实现推出的机制，不是猜测），因此
    全新安装（打包版首次启动、云端两个 systemd unit 同时起）时两个进程会互相踩。

    并发冲突的表现有两类，都已实测：

    1. **瞬时态**（QA 双进程毫秒对齐实验复现，D 盘 10 轮里 3 轮命中）：
       `sqlite3.OperationalError: attempt to write a readonly database`
       （发生在 `CREATE TABLE categories`），同目录立刻重跑 0.045s 成功 →
       纯属 schema 变更窗口里的瞬时不可写。**这类不认就会让 worker 进程直接退出**，
       症状与「worker 起不来」完全一样（web 静默降级 web-inproc，用户零提示）。
    2. **已存在**（`already exists` / `duplicate column name`）：机制上是可能的
       —— 反射窗口里另一方建完表，本方再去 CREATE 就会撞。

    ⚠️ 关于第 2 类，**要诚实记账**：QA 用 12 进程 × 5 轮（含毫秒屏障）跑了 80+ 次
    都没能复现出 `table notes already exists`，仓库、产物与临时日志里也没有残留证据。
    所以本文不再声称「实测复现过 notes already exists」，只保留「机制上可能」，并把
    它作为**幂等护栏**保留（成本为零，且真撞上时是崩溃 vs 继续启动的区别）。

    How
    ---
    命中「已存在」或「瞬时态」就重试（6 × 0.25s）：`checkfirst` 的反射会看到另一方
    已建好的表并跳过，把剩下的建完，两边收敛到同一套结构。**其余错误一律立刻抛**
    —— 绝不把真实 DDL 故障拖成「启动慢 1.5s 后照旧失败」。
    """
    for attempt in range(1, _CREATE_ALL_ATTEMPTS + 1):
        try:
            Base.metadata.create_all(bind=engine)
            return
        except OperationalError as exc:
            if not _is_retryable_ddl_error(exc) or attempt >= _CREATE_ALL_ATTEMPTS:
                raise
            logger.info(
                "建表时遇到可重试的并发冲突（第 %d/%d 次尝试）：%s",
                attempt, _CREATE_ALL_ATTEMPTS, str(exc).splitlines()[0][:160],
            )
            time.sleep(_CREATE_ALL_RETRY_SEC)


def init_db() -> None:
    """建表 / 补列 / 补索引（启动时调用）。

    Notes:
        启动路径本阶段**保持零变化**（P3-1 只引入 Alembic，不接管启动流程）：
        这里不会执行 `alembic upgrade`，也不读 `alembic_version`。
        - 全新环境：`create_all` 建出与基线一致的表结构；
        - 老库就地覆盖升级：`create_all` 不动老表，`_ensure_columns()` /
          `_ensure_indexes()` 补列补索引，保证程序能跑；
        - 已用 Alembic 迁移过的库：`create_all` 与补列补索引都是空转。
        - **两个进程同时首启**：`_create_all_tolerant()` 把「已存在」与「瞬时不可写/
          被锁」两类并发冲突都当可重试处理，否则全新安装时 worker 会崩在
          `CREATE TABLE` 上（瞬时态已由 QA 双进程实验复现；详见该函数 docstring）。
        真正的 schema 演进（P3-2 jobs 表、P4-3 IELTS 六表）一律走
        `backend/migrations/` 的 Alembic 迁移脚本。
    """
    from app import models  # noqa: F401  确保模型已注册

    _create_all_tolerant()
    _ensure_columns()
    _ensure_indexes()
    _ensure_multiuser_data()

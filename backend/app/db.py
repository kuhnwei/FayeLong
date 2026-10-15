"""数据库连接与初始化。"""

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import DB_PATH, ensure_dirs

ensure_dirs()

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
    future=True,
)


@event.listens_for(engine, "connect")
def _enable_sqlite_fk(dbapi_connection, _record) -> None:
    """SQLite 默认关闭外键约束；开启后 ondelete=CASCADE 才会真正生效。"""
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
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


# 轻量补列：SQLite 没有迁移框架，`create_all` 只会建新表、不会给老表加列。
# 这里按需 ALTER，保证「就地更新」（只换程序不碰 data/）时老库也能直接用。
_ADDED_COLUMNS: dict[str, dict[str, str]] = {
    "sentences": {"marks": "TEXT DEFAULT ''"},
    # 新增（媒体库分类）：老库就地升级时补列。可空、隐式默认 NULL →
    # SQLite 允许 `ALTER TABLE ... ADD COLUMN` 带 REFERENCES（启用 FK 时默认值必须为 NULL）。
    "media": {
        "category_id": "INTEGER REFERENCES categories(id) ON DELETE SET NULL",
    },
}

# 老库只跑 `ALTER ADD COLUMN`，不会自动补索引，需显式幂等建索引。
# 新库由 `create_all` 建同名索引，`IF NOT EXISTS` 保证两边都不报错。
_INDEXES: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_media_category_id ON media(category_id)",
)


def _ensure_columns() -> None:
    """给已存在的表补齐新增列（幂等）。"""
    with engine.begin() as conn:
        for table, columns in _ADDED_COLUMNS.items():
            rows = conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
            existing = {row[1] for row in rows}
            for name, ddl in columns.items():
                if name not in existing:
                    conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def _ensure_indexes() -> None:
    """补齐新增索引（幂等，`IF NOT EXISTS`）。"""
    with engine.begin() as conn:
        for statement in _INDEXES:
            conn.exec_driver_sql(statement)


def init_db() -> None:
    """建表 / 补列 / 补索引（启动时调用）。"""
    from app import models  # noqa: F401  确保模型已注册

    Base.metadata.create_all(bind=engine)
    _ensure_columns()
    _ensure_indexes()

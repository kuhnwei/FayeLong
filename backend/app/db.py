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
}


def _ensure_columns() -> None:
    """给已存在的表补齐新增列（幂等）。"""
    with engine.begin() as conn:
        for table, columns in _ADDED_COLUMNS.items():
            rows = conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
            existing = {row[1] for row in rows}
            for name, ddl in columns.items():
                if name not in existing:
                    conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def init_db() -> None:
    """建表 / 补列（启动时调用）。"""
    from app import models  # noqa: F401  确保模型已注册

    Base.metadata.create_all(bind=engine)
    _ensure_columns()

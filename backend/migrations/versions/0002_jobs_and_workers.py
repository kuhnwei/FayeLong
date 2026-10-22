"""P3-2 迁移：新增 `jobs`（调度真相源）与 `workers`（进程心跳）两张表。

语义
====
* **对新库**：建出 `jobs` / `workers` 与全部 5 个索引（其中 `uq_jobs_active`
  是**部分唯一索引**，见下）。
* **对老库 / 已 `create_all` 过的库**：`upgrade head` 必须是 no-op，绝不报
  "table already exists"。**为什么这条是硬要求**：打包版就地升级走的是
  `main.lifespan → init_db() → Base.metadata.create_all()`，`create_all` 会把
  `jobs` / `workers` 建出来 —— 之后再有人跑 `alembic upgrade head`（运维、
  `alembic check`、将来的自动升级），如果本脚本无条件 `create_table`，
  就会在**一个结构完全正常的库**上炸掉。因此建表/建索引**一律先反射判存在**。

⚠️ `uq_jobs_active` 必须是**部分唯一索引**（`WHERE status IN ('pending','running')`）
==============================================================================
它承担「入队幂等」：同一 `(kind, ref_id)` 同时只能有 1 个活跃任务，于是
重复 `enqueue` 天然是 no-op，崩溃恢复与 `requeue_unfinished()` 重叠也不会双入队。

写成普通 `unique=True`（漏掉 `sqlite_where=`）的后果是**致命且静默**的：
同一个媒体这辈子只能有一个任务，第二次上传/重试直接无效且不报错
（DD-001 §9 R1）。验收方式：

    sqlite3 <db> "SELECT sql FROM sqlite_master WHERE name='uq_jobs_active'"
    -- 必须含 WHERE status IN ('pending','running')

另：`jobs.ref_id` 必须 `NOT NULL`。SQLite 的唯一索引里 NULL 互不相等，
可空列会让「活跃任务唯一」这条约束被整体绕过。

刻意**不加**的东西（理由见 DD-001 §3.2，别在本迁移里"补全"）
==========================================================
* 不加 `updated_at`：会撒谎的字段比没有更糟（每条 UPDATE 都得记得写它）；
* 不加 `pool`：`kind → pool` 是编译期常量映射，入库等于存第二份真相；
* 不加外键：`ref_id` 是多态引用（本阶段 `media.id`，P4 起 `responses.id`），
  加 FK 只能指一张表，且删媒体时会陷入 CASCADE（丢审计）/ SET NULL（丢关联）
  两难。删媒体改由应用层 `jobs_service.purge_for_media()` 清理。

Revision ID: 0002
Revises: 0001
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import context, op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels = None
depends_on = None

#: 本迁移负责建的表（顺序即建表顺序，无外键依赖，但保持「先主后从」的直觉）。
TABLE_ORDER: tuple[str, ...] = ("jobs", "workers")

#: `uq_jobs_active` 的部分索引条件。**唯一真相源**：模型与迁移必须逐字一致。
ACTIVE_STATUS_PREDICATE = "status IN ('pending','running')"

#: 全部索引：(索引名, 表名, 列元组, 是否唯一, 部分索引条件或 None)。
INDEXES: tuple[tuple[str, str, tuple[str, ...], bool, str | None], ...] = (
    ("ix_jobs_claim", "jobs", ("status", "priority", "id"), False, None),
    ("uq_jobs_active", "jobs", ("kind", "ref_id"), True, ACTIVE_STATUS_PREDICATE),
    ("ix_jobs_kind_ref", "jobs", ("kind", "ref_id"), False, None),
    ("ix_jobs_status_heartbeat", "jobs", ("status", "heartbeat_at"), False, None),
    ("ix_workers_heartbeat", "workers", ("heartbeat_at",), False, None),
)


def _existing_tables() -> set[str]:
    """目标库中已存在的表名（离线模式返回空集，从而全量输出 DDL）。

    Returns:
        表名集合。

    Notes:
        离线模式（`alembic upgrade head --sql`）没有真实连接可反射，直接返回空集
        —— 这正是「生成一份完整 SQL 脚本」想要的行为。
    """
    if context.is_offline_mode():
        return set()
    return set(sa.inspect(op.get_bind()).get_table_names())


def _existing_indexes(table: str) -> set[str]:
    """目标库中某表已存在的索引名集合（离线模式返回空集，同上）。"""
    if context.is_offline_mode():
        return set()
    inspector = sa.inspect(op.get_bind())
    return {index["name"] for index in inspector.get_indexes(table) if index["name"]}


def upgrade() -> None:
    """建 `jobs` / `workers` 与 5 个索引（逐项幂等）。"""
    existing = _existing_tables()

    # ------------------------------------------------------------------ jobs
    if "jobs" not in existing:
        op.create_table(
            "jobs",
            # rowid 别名，自增
            sa.Column("id", sa.Integer(), nullable=False),
            # 见 services/jobs.py 的 KIND_* 常量
            sa.Column("kind", sa.String(length=32), nullable=False),
            # 多态引用：media.id（本阶段）/ responses.id（P4）。**NOT NULL**，
            # 否则 uq_jobs_active 会被 SQLite 的唯一索引 NULL 语义绕过。
            sa.Column("ref_id", sa.Integer(), nullable=False),
            sa.Column(
                "status",
                sa.String(length=16),
                server_default=sa.text("'pending'"),
                nullable=False,
            ),
            # ★ 阶段内进度 0-100（全局进度在 media.progress）
            sa.Column("progress", sa.Integer(), server_default=sa.text("0"), nullable=False),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("priority", sa.Integer(), server_default=sa.text("0"), nullable=False),
            # JSON 文本，本阶段恒为 '{}'
            sa.Column("payload", sa.Text(), server_default=sa.text("'{}'"), nullable=False),
            # 兼作 fencing token
            sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
            # 归属执行者；pending 时为 NULL
            sa.Column("worker_id", sa.String(length=64), nullable=True),
            # 租约：claim 时置 now，执行中定期续
            sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            # 首次 claim 时间（COALESCE 写入，重试不覆盖）
            sa.Column("started_at", sa.DateTime(), nullable=True),
            # done / failed 时间
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.CheckConstraint(
                "status IN ('pending','running','done','failed')",
                name="ck_jobs_status",
            ),
            sa.CheckConstraint("progress BETWEEN 0 AND 100", name="ck_jobs_progress"),
            sa.PrimaryKeyConstraint("id"),
        )

    # --------------------------------------------------------------- workers
    if "workers" not in existing:
        op.create_table(
            "workers",
            # uuid4().hex：不要用 hostname:pid（pid 会复用）
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("pid", sa.Integer(), nullable=False),
            sa.Column("host", sa.String(length=64), server_default=sa.text("''"), nullable=False),
            # external | web-inproc
            sa.Column(
                "mode",
                sa.String(length=16),
                server_default=sa.text("'external'"),
                nullable=False,
            ),
            # 'cpu=8,io=4'，纯诊断用
            sa.Column("pools", sa.String(length=64), server_default=sa.text("''"), nullable=False),
            sa.Column(
                "started_at",
                sa.DateTime(),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column(
                "heartbeat_at",
                sa.DateTime(),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    # ------------------------------------------------------------------ 建索引
    # 逐条幂等：已存在则跳过（`create_all` 建过的库索引名完全一致，因此是 no-op）。
    for index_name, table_name, columns, unique, where in INDEXES:
        if index_name in _existing_indexes(table_name):
            continue
        kwargs: dict[str, object] = {"unique": unique}
        if where is not None:
            # ★ 只有传 sqlite_where 才是「部分唯一索引」
            kwargs["sqlite_where"] = sa.text(where)
        op.create_index(index_name, table_name, list(columns), **kwargs)


def downgrade() -> None:
    """回退：先删 `workers` 再删 `jobs`。

    Notes:
        删表会连带删掉表上的索引，因此不必单独 `drop_index`。
        顺序按 `TABLE_ORDER` 逆序（先 workers 后 jobs）：本迁移两表无外键，
        顺序只是为了让「将来若加了引用关系」仍然可逆。
        ⚠️ 本函数会**丢掉全部任务历史**（`jobs` 是调度真相源）。生产回滚前请先
        确认没有 `pending` / `running` 任务，否则这些任务在回滚后会凭空消失。
    """
    if context.is_offline_mode():
        for table_name in reversed(TABLE_ORDER):
            op.drop_table(table_name)
        return

    existing = _existing_tables()
    for table_name in reversed(TABLE_ORDER):
        if table_name in existing:
            op.drop_table(table_name)

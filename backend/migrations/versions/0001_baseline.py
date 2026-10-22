"""基线迁移：v1.16 现状快照（9 张表 + 全部索引）。

语义
====
* **对新库**：完整建出 9 张表与全部索引。等价于 `Base.metadata.create_all`，
  但这里是**显式、可审阅、可 diff** 的 DDL —— 基线是后续所有迁移的地基，
  必须能逐行读懂，不接受 `create_all` 一句话。
* **对老库**（v1.16 及更早：表已存在但没有 `alembic_version`）：本迁移是
  **no-op**。已存在的表跳过建表，已存在的索引跳过建索引，只由 alembic 自己补
  一个 `alembic_version='0001'`，从此纳入版本管理。因此老库
  `upgrade head` 不会报 "table already exists"。

已知/有意的不一致（老库 vs 本脚本）
===================================
老库有两列是历史上用 `ALTER TABLE ADD COLUMN` 补的（见 `app/db.py` 的
`_ADDED_COLUMNS`）。SQLite 的 ALTER 只能加**可空**列，所以老库里：

========================  ==========================  ==========================
列                        老库（ALTER 遗留）           本脚本 / 模型意图（新库）
========================  ==========================  ==========================
`sentences.marks`         可空，`DEFAULT ''`            NOT NULL，`DEFAULT ''`
`media.category_id`       可空                          可空（一致）
========================  ==========================  ==========================

本脚本按「模型意图」建新库；老库保持现状（no-op），**列集合与索引集合完全一致**，
只差 `marks` 的 NOT NULL 这一个约束。这是刻意取舍：为一个历史遗留约束去整表
batch 重建，风险远大于收益，而 ORM 侧 `default=""` 保证不会写入 NULL。
若将来要收敛，另起一版迁移做 batch alter，不要动基线。

关于默认值：**不要打开 `compare_server_default=True`**
=====================================================
下面几列的 DDL 默认值来自本脚本显式写的 `server_default`，模型侧并没有
对应的 `server_default`：

=======================  ============================  =========================
列                       本脚本 DDL                    模型（entities.py）
=======================  ============================  =========================
`created_at`（6 张表）    `DEFAULT CURRENT_TIMESTAMP`    只有 `func.now()`
`notes.updated_at`        `DEFAULT CURRENT_TIMESTAMP`    只有 `func.now()`
`sentences.marks`         `DEFAULT ''`                   只有 Python 端 `default=""`
=======================  ============================  =========================

（6 张表 = categories / media / attempts / users / vocab / translations；
 合计 7 个模型侧声明的 `server_default`。）

`func.now()` 与 Python 端 `default=""` 都是**客户端**行为，不生成 DDL 默认值；
本脚本为了让老库/新库行为一致、并让裸 SQL 插入也安全，才在 DDL 里补上默认值。

`sentences.marks` 的 `DEFAULT ''` 溯源：它来自 v1.14 补列时的
`ALTER TABLE sentences ADD COLUMN marks TEXT DEFAULT ''`（见 `app/db.py` 的
`_ADDED_COLUMNS`），模型侧只有 Python 端 `default=""`、**没有** `server_default`。

⚠️ 因此**不要**用 `compare_server_default=True` 来收紧一致性：开启后**即使是
用本基线刚建好的、完全正确的空库**，`alembic check` 也会永久报一条
`modify_default(sentences.marks)`（实测），门禁会被一条假阳性卡死。
默认值一致性改由 `tests/test_migrations.py` 的
`test_fresh_schema_server_defaults_match_models`（结构，双向 + 白名单）与
`test_migrated_schema_accepts_orm_inserts`（行为冒烟）保证。

另外：`notes.updated_at` 的 `onupdate=func.now()` 是 **ORM 层**行为，SQLite 没有
触发器机制，因此 DDL 里只写 `DEFAULT CURRENT_TIMESTAMP`，**不要**造触发器。

Revision ID: 0001
Revises: -
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import context, op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels = None
depends_on = None

#: 本基线负责的 9 张表。顺序即建表顺序：父表在前，满足外键依赖。
TABLE_ORDER: tuple[str, ...] = (
    "categories",
    "media",
    "sentences",
    "attempts",
    "notes",
    "vocab",
    "settings",
    "users",
    "translations",
)

#: 全部索引：(索引名, 表名, 列元组, 是否唯一)。
#: 与 `models/entities.py` 的 `index=True` / `unique=True` 严格一一对应。
INDEXES: tuple[tuple[str, str, tuple[str, ...], bool], ...] = (
    ("ix_categories_name", "categories", ("name",), True),
    ("ix_categories_sort_order", "categories", ("sort_order",), False),
    ("ix_media_category_id", "media", ("category_id",), False),
    ("ix_sentences_media_id", "sentences", ("media_id",), False),
    ("ix_attempts_sentence_id", "attempts", ("sentence_id",), False),
    ("ix_notes_sentence_id", "notes", ("sentence_id",), True),
    ("ix_vocab_word", "vocab", ("word",), False),
    ("ix_users_username", "users", ("username",), True),
)


def _existing_tables() -> set[str]:
    """目标库中已存在的表名。

    Returns:
        表名集合；**离线模式**（`--sql`，无真实连接可反射）返回空集，
        从而让 `upgrade()` 无条件输出全部 DDL —— 这正是生成 SQL 脚本想要的。
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
    """建表 + 建索引；已存在的表/索引逐项跳过（对老库整体 no-op）。"""
    existing = _existing_tables()

    # ------------------------------------------------------------------ 建表
    if "categories" not in existing:
        op.create_table(
            "categories",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=32), nullable=False),
            sa.Column("sort_order", sa.Integer(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    if "media" not in existing:
        op.create_table(
            "media",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("type", sa.String(length=16), nullable=False),
            sa.Column("original_name", sa.String(length=255), nullable=False),
            sa.Column("file_path", sa.Text(), nullable=False),
            sa.Column("audio_path", sa.Text(), nullable=True),
            sa.Column("size_bytes", sa.Integer(), nullable=False),
            sa.Column("duration_ms", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("progress", sa.Integer(), nullable=False),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("origin", sa.String(length=16), nullable=False),
            sa.Column("source_ref", sa.Text(), nullable=True),
            # 所属分类：删分类时素材回落「未分类」（SET NULL），绝不是 CASCADE。
            sa.Column("category_id", sa.Integer(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["category_id"],
                ["categories.id"],
                name="fk_media_category_id_categories",
                ondelete="SET NULL",
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    if "sentences" not in existing:
        op.create_table(
            "sentences",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("media_id", sa.Integer(), nullable=False),
            sa.Column("idx", sa.Integer(), nullable=False),
            sa.Column("start_ms", sa.Integer(), nullable=False),
            sa.Column("end_ms", sa.Integer(), nullable=False),
            sa.Column("text_en", sa.Text(), nullable=False),
            sa.Column("text_zh", sa.Text(), nullable=False),
            sa.Column("clip_path", sa.Text(), nullable=True),
            sa.Column("is_edited", sa.Boolean(), nullable=False),
            # 原文「易听错」标记（JSON 数组）。老库此列由 ALTER 补出（可空），
            # 新库按模型意图建成 NOT NULL + DEFAULT ''，见模块 docstring。
            sa.Column("marks", sa.Text(), server_default=sa.text("''"), nullable=False),
            sa.ForeignKeyConstraint(
                ["media_id"],
                ["media.id"],
                name="fk_sentences_media_id_media",
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    if "attempts" not in existing:
        op.create_table(
            "attempts",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("sentence_id", sa.Integer(), nullable=False),
            sa.Column("input", sa.Text(), nullable=False),
            sa.Column("accuracy", sa.Float(), nullable=False),
            sa.Column("is_correct", sa.Boolean(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["sentence_id"],
                ["sentences.id"],
                name="fk_attempts_sentence_id_sentences",
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    if "notes" not in existing:
        op.create_table(
            "notes",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("sentence_id", sa.Integer(), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            # onupdate=func.now() 是 ORM 层行为，DDL 只写 DEFAULT，见模块 docstring。
            sa.Column(
                "updated_at",
                sa.DateTime(),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["sentence_id"],
                ["sentences.id"],
                name="fk_notes_sentence_id_sentences",
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    if "vocab" not in existing:
        op.create_table(
            "vocab",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("word", sa.String(length=128), nullable=False),
            sa.Column("lemma", sa.String(length=128), nullable=True),
            sa.Column("phonetic", sa.String(length=128), nullable=True),
            sa.Column("translation", sa.Text(), nullable=True),
            # media_id / sentence_id 刻意**不加外键**：生词要在素材被删后仍保留。
            sa.Column("media_id", sa.Integer(), nullable=True),
            sa.Column("sentence_id", sa.Integer(), nullable=True),
            sa.Column("context", sa.Text(), nullable=True),
            sa.Column("mastered", sa.Boolean(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    if "settings" not in existing:
        op.create_table(
            "settings",
            sa.Column("key", sa.String(length=64), nullable=False),
            sa.Column("value", sa.Text(), nullable=False),
            sa.PrimaryKeyConstraint("key"),
        )

    if "users" not in existing:
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("username", sa.String(length=64), nullable=False),
            sa.Column("password_hash", sa.String(length=255), nullable=False),
            sa.Column("salt", sa.String(length=64), nullable=False),
            sa.Column("iterations", sa.Integer(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column("last_login_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )

    if "translations" not in existing:
        op.create_table(
            "translations",
            sa.Column("key", sa.String(length=64), nullable=False),
            sa.Column("source_text", sa.Text(), nullable=False),
            sa.Column("target_text", sa.Text(), nullable=False),
            sa.Column("engine", sa.String(length=32), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("key"),
        )

    # ------------------------------------------------------------------ 建索引
    # 逐条幂等：老库若恰好缺某个索引（例如手工改过），这里会顺手补齐；
    # 已有则跳过，绝不报 "index already exists"。
    for index_name, table_name, columns, unique in INDEXES:
        if index_name in _existing_indexes(table_name):
            continue
        op.create_index(index_name, table_name, list(columns), unique=unique)


def downgrade() -> None:
    """回退到空库：先删索引，再按外键依赖逆序删表。

    ⚠️ **仅用于本地演练 / CI 验证可逆性**。生产环境永远不会走这里 ——
    回退到 base 意味着删掉全部数据（这正是「只允许在副本上演练」的原因）。
    因此本函数不做任何数据保留或兼容性补偿。
    """
    if context.is_offline_mode():
        # 离线模式无法反射，直接全量输出。
        for index_name, table_name, _columns, _unique in reversed(INDEXES):
            op.drop_index(index_name, table_name=table_name)
        for table_name in reversed(TABLE_ORDER):
            op.drop_table(table_name)
        return

    existing = _existing_tables()

    for index_name, table_name, _columns, _unique in reversed(INDEXES):
        if index_name in _existing_indexes(table_name):
            op.drop_index(index_name, table_name=table_name)

    # 逆序：translations/users/settings/vocab/notes/attempts/sentences/media/categories
    for table_name in reversed(TABLE_ORDER):
        if table_name in existing:
            op.drop_table(table_name)

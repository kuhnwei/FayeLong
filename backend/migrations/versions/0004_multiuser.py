"""v1.16.2 迁移：单用户门禁 → 多用户 + admin 管理。

语义
====
* **users 加 3 列**：`role`（user/admin）、`is_active`（软删除/停用）、
  `token_version`（会话吊销版本号）。均 `NOT NULL` + 非空常量默认。
* **4 张个人表加 `user_id`**：`attempts / notes / vocab / practice_sessions`。
  `vocab` 刻意不加外键（与 `media_id` / `sentence_id` 同口径：生词在素材被删后
  仍保留，且避免删用户级联删生词的歧义）；其余 3 张 `ON DELETE CASCADE`。
* **新增 `sentence_marks` 表**：把个人「易听错」标注从共享的 `sentences.marks`
  迁出，`(user_id, sentence_id)` 唯一。
* **`notes.sentence_id` 唯一约束 → `(user_id, sentence_id)` 唯一**：旧的单列唯一
  索引 `ix_notes_sentence_id` 降级为非唯一，新增 `uq_notes_user_sentence`。
* **数据回填**：老库唯一的账号回填到所有个人行的 `user_id`，`sentences.marks`
  迁到 `sentence_marks` 后清空。

为什么「先反射、再动作」且双轨收敛
==================================
与 `0002` / `0003` 同一理由：打包版就地升级走 `init_db() → create_all`，
`create_all` 会用**新模型**先建出带 `user_id` 的表与 `sentence_marks`，再跑
`upgrade head` 时若无条件 `ADD COLUMN` / `CREATE INDEX` 就会炸。因此每一步都先
反射判存在，`upgrade` 对「已 `create_all` 过」的库是 no-op。

**本迁移唯一的「约束级」操作是 notes 唯一索引切换**，但它不是表级 UNIQUE 约束，
而是显式唯一索引（`ix_notes_sentence_id`），SQLite 里等价于 `DROP INDEX +
CREATE INDEX`，因此同样能被 `db.py` 的 `_ensure_multiuser_data()` 自愈路径表达
—— 两条轨最终指向同一结构。

Revision ID: 0004
Revises: 0003
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import context, op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels = None
depends_on = None


#: 需要加 `user_id` 且带外键的表（vocab 例外，见模块 docstring）。
_USER_FK_TABLES: tuple[str, ...] = ("attempts", "notes", "practice_sessions")

#: 全部需要加 `user_id` 的表（含 vocab）。
_USER_ID_TABLES: tuple[str, ...] = ("attempts", "notes", "vocab", "practice_sessions")


def _existing_tables() -> set[str]:
    """目标库中已存在的表名（离线模式返回空集，从而全量输出 DDL）。"""
    if context.is_offline_mode():
        return set()
    return set(sa.inspect(op.get_bind()).get_table_names())


def _existing_indexes(table: str) -> set[str]:
    """目标库中某表已存在的索引名集合（离线模式返回空集，同上）。"""
    if context.is_offline_mode():
        return set()
    inspector = sa.inspect(op.get_bind())
    return {index["name"] for index in inspector.get_indexes(table) if index["name"]}


def _existing_columns(table: str) -> set[str]:
    """目标库中某表已存在的列名集合（离线模式返回空集，同上）。"""
    if context.is_offline_mode():
        return set()
    inspector = sa.inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns(table)}


def _index_unique(table: str, name: str) -> bool | None:
    """某索引是否唯一；索引不存在时返回 None（离线模式恒 None）。"""
    if context.is_offline_mode():
        return None
    for row in op.get_bind().exec_driver_sql(f"PRAGMA index_list({table})"):
        if row[1] == name:
            return bool(row[2])
    return None


def _add_user_id_column(table: str, *, with_fk: bool) -> None:
    """给个人表加 `user_id` 可空列（SQLite 的 ALTER 只能加可空列）。

    `with_fk` 时用原始 SQL 内联 `REFERENCES users(id)`：SQLite 允许
    `ALTER TABLE ADD COLUMN` 带 REFERENCES（启用外键时要求新列默认 NULL —— 正好
    满足，因为我们刻意 nullable）。**不写 ON DELETE**：SQLite 的 ALTER 无法表达
    它（会被反射成 NO ACTION），而模型侧也刻意不声明 ondelete（软删除策略）。
    """
    if "user_id" in _existing_columns(table):
        return
    if with_fk:
        op.execute(f"ALTER TABLE {table} ADD COLUMN user_id INTEGER REFERENCES users(id)")
    else:
        op.execute(f"ALTER TABLE {table} ADD COLUMN user_id INTEGER")


def upgrade() -> None:
    """加列 / 建表 / 切索引 / 回填（逐项幂等）。"""
    existing = _existing_tables()

    # ----------------------------------------------------------- users 加 3 列
    users_columns = _existing_columns("users")
    if "role" not in users_columns:
        op.add_column(
            "users",
            sa.Column("role", sa.String(16), nullable=False, server_default=sa.text("'user'")),
        )
    if "is_active" not in users_columns:
        op.add_column(
            "users",
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        )
    if "token_version" not in users_columns:
        op.add_column(
            "users",
            sa.Column("token_version", sa.Integer(), nullable=False, server_default=sa.text("0")),
        )

    # --------------------------------------------------- 4 张个人表加 user_id
    for table in _USER_FK_TABLES:
        _add_user_id_column(table, with_fk=True)
    _add_user_id_column("vocab", with_fk=False)

    # --------------------------------------------------------- sentence_marks
    if "sentence_marks" not in existing:
        op.create_table(
            "sentence_marks",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("sentence_id", sa.Integer(), nullable=False),
            sa.Column("ranges", sa.Text(), nullable=False, server_default=sa.text("''")),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["sentence_id"], ["sentences.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )

    # --------------------------------------------------------- notes 索引切换
    # 老库的 `ix_notes_sentence_id` 是唯一索引，降级为非唯一；再补联合唯一索引。
    unique = _index_unique("notes", "ix_notes_sentence_id")
    if unique is True:
        op.drop_index("ix_notes_sentence_id", table_name="notes")
        op.create_index("ix_notes_sentence_id", "notes", ["sentence_id"], unique=False)
    elif unique is None and "ix_notes_sentence_id" not in _existing_indexes("notes"):
        # 离线模式或索引缺失：无条件建非唯一（幂等）。
        op.create_index("ix_notes_sentence_id", "notes", ["sentence_id"], unique=False)

    if "uq_notes_user_sentence" not in _existing_indexes("notes"):
        op.create_index("uq_notes_user_sentence", "notes", ["user_id", "sentence_id"], unique=True)
    if "ix_notes_user_id" not in _existing_indexes("notes"):
        op.create_index("ix_notes_user_id", "notes", ["user_id"], unique=False)

    # --------------------------------------------------------- 补 user_id 索引
    for index_name, table_name in (
        ("ix_attempts_user_id", "attempts"),
        ("ix_vocab_user_id", "vocab"),
        ("ix_practice_sessions_user_id", "practice_sessions"),
    ):
        if index_name not in _existing_indexes(table_name):
            op.create_index(index_name, table_name, ["user_id"], unique=False)

    # ------------------------------------------------------ sentence_marks 索引
    for index_name, columns, unique_flag in (
        ("ix_sentence_marks_user_id", ["user_id"], False),
        ("ix_sentence_marks_sentence_id", ["sentence_id"], False),
        ("uq_sentence_marks_user_sentence", ["user_id", "sentence_id"], True),
    ):
        if index_name not in _existing_indexes("sentence_marks"):
            op.create_index(index_name, "sentence_marks", columns, unique=unique_flag)

    # ------------------------------------------------------------- 数据回填
    if context.is_offline_mode():
        return
    bind = op.get_bind()
    legacy = bind.exec_driver_sql("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()
    if legacy is None:
        return  # 全新空库：无可回填，交给 setup 引导建 admin
    legacy_id = int(legacy[0])

    for table in _USER_ID_TABLES:
        bind.exec_driver_sql(
            f"UPDATE {table} SET user_id = ? WHERE user_id IS NULL", (legacy_id,)
        )

    bind.exec_driver_sql(
        "INSERT INTO sentence_marks(user_id, sentence_id, ranges) "
        "SELECT ?, id, marks FROM sentences "
        "WHERE marks IS NOT NULL AND marks <> '' "
        "AND NOT EXISTS (SELECT 1 FROM sentence_marks sm WHERE sm.sentence_id = sentences.id)",
        (legacy_id,),
    )
    bind.exec_driver_sql("UPDATE sentences SET marks = ''")


def downgrade() -> None:
    """回退到 0003：删 sentence_marks、删 user_id 列、恢复 notes 唯一索引与 marks。

    ⚠️ **仅演练用**：多用户的 marks 合并回 `sentences.marks` 会丢失归属（只取
    每个句子的第一份），生产环境永不回退。
    """
    if context.is_offline_mode():
        # 离线模式只输出逆向 DDL，不碰数据。
        op.drop_index("uq_sentence_marks_user_sentence", table_name="sentence_marks")
        op.drop_index("ix_sentence_marks_user_id", table_name="sentence_marks")
        op.drop_index("ix_sentence_marks_sentence_id", table_name="sentence_marks")
        op.drop_table("sentence_marks")
        return

    bind = op.get_bind()

    # 1. marks 合并回 sentences（每个句子取第一份）。
    if "sentence_marks" in _existing_tables():
        rows = bind.exec_driver_sql(
            "SELECT sentence_id, ranges FROM sentence_marks ORDER BY id"
        ).fetchall()
        for sentence_id, ranges in rows:
            bind.exec_driver_sql(
                "UPDATE sentences SET marks = ? WHERE id = ?", (ranges, sentence_id)
            )
        # 2. 删 sentence_marks 表（先删索引）。
        for name in (
            "uq_sentence_marks_user_sentence",
            "ix_sentence_marks_user_id",
            "ix_sentence_marks_sentence_id",
        ):
            if name in _existing_indexes("sentence_marks"):
                op.drop_index(name, table_name="sentence_marks")
        op.drop_table("sentence_marks")

    # 3. 先删掉引用 user_id 的索引（batch 重建表时不会自动跳过它们，否则
    #    drop_column 之后重建 `ix_*_user_id` 会因「列不存在」而失败）。
    for index_name, table_name in (
        ("ix_attempts_user_id", "attempts"),
        ("ix_notes_user_id", "notes"),
        ("uq_notes_user_sentence", "notes"),
        ("ix_vocab_user_id", "vocab"),
        ("ix_practice_sessions_user_id", "practice_sessions"),
    ):
        if index_name in _existing_indexes(table_name):
            op.drop_index(index_name, table_name=table_name)

    # 4. batch 删列（引用被删列的外键随重建表一并消失）。
    for table in _USER_ID_TABLES:
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_column("user_id")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("role")
        batch_op.drop_column("is_active")
        batch_op.drop_column("token_version")

    # 5. 恢复 notes 的 sentence_id 唯一索引（upgrade 时降级为非唯一）。
    if "ix_notes_sentence_id" in _existing_indexes("notes"):
        op.drop_index("ix_notes_sentence_id", table_name="notes")
    op.create_index("ix_notes_sentence_id", "notes", ["sentence_id"], unique=True)

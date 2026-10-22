"""P4-3 迁移：新增 IELTS 题库与作答的 6 张表 + 写作批改缓存 1 张表。

语义
====
* **对新库**：建出 `papers / sections / passages / questions / practice_sessions /
  responses / writing_grade_cache` 与全部 7 个显式索引。
* **对老库 / 已 `create_all` 过的库**：`upgrade head` 必须是 **no-op**，绝不报
  "table already exists"。理由与 `0002` 完全一致 —— 打包版就地升级走
  `main.lifespan → init_db() → Base.metadata.create_all()`，`create_all` 会先把
  新表建出来；之后运维/`alembic check` 再跑 `upgrade head` 时若无条件
  `create_table`，就会在**一个结构完全正常的库**上炸掉。因此建表/建索引一律先反射。

* **老表一个字节都不动**：本迁移只 `CREATE TABLE` 新表 + 建索引，不 `ALTER` 任何
  既有表，也不 `UPDATE` 任何数据。验证方式：拷 `data/app.db` 到临时目录，比对 9 张
  老表的 `PRAGMA table_info` 与行数快照前后完全一致（`tests/test_migrations.py` 的
  `test_real_database_copy_upgrade_keeps_everything` 逐列守着）。

设计取舍（写在这里，免得下次有人"顺手优化"）
==========================================
1. **JSON 列用 `sa.JSON`**：SQLite 里落成 `TEXT` 亲和，但反射回来的类型名仍是
   `JSON`，因此「结构与模型零差异」的比对两侧一致（实测：
   `PRAGMA table_info` 的 type 为 `JSON`）。用 `Text` 也能跑，但那样模型里就得
   到处 `json.dumps/loads`，多一处手写序列化就多一个形状漂移的来源。
2. **`(session_id, question_id)` 用 `UniqueConstraint` 而不是命名唯一索引**：
   它承担「一题一次作答、暂存走 UPDATE」的语义，是**表约束**而不是查询辅助索引。
   SQLite 会为它建 `sqlite_autoindex_*`（本项目 `test_migrations.py` 的索引比对
   已显式过滤这类自动索引）。行为侧另有专项断言：重复插入同一 `(session, question)`
   必须 `IntegrityError`。
3. **对外引用不加外键**（`sections.media_id` / `questions.ref_sentence_id`）：
   与 `jobs.ref_id` 同一条理由（多态引用 + 删素材的清理策略要由应用层决定）。
   内部父子关系全部 `ON DELETE CASCADE`。
4. **刻意不建 `CHECK` 约束**：`papers.mode` / `sections.kind` / `sessions.status`
   的取值集合会随题型与流程演进（P4-3 之后还有 P4-4、P5 的考试 UI），把枚举钉进
   DDL 会让每次扩展都要重建表（SQLite 不支持改 CHECK）。取值合法性由 pydantic
   schema 与 `Literal` 收口 —— 那里改一行就生效，且报错更友好。

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import context, op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | None = "0002"
branch_labels = None
depends_on = None

#: 本迁移负责建的表（顺序即建表顺序，**必须**满足外键依赖：先父后子）。
TABLE_ORDER: tuple[str, ...] = (
    "papers",
    "sections",
    "passages",
    "questions",
    "practice_sessions",
    "responses",
    "writing_grade_cache",
)

#: 全部显式索引：(索引名, 表名, 列元组)。SQLite 不会给外键列自动建索引，
#: 而这几列是「按父行取子行」的唯一入口（`GET /api/papers/{id}` 会用到）。
INDEXES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("ix_sections_paper_id", "sections", ("paper_id",)),
    ("ix_passages_section_id", "passages", ("section_id",)),
    ("ix_questions_section_id", "questions", ("section_id",)),
    ("ix_questions_passage_id", "questions", ("passage_id",)),
    ("ix_practice_sessions_paper_id", "practice_sessions", ("paper_id",)),
    ("ix_responses_session_id", "responses", ("session_id",)),
    ("ix_responses_question_id", "responses", ("question_id",)),
)


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


def upgrade() -> None:
    """建 7 张新表与 7 个索引（逐项幂等）。"""
    existing = _existing_tables()

    # ----------------------------------------------------------------- papers
    if "papers" not in existing:
        op.create_table(
            "papers",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False),
            # full_mock | section_drill
            sa.Column("mode", sa.String(length=16), nullable=False),
            sa.Column("source", sa.String(length=255), nullable=False),
            # JSON 数组：标签
            sa.Column("tags", sa.JSON(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    # --------------------------------------------------------------- sections
    if "sections" not in existing:
        op.create_table(
            "sections",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("paper_id", sa.Integer(), nullable=False),
            # listening | reading | writing | speaking
            sa.Column("kind", sa.String(length=16), nullable=False),
            sa.Column("ordinal", sa.Integer(), nullable=False),
            # 0 = 不限时
            sa.Column("time_limit_sec", sa.Integer(), nullable=False),
            sa.Column("instructions", sa.Text(), nullable=False),
            # 听力复用现有音频（media.id）；**刻意不加外键**（见模块 docstring 第 3 条）
            sa.Column("media_id", sa.Integer(), nullable=True),
            sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )

    # --------------------------------------------------------------- passages
    if "passages" not in existing:
        op.create_table(
            "passages",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("section_id", sa.Integer(), nullable=False),
            sa.Column("ordinal", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("body_md", sa.Text(), nullable=False),
            sa.ForeignKeyConstraint(["section_id"], ["sections.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )

    # -------------------------------------------------------------- questions
    if "questions" not in existing:
        op.create_table(
            "questions",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("section_id", sa.Integer(), nullable=False),
            sa.Column("passage_id", sa.Integer(), nullable=True),
            sa.Column("ordinal", sa.Integer(), nullable=False),
            # 题型 code（与 services/question_types 注册表同名，决定判分器）
            sa.Column("type", sa.String(length=32), nullable=False),
            sa.Column("stem", sa.Text(), nullable=False),
            # JSON 数组：选项
            sa.Column("options", sa.JSON(), nullable=False),
            # JSON：标准答案 / 评分标准。**永不下发**
            sa.Column("answer", sa.JSON(), nullable=False),
            sa.Column("explanation", sa.Text(), nullable=False),
            # 听写题复用现有句子（sentences.id）；**刻意不加外键**
            sa.Column("ref_sentence_id", sa.Integer(), nullable=True),
            sa.ForeignKeyConstraint(["section_id"], ["sections.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["passage_id"], ["passages.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )

    # ------------------------------------------------------ practice_sessions
    if "practice_sessions" not in existing:
        op.create_table(
            "practice_sessions",
            sa.Column("id", sa.Integer(), nullable=False),
            # NULL = 无试卷的自由练习（draft_kind 说明形态）
            sa.Column("paper_id", sa.Integer(), nullable=True),
            sa.Column("draft_kind", sa.String(length=32), nullable=True),
            sa.Column(
                "started_at",
                sa.DateTime(),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column("submitted_at", sa.DateTime(), nullable=True),
            # in_progress | grading | graded | degraded
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("time_spent_sec", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )

    # -------------------------------------------------------------- responses
    if "responses" not in existing:
        op.create_table(
            "responses",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("session_id", sa.Integer(), nullable=False),
            sa.Column("question_id", sa.Integer(), nullable=False),
            # JSON：用户作答
            sa.Column("user_answer", sa.JSON(), nullable=False),
            # ★ 可空：NULL = 尚未判分（异步题在等 grade_writing job），
            #   与「判了 0 分」必须区分得出来。
            sa.Column("score", sa.Float(), nullable=True),
            sa.Column("max_score", sa.Float(), nullable=True),
            sa.Column("graded_at", sa.DateTime(), nullable=True),
            # JSON：判分明细
            sa.Column("detail", sa.JSON(), nullable=False),
            sa.ForeignKeyConstraint(
                ["session_id"], ["practice_sessions.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(["question_id"], ["questions.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            # 「一题一次作答」：暂存走 UPDATE，靠这条约束在数据库侧兜住
            sa.UniqueConstraint(
                "session_id", "question_id", name="uq_responses_session_question"
            ),
        )

    # --------------------------------------------------- writing_grade_cache
    if "writing_grade_cache" not in existing:
        op.create_table(
            "writing_grade_cache",
            # sha1(question_id + "\x00" + normalized_response)
            sa.Column("content_hash", sa.String(length=64), nullable=False),
            sa.Column("question_id", sa.Integer(), nullable=True),
            # JSON：GradeResult.as_dict()
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("content_hash"),
        )

    # ------------------------------------------------------------------ 建索引
    for index_name, table_name, columns in INDEXES:
        if index_name in _existing_indexes(table_name):
            continue
        op.create_index(index_name, table_name, list(columns), unique=False)


def downgrade() -> None:
    """回退：按建表逆序删掉 7 张表。

    Notes:
        删表会连带删掉表上的索引，因此不必单独 `drop_index`。
        ⚠️ 本函数会**丢掉全部 IELTS 题库与作答记录**（`papers` 是题库的根）。
        老表（media / sentences / attempts …）不受影响 —— 本迁移从未碰过它们。
    """
    if context.is_offline_mode():
        for table_name in reversed(TABLE_ORDER):
            op.drop_table(table_name)
        return

    existing = _existing_tables()
    for table_name in reversed(TABLE_ORDER):
        if table_name in existing:
            op.drop_table(table_name)

"""数据库表模型（对应设计文档 §8）。"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Category(Base):
    """媒体库分类（单层，互斥）。

    —— 每个素材至多属于一个分类（`media.category_id`），`NULL` 表示「未分类」。
    「未分类」**不建真实记录**，一律用 `category_id IS NULL` 表达（见规格 §2.3）。
    """

    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Media(Base):
    """导入的音频/视频素材。"""

    __tablename__ = "media"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    type: Mapped[str] = mapped_column(String(16), default="audio")  # audio / video
    original_name: Mapped[str] = mapped_column(String(255), default="")  # 原始文件名
    file_path: Mapped[str] = mapped_column(Text)          # 原始文件（视频也保留）
    audio_path: Mapped[str | None] = mapped_column(Text, nullable=True)  # 转码后 16k 单声道 wav
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    # pending / transcoding / ready / asr / translating / clipping / done / failed
    status: Mapped[str] = mapped_column(String(16), default="pending")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    origin: Mapped[str] = mapped_column(String(16), default="upload")  # upload / inbox
    source_ref: Mapped[str | None] = mapped_column(Text, nullable=True)  # 收件箱来源绝对路径
    # 所属分类（单层互斥）；NULL = 未分类。删除分类时素材回落未分类（绝不是 CASCADE）。
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    sentences: Mapped[list["Sentence"]] = relationship(
        back_populates="media", cascade="all, delete-orphan"
    )


class Sentence(Base):
    """按句切分后的学习单元。"""

    __tablename__ = "sentences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    media_id: Mapped[int] = mapped_column(
        ForeignKey("media.id", ondelete="CASCADE"), index=True
    )
    idx: Mapped[int] = mapped_column(Integer, default=0)
    start_ms: Mapped[int] = mapped_column(Integer, default=0)
    end_ms: Mapped[int] = mapped_column(Integer, default=0)
    text_en: Mapped[str] = mapped_column(Text, default="")
    text_zh: Mapped[str] = mapped_column(Text, default="")
    clip_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_edited: Mapped[bool] = mapped_column(Boolean, default=False)
    # 原文「易听错」标记（v1.14）：JSON 数组，元素为闭区间 [起始词序, 结束词序]（0 基）
    # 契约：**永不写 NULL**。这里只有 Python 端 default=""（没有 server_default），
    # 但 Alembic 基线（migrations/versions/0001_baseline.py）建新库时给了
    # `NOT NULL DEFAULT ''`；老库该列由 v1.14 的 ALTER 补出、允许 NULL，属已知遗留，
    # 收敛要另起一版迁移。改这一列前先读基线的「关于默认值」段。
    marks: Mapped[str] = mapped_column(Text, default="")

    media: Mapped[Media] = relationship(back_populates="sentences")
    note: Mapped["Note | None"] = relationship(
        back_populates="sentence", cascade="all, delete-orphan", uselist=False
    )
    attempts: Mapped[list["Attempt"]] = relationship(
        back_populates="sentence", cascade="all, delete-orphan"
    )


class Attempt(Base):
    """一次听写尝试记录。"""

    __tablename__ = "attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sentence_id: Mapped[int] = mapped_column(
        ForeignKey("sentences.id", ondelete="CASCADE"), index=True
    )
    input: Mapped[str] = mapped_column(Text, default="")
    accuracy: Mapped[float] = mapped_column(Float, default=0.0)
    is_correct: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    sentence: Mapped[Sentence] = relationship(back_populates="attempts")


class Note(Base):
    """句子笔记（每句至多一条）。"""

    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sentence_id: Mapped[int] = mapped_column(
        ForeignKey("sentences.id", ondelete="CASCADE"), unique=True, index=True
    )
    content: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    sentence: Mapped[Sentence] = relationship(back_populates="note")


class Vocab(Base):
    """生词本。"""

    __tablename__ = "vocab"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    word: Mapped[str] = mapped_column(String(128), index=True)
    lemma: Mapped[str | None] = mapped_column(String(128), nullable=True)
    phonetic: Mapped[str | None] = mapped_column(String(128), nullable=True)
    translation: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sentence_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    context: Mapped[str | None] = mapped_column(Text, nullable=True)
    mastered: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Setting(Base):
    """键值配置。"""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class User(Base):
    """站点账号（v1.12 登录门禁）。

    当前是**单账号门禁**：本表通常只有一行 —— 全局共用一份学习数据。
    不存明文密码，只存 PBKDF2 派生值 + 盐 + 迭代次数（迭代次数落库，
    将来调高默认值不会让老账号失效）。
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))  # PBKDF2-HMAC-SHA256 十六进制
    salt: Mapped[str] = mapped_column(String(64))            # 十六进制盐
    iterations: Mapped[int] = mapped_column(Integer, default=200_000)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Translation(Base):
    """在线翻译结果缓存：同一句不重复请求，节省免费额度。"""

    __tablename__ = "translations"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)  # sha1(src|tgt|text)
    source_text: Mapped[str] = mapped_column(Text, default="")
    target_text: Mapped[str] = mapped_column(Text, default="")
    engine: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ---------------------------------------------------------------------------
# P3-2：任务调度真相源 + worker 进程心跳（见 docs/DD-001-P3-2-jobs与分池-系统设计.md §3）
# ---------------------------------------------------------------------------


class Job(Base):
    """一个可被 worker 认领的调度单元（stage job）。

    设计要点（逐条对应 DD-001 §3.1 / §3.2 / §4.3，改代码前务必先读）：

    * **`status` 只有 4 个取值**：`pending` / `running` / `done` / `failed`。
      **没有 `cancelled`** —— 取消 = 删行（删媒体时由应用层 `purge_for_media` 清理）。
    * **`progress` 是「阶段内」进度 0-100**，不是全局进度；全局进度在
      `media.progress`（由 `media._scale()` 映射）。两处不要混。
    * **`attempts` 兼作 fencing token**：claim 时 +1，之后所有写回都带
      `WHERE id=? AND worker_id=? AND attempts=?`，rowcount=0 即自杀。
    * **`ref_id` 非空**：`uq_jobs_active` 是**部分唯一索引**，NULL 在唯一索引里
      互不相等，会整体绕过约束。本阶段指向 `media.id`，P4 起 `grade_writing`
      指向 `responses.id`（多态引用 → 刻意**不加外键**）。
    * **不加 `updated_at`**：`heartbeat_at` 已能回答「最后一次有动静是什么时候」，
      而 `updated_at` 要求每条 UPDATE 都记得写它，漏一处就变成会撒谎的字段。
    * **不加 `pool`**：`kind → pool` 是编译期常量映射（`services/jobs.py::KIND_POOL`），
      入库等于存第二份真相。
    """

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: 见 services/jobs.py 的 KIND_* 常量，禁止裸字符串
    kind: Mapped[str] = mapped_column(String(32))
    #: 多态引用：本阶段 = media.id；P4 = responses.id。**非空**（部分唯一索引依赖）
    ref_id: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(
        String(16), default="pending", server_default=text("'pending'")
    )
    #: ★ 阶段内进度 0-100（不是全局进度）
    progress: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0")
    )
    #: 最近一次失败原因，截断 500 字
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: 越大越优先
    priority: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0")
    )
    #: JSON 文本，本阶段恒为 "{}"；读取一律 json.loads(job.payload or "{}")
    payload: Mapped[str] = mapped_column(
        Text, default="{}", server_default=text("'{}'")
    )
    #: 兼作 fencing token（见 DD-001 §4.3 第 2 条）
    attempts: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0")
    )
    #: 归属执行者；pending 时为 NULL
    worker_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: 租约：claim 时置 now，执行中每 job_lease_interval_sec 续一次
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    #: 首次 claim 时间（COALESCE 写入，重试不覆盖）
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    #: done / failed 时间
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','running','done','failed')",
            name="ck_jobs_status",
        ),
        CheckConstraint(
            "progress BETWEEN 0 AND 100",
            name="ck_jobs_progress",
        ),
        # 认领：status 等值过滤走索引；priority DESC, id ASC 是「高优先、先进先出」
        Index("ix_jobs_claim", "status", "priority", "id"),
        # ★ 入队幂等：**部分**唯一索引（只约束活跃行）。
        # ⚠️ 绝不能写成普通 unique=True —— 那会让「一个媒体一生只能跑一次任务」，
        #    且第二次 enqueue 静默无效（不报错），属于致命 bug（DD-001 §9 R1）。
        Index(
            "uq_jobs_active",
            "kind",
            "ref_id",
            unique=True,
            sqlite_where=text("status IN ('pending','running')"),
        ),
        # 全量索引：查某媒体的任务历史 / 删媒体时清任务（部分索引只覆盖活跃行）
        Index("ix_jobs_kind_ref", "kind", "ref_id"),
        # 恢复扫描：WHERE status='running' AND heartbeat_at < ?
        Index("ix_jobs_status_heartbeat", "status", "heartbeat_at"),
    )


class Worker(Base):
    """worker 进程心跳行（每进程一行，`id` 是 `uuid4().hex`）。

    它同时解决三件事：① web 判断「独立 worker 是否在线」（`web_inproc_worker=auto`
    的接管依据）；② 崩溃检测不必逐 job 高频写；③ `/api/health` 能给出可判断的现场。

    * 每 10s 由心跳线程一条 `UPDATE ... SET heartbeat_at=CURRENT_TIMESTAMP`；
    * 在线判定：`heartbeat_at > now - worker_ttl`（默认 30s）；
    * 启动时清理 10 分钟前的死行；正常退出时删自己那行。
    * **不要用 `hostname:pid` 当 id**：pid 会复用，重启后旧行可能「看起来还活着」。
    """

    __tablename__ = "workers"

    #: uuid4().hex（64 字符列宽足够）
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    pid: Mapped[int] = mapped_column(Integer)
    host: Mapped[str] = mapped_column(String(64), default="", server_default=text("''"))
    #: external | web-inproc
    mode: Mapped[str] = mapped_column(
        String(16), default="external", server_default=text("'external'")
    )
    #: 'cpu=8,io=4'，纯诊断用（不参与任何容量决策）
    pools: Mapped[str] = mapped_column(String(64), default="", server_default=text("''"))
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (Index("ix_workers_heartbeat", "heartbeat_at"),)


# ---------------------------------------------------------------------------
# P4-3：IELTS 题库与作答（ADR-001 §5.5.2 的 6 张新表）
#
# 三条**不可谈判**的边界（改这个区块前先读 ADR-001 §5.5.2 与 Q4）：
#   1. **不改 `media` / `sentences` / `attempts` 任何一个字段**。听力 section 复用现有
#      音频靠 `sections.media_id`，听写题复用现有句子靠 `questions.ref_sentence_id`，
#      历史数据零迁移、零风险。
#   2. `options` / `answer` / `user_answer` / `detail` 一律 **JSON 列**。不同题型的答案
#      形状差异极大（"A" / ["A","C"] / [可接受答案] / 范文+评分标准），硬拆列会不断
#      `ALTER TABLE` —— 那正是 D1 债务的成因。
#   3. **`media.status` 状态机与作答会话状态是两条独立的轴，不许合并**：前者是
#      「素材处理进度」，后者是「考试作答进度」，生命周期与触发者完全不同。
#
# ⚠️ 对外引用（`sections.media_id` / `questions.ref_sentence_id`）**刻意不加外键**，
#    与 `jobs.ref_id` 同一条理由：加 FK 后删素材/删句只有两个选择 —— 级联删掉试卷
#    结构，或 SET NULL 留下指向虚无的题。删素材时的清理应由应用层显式做（IELTS 的
#    UI 落地时再补，本阶段没有入口能删它）。内部父子关系（paper→section→passage→
#    question、session→response）则**全部**带 FK + CASCADE：它们是一个整体，
#    父行没了子行必然无意义。
# ---------------------------------------------------------------------------


class Paper(Base):
    """试卷（IELTS 套题的顶层容器）。

    Attributes:
        mode: `full_mock`（整套模考）/ `section_drill`（单项练习）。
        tags: JSON 数组（标签字符串），**永不为 NULL**（默认 `[]`），
            这样前端不必判空，也不会出现 `NULL` 与 `[]` 两种「空」。
    """

    __tablename__ = "papers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    #: full_mock | section_drill
    mode: Mapped[str] = mapped_column(String(16), default="full_mock")
    #: 出处（如 "Cambridge 4 Test 1"），纯展示用
    source: Mapped[str] = mapped_column(String(255), default="")
    #: JSON 数组：标签
    tags: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    sections: Mapped[list["Section"]] = relationship(
        back_populates="paper", cascade="all, delete-orphan"
    )


class Section(Base):
    """分卷（听力 / 阅读 / 写作 / 口语）。

    Attributes:
        kind: `listening` | `reading` | `writing` | `speaking`。
        ordinal: 卷内顺序（0 基）。
        time_limit_sec: 限时（秒）；0 = 不限时。
        media_id: **听力** section 复用的现有音频（指向 `media.id`，**无外键**，
            理由见本区块顶部）。阅读/写作 section 为 NULL。
    """

    __tablename__ = "sections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    paper_id: Mapped[int] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), index=True
    )
    #: listening | reading | writing | speaking
    kind: Mapped[str] = mapped_column(String(16), default="")
    ordinal: Mapped[int] = mapped_column(Integer, default=0)
    #: 限时（秒）；0 = 不限时。限时落在 section 上，**不污染** media 状态机。
    time_limit_sec: Mapped[int] = mapped_column(Integer, default=0)
    instructions: Mapped[str] = mapped_column(Text, default="")
    #: 听力 section 复用的音频（media.id）；无外键
    media_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    paper: Mapped[Paper] = relationship(back_populates="sections")
    passages: Mapped[list["Passage"]] = relationship(
        back_populates="section", cascade="all, delete-orphan"
    )
    questions: Mapped[list["Question"]] = relationship(
        back_populates="section", cascade="all, delete-orphan"
    )


class Passage(Base):
    """阅读文章（`body_md` 存 Markdown 正文）。"""

    __tablename__ = "passages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    section_id: Mapped[int] = mapped_column(
        ForeignKey("sections.id", ondelete="CASCADE"), index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(255), default="")
    body_md: Mapped[str] = mapped_column(Text, default="")

    section: Mapped[Section] = relationship(back_populates="passages")
    questions: Mapped[list["Question"]] = relationship(back_populates="passage")


class Question(Base):
    """一道题。

    Attributes:
        type: 题型 `code`（与 `services/question_types` 的注册表同名，
            如 `dictation` / `writing` / `reading_mcq`）。**判分入口由它决定**，
            因此它不是一个自由的展示字段。
        answer: JSON，**标准答案 + 评分标准**。⚠️ **绝不下发给客户端**
            （见 `api/papers.py` 的「answer 不下发」铁律）。
        ref_sentence_id: `type='dictation'` 时指向 `sentences.id`（无外键，理由同上）。
    """

    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    section_id: Mapped[int] = mapped_column(
        ForeignKey("sections.id", ondelete="CASCADE"), index=True
    )
    passage_id: Mapped[int | None] = mapped_column(
        ForeignKey("passages.id", ondelete="CASCADE"), nullable=True, index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, default=0)
    #: 题型 code（决定判分器与前端组件）
    type: Mapped[str] = mapped_column(String(32), default="")
    stem: Mapped[str] = mapped_column(Text, default="")
    #: JSON 数组：选项（选择题）。非选择题为 []
    options: Mapped[list] = mapped_column(JSON, default=list)
    #: JSON：标准答案 / 评分标准。**永不下发**
    answer: Mapped[dict] = mapped_column(JSON, default=dict)
    explanation: Mapped[str] = mapped_column(Text, default="")
    #: 听写题复用的现有句子（sentences.id）；无外键
    ref_sentence_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    section: Mapped[Section] = relationship(back_populates="questions")
    passage: Mapped[Passage | None] = relationship(back_populates="questions")


class PracticeSession(Base):
    """一次作答会话（考试流程的那条轴）。

    状态机（**与 `media.status` 完全无关**，两条轴不许合并）::

        in_progress  ──交卷──┬─ 全部 sync 题当场判完 ──► graded
                            └─ 有 async 题入队       ──► grading ──worker──┬─► graded
                                                                          └─► degraded

    * `in_progress`：开始作答，可反复 `PATCH .../responses`；
    * `grading`：已交卷，仍有题在 `jobs` 里等 IO 池判（写作批改）；
    * `graded`：全部判完；
    * `degraded`：全部判完，但至少一题走了降级路径（外部服务不可用/关停/超配额）
      —— **它是成功态，不是失败态**（ADR-001 §7.1 第 3 条：绝不因第三方挂了导致
      交卷不可用）。

    ⚠️ 刻意**没有** `submitted` 这个中间态：交卷要么当场判完（→ `graded`），要么
    入队等判（→ `grading`），一个会立刻被下一个状态取代的「已提交」既无法观测，
    也会诱导调用方误以为「提交了就算完成」。

    Attributes:
        paper_id: 所属试卷；`NULL` = 无试卷的自由练习（`draft_kind` 说明形态）。
        time_spent_sec: 交卷时由客户端上报（0 = 未知）。
    """

    __tablename__ = "practice_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    paper_id: Mapped[int | None] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), nullable=True, index=True
    )
    #: 无试卷练习的形态标识（如 "writing_draft"）
    draft_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    #: in_progress | grading | graded | degraded（见类 docstring）
    status: Mapped[str] = mapped_column(String(16), default="in_progress")
    time_spent_sec: Mapped[int] = mapped_column(Integer, default=0)

    responses: Mapped[list["Response"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class Response(Base):
    """逐题作答（`(session_id, question_id)` 唯一，upsert 语义）。

    Attributes:
        score / max_score / graded_at: **可空**，`NULL` = 尚未判分（异步题在等
            `grade_writing` job）。这不是「判了 0 分」，两者必须区分得出来。
        detail: JSON，判分明细（词级 diff / 评分细则 / 降级说明）。
    """

    __tablename__ = "responses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("practice_sessions.id", ondelete="CASCADE"), index=True
    )
    question_id: Mapped[int] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), index=True
    )
    #: JSON：用户作答（形状由题型决定）
    user_answer: Mapped[dict] = mapped_column(JSON, default=dict)
    #: 得分；NULL = 未判分
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    graded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    #: JSON：判分明细
    detail: Mapped[dict] = mapped_column(JSON, default=dict)

    session: Mapped[PracticeSession] = relationship(back_populates="responses")

    __table_args__ = (
        # 一题一次作答：暂存是 UPDATE 而不是 INSERT 新行（upsert 的数据库侧保证）
        UniqueConstraint(
            "session_id", "question_id", name="uq_responses_session_question"
        ),
    )


class WritingGradeCache(Base):
    """写作批改结果缓存（P4-4 · ADR-001 §7.1 第 2 条「结果必须缓存」）。

    key = `sha1(question_id + "\\x00" + normalized_response)`。

    为什么必须缓存：一次写作批改是一次**付费**的外部调用。同一篇作文反复提交
    （刷新、重试、同一个模板句）不该重复付费。语义上它等价于 `translations`
    表的 sha1 key 模式，只是 value 是结构化判分结果。

    ⚠️ **只缓存「真的调过外部服务」的结果**，降级结果（关闭 / 超配额 / 外部失败）
    **不写缓存** —— 否则用户在关掉 provider 时跑一遍，之后启用 provider 也永远拿到
    那份降级结果，等于把「临时降级」固化成「永久结论」。
    """

    __tablename__ = "writing_grade_cache"

    #: sha1 十六进制（64 字符列宽足够）
    content_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    question_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: 结构化判分结果（GradeResult.as_dict()）
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

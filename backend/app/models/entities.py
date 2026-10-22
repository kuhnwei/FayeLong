"""数据库表模型（对应设计文档 §8）。"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
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

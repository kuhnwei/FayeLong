"""数据库表模型（对应设计文档 §8）。"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
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

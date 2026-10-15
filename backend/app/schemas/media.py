"""媒体相关的请求 / 响应模型。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.dictation import DictationSummary


class MediaOut(BaseModel):
    """媒体列表项。"""

    id: int
    title: str
    type: str                      # audio / video
    original_name: str
    duration_ms: int
    size_bytes: int
    status: str                    # pending / transcoding / ready / asr / translating / clipping / done / failed
    progress: int
    error: str | None = None
    origin: str                    # upload / inbox
    created_at: datetime
    has_audio: bool                # 转码音频是否已就绪，可就地播放
    stream_url: str
    sentence_count: int = 0        # 已切分句子数（M2）


class MediaListResponse(BaseModel):
    items: list[MediaOut]
    total: int


class SentenceOut(BaseModel):
    """句子（M2 起才会有数据；听写统计字段由 M3 填充）。"""

    id: int
    idx: int
    start_ms: int
    end_ms: int
    text_en: str
    text_zh: str
    is_edited: bool
    clip_url: str | None = None

    # ---- 听写统计（M3 / FR-A4）----
    attempt_count: int = 0
    best_accuracy: float = 0.0
    last_accuracy: float | None = None
    last_input: str = ""
    mastered: bool = False

    # ---- 原文易听错标记（v1.14）：闭区间 [起始词序, 结束词序]，0 基 ----
    marks: list[list[int]] = Field(default_factory=list)


class SentenceListResponse(BaseModel):
    items: list[SentenceOut]
    total: int


class MediaDetailOut(MediaOut):
    sentences: list[SentenceOut] = Field(default_factory=list)
    dictation: DictationSummary | None = None


class MediaUpdate(BaseModel):
    title: str | None = None


class ImportRequest(BaseModel):
    """从收件箱导入；files 为空表示导入全部未导入的受支持文件。"""

    files: list[str] | None = None


class InboxItem(BaseModel):
    name: str
    path: str
    ext: str
    supported: bool
    size_bytes: int
    imported: bool


class InboxResponse(BaseModel):
    inbox_dir: str
    items: list[InboxItem]


# --------------------------- M2：句子编辑 ---------------------------


class SentenceUpdate(BaseModel):
    """PATCH 单句：仅传需要修改的字段（FR-M6 人工校对）。"""

    text_en: str | None = None
    text_zh: str | None = None
    start_ms: int | None = None
    end_ms: int | None = None
    # 易听错标记：传了就整体替换（空数组 = 清空）
    marks: list[list[int]] | None = None


class SentenceSplitIn(BaseModel):
    """在 `at_ms` 处把一句拆成两句。"""

    at_ms: int
    text_left: str | None = None
    text_right: str | None = None


class SentenceMergeIn(BaseModel):
    """与相邻句合并。"""

    direction: Literal["next", "prev"] = "next"


class ProgressEvent(BaseModel):
    """处理进度（SSE 推 / 轮询兜底共用）。"""

    media_id: int
    status: str
    progress: int
    stage: str
    error: str | None = None
    sentence_count: int = 0
    done: bool = False

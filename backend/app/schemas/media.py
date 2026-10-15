"""媒体相关的请求 / 响应模型。"""

from datetime import datetime
from typing import Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator

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
    category_id: int | None = None  # 所属分类；null = 未分类（媒体库分类机制新增字段）
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
    """PATCH 单个媒体：仅传需要修改的字段。

    `category_id` 用于归类：显式传 `null` = 移到「未分类」；
    「未传」与「传 null」由 `model_fields_set` 区分（见 app/api/media.py）。
    """

    title: str | None = None
    category_id: int | None = None


class ImportRequest(BaseModel):
    """从收件箱导入；files 为空表示导入全部未导入的受支持文件。"""

    files: list[str] | None = None
    # 本次导入的素材统一归入该分类；null = 未分类（默认）
    category_id: int | None = None


def _check_ids(value: Any) -> Any:
    """`mode="before"` 校验：`ids` 必须是非空数组（规格 §3.2b：400 ids 为空/非数组）。

    在字段类型约束之前抛出 400 —— 否则 Pydantic 会把它变成 422，与契约不符。
    """
    if not isinstance(value, list):
        raise HTTPException(status_code=400, detail="ids 必须是非空数组")
    if not value:
        raise HTTPException(status_code=400, detail="ids 不能为空")
    return value


class BatchCategoryRequest(BaseModel):
    """批量把素材移动到某个分类。

    `category_id` **必填**（规格 §3.2b）：显式传 `null` = 移到「未分类」，
    从而区分「有意移到未分类」与「客户端漏传」。
    """

    ids: list[int]
    category_id: int | None

    _check_ids = field_validator("ids", mode="before")(_check_ids)


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

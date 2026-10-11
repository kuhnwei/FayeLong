"""生词本相关的请求 / 响应模型（M4 / FR-S7 · FR-A5）。"""

from datetime import datetime

from pydantic import BaseModel, Field


class VocabCreate(BaseModel):
    """加入生词本。

    `context` 为出现该词的上下文句子，`media_id` / `sentence_id` 用于溯源。
    """

    word: str = Field(min_length=1, max_length=128)
    lemma: str | None = Field(default=None, max_length=128)
    phonetic: str | None = Field(default=None, max_length=128)
    translation: str | None = None
    media_id: int | None = None
    sentence_id: int | None = None
    context: str | None = Field(default=None, max_length=1000)


class VocabUpdate(BaseModel):
    """修改生词（仅传需要改的字段）。"""

    translation: str | None = None
    context: str | None = Field(default=None, max_length=1000)
    mastered: bool | None = None


class VocabOut(BaseModel):
    id: int
    word: str
    lemma: str | None = None
    phonetic: str | None = None
    translation: str | None = None
    media_id: int | None = None
    sentence_id: int | None = None
    context: str | None = None
    mastered: bool = False
    created_at: datetime

    media_title: str | None = None      # 来源媒体标题（便于列表展示与导出）
    duplicated: bool = False            # POST 时用于提示「该词已在生词本」


class VocabListResponse(BaseModel):
    items: list[VocabOut]
    total: int
    mastered: int = 0                   # 已掌握数量（列表头部统计）

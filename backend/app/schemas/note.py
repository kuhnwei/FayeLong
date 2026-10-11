"""句子笔记相关的请求 / 响应模型（M4 / FR-S8 · M5 / FR-A6）。"""

from datetime import datetime

from pydantic import BaseModel, Field


class NoteUpsert(BaseModel):
    """保存句子笔记。内容为空字符串表示删除该笔记。"""

    content: str = Field(default="", max_length=8000)


class NoteOut(BaseModel):
    """一句的笔记（每句至多一条）。"""

    sentence_id: int
    content: str = ""
    updated_at: datetime | None = None
    exists: bool = False        # 是否已保存过（用于前端展示状态）


# --------------------------- M5：笔记汇总（FR-A6）---------------------------


class MediaNoteItem(BaseModel):
    """汇总面板 / 导出里的一个条目：句子 + 笔记 + 听写概要。"""

    sentence_id: int
    idx: int
    text_en: str = ""
    text_zh: str = ""
    content: str = ""
    updated_at: datetime | None = None
    # 该句听写概要（便于复习时判断掌握程度）
    attempt_count: int = 0
    best_accuracy: float = 0.0
    mastered: bool = False


class MediaNotesResponse(BaseModel):
    """某个媒体的全部句子笔记（按句序）。"""

    media_id: int
    title: str
    total: int = 0               # 有笔记的句子数
    sentence_count: int = 0      # 该媒体句子总数（用于「N / M 句有笔记」）
    items: list[MediaNoteItem] = Field(default_factory=list)

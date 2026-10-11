"""句子笔记相关的请求 / 响应模型（M4 / FR-S8）。"""

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

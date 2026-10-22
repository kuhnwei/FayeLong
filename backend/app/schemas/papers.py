"""IELTS 试卷相关的响应模型（`GET /api/papers*`）。

🔴 **铁律：`answer` 绝不下发**
==============================
`questions.answer` 里装着标准答案与评分标准。它一旦进了响应体，学生在 F12 的
Network 面板里就能看到全部答案 —— 「隐藏内容不进响应」是本项目从 v1.12 起就坚持的
原则（与听写「原文默认隐藏」同一套立场）。

因此本模块的 `QuestionOut` **刻意没有** `answer` 字段：不是「忘了序列化」，而是
**结构上不可能泄漏** —— pydantic 只输出自己声明的字段。`tests/test_papers_api.py`
另有一条断言：整个响应体文本里不出现答案原文。

`explanation` 同理只在 report 阶段下发（那时已经交卷，看到解析是学习而不是作弊）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

__all__ = [
    "PaperDetailOut",
    "PaperListResponse",
    "PaperOut",
    "PassageOut",
    "QuestionOut",
    "SectionOut",
]


class QuestionOut(BaseModel):
    """一道题的**公开**视图（无 answer / explanation）。"""

    id: int
    section_id: int
    passage_id: int | None = Field(
        default=None, description="归属文章；听力/独立题为 null"
    )
    ordinal: int = Field(..., description="卷内题号（0 基）")
    type: str = Field(..., description="题型 code，与 /api/question-types 对齐")
    stem: str = Field(default="", description="题干")
    options: list[Any] = Field(default_factory=list, description="选项；非选择题为空")
    ref_sentence_id: int | None = Field(
        default=None, description="听写题复用的句子 id（句子内容走 /api/sentences）"
    )


class PassageOut(BaseModel):
    """一篇文章 + 它的题（**只包含 passage_id 指向它的题**）。"""

    id: int
    section_id: int
    ordinal: int
    title: str = ""
    body_md: str = ""
    questions: list[QuestionOut] = Field(default_factory=list)


class SectionOut(BaseModel):
    """一个分卷 + 直属题（passage_id 为空的题，例如听力/写作）。"""

    id: int
    paper_id: int
    kind: str = Field(..., description="listening | reading | writing | speaking")
    ordinal: int
    time_limit_sec: int = Field(0, description="限时（秒）；0 = 不限时")
    instructions: str = ""
    media_id: int | None = Field(
        default=None, description="听力复用的音频（media.id）；其它题型为 null"
    )
    passages: list[PassageOut] = Field(default_factory=list)
    questions: list[QuestionOut] = Field(default_factory=list)


class PaperOut(BaseModel):
    """试卷列表项（含计数，避免前端为每张卷子再发一次请求）。"""

    id: int
    title: str = ""
    mode: str = Field(..., description="full_mock | section_drill")
    source: str = ""
    tags: list[str] = Field(default_factory=list)
    created_at: datetime | None = None
    section_count: int = 0
    question_count: int = 0


class PaperListResponse(BaseModel):
    """`GET /api/papers` 的响应。"""

    items: list[PaperOut] = Field(default_factory=list)
    total: int = 0


class PaperDetailOut(BaseModel):
    """`GET /api/papers/{id}` 的响应（结构树，无任何答案）。"""

    id: int
    title: str = ""
    mode: str = ""
    source: str = ""
    tags: list[str] = Field(default_factory=list)
    created_at: datetime | None = None
    sections: list[SectionOut] = Field(default_factory=list)

"""作答会话相关的请求/响应模型（`/api/sessions*` 与 `POST /api/papers/{id}/sessions`）。

状态机见 `models/entities.py::PracticeSession` 的类 docstring：
`in_progress → grading → graded | degraded`（**没有** `submitted` 中间态）。

`score` / `max_score` 可空是刻意的：`null` = **尚未判分**（写作题在等 worker），
与「判了 0 分」是两件事。前端据此决定显示「批改中」还是「0 分」。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

__all__ = [
    "ReportItemOut",
    "ReportOut",
    "ResponseIn",
    "ResponseOut",
    "ResponsesPatch",
    "SessionOut",
]


class ResponseIn(BaseModel):
    """暂存作答的单条输入。"""

    question_id: int
    answer: dict[str, Any] = Field(
        default_factory=dict, description="作答内容（形状由题型决定）"
    )


class ResponsesPatch(BaseModel):
    """`PATCH /api/sessions/{id}/responses` 的请求体（**批量 upsert**）。"""

    responses: list[ResponseIn] = Field(default_factory=list)
    time_spent_sec: int | None = Field(
        default=None, ge=0, description="客户端已用时长（秒）；不传则不改"
    )


class ResponseOut(BaseModel):
    """一条作答（**不含判分明细**）。

    🔴 **刻意没有 `detail` 字段**：`detail` 会包含听写题的 `expected`（正确答案）
    与写作题的 `reference_answer`，属「交卷后才允许披露」的内容。它只经
    `ReportItemOut`（`GET /api/sessions/{id}/report`，未交卷直接 409）下发。
    暂存/交卷两条响应都返回 `SessionOut`，因此在这两侧都**不可能**把它带出来 ——
    这比「序列化时记得删掉」可靠得多。
    """

    id: int
    question_id: int
    user_answer: dict[str, Any] = Field(default_factory=dict)
    score: float | None = Field(default=None, description="null = 尚未判分")
    max_score: float | None = Field(default=None, description="null = 尚未判分")
    graded_at: datetime | None = None


class SessionOut(BaseModel):
    """会话视图（作答进度 + 汇总）。"""

    id: int
    paper_id: int | None = None
    draft_kind: str | None = None
    status: str = Field(..., description="in_progress | grading | graded | degraded")
    started_at: datetime | None = None
    submitted_at: datetime | None = None
    time_spent_sec: int = 0
    answered: int = Field(0, description="已作答条数")
    graded: int = Field(0, description="已判分条数")
    pending: int = Field(0, description="尚未判分条数（>0 时前端应轮询）")
    total_score: float = 0.0
    max_score: float = 0.0
    responses: list[ResponseOut] = Field(default_factory=list)


class ReportItemOut(BaseModel):
    """成绩报告里的单题明细。

    与 `QuestionOut` 的区别：**这里下发 `explanation`** —— 交卷之后看解析是学习，
    不是作弊（未交卷时 `GET /api/papers/{id}` 仍然不含它）。
    """

    response_id: int | None = None
    question_id: int
    type: str = ""
    ordinal: int = 0
    stem: str = ""
    user_answer: dict[str, Any] = Field(default_factory=dict)
    score: float | None = None
    max_score: float | None = None
    graded: bool = False
    detail: dict[str, Any] = Field(default_factory=dict)
    explanation: str = ""


class ReportOut(BaseModel):
    """`GET /api/sessions/{id}/report` 的响应。

    `pending > 0` 时报告**不是错误**：写作批改还在 worker 里跑，前端应继续轮询
    （这正是「交卷不阻塞」的代价与证据）。
    """

    session: SessionOut
    items: list[ReportItemOut] = Field(default_factory=list)
    total_score: float = 0.0
    max_score: float = 0.0
    pending: int = 0

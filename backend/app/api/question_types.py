"""题型注册表下发接口（ADR-001 §5.5.3 的 `GET /api/question-types`）。

为什么需要这个端点
==================
前后端各有一份「题型清单」是最典型的漂移点：后端加了 `writing`，前端没加 →
用户点进去白屏；前端删了 `echo`，后端还在下发 → 用户看到点不动的按钮。
因此清单**只有一份**（后端注册表），前端启动后拉取并对齐（拉不到就降级）。

本端点**每次请求实时读注册表**（不做进程内缓存）：新增题型只要 import 对应模块，
这里一行都不用改 —— 这正是 G4-① 的验收判据。
"""

from __future__ import annotations

from fastapi import APIRouter

from app.schemas.question_type import QuestionTypeListOut, QuestionTypeOut
from app.services.question_types import all_types, describe

router = APIRouter(prefix="/api/question-types", tags=["question-types"])


@router.get("", response_model=QuestionTypeListOut)
def list_question_types() -> QuestionTypeListOut:
    """下发全部已注册题型（code / label / grade_mode / requires_external）。

    Returns:
        `{"types": [...]}`，按 `code` 升序；注册表为空时返回 `{"types": []}`。

    Notes:
        端点以 **GET `/api/question-types`** 暴露（与现有 34 个端点同一风格：
        复数资源名 + 无尾部斜杠）。它受 `main.py` 的全局登录门禁保护 ——
        清单里不含任何题目内容，但仍然不该给未登录者看站点结构。
    """
    return QuestionTypeListOut(
        types=[QuestionTypeOut(**describe(qtype)) for qtype in all_types()]
    )

"""题型注册表下发（`GET /api/question-types`）的响应模型。

为什么要有这一层 pydantic 模型（而不是直接返回 dict）
==================================================
1. **契约可见**：字段会出现在 `contracts/openapi-v1.json` 里，前端生成的 TS 类型
   能直接对位（P4 之前的 `HealthResponse` 就是反面教材 —— 内联匿名 dict，
   前端只能手写类型）。
2. **防漂移**：`grade_mode` 用 `Literal` 收口，题型实现里写错大小写会被
   `registry` 与这里两道关卡同时挡住。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

__all__ = ["QuestionTypeListOut", "QuestionTypeOut"]


class QuestionTypeOut(BaseModel):
    """一个题型的契约四元组。"""

    code: str = Field(..., description="题型标识，与前端 question-types 目录同名")
    label: str = Field(..., description="中文展示名（为空时后端已按 code 兜底）")
    grade_mode: Literal["sync", "async"] = Field(
        ...,
        description="判分模式：sync=纯函数就地判分；async=入 jobs 表由 IO 池判分",
    )
    requires_external: bool = Field(
        False,
        description="判分是否依赖外部服务；为真时前端应展示降级提示",
    )


class QuestionTypeListOut(BaseModel):
    """`GET /api/question-types` 的响应体；注册表为空时 `types == []`。"""

    types: list[QuestionTypeOut] = Field(default_factory=list)

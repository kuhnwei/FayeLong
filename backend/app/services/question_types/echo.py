"""占位题型 `echo`：只回显用户作答、永远满分（**仅供 G4-① 的挂载预演**）。

它要证明的事
============
「新增一个题型 = **新增一个模块**（本文件）+ 前端**两个组件**
（`frontend-vue/src/question-types/echo/{Answer,Result}.vue`）」，
而 `question_types/base.py` / `registry.py` / `api/question_types.py` /
`frontend-vue/src/question-types/index.ts` / `pages/StudyPage.vue`
**一行都不用改**。

⚠️ **默认不注册**（`question_types/__init__.py` 刻意不 import 本模块）
====================================================================
它没有业务价值，出现在对外注册表里只会让「题型清单」这个契约长出噪音，
前端也会多出一个用户永远点不到的题型。因此启用它必须**显式**调用
:func:`register_echo`：

.. code-block:: python

    from app.services.question_types.echo import register_echo
    from app.services.question_types.registry import unregister

    register_echo()          # 之后 GET /api/question-types 会多出 "echo"
    ...
    unregister("echo")       # 用完清掉，别污染别的用例

实测结论（P4 批次 A 报告 §四）：注册 echo 只碰这两个文件，端点无需改动。
"""

from __future__ import annotations

from typing import Any

from app.services.question_types.base import BaseQuestionType, GradeResult
from app.services.question_types.registry import register

__all__ = ["CODE", "TYPE", "EchoQuestionType", "register_echo"]

#: 题型标识（前端目录名必须是 `frontend-vue/src/question-types/echo/`）。
CODE = "echo"


class EchoQuestionType(BaseQuestionType):
    """回显题型：把用户写的东西原样塞进 `detail`，`score == max_score == 1`。

    Notes:
        判分永远正确 —— 这是刻意的「最小可用题型」，让「挂载链路」与「判分质量」
        两件事解耦：挂载预演失败时，责任 100% 在链路而不是算法。
    """

    code = CODE
    label = "回显（演示）"
    grade_mode = "sync"
    requires_external = False

    def validate(self, payload: dict[str, Any]) -> None:
        """最小校验：payload 是 dict 即可（回显题型不需要标准答案）。"""
        super().validate(payload)

    def normalize(self, response: dict[str, Any]) -> dict[str, Any]:
        """归一化作答：去首尾空白，缺字段按空串处理。"""
        super().normalize(response)
        raw = response.get("text", response.get("input", ""))
        return {"text": "" if raw is None else str(raw).strip()}

    def grade(self, answer: dict[str, Any], response: dict[str, Any]) -> GradeResult:
        """回显判分：永远满分，`detail["echo"]` 是用户原话。"""
        self.validate(answer)
        text = self.normalize(response)["text"]
        return GradeResult(
            score=1.0,
            max_score=1.0,
            correct=True,
            detail={"echo": text, "answer_keys": sorted(answer.keys())},
        )


#: 全局唯一实例（重复调用 `register_echo()` 时靠「同一对象」走幂等分支）。
TYPE = EchoQuestionType()


def register_echo() -> EchoQuestionType:
    """把占位题型 `echo` 注册进全局注册表（幂等）。

    Returns:
        注册的实例（方便测试直接拿来判分）。
    """
    register(TYPE)
    return TYPE

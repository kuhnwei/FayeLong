"""`writing` 题型（P4-4）：**异步判分** + 必带降级路径。

为什么它是本仓库第一个 `grade_mode="async"` 的题型
================================================
一次写作批改是数秒级的外部网络调用。若与听写共用同步路径，一次交卷就会把 HTTP
请求线程按住数秒（ADR-001 §7.1 第 1 条明令禁止）。因此：

* `POST /api/sessions/{id}/submit` 遇到它**只入队**（`kind='grade_writing'`，
  `ref_id = responses.id`）并把 session 置 `grading`，立刻返回；
* 真正的判分在 worker 的 **IO 池**里跑（CPU 池绝不认领，见 `_PoolRunner` 的 kind 过滤）。

**降级不是失败**（§7.1 第 3 条）
==============================
外部服务关闭（默认）/ 未配置 / 超配额 / 网络失败时，本模块返回
「参考范文 + 评分标准 + 自评清单」，`detail["mode"] == "degraded"`。
session 最终是 `degraded` 而不是 `failed` —— **绝不能因为第三方挂了导致交卷不可用**。

question.answer 的约定形状
========================
::

    {
      "prompt": "Some people think ... Discuss.",   # 题目要求（可选）
      "reference_answer": "...",                    # 参考范文（降级时必给，最有用）
      "criteria": [{"name": "任务完成度", "max": 3}, ...],   # 评分标准
      "self_checklist": ["是否回应了全部问题？", ...],        # 自评清单
      "max_score": 9.0,                             # 可选；缺省按 criteria 求和或 9.0
      "min_words": 250                              # 可选；只用于字数提示
    }

`answer` / `user_answer` 都是 JSON 列，因此扩展字段不需要迁移。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.core.config import settings
from app.services.grading import provider as provider_module
from app.services.question_types.base import BaseQuestionType, GradeResult
from app.services.question_types.registry import register

__all__ = ["CODE", "TYPE", "AsyncGradeRequired", "WritingQuestionType"]

logger = logging.getLogger(__name__)

#: 题型标识（与前端 `src/question-types/writing/` 目录同名）。
CODE = "writing"


class AsyncGradeRequired(RuntimeError):
    """在同步路径上调用了异步题型的 `grade()`。

    这是一个**编程错误**（调度层应先看 `grade_mode`），不是用户错误：
    抛出来是为了让「误在请求线程里批改」当场暴露，而不是静默慢 30 秒。
    """


class WritingQuestionType(BaseQuestionType):
    """雅思写作：外部批改 + 本地降级。"""

    code = CODE
    label = "写作"
    #: ★ 必须入队到 IO 池判分（ADR-001 §7.1 第 1 条）
    grade_mode = "async"
    #: ★ 判分依赖外部服务 —— 前端据此展示「可能降级」的提示
    requires_external = True

    # ---------------------------------------------------------------- 题目数据
    def validate(self, payload: dict[str, Any]) -> None:
        """校验题目数据：至少要能给出**某种**可用的反馈。

        Args:
            payload: `questions.answer` 反序列化后的 dict。

        Raises:
            TypeError: 不是 dict。
            ValueError: 范文 / 评分标准 / 自评清单三者全空 —— 那种题在降级时
                什么都给不出来，属于**题目数据缺陷**，必须当场发现。
        """
        super().validate(payload)
        has_reference = bool(str(payload.get("reference_answer") or "").strip())
        has_criteria = bool(payload.get("criteria"))
        has_checklist = bool(payload.get("self_checklist"))
        if not (has_reference or has_criteria or has_checklist):
            raise ValueError(
                "writing 题目缺少 reference_answer / criteria / self_checklist："
                "降级路径将无内容可展示（交卷仍会成功，但学生只能看到空白）"
            )

    # ------------------------------------------------------------------ 作答
    def normalize(self, response: dict[str, Any]) -> dict[str, Any]:
        """归一化作答：只保留 `text` 字段并 strip（缓存键基于它）。

        Notes:
            刻意**不做**大小写/标点/换行折叠：写作的原文会被展示给学生看，
            改动它等于篡改他的作业。strip 只为吃掉首尾空白造成的缓存未命中。
        """
        super().normalize(response)
        raw = response.get("text", response.get("input", ""))
        return {"text": "" if raw is None else str(raw).strip()}

    # ------------------------------------------------------------------ 同步
    def grade(self, answer: dict[str, Any], response: dict[str, Any]) -> GradeResult:
        """**禁止**同步判分。

        Raises:
            AsyncGradeRequired: 永远抛出（见类 docstring）。
        """
        raise AsyncGradeRequired(
            "writing 是 async 题型：交卷必须入队 grade_writing（IO 池），"
            "不能在请求线程里同步调用 grade()"
        )

    # ------------------------------------------------------------------ 异步
    def grade_async(self, answer: dict[str, Any], response: dict[str, Any]) -> GradeResult:
        """调用外部批改；**任何**不可用情形都返回降级结果，绝不抛。

        Args:
            answer: 题目数据（见模块 docstring）。
            response: 用户作答（`{"text": "..."}`）。

        Returns:
            `GradeResult`。`detail["mode"]` 为 `"graded"` 或 `"degraded"`：
            * `graded`   —— 真的调到了外部服务，`detail` 带评语与 token 用量；
            * `degraded` —— 走降级包（参考范文 / 评分标准 / 自评清单），
              `detail["reason"]` 写明原因（`provider_off` / `daily_limit` / …）。

        Notes:
            `detail["provider_called"]` 是**成本闸的记账依据**：只有它为真时才计入
            当日调用次数（缓存命中记 0）。网络失败也算「调用过」（保守记账，
            否则一个持续失败的 provider 会让日上限形同虚设）。
        """
        self.validate(answer)
        essay = self.normalize(response)["text"]
        max_score = self.max_score(answer)

        attempted = False
        try:
            provider = provider_module.resolve_provider()
            if getattr(provider, "name", "") == "off":
                raise provider_module.ProviderUnavailable("provider_off")
            attempted = True
            outcome = provider.grade(
                prompt=self.build_prompt(answer, essay),
                max_tokens=int(settings.grading_max_tokens),
            )
        except provider_module.ProviderUnavailable as exc:
            logger.info("写作批改走降级（不可用）：%s", exc)
            return self.degraded(answer, essay, reason=str(exc) or "unavailable")
        except provider_module.ProviderError as exc:
            logger.warning("写作批改走降级（外部失败）：%s", exc)
            return self.degraded(
                answer, essay, reason=str(exc) or "provider_error", provider_called=True
            )

        score = _clamp(outcome.score, max_score)
        return GradeResult(
            score=score,
            max_score=max_score,
            # 写作没有「判对/判错」：达到 60% 记为「达标」，只影响汇总的掌握率统计。
            correct=bool(max_score > 0 and score >= 0.6 * max_score),
            detail={
                "mode": "graded",
                "provider": getattr(provider, "name", "unknown"),
                "model": outcome.model,
                "feedback": outcome.feedback,
                "tokens": int(outcome.tokens),
                "provider_called": attempted,
                "rubric": _rubric(answer),
                "word_count": _word_count(essay),
            },
        )

    # ------------------------------------------------------------------ 降级
    def degraded(
        self,
        answer: dict[str, Any],
        essay: str,
        *,
        reason: str,
        provider_called: bool = False,
    ) -> GradeResult:
        """构造降级结果（参考范文 + 评分标准 + 自评清单）。

        Args:
            answer: 题目数据。
            essay: 归一化后的作文。
            reason: 降级原因（落进 `detail["reason"]`，前端可原样展示）。
            provider_called: 是否真的尝试过外部调用（成本记账用）。

        Returns:
            `score=0`、`correct=False` 的 `GradeResult`，`detail["mode"]=="degraded"`。

        Notes:
            **分数记 0 而不是「估计分」**：没批就是没批，给一个假的估计分比不给更糟
            （学生会把它当真实成绩）。降级包里的范文与评分标准才是可行动的信息。
        """
        return GradeResult(
            score=0.0,
            max_score=self.max_score(answer),
            correct=False,
            detail={
                "mode": "degraded",
                "reason": str(reason)[:200],
                "provider_called": bool(provider_called),
                "tokens": 0,
                "reference_answer": str(answer.get("reference_answer") or ""),
                "criteria": _rubric(answer),
                "self_checklist": [
                    str(item) for item in (answer.get("self_checklist") or []) if str(item).strip()
                ],
                "word_count": _word_count(essay),
                "min_words": _as_optional_int(answer.get("min_words")),
            },
        )

    # ------------------------------------------------------------------ 助手
    def max_score(self, answer: dict[str, Any]) -> float:
        """满分口径：显式 `max_score` > criteria 求和 > 9.0（雅思写作默认）。"""
        explicit = answer.get("max_score")
        try:
            if explicit is not None and float(explicit) > 0:
                return float(explicit)
        except (TypeError, ValueError):
            pass
        total = 0.0
        for item in answer.get("criteria") or []:
            if isinstance(item, dict):
                try:
                    total += max(0.0, float(item.get("max") or 0))
                except (TypeError, ValueError):
                    continue
        return total if total > 0 else 9.0

    def build_prompt(self, answer: dict[str, Any], essay: str) -> str:
        """构造送给 provider 的提示词（**JSON 字符串**，稳定可断言）。

        Args:
            answer: 题目数据。
            essay: 归一化后的作文。

        Returns:
            紧凑 JSON 文本；字段固定为 task / rubric / reference_answer / essay /
            max_score。provider 只当字符串用，不解读语义。
        """
        payload = {
            "task": str(answer.get("prompt") or ""),
            "rubric": _rubric(answer),
            "reference_answer": str(answer.get("reference_answer") or ""),
            "essay": essay,
            "max_score": self.max_score(answer),
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)


def _rubric(answer: dict[str, Any]) -> list[dict[str, Any]]:
    """把 `criteria` 规整成 `[{"name": str, "max": float}]`（坏条目丢弃）。"""
    items: list[dict[str, Any]] = []
    for raw in answer.get("criteria") or []:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        if not name:
            continue
        try:
            ceiling = float(raw.get("max") or 0)
        except (TypeError, ValueError):
            ceiling = 0.0
        items.append({"name": name, "max": max(0.0, ceiling)})
    return items


def _word_count(text: str) -> int:
    """按空白切词的数字数（与前端提示口径一致，不做语言学处理）。"""
    return len([chunk for chunk in (text or "").split() if chunk])


def _clamp(score: float, max_score: float) -> float:
    """把 provider 的分数夹到 `[0, max_score]`（防止模型给出 12/9 之类的越界值）。"""
    value = float(score)
    if value < 0:
        return 0.0
    if max_score > 0 and value > max_score:
        return max_score
    return value


def _as_optional_int(value: Any) -> int | None:
    """宽容转成 int；不可转时 `None`。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


#: 全局唯一实例（注册表里放的就是它）。
TYPE = WritingQuestionType()

#: **导入即注册**（`question_types/__init__.py` 会 import 本模块）。
register(TYPE)

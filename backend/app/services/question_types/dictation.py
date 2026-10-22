"""`dictation` 题型：把现有 `services/dictation.py` 的纯函数**原样包装**。

这是「听写降级为一种题型」的落地动作（ADR-001 §5.5.1）：

* `services/dictation.py` **一个字符都不改** —— 它是纯函数（无 I/O、无 Session），
  被 P0-5 的单测锁着，改它就是动安全网。
* 本模块只做三件事：**取字段**（answer/response 的 dict 形状 → 两个字符串）、
  **调 `evaluate()`**、**把它的返回值塞进 `GradeResult.detail`**。
* `evaluate()` 的返回结构原样保留（`tokens` / `total_words` / `correct` /
  `wrong` / `missing` / `extra` / `accuracy` / `is_correct`），因为前端的
  `DiffResult` 直接渲染它（`verify_m4` / `verify_mobile` 靠这些字段的 DOM）。

answer / response 的形状
=======================
::

    answer   = {"expected_text": "The quick brown fox."}   # 标准答案（句子原文）
               # 兼容键：text_en（sentences 表列名）、expected
    response = {"text": "the quick brown fox"}             # 用户听写
               # 兼容键：input（attempts 表列名）—— 历史记录直接喂进来也能算

`score` / `max_score` 的口径：**正确词数 / 标准答案总词数**。
不直接用百分比：百分比是 `detail["accuracy"]` 的职责（已按老口径 round 到 1 位），
而 0–N 的原始计数更适合跨题型汇总（避免 88.5% 这类不可加的数值）。
"""

from __future__ import annotations

from typing import Any

from app.services import dictation as dictation_service
from app.services.question_types.base import BaseQuestionType, GradeResult
from app.services.question_types.registry import register

__all__ = ["CODE", "TYPE", "DictationQuestionType"]

#: 题型标识（与前端 `src/question-types/dictation/` 目录同名）。
CODE = "dictation"

#: 标准答案字段的候选键（按优先级）。`text_en` 是 sentences 表的列名，
#: `expected` 是旧 `overview()` 的语义名 —— 三个都收，调用方不必猜。
_EXPECTED_KEYS: tuple[str, ...] = ("expected_text", "text_en", "expected")
#: 作答字段的候选键。`input` 是 attempts 表的列名（历史记录直接回灌时用到）。
_RESPONSE_KEYS: tuple[str, ...] = ("text", "input")


class DictationQuestionType(BaseQuestionType):
    """听写题型：包装 :func:`app.services.dictation.evaluate`。

    Notes:
        判分逻辑**完全**在 `services/dictation.py` 里，本类不含任何 diff 算法。
        这样「题型化」不会引入第二份听写实现，P0-5 的单测继续罩着真正的逻辑。
    """

    code = CODE
    label = "听写"
    #: 纯函数就地判分（毫秒级），不需要 jobs 表。
    grade_mode = "sync"
    #: 不依赖任何外部服务（本地 difflib）。
    requires_external = False

    # ---------------------------------------------------------------- 题目数据
    def validate(self, payload: dict[str, Any]) -> None:
        """校验题目数据：必须有非空的 `expected_text`。

        Args:
            payload: 题目数据 dict。

        Raises:
            TypeError: `payload` 不是 dict。
            ValueError: 缺 `expected_text` 或全为空白。
        """
        super().validate(payload)
        text = _pick_text(payload, _EXPECTED_KEYS)
        if not text.strip():
            raise ValueError(
                "dictation 题目缺少标准答案：expected_text（或 text_en）不能为空"
                "—— 没有原文就无法给出词级 diff"
            )

    # ------------------------------------------------------------------ 作答
    def normalize(self, response: dict[str, Any]) -> dict[str, Any]:
        """归一化作答：只去首尾空白，**不做大小写/标点处理**。

        Notes:
            大小写与标点由 `services/dictation.py` 的 `normalize_word()` 按
            `settings.dictation_ignore_case / _ignore_punctuation` 决定 ——
            那是纯函数内部的事，这里再处理一遍会与既有行为不一致（同一个作答
            经 HTTP 提交与经本类判分会得到不同分数，那是最难查的一类 bug）。
        """
        super().normalize(response)
        return {"text": _pick_text(response, _RESPONSE_KEYS).strip()}

    # ------------------------------------------------------------------ 判分
    def grade(self, answer: dict[str, Any], response: dict[str, Any]) -> GradeResult:
        """调 :func:`app.services.dictation.evaluate` 判分。

        Args:
            answer: 题目数据（`expected_text` / `text_en` / `expected`）。
            response: 用户作答（`text` / `input`）。

        Returns:
            `score` = 正确词数，`max_score` = 标准答案总词数，
            `correct` = `evaluate()` 的 `is_correct`，
            `detail` = `evaluate()` 的**完整**返回值（前端 `DiffResult` 直接渲染）。

        Raises:
            ValueError: 题目数据里没有标准答案（无法判分）。
        """
        self.validate(answer)
        expected_text = _pick_text(answer, _EXPECTED_KEYS)
        actual_text = self.normalize(response)["text"]

        detail = dictation_service.evaluate(expected_text, actual_text)
        total_words = int(detail.get("total_words") or 0)
        correct_words = int(detail.get("correct") or 0)

        return GradeResult(
            score=float(correct_words),
            max_score=float(total_words),
            correct=bool(detail.get("is_correct")),
            detail=detail,
        )


def _pick_text(payload: dict[str, Any], keys: tuple[str, ...]) -> str:
    """按 `keys` 的优先级从 `payload` 里取一个字符串字段（都没有则空串）。

    Args:
        payload: 数据 dict。
        keys: 候选键名（按优先级）。

    Returns:
        第一个命中且为字符串的值；没有命中返回 ``""``。

    Raises:
        TypeError: 命中的值存在但不是字符串（早失败，避免 str(None) 之类的静默错误）。
    """
    if not isinstance(payload, dict):
        return ""
    for key in keys:
        if key not in payload:
            continue
        value = payload.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            raise TypeError(
                f"字段 {key!r} 必须是字符串（收到 {type(value).__name__}）"
            )
        return value
    return ""


#: 全局唯一实例（注册表里放的就是它）。
TYPE = DictationQuestionType()

#: **导入即注册**（`question_types/__init__.py` 会 import 本模块）。
register(TYPE)

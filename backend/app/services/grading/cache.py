"""写作批改结果缓存（ADR-001 §7.1 第 2 条「结果必须缓存」）。

key = `sha1(question_id + "\\x00" + normalized_response)`，落 `writing_grade_cache`。

三条设计取舍
============
1. **只缓存真批改结果**。降级结果（provider 关闭 / 超配额 / 外部失败）**不入缓存** ——
   否则「先在关掉付费的情况下跑一遍」会把临时降级固化成永久结论，之后即使启用
   provider 也永远命中那份降级包。
2. **归一化由题型负责**（`QuestionType.normalize`）。缓存键只用归一化后的文本，
   因此「首尾空白不同」「全角空格」这类差异不会各付一次费。
3. **命中不做任何写**（纯读路径）。命中即返回，连 `graded_at` 都不更新 ——
   缓存的语义是「同样的作业批过」，不是「刚批过」。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy.orm import Session

from app.models import WritingGradeCache
from app.services.question_types.base import GradeResult

__all__ = [
    "cache_key",
    "get_cached",
    "put_cached",
    "result_from_payload",
]


def cache_key(question_id: int, normalized: dict[str, Any]) -> str:
    """算出缓存键。

    Args:
        question_id: 题目 id（同一篇作文在不同题目下分数不同，必须进 key）。
        normalized: 题型归一化后的作答 dict。

    Returns:
        40 字符的 sha1 十六进制串。

    Notes:
        JSON 用 `sort_keys=True` 序列化：归一化后的 dict 若键序不同（例如两条
        写入路径一个用 `{"text":...}`、一个用 `{"input":...}` 再合并），不排序
        就会得到两个 key —— 那是「缓存看起来失效」的经典成因。
    """
    payload = json.dumps(normalized, ensure_ascii=False, sort_keys=True, default=str)
    raw = f"{int(question_id)}\x00{payload}".encode("utf-8")
    return hashlib.sha1(raw).hexdigest()


def result_from_payload(payload: dict[str, Any] | None) -> GradeResult | None:
    """把缓存里的 payload 还原成 :class:`GradeResult`。

    Args:
        payload: 缓存行里的 `payload`（即 `GradeResult.as_dict()` 的结果）。

    Returns:
        `GradeResult`；payload 不是合法形状时返回 `None`（视作未命中，绝不抛）。
        缓存是**加速手段**，不是真相源：一条坏记录不该让交卷失败。
    """
    if not isinstance(payload, dict) or not payload:
        return None
    try:
        return GradeResult(
            score=payload["score"],
            max_score=payload["max_score"],
            correct=bool(payload.get("correct", False)),
            detail=payload.get("detail") if isinstance(payload.get("detail"), dict) else {},
        )
    except (KeyError, TypeError, ValueError):
        return None


def get_cached(db: Session, key: str) -> GradeResult | None:
    """按 key 取缓存结果；未命中返回 `None`。

    Args:
        db: 会话（只读）。
        key: :func:`cache_key` 的结果。
    """
    row = db.get(WritingGradeCache, key)
    if row is None:
        return None
    return result_from_payload(row.payload)


def put_cached(
    db: Session,
    key: str,
    question_id: int | None,
    result: GradeResult,
) -> bool:
    """写入一条缓存（**不 commit**，与调用方的事务一起提交）。

    Args:
        db: 会话。
        key: :func:`cache_key` 的结果。
        question_id: 题目 id（仅诊断用，不参与唯一性）。
        result: 判分结果。

    Returns:
        `True` = 新写入；`False` = 已存在同 key 的行（不改写，先写先赢）。

    Notes:
        已存在就**不改写**：同一 key 意味着同一 `(题目, 归一化作答)`，理论上结果
        相同；真实世界里两次批改可能差 0.5 分（LLM 非确定性）。保留第一次的结果，
        让「同一个学生反复提交同一篇作文看到同一个分数」—— 这比「每次都变」更可解释。
    """
    existing = db.get(WritingGradeCache, key)
    if existing is not None:
        return False
    db.add(
        WritingGradeCache(
            content_hash=key,
            question_id=int(question_id) if question_id is not None else None,
            payload=result.as_dict(),
        )
    )
    return True

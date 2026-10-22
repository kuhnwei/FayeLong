"""批改成本闸（ADR-001 §7.1 第 5 条「成本可控」）。

为什么落在 `settings` 键值表而不是新建一张表
==========================================
任务书允许「落 `settings` 或缓存表旁」。选 `settings` 的理由：**它不是一个业务
实体**，只是两个计数器；为它建表会让 P4 的表清单再长一格，而它连查询需求都没有
（只在判分前读一次、判分后写一次）。key 形如 `grading.usage.2026-10-21`，
按 UTC 日分桶，value 是 `{"calls": n, "tokens": n}`。

并发口径（诚实说明）
==================
读-改-写不是原子的：IO 池 4 个线程理论上可能同时读到同一个旧值。后果是**偶尔少计
一两次调用**（不会多计）。个人自用 + `grading_daily_max` 只是「防账单失控」的粗闸，
这个误差可以接受；真要精确就得加行级锁/独立计数表，那是为 200 次/天的量级付
过高的复杂度。**但如果将来把 provider 开放给多用户，这里必须重做。**

⚠️ 这个模块**绝不存密钥**：只存两个整数。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models import Setting

__all__ = [
    "KEY_PREFIX",
    "is_exhausted",
    "read_usage",
    "record_usage",
    "today_key",
]

logger = logging.getLogger(__name__)

#: `settings.key` 的前缀（后接 UTC 日期）。
KEY_PREFIX = "grading.usage."


def today_key(now: datetime | None = None) -> str:
    """当天的计数键（UTC，`grading.usage.YYYY-MM-DD`）。

    Args:
        now: 注入的当前时间（测试用）；默认取 UTC now。

    Notes:
        用 UTC 而不是本地时区：一天的长度恒定 24h，不会因为夏令时变成 23/25 小时；
        也与 SQLite 的 `CURRENT_TIMESTAMP` 同口径（全项目一致）。
    """
    moment = now or datetime.now(timezone.utc)
    return f"{KEY_PREFIX}{moment.astimezone(timezone.utc).date().isoformat()}"


def read_usage(db: Session, key: str | None = None) -> dict[str, int]:
    """读取某个计数键的用量。

    Args:
        db: 会话。
        key: 计数键（默认当天）。

    Returns:
        `{"calls": int, "tokens": int}`；键不存在时两项均为 0。

    Notes:
        value 不是合法 JSON / 不是 dict / 值不是数字时一律按 0 处理并 warn ——
        计数被写坏不该让交卷失败。
    """
    row = db.get(Setting, key or today_key())
    if row is None:
        return {"calls": 0, "tokens": 0}
    try:
        data: Any = json.loads(row.value or "{}")
    except json.JSONDecodeError:
        logger.warning("批改用量键 %s 的值不是合法 JSON，按 0 处理", row.key)
        return {"calls": 0, "tokens": 0}
    if not isinstance(data, dict):
        logger.warning("批改用量键 %s 的值不是对象，按 0 处理", row.key)
        return {"calls": 0, "tokens": 0}
    return {
        "calls": _as_int(data.get("calls")),
        "tokens": _as_int(data.get("tokens")),
    }


def record_usage(db: Session, *, calls: int = 1, tokens: int = 0, key: str | None = None) -> dict[str, int]:
    """累加用量（**不 commit**，与调用方事务一起提交）。

    Args:
        db: 会话。
        calls: 本次新增的外部调用次数（缓存命中记 0）。
        tokens: 本次新增的 token 数。
        key: 计数键（默认当天）。

    Returns:
        累加后的 `{"calls": n, "tokens": n}`。
    """
    target = key or today_key()
    current = read_usage(db, target)
    updated = {
        "calls": current["calls"] + max(0, int(calls)),
        "tokens": current["tokens"] + max(0, int(tokens)),
    }
    row = db.get(Setting, target)
    payload = json.dumps(updated, ensure_ascii=False)
    if row is None:
        db.add(Setting(key=target, value=payload))
    else:
        row.value = payload
    return updated


def is_exhausted(db: Session, limit: int, key: str | None = None) -> bool:
    """当天的外部调用次数是否已用尽。

    Args:
        db: 会话。
        limit: 上限（`settings.grading_daily_max`）；`<= 0` 表示**不限制**。
        key: 计数键（默认当天）。

    Returns:
        `True` = 已用尽（调用方应直接走降级）。
    """
    if int(limit) <= 0:
        return False
    return read_usage(db, key)["calls"] >= int(limit)


def _as_int(value: Any) -> int:
    """把任意值宽容地转成非负整数（坏值 → 0）。"""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, number)

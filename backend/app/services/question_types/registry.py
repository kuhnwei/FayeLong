"""题型注册表：`code` → 题型实例的**唯一**入口。

为什么要注册表（而不是一个 dict 常量）
====================================
ADR-001 §5.5.1 的验收判据是「新增一个题型 **只加一个模块**，不改核心」。
注册表把「有哪些题型」从**代码清单**变成**副作用**：某个模块被 import，
它就登记自己；API 端点只读注册表，因此新增题型时端点的代码**一行都不用动**。

三条硬约定
==========
1. **注册表为空也不许炸**：`all_types()` 返回空元组、`get()` 返回 `None`，
   `GET /api/question-types` 老老实实返回 ``{"types": []}``。空表是合法状态
   （例如有人只 import 了本模块却没 import 任何题型），不是错误。
2. **同一 code 重复注册必须报错**：静默覆盖会让「两个模块争一个 code」变成
   谁后 import 谁赢 —— 排查这类 bug 的成本远高于启动时报错。
   唯一例外是**同一个对象**重复注册（幂等，用于模块被重复 import 的场景）。
3. **注册顺序不影响结果**：`all_types()` 按 `code` 排序输出，
   契约文件与测试断言都不依赖 import 顺序。
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, TypeVar

from app.services.question_types.base import (
    GRADE_MODES,
    QuestionType,
    describe,
)

__all__ = [
    "all_types",
    "clear",
    "get",
    "register",
    "registered_codes",
    "unregister",
]

logger = logging.getLogger(__name__)

#: 全局注册表。**只在 import 期与测试里写**，运行期只读。
_REGISTRY: dict[str, QuestionType] = {}

#: 注册表的可重入锁。uvicorn 的 import 发生在启动阶段（单线程），但
#: `register()` 是公开 API（测试 / 未来的插件热加载会并发调它），加锁成本可忽略。
_LOCK = threading.RLock()

_T = TypeVar("_T")

#: 题型必须实现的四个方法（缺任何一个都不算合格，注册时点名报错）。
_REQUIRED_METHODS: tuple[str, ...] = ("validate", "normalize", "grade", "grade_async")


def register(candidate: Any = None, /, *, code: str | None = None) -> Any:
    """把一个题型登记进全局注册表（既是函数，也是装饰器）。

    Args:
        candidate: 题型**实例**或**类**（传类时按无参构造实例化）。
            省略时返回装饰器，用于 ``@register`` / ``@register(code="x")`` 写法。
        code: 覆盖题型自身的 `code`（仅当实现里没写 `code` 时才需要）。

    Returns:
        传入的那个对象（装饰器语义：原样返回，``@register`` 不会替换被装饰对象）。

    Raises:
        TypeError: 候选对象缺 `code` / 缺必需方法 / 传入的类无法无参构造。
        ValueError: `code` 已被**另一个**实现占用（防静默覆盖）。

    Examples:
        >>> register(DictationQuestionType())        # doctest: +SKIP
        >>> @register                                 # doctest: +SKIP
        ... class MyType(BaseQuestionType):
        ...     code = "my_type"
    """
    if candidate is None:
        # 装饰器工厂：`@register` 或 `@register(code="x")`
        def _decorator(target: _T) -> _T:
            register(target, code=code)
            return target

        return _decorator

    qtype = _coerce(candidate)
    key = _check_contract(qtype, code)

    with _LOCK:
        existing = _REGISTRY.get(key)
        if existing is qtype:
            # 同一个对象被登记两次：幂等（模块被重复 import 的常见场景）
            logger.debug("题型 %r 已登记（同一对象，忽略重复注册）", key)
            return candidate
        if existing is not None:
            raise ValueError(
                f"题型 code={key!r} 已被 {type(existing).__name__} 注册，"
                f"拒绝用 {type(qtype).__name__} 覆盖（如需替换，先 unregister({key!r})）"
            )
        _REGISTRY[key] = qtype
    logger.debug("已注册题型 %r（grade_mode=%s）", key, qtype.grade_mode)
    return candidate


def get(code: str) -> QuestionType | None:
    """按 `code` 取题型实例；未注册返回 `None`（**不抛异常**）。"""
    with _LOCK:
        return _REGISTRY.get(str(code or ""))


def all_types() -> tuple[QuestionType, ...]:
    """全部已注册题型，按 `code` 升序（注册表为空时返回空元组）。"""
    with _LOCK:
        items = list(_REGISTRY.values())
    return tuple(sorted(items, key=lambda item: str(item.code)))


def registered_codes() -> tuple[str, ...]:
    """全部已注册的 `code`，升序（供日志与测试断言）。"""
    return tuple(str(item.code) for item in all_types())


def unregister(code: str) -> bool:
    """注销一个题型；返回是否真的删掉了。

    Args:
        code: 题型标识。

    Notes:
        生产路径上没人调用它 —— 它存在是为了让**测试**能在注册占位题型（如
        G4-① 的 `echo`）之后把注册表恢复干净，避免污染其它用例。
    """
    key = str(code or "")
    with _LOCK:
        existed = _REGISTRY.pop(key, None) is not None
    if existed:
        logger.debug("已注销题型 %r", key)
    return existed


def clear() -> int:
    """清空注册表，返回清掉的条数（**仅供测试**）。

    ⚠️ 清空之后必须重新 import 题型模块才会恢复 —— 因此测试里用完要成对调用
    `unregister()`，而不是 `clear()`。
    """
    with _LOCK:
        count = len(_REGISTRY)
        _REGISTRY.clear()
    logger.debug("题型注册表已清空（%d 条）", count)
    return count


# ---------------------------------------------------------------------------
# 内部：候选对象 → 合格实例
# ---------------------------------------------------------------------------


def _coerce(candidate: Any) -> QuestionType:
    """把候选对象变成实例（类 → 无参构造；实例 → 原样）。"""
    if isinstance(candidate, type):
        try:
            return candidate()  # type: ignore[call-arg]
        except TypeError as exc:  # pragma: no cover - 只在不合格的实现上触发
            raise TypeError(
                f"题型类 {candidate.__name__} 无法无参构造（注册器需要实例）：{exc}"
            ) from exc
    return candidate


def _check_contract(qtype: Any, code: str | None) -> str:
    """逐项校验契约，返回最终使用的 `code`。

    Args:
        qtype: 候选实例。
        code: 显式传入的 `code`（优先于实例自身的）。

    Returns:
        规范化后的 `code`（去首尾空白）。

    Raises:
        TypeError: 缺方法 / 实例不是对象。
        ValueError: `code` 为空 / `grade_mode` 非法。
    """
    for name in _REQUIRED_METHODS:
        method: Callable[..., Any] | None = getattr(qtype, name, None)
        if not callable(method):
            raise TypeError(
                f"题型 {type(qtype).__name__} 缺少可调用方法 {name}()；"
                f"{' / '.join(_REQUIRED_METHODS)} 四者缺一不可"
            )

    key = str(code if code is not None else getattr(qtype, "code", "") or "").strip()
    if not key:
        raise ValueError(
            f"题型 {type(qtype).__name__} 没有 code；请设置类属性 code 或 register(code='...')"
        )

    mode = str(getattr(qtype, "grade_mode", "") or "").strip()
    if mode not in GRADE_MODES:
        raise ValueError(
            f"题型 {key!r} 的 grade_mode={mode!r} 非法，只能是 {GRADE_MODES} 之一"
        )

    # 校验通过后把最终 code / label 补齐到实例上（契约下发时口径统一）。
    # 用 `_safe_setattr`：`__slots__` / frozen 的实现不该因为这一行注册失败，
    # 它们的 `code` 本来就写在类属性里，属于「无需补齐」的正常情况。
    if getattr(qtype, "code", None) != key:
        _safe_setattr(qtype, "code", key)
    if not str(getattr(qtype, "label", "") or "").strip():
        _safe_setattr(qtype, "label", key)

    # 显式读一次 describe()，保证下发给前端的四元组在注册期就是可序列化的。
    describe(qtype)
    return key


def _safe_setattr(target: Any, name: str, value: Any) -> None:
    """尽力给实例补一个属性；不允许赋值时静默跳过（类属性已经可读就够用）。"""
    try:
        setattr(target, name, value)
    except (AttributeError, TypeError):  # pragma: no cover - 仅 slots / frozen 实现会走到
        logger.debug("题型 %r 不支持写入属性 %s（沿用类属性）", type(target).__name__, name)

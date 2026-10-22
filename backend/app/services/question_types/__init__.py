"""题型插件包 —— **导入即注册**。

使用方式::

    from app.services.question_types import all_types, get   # 导入即完成 dictation 注册
    qtype = get("dictation")

为什么在 `__init__` 里 import 具体题型
=====================================
注册表的语义是「被 import 的模块登记自己」。若 `__init__` 不 import 任何题型，
调用方就必须**知道有哪些题型**并逐个 import —— 那正是「新增题型要改核心」
的旧形态。因此这里显式 import `dictation`（生产题型），让
``import app.services.question_types`` 单独就足以拿到完整注册表。

⚠️ 刻意**不** import 演示题型 `echo`：它只用于 G4-①「零改核心即可挂载」的预演，
默认不进对外注册表（见 `echo.py` 顶部说明）。要启用请显式 `register_echo()`。
"""

from __future__ import annotations

from app.services.question_types.base import (
    GRADE_MODE_ASYNC,
    GRADE_MODE_SYNC,
    GRADE_MODES,
    BaseQuestionType,
    GradeMode,
    GradeResult,
    QuestionType,
    describe,
)
# 导入即注册：`dictation` 模块底部调用了 `registry.register(TYPE)`
from app.services.question_types import dictation as _dictation  # noqa: F401
from app.services.question_types.registry import (
    all_types,
    clear,
    get,
    register,
    registered_codes,
    unregister,
)

__all__ = [
    # 契约
    "GRADE_MODES",
    "GRADE_MODE_ASYNC",
    "GRADE_MODE_SYNC",
    "BaseQuestionType",
    "GradeMode",
    "GradeResult",
    "QuestionType",
    "describe",
    # 注册表
    "all_types",
    "clear",
    "get",
    "register",
    "registered_codes",
    "unregister",
]

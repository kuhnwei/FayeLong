"""题型插件契约（ADR-001 §5.5.1 + §7.1 的异步修订）。

一个题型 = 本包下的一个模块（`dictation.py`、未来的 `reading_mcq.py` …），
对外只承诺三件事：**题目数据怎么校验**、**作答怎么归一化**、**怎么判分**。
核心代码（API / worker / 前端）不认识任何具体题型，只认 :class:`QuestionType`
这个**结构化契约** + 注册表里的 `code`。

判分模式（§7.1 强制约束）
========================
`grade_mode` 只有两个取值：

* ``"sync"`` —— 纯函数即时判分（听写 / 选择 / 填空…），走 :meth:`QuestionType.grade`；
* ``"async"`` —— 必须走 `jobs` 表 + IO 池（写作批改要调外部服务，数秒级），
  走 :meth:`QuestionType.grade_async`。

为什么非要有这个字段：写作批改是数秒级的外部网络调用，若与听写共用同步路径，
一次交卷就会把请求线程按住数秒（ADR-001 §7.1 第 1 条「交卷只入队」）。
调度层靠它决定「就地算」还是「入队算」，因此它是**契约的一部分**，不是实现细节。

本模块只放**契约与默认实现**，不 import 任何具体题型（避免循环 import）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal, Protocol, runtime_checkable

__all__ = [
    "GRADE_MODES",
    "GRADE_MODE_ASYNC",
    "GRADE_MODE_SYNC",
    "BaseQuestionType",
    "GradeMode",
    "GradeResult",
    "QuestionType",
    "describe",
]

#: 同步判分：纯函数，就地返回（听写 / 选择 / 填空）。
GRADE_MODE_SYNC = "sync"
#: 异步判分：必须入 `jobs` 表 + IO 池（写作批改）。
GRADE_MODE_ASYNC = "async"

#: 合法判分模式（注册表据此校验，防止写了 ``"Sync"`` 之类的笔误静默通过）。
GRADE_MODES: tuple[str, ...] = (GRADE_MODE_SYNC, GRADE_MODE_ASYNC)

#: 判分模式的类型别名（与 ADR-001 §7.1 的 `Literal["sync","async"]` 一致）。
GradeMode = Literal["sync", "async"]


@dataclass(frozen=True)
class GradeResult:
    """一次判分的结果（**所有**题型唯一的返回形状）。

    Attributes:
        score: 得分。口径由题型自己定（听写 = 正确词数，写作 = 0–9 分制）。
        max_score: 满分，必须与 `score` 同口径，便于跨题型汇总。
        correct: 是否判对（承载「已掌握」等语义，不与 `score` 冗余）。
        detail: 供前端渲染的明细（词级 diff / 逐空对错 / 评分细则）。
            **必须是 dict**：P4-3 起它直接落 `responses.detail` 的 JSON 列，
            形状因题型而异，硬拆列会不断 `ALTER TABLE`（ADR-001 §5.5.2）。

    Notes:
        `frozen=True` 是刻意的：结果对象会被多个消费者读（API 返回、日志、
        落库），可变对象容易被下游就地改写而互相污染。字段归一化（`score` /
        `max_score` 转 float、`detail` 兜底成空 dict）在 :meth:`__post_init__`
        里做完，因此**构造出来的一定是干净的**，下游不必重复防御。
    """

    score: float
    max_score: float
    correct: bool
    detail: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """字段归一化 + 合法性校验（`frozen=True` 必须用 `object.__setattr__`）。"""
        score = _as_finite_float(self.score, "score")
        max_score = _as_finite_float(self.max_score, "max_score")
        if max_score < 0:
            raise ValueError(f"GradeResult.max_score 不能为负（收到 {max_score!r}）")
        if score < 0:
            raise ValueError(f"GradeResult.score 不能为负（收到 {score!r}）")
        detail = {} if self.detail is None else self.detail
        if not isinstance(detail, dict):
            raise TypeError(
                f"GradeResult.detail 必须是 dict（收到 {type(detail).__name__}）"
                "—— 它以 JSON 列落库，list/str 会让下游渲染与查询都失真"
            )
        object.__setattr__(self, "score", score)
        object.__setattr__(self, "max_score", max_score)
        object.__setattr__(self, "correct", bool(self.correct))
        object.__setattr__(self, "detail", detail)

    @property
    def ratio(self) -> float:
        """得分率（0–1）；`max_score == 0` 时按「全对」记 1.0（空题视为无错）。"""
        if self.max_score <= 0:
            return 1.0
        return self.score / self.max_score

    def as_dict(self) -> dict[str, Any]:
        """压成可 JSON 序列化的 dict（落 `responses` 表 / 直接塞进 API 响应）。"""
        return {
            "score": self.score,
            "max_score": self.max_score,
            "correct": self.correct,
            "detail": self.detail,
        }


def _as_finite_float(value: Any, name: str) -> float:
    """把数值归一成有限 float（NaN / inf 一律拒绝：它们无法落 JSON）。"""
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"GradeResult.{name} 必须是数值（收到 {value!r}）") from exc
    if not math.isfinite(number):
        raise ValueError(f"GradeResult.{name} 必须是有限数（收到 {value!r}）")
    return number


@runtime_checkable
class QuestionType(Protocol):
    """题型契约（结构化类型：**不要求**继承任何基类）。

    实现者只需具备下列属性与方法，`registry.register()` 会逐项检查。
    推荐继承 :class:`BaseQuestionType` 拿到默认实现（少写 4 个样板方法）。

    Attributes:
        code: 题型标识，全局唯一，与前端 `src/question-types/<code>/` 目录同名。
        grade_mode: ``"sync"``（就地判分）或 ``"async"``（入队 + IO 池判分）。
        label: 中文展示名（下发给前端做按钮/标签文案）。
        requires_external: 判分是否依赖外部服务（为 True 时前端应展示降级提示，
            见 ADR-001 §7.1 第 3 条）。
    """

    code: str
    grade_mode: GradeMode
    label: str
    requires_external: bool

    def validate(self, payload: dict[str, Any]) -> None:
        """校验题目数据是否合法；不合法时抛异常（`ValueError` / `TypeError`）。

        Args:
            payload: 题目数据（不同题型形状不同，由题型自己解读）。

        Raises:
            ValueError: 题目数据缺字段或取值非法。
            TypeError: 字段类型不对。
        """
        ...

    def normalize(self, response: dict[str, Any]) -> dict[str, Any]:
        """把用户作答归一化（去首尾空白 / 统一大小写 / 拆分多空）。

        Args:
            response: 原始作答（形状由题型自己定义）。

        Returns:
            归一化后的作答 dict（**只做清洗，不做判分**）。
        """
        ...

    def grade(self, answer: dict[str, Any], response: dict[str, Any]) -> GradeResult:
        """同步判分（`grade_mode == "sync"` 的题型实现此方法）。

        Args:
            answer: 题目数据（含标准答案）。
            response: 用户作答（原始形状，实现内部自行 `normalize`）。

        Returns:
            判分结果。
        """
        ...

    def grade_async(self, answer: dict[str, Any], response: dict[str, Any]) -> GradeResult:
        """异步判分（`grade_mode == "async"` 的题型实现此方法，在 worker 中执行）。

        Args:
            answer: 题目数据（含标准答案）。
            response: 用户作答。

        Returns:
            判分结果。

        Notes:
            它**不能**在 HTTP 请求线程里被调用（数秒级外部调用会卡住请求）。
            `sync` 题型的默认实现直接委托 :meth:`grade`，这样「调度层误用」
            也不会变成 500，只是白跑一趟同步逻辑。
        """
        ...


class BaseQuestionType:
    """题型的默认实现基类（可选继承；不继承也能注册，契约是结构化的）。

    提供四样东西：
    1. 类属性默认值（`label` 兜底用 `code`、`grade_mode` 默认 sync、不需要外部服务）；
    2. `validate()` 的宽松默认实现（只要求 payload 是 dict）；
    3. `normalize()` 的恒等实现（浅拷贝，不原地改调用方的对象）；
    4. `grade_async()` → :meth:`grade` 的兜底委托（sync 题型不必重复实现）。

    ⚠️ `grade()` **没有**默认实现（判分是题型存在的唯一理由，缺了必须报错）。
    """

    #: 题型标识；子类必须覆盖成非空字符串，否则注册时报错。
    code: ClassVar[str] = ""
    #: 判分模式；子类按需改成 ``"async"``。
    grade_mode: ClassVar[GradeMode] = GRADE_MODE_SYNC
    #: 中文展示名；留空时注册表按 `code` 兜底。
    label: ClassVar[str] = ""
    #: 是否需要外部服务（写作批改这类 True）。
    requires_external: ClassVar[bool] = False

    def validate(self, payload: dict[str, Any]) -> None:
        """默认校验：只要求 `payload` 是 dict（具体字段由子类自己查）。"""
        if not isinstance(payload, dict):
            raise TypeError(
                f"{type(self).__name__}.validate() 需要 dict（收到 {type(payload).__name__}）"
            )

    def normalize(self, response: dict[str, Any]) -> dict[str, Any]:
        """默认归一化：浅拷贝（不原地改调用方的对象，避免调用方数据被悄悄污染）。"""
        if not isinstance(response, dict):
            raise TypeError(
                f"{type(self).__name__}.normalize() 需要 dict（收到 {type(response).__name__}）"
            )
        return dict(response)

    def grade(self, answer: dict[str, Any], response: dict[str, Any]) -> GradeResult:
        """判分入口（子类必须实现）。"""
        raise NotImplementedError(
            f"{type(self).__name__} 没有实现 grade()；sync 题型必须实现它"
        )

    def grade_async(self, answer: dict[str, Any], response: dict[str, Any]) -> GradeResult:
        """异步判分的兜底：直接复用同步实现（async 题型应覆盖它）。"""
        return self.grade(answer, response)

    def describe(self) -> dict[str, Any]:
        """本型的契约四元组（等价于 :func:`describe`）。"""
        return describe(self)


def describe(qtype: QuestionType) -> dict[str, Any]:
    """把一个题型压成 `GET /api/question-types` 里的四元组。

    Args:
        qtype: 任意符合 :class:`QuestionType` 契约的对象。

    Returns:
        ```{"code": ..., "label": ..., "grade_mode": ..., "requires_external": ...}```

    Notes:
        端点和日志共用这一份口径，避免「端点写一套、日志写另一套」的漂移。
        `label` 为空时用 `code` 兜底（前端不会显示空标签）。
    """
    code = str(getattr(qtype, "code", "") or "")
    label = str(getattr(qtype, "label", "") or "") or code
    return {
        "code": code,
        "label": label,
        "grade_mode": str(getattr(qtype, "grade_mode", GRADE_MODE_SYNC)),
        "requires_external": bool(getattr(qtype, "requires_external", False)),
    }

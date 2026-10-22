"""写作批改的**编排**（P4-4）：缓存 → 成本闸 → 外部批改 → 降级 → 落库。

分工（三层，各自只做一件事）
==========================
* `provider.py` —— 怎么调外部服务（可注入、可关闭、密钥打码）；
* `writing.py`（题型）—— 怎么把一篇作文变成 `GradeResult`（提示词、降级包）；
* 本模块 —— **什么时候**调：先查缓存、再看当日配额、然后入队/执行、最后落库。

为什么缓存与配额不放在题型里
==========================
`QuestionType.grade_async(answer, response)` 的签名里没有数据库会话（契约不能改）。
把它们放进题型就等于让题型自己开 Session，那会破坏「题型是纯判分器」的分层。
因此 DB 相关的一切都在这一层。

job 语义（`kind='grade_writing'`，IO 池）
=======================================
* `ref_id` = `responses.id`（多态引用，无外键）；
* 幂等：`responses.graded_at` 非空即跳过（重试 / 重复入队都安全）；
* fencing：写回前 `jobs.touch()`（带 `worker_id + attempts` 的 UPDATE）与业务写
  **同一事务**提交 —— 老执行者迟到写回时 `rowcount == 0`，直接 `JobAborted`，
  不会覆盖接管者的结果（P4 批次 A 的 A1 修的就是这条的「终态失败」分支）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import PracticeSession, Question, Response
from app.services import jobs as jobs_service
from app.services.grading import budget
from app.services.grading import cache
from app.services.jobs import JobAborted, JobCtx
from app.services.question_types.base import GradeResult

__all__ = [
    "GradingOutcome",
    "enqueue_grade",
    "finalize_session",
    "grade_and_cache",
    "run_grade_job",
]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GradingOutcome:
    """一次判分编排的结果（供测试断言「缓存命中 / 调了几次外部服务」）。

    Attributes:
        result: 判分结果。
        cached: 是否命中缓存。
        provider_calls: 本次**实际**发生的外部调用次数（0 或 1）。
    """

    result: GradeResult
    cached: bool
    provider_calls: int


def enqueue_grade(response_id: int) -> int | None:
    """把一条作答加入写作批改队列（**唯一**入队入口）。

    Args:
        response_id: `responses.id`。

    Returns:
        job id；已有活跃任务时 `None`（`uq_jobs_active` 的幂等语义）。

    Notes:
        `kind='grade_writing'` 在 `KIND_POOL` 里映射到 **IO 池**，CPU 池的认领口径
        是「排除 IO 池的 kind」，因此 CPU 池**绝不会**认领它（有用例逐条守着）。
    """
    return jobs_service.enqueue(jobs_service.KIND_GRADE_WRITING, int(response_id))


def grade_and_cache(
    db: Session,
    *,
    question_id: int,
    qtype: Any,
    answer: dict[str, Any],
    response: dict[str, Any],
) -> GradingOutcome:
    """判分并维护缓存与用量（**不 commit**，与调用方事务一起提交）。

    Args:
        db: 会话。
        question_id: 题目 id（进缓存键）。
        qtype: 题型实例（必须 `grade_mode == "async"`）。
        answer: 题目数据（`questions.answer`）。
        response: 用户作答（`responses.user_answer`）。

    Returns:
        `GradingOutcome`。

    Notes:
        三条分支的顺序**不能换**：
        1. 缓存命中 → 直接返回（**零外部调用、零计费**）；
        2. 当日配额用尽 → 直接降级（**不调外部服务**，否则配额就没意义了）；
        3. 真调 —— 若 `detail["mode"] == "graded"` 才写缓存（降级结果不缓存，
           否则「临时关掉 provider」会被固化成永久结论）。
    """
    normalized = qtype.normalize(response)
    key = cache.cache_key(question_id, normalized)

    hit = cache.get_cached(db, key)
    if hit is not None:
        logger.debug("写作批改命中缓存 question=%s key=%s", question_id, key[:12])
        return GradingOutcome(result=hit, cached=True, provider_calls=0)

    limit = int(settings.grading_daily_max)
    if budget.is_exhausted(db, limit):
        logger.warning("写作批改已达当日上限 %d，走降级", limit)
        return GradingOutcome(
            result=_degrade(qtype, answer, normalized, reason="daily_limit"),
            cached=False,
            provider_calls=0,
        )

    result = qtype.grade_async(answer, response)
    detail = result.detail or {}
    called = bool(detail.get("provider_called"))

    if detail.get("mode") == "graded":
        cache.put_cached(db, key, question_id, result)

    budget.record_usage(db, calls=1 if called else 0, tokens=int(detail.get("tokens") or 0))
    return GradingOutcome(
        result=result, cached=False, provider_calls=1 if called else 0
    )


def _degrade(
    qtype: Any, answer: dict[str, Any], normalized: dict[str, Any], *, reason: str
) -> GradeResult:
    """构造降级结果（优先用题型自己的降级包，否则给一个通用最小包）。

    Args:
        qtype: 题型实例。
        answer: 题目数据。
        normalized: 已归一化的作答。
        reason: 降级原因。

    Returns:
        `detail["mode"] == "degraded"` 的 `GradeResult`。
    """
    builder = getattr(qtype, "degraded", None)
    if callable(builder):
        return builder(answer, str(normalized.get("text") or ""), reason=reason)
    return GradeResult(
        score=0.0,
        max_score=float(answer.get("max_score") or 0.0),
        correct=False,
        detail={"mode": "degraded", "reason": reason, "provider_called": False},
    )


def finalize_session(db: Session, session_id: int) -> str | None:
    """按「是否还有未判分的作答」推进 session 状态。

    Args:
        db: 会话（**不 commit**）。
        session_id: 会话 id。

    Returns:
        收敛后的状态字符串；会话不存在时 `None`。

    Notes:
        * 还有 `graded_at IS NULL` 的作答 → 保持 `grading`（别的 job 还在跑）；
        * 全部判完 → `degraded`（至少一题降级）或 `graded`。

        `degraded` **优先于** `graded`：只要有一题没拿到真批改，整个会话就不能
        宣称「已完整批改」—— 这直接影响学生要不要重做/自评。
    """
    session = db.get(PracticeSession, int(session_id))
    if session is None:
        return None
    rows = db.query(Response).filter(Response.session_id == int(session_id)).all()
    if any(row.graded_at is None for row in rows):
        session.status = "grading"
        return session.status
    # ★ 用**正向**判据（每题都必须是 graded）而不是「有没有 degraded」：
    #   将来若多出别的非正常结局（ungraded / 题目数据缺陷），这条也不会漏判。
    degraded = any(
        not (isinstance(row.detail, dict) and row.detail.get("mode") in (None, "graded"))
        for row in rows
    )
    session.status = "degraded" if degraded else "graded"
    return session.status


def run_grade_job(ctx: JobCtx) -> None:
    """worker handler：判一条 `responses` 行（`kind='grade_writing'`）。

    Args:
        ctx: 执行上下文（`ref_id` = `responses.id`）。

    Raises:
        JobAborted: 我在写回前已失去执行权（fencing 失败）。
        RuntimeError: 题目/题型不存在（重试无意义，由 `job_max_attempts` 收敛）。
    """
    # 延迟导入：`question_types` 包会 import 各题型，而题型又可能回头用 grading
    # 的 provider —— 顶层 import 会形成一个「看起来能过、改一行就炸」的环。
    from app.services.question_types import get as get_question_type

    response_id = int(ctx.ref_id)
    with ctx.session() as db:
        row = db.get(Response, response_id)
        if row is None:
            logger.warning("%s 作答行不存在（会话被删），跳过", ctx.label())
            return
        if row.graded_at is not None:
            logger.info("%s 已判分，跳过（幂等）", ctx.label())
            return

        question = db.get(Question, int(row.question_id))
        if question is None:
            raise RuntimeError(f"题目 {row.question_id} 不存在，无法判分")

        qtype = get_question_type(question.type)
        if qtype is None:
            raise RuntimeError(f"未知题型 {question.type!r}，无法判分")

        try:
            outcome = grade_and_cache(
                db,
                question_id=int(question.id),
                qtype=qtype,
                answer=question.answer if isinstance(question.answer, dict) else {},
                response=row.user_answer if isinstance(row.user_answer, dict) else {},
            )
        except (ValueError, TypeError) as exc:
            # 题目数据缺陷（例如写作题连范文/评分标准都没有）：**不能**让 job 失败
            # —— 失败重试 3 次也还是同样的数据，最终只会在会话上留下一个永远
            # `grading` 的窟窿。这里把该题记成 `ungraded`，让会话收敛到 `degraded`。
            logger.warning("%s 题目数据无法判分：%s", ctx.label(), exc)
            outcome = GradingOutcome(
                result=GradeResult(
                    score=0.0,
                    max_score=0.0,
                    correct=False,
                    detail={"mode": "ungraded", "reason": str(exc)[:200]},
                ),
                cached=False,
                provider_calls=0,
            )

        # ★ fence 与写回同一事务：`touch()` 是带 worker_id + attempts 的 UPDATE，
        #   rowcount == 0 即「我已不是合法执行者」，此时一行都不许写。
        if not jobs_service.touch(db, ctx.job_id, ctx.my_attempt, ctx.worker_id):
            raise JobAborted(f"{ctx.label()} 已失去执行权，放弃写回")

        result = outcome.result
        row.score = float(result.score)
        row.max_score = float(result.max_score)
        row.detail = result.detail
        row.graded_at = _utcnow()
        status = finalize_session(db, int(row.session_id))
        db.commit()

    logger.info(
        "%s 判分完成：score=%s/%s mode=%s cached=%s session=%s",
        ctx.label(),
        result.score,
        result.max_score,
        (result.detail or {}).get("mode"),
        outcome.cached,
        status,
    )


def _utcnow() -> datetime:
    """naive UTC「现在」（与 SQLite 的 `CURRENT_TIMESTAMP` 同口径）。

    Notes:
        SQLite 存的是 `YYYY-MM-DD HH:MM:SS` 的 naive UTC；这里写库时用同样形态，
        避免同一列里混进带时区的值与不带时区的值（排序/比较会因此错乱）。
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)

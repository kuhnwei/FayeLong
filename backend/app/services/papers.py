"""IELTS 试卷与作答会话的领域逻辑（P4-3）。

为什么单开一个 service（而不是全写在 `api/` 里）
============================================
三个端点的数据形状共享同一套「结构树 / 会话汇总 / 报告」构造逻辑，写在 API 层会
复制三份；而这套逻辑里最容易出错的恰恰是**查询次数**（N+1）与**字段白名单**
（`answer` 不下发）。放到 service 层后：
* `list_papers()` 是**一条** SQL（两个聚合子查询 JOIN），与试卷数量无关；
* `paper_structure()` 固定 **4 条** SQL（papers → sections → passages → questions）；
* 结构树只挑白名单字段，`answer` / `explanation` 从不出现在这里。

判分分流（P4-4）
==============
交卷时按题型的 `grade_mode` 分流：
* `sync`  → 当场判（听写等纯函数）；
* `async` → **只入队**（`kind='grade_writing'`，IO 池），session 置 `grading`，
  请求立刻返回 —— 绝不在请求线程里等外部批改（ADR-001 §7.1 第 1 条）。

交卷幂等
========
`submitted_at` 非空即视为「已交卷」：重复提交不会重新判分、不会重复入队，
只**补入队**（`_ensure_grade_jobs`）—— 这样「commit 成功但入队前进程崩了」
留下的 `grading` 会话，用户再点一次交卷就能自愈（`uq_jobs_active` 保证不重复）。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Paper, Passage, PracticeSession, Question, Response, Section
from app.services.grading import enqueue_grade
from app.services.question_types import get as get_question_type

logger = logging.getLogger(__name__)

__all__ = [
    "EmptySubmissionError",
    "PaperNotFoundError",
    "SessionLockedError",
    "SessionNotFoundError",
    "SessionNotSubmittedError",
    "UnknownQuestionError",
    "create_session",
    "ensure_grade_jobs",
    "list_papers",
    "paper_structure",
    "report",
    "session_summary",
    "submit_session",
    "upsert_responses",
]

#: 会话状态取值（与 `models/entities.py::PracticeSession` 的 docstring 对齐）。
STATUS_IN_PROGRESS = "in_progress"
STATUS_GRADING = "grading"
STATUS_GRADED = "graded"
STATUS_DEGRADED = "degraded"


class PaperNotFoundError(LookupError):
    """试卷不存在。"""


class SessionNotFoundError(LookupError):
    """会话不存在。"""


class SessionLockedError(RuntimeError):
    """会话已交卷，不能再改作答。"""


class EmptySubmissionError(RuntimeError):
    """一条作答都没有就交卷。"""


class SessionNotSubmittedError(RuntimeError):
    """会话还没交卷，不允许读报告（未交卷可读解析会变成「提前看答案」）。

    Notes:
        它是**领域层**的闸（`report()` 自己抛），不是 API 层的 if：
        将来的导出/SSE/批处理入口都过同一条闸。
    """


class UnknownQuestionError(ValueError):
    """作答里出现了不属于该试卷的题号。"""


# ---------------------------------------------------------------------------
# 试卷
# ---------------------------------------------------------------------------


def list_papers(db: Session) -> list[dict[str, Any]]:
    """列出全部试卷（含分卷数 / 题目数，**一条 SQL**）。

    Args:
        db: 会话。

    Returns:
        `[{id, title, mode, source, tags, created_at, section_count,
        question_count}, ...]`，按 id 倒序（新的在前）。

    Notes:
        计数用两个 `GROUP BY` 子查询再 `OUTER JOIN`：一张卷子没有分卷时也要出现
        （`COALESCE(..., 0)`），否则「刚建好的空卷子」会从列表里消失。
        **绝不能**改成「先查 papers 再逐个 count」—— 那是 N+1。
    """
    section_counts = (
        db.query(
            Section.paper_id.label("paper_id"),
            func.count(Section.id).label("n"),
        )
        .group_by(Section.paper_id)
        .subquery()
    )
    question_counts = (
        db.query(
            Section.paper_id.label("paper_id"),
            func.count(Question.id).label("n"),
        )
        .join(Question, Question.section_id == Section.id)
        .group_by(Section.paper_id)
        .subquery()
    )
    rows = (
        db.query(
            Paper,
            func.coalesce(section_counts.c.n, 0),
            func.coalesce(question_counts.c.n, 0),
        )
        .outerjoin(section_counts, section_counts.c.paper_id == Paper.id)
        .outerjoin(question_counts, question_counts.c.paper_id == Paper.id)
        .order_by(Paper.id.desc())
        .all()
    )
    return [
        {
            "id": paper.id,
            "title": paper.title,
            "mode": paper.mode,
            "source": paper.source,
            "tags": list(paper.tags or []),
            "created_at": paper.created_at,
            "section_count": int(sections or 0),
            "question_count": int(questions or 0),
        }
        for paper, sections, questions in rows
    ]


def paper_structure(db: Session, paper_id: int) -> dict[str, Any]:
    """取一张试卷的完整结构树（**不含任何答案**）。

    Args:
        db: 会话。
        paper_id: 试卷 id。

    Returns:
        `{id, title, mode, source, tags, created_at, sections: [...]}`。

    Raises:
        PaperNotFoundError: 试卷不存在。

    Notes:
        * 固定 4 条 SQL：paper / sections / passages / questions（各自一次 `IN` 查询），
          与题目数量无关。
        * 每道题**只出现一次**：`passage_id` 非空的挂在 `PassageOut.questions`，
          为空（听力、写作这类）的挂在 `SectionOut.questions`。前端据此渲染两个区。
        * `answer` / `explanation` 在这里**根本不取**（`_question_public` 只挑白名单
          字段），而不是「取了再删」—— 后者一次手滑就会泄漏。
    """
    paper = db.get(Paper, int(paper_id))
    if paper is None:
        raise PaperNotFoundError(f"试卷 {paper_id} 不存在")

    sections = (
        db.query(Section).filter(Section.paper_id == paper.id).order_by(Section.ordinal, Section.id).all()
    )
    section_ids = [section.id for section in sections]
    passages = (
        db.query(Passage)
        .filter(Passage.section_id.in_(section_ids))
        .order_by(Passage.ordinal, Passage.id)
        .all()
        if section_ids
        else []
    )
    questions = (
        db.query(Question)
        .filter(Question.section_id.in_(section_ids))
        .order_by(Question.ordinal, Question.id)
        .all()
        if section_ids
        else []
    )

    passage_nodes: dict[int, dict[str, Any]] = {}
    for passage in passages:
        passage_nodes[passage.id] = {
            "id": passage.id,
            "section_id": passage.section_id,
            "ordinal": passage.ordinal,
            "title": passage.title,
            "body_md": passage.body_md,
            "questions": [],
        }

    section_nodes: dict[int, dict[str, Any]] = {}
    for section in sections:
        section_nodes[section.id] = {
            "id": section.id,
            "paper_id": section.paper_id,
            "kind": section.kind,
            "ordinal": section.ordinal,
            "time_limit_sec": section.time_limit_sec,
            "instructions": section.instructions,
            "media_id": section.media_id,
            "passages": [],
            "questions": [],
        }

    for question in questions:
        node = _question_public(question)
        if question.passage_id is not None and question.passage_id in passage_nodes:
            passage_nodes[question.passage_id]["questions"].append(node)
        elif question.section_id in section_nodes:
            section_nodes[question.section_id]["questions"].append(node)

    for passage in passages:
        parent = section_nodes.get(passage.section_id)
        if parent is not None:
            parent["passages"].append(passage_nodes[passage.id])

    return {
        "id": paper.id,
        "title": paper.title,
        "mode": paper.mode,
        "source": paper.source,
        "tags": list(paper.tags or []),
        "created_at": paper.created_at,
        "sections": [section_nodes[section.id] for section in sections],
    }


def _question_public(question: Question) -> dict[str, Any]:
    """题目的**公开**视图（白名单字段，永不含 answer / explanation）。"""
    return {
        "id": question.id,
        "section_id": question.section_id,
        "passage_id": question.passage_id,
        "ordinal": question.ordinal,
        "type": question.type,
        "stem": question.stem,
        "options": list(question.options or []),
        "ref_sentence_id": question.ref_sentence_id,
    }


# ---------------------------------------------------------------------------
# 会话
# ---------------------------------------------------------------------------


def create_session(db: Session, paper_id: int) -> PracticeSession:
    """开始一次作答。

    Args:
        db: 会话。
        paper_id: 试卷 id。

    Returns:
        新建的 `PracticeSession`（`status='in_progress'`）。

    Raises:
        PaperNotFoundError: 试卷不存在。
    """
    paper = db.get(Paper, int(paper_id))
    if paper is None:
        raise PaperNotFoundError(f"试卷 {paper_id} 不存在")
    session = PracticeSession(paper_id=paper.id, status=STATUS_IN_PROGRESS, time_spent_sec=0)
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def _paper_question_ids(db: Session, paper_id: int | None) -> set[int]:
    """一张试卷下全部题的 id 集合（一条 SQL）。"""
    if paper_id is None:
        return set()
    rows = (
        db.query(Question.id)
        .join(Section, Question.section_id == Section.id)
        .filter(Section.paper_id == int(paper_id))
        .all()
    )
    return {int(row[0]) for row in rows}


def upsert_responses(
    db: Session, session: PracticeSession, items: Iterable[tuple[int, dict[str, Any]]]
) -> list[Response]:
    """批量暂存作答（**upsert**：一题一行，重复提交是覆盖而不是新增）。

    Args:
        db: 会话。
        session: 目标会话。
        items: `[(question_id, answer), ...]`。

    Returns:
        该会话全部作答行（按 question_id 升序）。

    Raises:
        SessionLockedError: 会话已交卷。
        UnknownQuestionError: 题号不属于本试卷。

    Notes:
        `(session_id, question_id)` 上有唯一约束，因此这里**必须先查后改**：
        不查直接 `add` 会在第二次暂存时炸 `IntegrityError`。
    """
    if session.submitted_at is not None or session.status != STATUS_IN_PROGRESS:
        raise SessionLockedError("会话已交卷，不能修改作答")

    payload = [(int(qid), dict(answer or {})) for qid, answer in items]
    allowed = _paper_question_ids(db, session.paper_id)
    unknown = sorted({qid for qid, _ in payload} - allowed)
    if unknown:
        raise UnknownQuestionError(f"题号不属于本试卷：{unknown}")

    existing = {
        int(row.question_id): row
        for row in db.query(Response).filter(Response.session_id == session.id).all()
    }
    touched: list[Response] = []
    for question_id, answer in payload:
        row = existing.get(question_id)
        if row is None:
            row = Response(session_id=session.id, question_id=question_id, user_answer=answer, detail={})
            db.add(row)
            existing[question_id] = row
        else:
            row.user_answer = answer
            # 暂存阶段理论上不会已有判分结果（交卷才判），但显式清空更安全：
            # 改过的答案绝不能带着上一次的分数。
            row.score = None
            row.max_score = None
            row.graded_at = None
            row.detail = {}
        touched.append(row)
    db.commit()

    return (
        db.query(Response)
        .filter(Response.session_id == session.id)
        .order_by(Response.question_id)
        .all()
    )


def submit_session(db: Session, session: PracticeSession) -> dict[str, Any]:
    """交卷判分：sync 题当场判，async 题入队。

    Args:
        db: 会话。
        session: 目标会话。

    Returns:
        `{"status": ..., "pending": n, "graded": n}`（`pending > 0` 说明还有题在等
        worker 批改）。

    Raises:
        EmptySubmissionError: 一条作答都没有。

    Notes:
        * **幂等**：已交卷的会话不会重新判分；只补入队未判分的异步题
          （`_ensure_grade_jobs`），因此「commit 成功但入队失败」的会话能被再次提交治愈。
        * 单题判分失败（题目数据缺陷）**不影响交卷**：该题记 `mode='ungraded'`，
          会话降级为 `degraded` —— 一道坏题不该让整张卷子交不上。
        * 入队在 `commit` **之后**：`enqueue()` 自己开事务提交，不能塞进本事务；
          由此产生的「commit 与 enqueue 之间的崩溃窗口」由上面的幂等补入队兜住。
    """
    if session.submitted_at is not None:
        healed = _ensure_grade_jobs(db, session)
        if healed:
            logger.warning("会话 %s 已交卷但仍有 %d 条作答未入队，已补入队", session.id, healed)
        return _submission_summary(db, session)

    responses = db.query(Response).filter(Response.session_id == session.id).all()
    if not responses:
        raise EmptySubmissionError("还没有作答，无法交卷")

    questions = _questions_of(db, {int(row.question_id) for row in responses})
    pending: list[int] = []
    ungraded = 0

    for row in responses:
        question = questions.get(int(row.question_id))
        if question is None:
            row.detail = {"mode": "ungraded", "reason": "question_missing"}
            ungraded += 1
            continue
        qtype = get_question_type(question.type)
        if qtype is None:
            row.detail = {"mode": "ungraded", "reason": f"unknown_question_type:{question.type}"}
            ungraded += 1
            continue
        if str(getattr(qtype, "grade_mode", "sync")) == "async":
            # 只入队，不在这里等（ADR-001 §7.1 第 1 条）
            pending.append(int(row.id))
            continue
        try:
            result = qtype.grade(
                question.answer if isinstance(question.answer, dict) else {},
                row.user_answer if isinstance(row.user_answer, dict) else {},
            )
        except (ValueError, TypeError) as exc:
            # 题目数据缺陷（缺标准答案等）→ 该题记 ungraded，交卷照常成功
            logger.warning("会话 %s 的题 %s 判分失败：%s", session.id, question.id, exc)
            row.detail = {"mode": "ungraded", "reason": str(exc)[:200]}
            ungraded += 1
            continue
        row.score = float(result.score)
        row.max_score = float(result.max_score)
        row.detail = result.detail
        row.graded_at = _utcnow()

    session.submitted_at = _utcnow()
    if pending:
        session.status = STATUS_GRADING
    elif ungraded or not _all_graded(responses):
        session.status = STATUS_DEGRADED
    else:
        session.status = STATUS_GRADED
    db.commit()

    for response_id in pending:
        enqueue_grade(response_id)

    return _submission_summary(db, session)


def _submission_summary(db: Session, session: PracticeSession) -> dict[str, Any]:
    """交卷返回的最小摘要（详细视图交给 `session_summary`）。"""
    summary = session_summary(db, session)
    return {
        "status": summary["status"],
        "pending": summary["pending"],
        "graded": summary["graded"],
        "total_score": summary["total_score"],
        "max_score": summary["max_score"],
    }


def ensure_grade_jobs(db: Session, session: PracticeSession) -> int:
    """公开的「补入队」入口（供 API 在已交卷分支调用）。"""
    return _ensure_grade_jobs(db, session)


def _ensure_grade_jobs(db: Session, session: PracticeSession) -> int:
    """给「已交卷但尚未判分」的异步题补入队（幂等）。

    Args:
        db: 会话。
        session: 目标会话。

    Returns:
        本次真正入队的条数（`enqueue()` 返回 None 的重复项不计）。

    Notes:
        只处理 `graded_at IS NULL` 且题型为 async 的作答；同步题若还是 NULL，
        说明它当初判分失败了，**不该**重新入队（`grade_writing` 的 handler 不认
        同步题型，会白跑三次再失败）。
    """
    rows = (
        db.query(Response)
        .filter(Response.session_id == session.id, Response.graded_at.is_(None))
        .all()
    )
    if not rows:
        return 0
    questions = _questions_of(db, {int(row.question_id) for row in rows})
    enqueued = 0
    for row in rows:
        question = questions.get(int(row.question_id))
        if question is None:
            continue
        qtype = get_question_type(question.type)
        if qtype is None or str(getattr(qtype, "grade_mode", "sync")) != "async":
            continue
        if enqueue_grade(int(row.id)) is not None:
            enqueued += 1
    return enqueued


def session_summary(db: Session, session: PracticeSession) -> dict[str, Any]:
    """会话视图（作答进度 + 汇总）。固定 3 条 SQL（session / responses / questions）。"""
    responses = (
        db.query(Response)
        .filter(Response.session_id == session.id)
        .order_by(Response.id)
        .all()
    )
    graded = [row for row in responses if row.graded_at is not None]
    #: `pending` 的语义是「**还会**被 worker 判出来」，因此必须排除 `ungraded`
    #: （题型未注册 / 题目数据缺陷）—— 那些永远不会变成已判分，把它们算进 pending
    #: 会让前端永久轮询。它们只体现为 `detail.mode == "ungraded"` 与 session 的
    #: `degraded` 状态。
    pending = [
        row
        for row in responses
        if row.graded_at is None and _mode_of(row) != "ungraded"
    ]
    return {
        "id": session.id,
        "paper_id": session.paper_id,
        "draft_kind": session.draft_kind,
        "status": session.status,
        "started_at": session.started_at,
        "submitted_at": session.submitted_at,
        "time_spent_sec": session.time_spent_sec,
        "answered": len(responses),
        "graded": len(graded),
        "pending": len(pending),
        "total_score": round(sum(float(row.score or 0.0) for row in graded), 2),
        "max_score": round(sum(float(row.max_score or 0.0) for row in graded), 2),
        "responses": [
            {
                "id": row.id,
                "question_id": row.question_id,
                "user_answer": row.user_answer or {},
                "score": row.score,
                "max_score": row.max_score,
                "graded_at": row.graded_at,
                # ⚠️ 这里**故意不给 `detail`**：它是交卷后才允许披露的内容
                #    （听写的 expected / 写作的 reference_answer），只经 report 下发。
                #    `schemas/sessions.py::ResponseOut` 里也没有该字段，两道保险。
            }
            for row in responses
        ],
    }


def report(db: Session, session: PracticeSession) -> dict[str, Any]:
    """成绩报告：会话汇总 + 逐题明细（**含 explanation**）。

    Args:
        db: 会话。
        session: 目标会话。

    Returns:
        `{"session": ..., "items": [...], "total_score": .., "max_score": .., "pending": n}`。

    Raises:
        SessionNotSubmittedError: 会话还没交卷（`submitted_at IS NULL`）。

    Notes:
        **报告是「交卷后的成绩单」**，未交卷就不该存在 —— 因此这里（而不是只在 API
        层）设闸：任何未来入口（导出、SSE、批处理）都必须过同一道闸，否则「先
        暂存几题、不交卷、直接读报告」就能提前看到解析。

        为什么选 409 + 拒绝，而不是删减字段（例如置空 `explanation`）：
        置空会让前端渲染出一份**看起来正常、实则残缺**的报告，用户只会以为
        「解析就是空的」，比明确报错更难排查；而 409 顺势把「未交卷题的分数」
        也一起挡住了（虽然当前未交卷时分数必为 NULL，但那是实现细节，不是契约）。

        **`grading` 状态（写作题还在 worker 里判）是允许读的**：那时已经交卷，
        `pending > 0` 只表示「还有题在判」，前端据此轮询；已判完的题正常出分。

        未判分的题 `score` 为 `null`、`graded=False`；`pending > 0` 时调用方应继续
        轮询（写作批改还在 worker 里）。**报告不是「非全绿就报错」的接口**。

        ⚠️ **`detail` 只在交卷后经本函数可见**（`ResponseOut` 里刻意没有该字段）。
        将来若新增任何「读取作答明细」的入口（实时判分预览、导出、SSE 推送），
        **必须同样校验 `submitted_at`** —— 否则就把 `answer` 侧的 `explanation`
        防线从侧面绕开了。同理：`responses.detail` 会包含听写题的 `expected` 与
        写作题的 `reference_answer`，那是既定的「学习用途披露」，只允许发生在交卷后。
    """
    if session.submitted_at is None:
        raise SessionNotSubmittedError("会话尚未交卷，交卷后才能查看报告")

    summary = session_summary(db, session)
    responses = (
        db.query(Response)
        .filter(Response.session_id == session.id)
        .order_by(Response.question_id)
        .all()
    )
    questions = _questions_of(db, {int(row.question_id) for row in responses})
    items: list[dict[str, Any]] = []
    for row in responses:
        question = questions.get(int(row.question_id))
        items.append(
            {
                "response_id": row.id,
                "question_id": row.question_id,
                "type": question.type if question is not None else "",
                "ordinal": question.ordinal if question is not None else 0,
                "stem": question.stem if question is not None else "",
                "user_answer": row.user_answer or {},
                "score": row.score,
                "max_score": row.max_score,
                "graded": row.graded_at is not None,
                "detail": row.detail or {},
                # 交卷之后才下发解析：学习用途，不是作弊通道
                "explanation": question.explanation if question is not None else "",
            }
        )
    return {
        "session": summary,
        "items": items,
        "total_score": summary["total_score"],
        "max_score": summary["max_score"],
        "pending": summary["pending"],
    }


def _questions_of(db: Session, ids: set[int]) -> dict[int, Question]:
    """按 id 批量取题（一条 SQL，避免逐题 `db.get`）。"""
    if not ids:
        return {}
    rows = db.query(Question).filter(Question.id.in_(sorted(ids))).all()
    return {int(row.id): row for row in rows}


def _all_graded(responses: Iterable[Response]) -> bool:
    """是否每题都拿到了**真**判分（`detail.mode` 不是 degraded / ungraded）。"""
    for row in responses:
        if row.graded_at is None:
            return False
        if _mode_of(row) in ("degraded", "ungraded"):
            return False
    return True


def _mode_of(row: Response) -> str:
    """取一条作答的判分模式（`detail.mode`）；没有该字段时返回空串。

    Notes:
        同步题（听写）的 `detail` 是 `evaluate()` 的原始返回，**没有** `mode` 字段 ——
        空串表示「正常同步判分」，与 `graded` 同等对待。
    """
    detail = row.detail if isinstance(row.detail, dict) else {}
    return str(detail.get("mode") or "")


def _utcnow() -> datetime:
    """naive UTC「现在」（与 SQLite `CURRENT_TIMESTAMP` 同口径）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)

"""作答会话接口（ADR-001 §5.5.3）。

- `PATCH /api/sessions/{id}/responses`  暂存/更新作答（**批量 upsert**，仅 in_progress）
- `POST  /api/sessions/{id}/submit`     交卷判分（**幂等**；async 题只入队）
- `GET   /api/sessions/{id}/report`     成绩报告（**未交卷 → 409**；交卷后才含 explanation）

判分分流与降级的细节见 `services/papers.py::submit_session` 与
`services/grading/service.py`。这里只做 HTTP 语义映射：

| 领域异常 | HTTP |
|---|---|
| `SessionNotFoundError` / `PaperNotFoundError` | 404 |
| `SessionLockedError`（已交卷还改作答） | 409 |
| `EmptySubmissionError`（一条都没答就交卷） | 409 |
| `SessionNotSubmittedError`（未交卷就读报告） | 409 |
| `UnknownQuestionError`（题号不属于本试卷） | 400 |

⚠️ **明细（`detail`）只在 report 里**：`ResponseOut` 刻意不含该字段，因此
「暂存 / 交卷」两条响应都不会带出听写的 `expected` 或写作的 `reference_answer`。
新增任何读取入口都必须同样校验 `submitted_at`（闸在 `services/papers.py::report`）。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.db import get_db
from app.models import PracticeSession, User
from app.schemas.sessions import ReportOut, ResponsesPatch, SessionOut
from app.services import papers as papers_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


def _load_session(db: Session, session_id: int, user_id: int) -> PracticeSession:
    """取会话；不存在或不属于当前用户时 404（多用户隔离，防 IDOR）。"""
    session = db.query(PracticeSession).filter(
        PracticeSession.id == session_id, PracticeSession.user_id == user_id
    ).first()
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return session


@router.patch("/{session_id}/responses", response_model=SessionOut)
def patch_responses(
    session_id: int,
    payload: ResponsesPatch,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SessionOut:
    """暂存/更新作答（批量 upsert：同一题重复提交是覆盖，不是新增）。

    Raises:
        HTTPException: 404 会话不存在；409 已交卷；400 题号不属于本试卷。
    """
    session = _load_session(db, session_id, user.id)
    try:
        papers_service.upsert_responses(
            db, session, [(item.question_id, item.answer) for item in payload.responses]
        )
    except papers_service.SessionLockedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except papers_service.UnknownQuestionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    if payload.time_spent_sec is not None:
        session.time_spent_sec = int(payload.time_spent_sec)
        db.commit()

    return SessionOut(**papers_service.session_summary(db, session))


@router.post("/{session_id}/submit", response_model=SessionOut)
def submit_session(
    session_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SessionOut:
    """交卷判分。

    Notes:
        * **幂等**：重复提交不重新判分；只会为「已交卷但还没入队」的异步题补入队。
        * 返回值里 `status='grading'` + `pending>0` 意味着写作批改还在 worker 里跑，
          前端应轮询 `GET /api/sessions/{id}/report`（**交卷请求绝不阻塞**）。
        * 请求线程**绝不**调用外部批改服务：async 题只入队。

    Raises:
        HTTPException: 404 会话不存在；409 还没有作答。
    """
    session = _load_session(db, session_id, user.id)
    try:
        papers_service.submit_session(db, session)
    except papers_service.EmptySubmissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return SessionOut(**papers_service.session_summary(db, session))


@router.get("/{session_id}/report", response_model=ReportOut)
def get_report(
    session_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReportOut:
    """成绩报告（`pending > 0` 时说明还有题在等判分，不是错误）。

    Raises:
        HTTPException: 404 会话不存在；**409 尚未交卷**（报告是交卷后的成绩单）。
    """
    session = _load_session(db, session_id, user.id)
    try:
        data = papers_service.report(db, session)
    except papers_service.SessionNotSubmittedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return ReportOut(**data)

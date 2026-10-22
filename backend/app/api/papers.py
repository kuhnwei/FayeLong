"""IELTS 试卷接口（ADR-001 §5.5.3）。

- `GET  /api/papers`                  试卷列表（含分卷/题目计数，一条 SQL）
- `GET  /api/papers/{id}`             试卷结构（sections + passages + questions）
- `POST /api/papers/{id}/sessions`    开始一次作答 → 201

🔴 **`answer` 绝不下发**：结构树只走 `schemas/papers.py` 的白名单字段
（`QuestionOut` 里根本没有 `answer`），并且 `services/papers.py` 只挑字段、
不把 ORM 实体直接扔给 pydantic。

所有端点都受 `main.py` 的全局登录门禁保护（与既有 34+1 个端点一致）。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.papers import PaperDetailOut, PaperListResponse, PaperOut
from app.schemas.sessions import SessionOut
from app.services import papers as papers_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/papers", tags=["papers"])


@router.get("", response_model=PaperListResponse)
def list_papers(db: Session = Depends(get_db)) -> PaperListResponse:
    """试卷列表（新的在前）。

    Notes:
        计数（`section_count` / `question_count`）由两个聚合子查询一次算完，
        **不会**为每张卷子再查一次（N+1 是这类列表接口最常见的性能坑）。
    """
    items = papers_service.list_papers(db)
    return PaperListResponse(items=[PaperOut(**item) for item in items], total=len(items))


@router.get("/{paper_id}", response_model=PaperDetailOut)
def get_paper(paper_id: int, db: Session = Depends(get_db)) -> PaperDetailOut:
    """试卷结构（无答案）。

    Raises:
        HTTPException: 404 —— 试卷不存在。
    """
    try:
        data = papers_service.paper_structure(db, paper_id)
    except papers_service.PaperNotFoundError:
        raise HTTPException(status_code=404, detail="试卷不存在") from None
    return PaperDetailOut(**data)


@router.post("/{paper_id}/sessions", response_model=SessionOut, status_code=201)
def create_session(paper_id: int, db: Session = Depends(get_db)) -> SessionOut:
    """开始一次作答（`status='in_progress'`）。

    Raises:
        HTTPException: 404 —— 试卷不存在。
    """
    try:
        session = papers_service.create_session(db, paper_id)
    except papers_service.PaperNotFoundError:
        raise HTTPException(status_code=404, detail="试卷不存在") from None
    return SessionOut(**papers_service.session_summary(db, session))

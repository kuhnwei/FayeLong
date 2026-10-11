"""听写练习接口（M3 / FR-S2 · FR-S3 · FR-A4）。

- `POST /api/attempts`                  提交一次听写 → 服务端算词级 diff 与正确率 → 落库
- `GET  /api/sentences/{id}/attempts`   读取某句的听写历史（倒序）

校验算法在 `services/dictation.py`（纯函数），这里只负责取标准答案、落库与回填统计。
服务端作为**唯一判定源**，前端不做二次 diff，避免两套实现漂移。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Attempt, Sentence
from app.schemas.dictation import (
    AttemptCreate,
    AttemptListResponse,
    AttemptRecord,
    AttemptResult,
)
from app.services import dictation as dictation_service
from app.services import study as study_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["dictation"])


@router.post("/api/attempts", response_model=AttemptResult, status_code=201)
def create_attempt(
    payload: AttemptCreate,
    db: Session = Depends(get_db),
) -> AttemptResult:
    """提交一次听写：与标准答案比对，记录结果并返回词级明细。"""
    sentence = db.get(Sentence, payload.sentence_id)
    if sentence is None:
        raise HTTPException(status_code=404, detail="句子不存在")
    if not sentence.text_en.strip():
        raise HTTPException(status_code=409, detail="该句没有标准答案，无法校验听写")

    text = (payload.input or "").strip()
    result = dictation_service.evaluate(sentence.text_en, text)

    attempt = Attempt(
        sentence_id=sentence.id,
        input=text,
        accuracy=float(result["accuracy"]),
        is_correct=bool(result["is_correct"]),
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt)

    stat = study_service.sentence_stats(db, sentence.id)

    return AttemptResult(
        sentence_id=sentence.id,
        attempt_id=attempt.id,
        input=text,
        accuracy=result["accuracy"],
        is_correct=result["is_correct"],
        tokens=result["tokens"],
        total_words=result["total_words"],
        correct=result["correct"],
        wrong=result["wrong"],
        missing=result["missing"],
        extra=result["extra"],
        attempt_count=stat.attempt_count,
        best_accuracy=stat.best_accuracy,
        mastered=stat.mastered,
        created_at=attempt.created_at,
    )


@router.get("/api/sentences/{sentence_id}/attempts", response_model=AttemptListResponse)
def list_attempts(
    sentence_id: int,
    limit: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
) -> AttemptListResponse:
    """某句的听写历史（按时间倒序）。"""
    if db.get(Sentence, sentence_id) is None:
        raise HTTPException(status_code=404, detail="句子不存在")

    total = db.query(Attempt).filter(Attempt.sentence_id == sentence_id).count()
    rows = (
        db.query(Attempt)
        .filter(Attempt.sentence_id == sentence_id)
        .order_by(Attempt.id.desc())
        .limit(limit)
        .all()
    )
    return AttemptListResponse(
        items=[
            AttemptRecord(
                id=row.id,
                input=row.input,
                accuracy=round(row.accuracy, 1),
                is_correct=row.is_correct,
                created_at=row.created_at,
            )
            for row in rows
        ],
        total=total,
    )

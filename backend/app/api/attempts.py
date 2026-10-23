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

from app.api.auth import get_current_user
from app.db import get_db
from app.models import Attempt, Sentence, User
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
    user: User = Depends(get_current_user),
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
        user_id=user.id,
        input=text,
        accuracy=float(result["accuracy"]),
        is_correct=bool(result["is_correct"]),
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt)

    stat = study_service.sentence_stats(db, sentence.id, user.id)

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
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AttemptListResponse:
    """某句的听写历史（按时间倒序），每条记录附带词级明细。

    明细是**读取时按当前原文实时重算的复盘视图**，不落库（`attempts` 表只追加、
    不存词级明细）。因此比对基准始终是句子当前的标准答案 `text_en`；若原文后来被
    校对改过，明细会随之变化，但每条记录的 `accuracy` / `is_correct` 仍是**提交当时
    写入数据库的历史值**（历史成绩是当时的事实，不因改原文而变）。
    """
    sentence = db.get(Sentence, sentence_id)
    if sentence is None:
        raise HTTPException(status_code=404, detail="句子不存在")

    total = (
        db.query(Attempt)
        .filter(Attempt.sentence_id == sentence_id, Attempt.user_id == user.id)
        .count()
    )
    rows = (
        db.query(Attempt)
        .filter(Attempt.sentence_id == sentence_id, Attempt.user_id == user.id)
        .order_by(Attempt.id.desc())
        .limit(limit)
        .all()
    )

    items: list[AttemptRecord] = []
    for row in rows:
        # 以当前原文为基准重算明细；input / text_en 为空时 evaluate 会正常返回
        # （空 tokens、计数全 0），无需特判。
        detail = dictation_service.evaluate(sentence.text_en, row.input or "")
        items.append(
            AttemptRecord(
                id=row.id,
                input=row.input,
                accuracy=round(row.accuracy, 1),  # 数据库历史值，不用重算值覆盖
                is_correct=row.is_correct,        # 同上
                created_at=row.created_at,
                tokens=detail["tokens"],
                total_words=detail["total_words"],
                correct=detail["correct"],
                wrong=detail["wrong"],
                missing=detail["missing"],
                extra=detail["extra"],
            )
        )

    return AttemptListResponse(items=items, total=total)

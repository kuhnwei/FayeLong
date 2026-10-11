"""全局学习概览接口（M5 打磨）。

一处聚合媒体 / 句子 / 笔记 / 生词 / 听写的全局计数，
供前端头部与空状态展示，避免各页面重复多次请求。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import (
    STATUS_ASR,
    STATUS_CLIPPING,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_TRANSCODING,
    STATUS_TRANSLATING,
)
from app.db import get_db
from app.models import Attempt, Media, Note, Sentence, Vocab
from app.schemas.stats import (
    AttemptStatsOut,
    MediaStatsOut,
    StatsOut,
    VocabStatsOut,
)

router = APIRouter(prefix="/api/stats", tags=["stats"])

# 与前端 PROCESSING_STATUSES 对齐：ready 表示音频已就绪（不算处理中）
_PROCESSING_STATUSES = (
    STATUS_PENDING,
    STATUS_TRANSCODING,
    STATUS_ASR,
    STATUS_TRANSLATING,
    STATUS_CLIPPING,
)


def _count(db: Session, model) -> int:
    return db.query(func.count(model.id)).scalar() or 0


@router.get("", response_model=StatsOut)
def get_stats(db: Session = Depends(get_db)) -> StatsOut:
    """返回全局学习概览。"""
    media_total = _count(db, Media)
    processing = sum(
        (db.query(func.count(Media.id)).filter(Media.status == s).scalar() or 0)
        for s in _PROCESSING_STATUSES
    )
    failed = db.query(func.count(Media.id)).filter(Media.status == STATUS_FAILED).scalar() or 0
    done = db.query(func.count(Media.id)).filter(Media.status == STATUS_DONE).scalar() or 0

    vocab_total = _count(db, Vocab)
    vocab_mastered = (
        db.query(func.count(Vocab.id)).filter(Vocab.mastered.is_(True)).scalar() or 0
    )

    attempts_total = _count(db, Attempt)
    attempted_sentences = (
        db.query(func.count(func.distinct(Attempt.sentence_id))).scalar() or 0
    )
    mastered_sentences = (
        db.query(func.count(func.distinct(Attempt.sentence_id)))
        .filter(Attempt.is_correct.is_(True))
        .scalar()
        or 0
    )

    return StatsOut(
        media=MediaStatsOut(
            total=media_total,
            done=done,
            processing=processing,
            failed=failed,
        ),
        sentences=_count(db, Sentence),
        notes=_count(db, Note),
        vocab=VocabStatsOut(total=vocab_total, mastered=vocab_mastered),
        attempts=AttemptStatsOut(
            total=attempts_total,
            attempted_sentences=attempted_sentences,
            mastered_sentences=mastered_sentences,
        ),
    )

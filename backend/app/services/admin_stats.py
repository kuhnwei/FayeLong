"""管理员统计（v1.16.2）：按 `user_id` 聚合各用户的学习数据。"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Attempt, Note, PracticeSession, Vocab


def _streak_days(db: Session, user_id: int) -> int:
    """从今天向前数连续有听写的天数（今天无听写 → 0，与 stats/overview 同口径）。"""
    rows = (
        db.query(func.date(Attempt.created_at, "localtime").label("day"))
        .filter(Attempt.user_id == user_id)
        .group_by("day")
        .all()
    )
    days_with_attempts = {row.day for row in rows}
    today = date.today()
    streak = 0
    for i in range(365):
        if (today - timedelta(days=i)).isoformat() in days_with_attempts:
            streak += 1
        else:
            break
    return streak


def user_summary(db: Session, user_id: int) -> dict:
    """单用户学习统计摘要（全部按 `user_id` 聚合）。"""
    avg_accuracy = (
        db.query(func.avg(Attempt.accuracy))
        .filter(Attempt.user_id == user_id)
        .scalar()
    )
    return {
        "attempts_total": (
            db.query(func.count(Attempt.id))
            .filter(Attempt.user_id == user_id)
            .scalar()
            or 0
        ),
        "attempts_avg_accuracy": round(avg_accuracy, 2) if avg_accuracy is not None else None,
        "attempted_sentences": (
            db.query(func.count(func.distinct(Attempt.sentence_id)))
            .filter(Attempt.user_id == user_id)
            .scalar()
            or 0
        ),
        "mastered_sentences": (
            db.query(func.count(func.distinct(Attempt.sentence_id)))
            .filter(Attempt.user_id == user_id, Attempt.is_correct.is_(True))
            .scalar()
            or 0
        ),
        "vocab_total": (
            db.query(func.count(Vocab.id)).filter(Vocab.user_id == user_id).scalar() or 0
        ),
        "vocab_mastered": (
            db.query(func.count(Vocab.id))
            .filter(Vocab.user_id == user_id, Vocab.mastered.is_(True))
            .scalar()
            or 0
        ),
        "notes_count": (
            db.query(func.count(Note.id)).filter(Note.user_id == user_id).scalar() or 0
        ),
        "sessions_total": (
            db.query(func.count(PracticeSession.id))
            .filter(PracticeSession.user_id == user_id)
            .scalar()
            or 0
        ),
        "streak_days": _streak_days(db, user_id),
    }

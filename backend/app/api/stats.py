"""全局学习概览接口（M5 打磨）与统计页 overview（P2）。

一处聚合媒体 / 句子 / 笔记 / 生词 / 听写的全局计数，
供前端头部与空状态展示，避免各页面重复多次请求。
"""

from __future__ import annotations

from datetime import date, timedelta

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
    CourseProgressOut,
    DailyPoint,
    KpiOut,
    MediaStatsOut,
    OverviewOut,
    RecentAttemptOut,
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


@router.get("/overview", response_model=OverviewOut)
def get_overview(days: int = 14, db: Session = Depends(get_db)) -> OverviewOut:
    """统计页 14 天学习概览（ARCH §6.1）。

    口径：
    - 所有「按日」聚合用 `func.date(..., 'localtime')` 得到**本地日** `YYYY-MM-DD`；
    - `daily` 恒为 `days` 长（0 填充，无听写日 attempts/accuracy/new_vocab 显式 0）；
    - `streak_days`：从今天向前数连续 `attempts>0` 的天数，今天无听写 → 0；
    - `courses.pct` 0–100 float，`total=0` 时 0；按 pct desc 取前 10；
    - `recent` 按 `created_at desc` 取 6 条；
    - 空库返回 HTTP 200 全零结构（非 404）。
    """
    days = max(1, min(days, 365))
    today = date.today()
    date_seq = [(today - timedelta(days=days - 1 - i)).isoformat() for i in range(days)]

    # ---- 按日聚合：听写量 + 平均正确率 ----
    attempt_rows = (
        db.query(
            func.date(Attempt.created_at, "localtime").label("day"),
            func.count(Attempt.id).label("attempts"),
            func.avg(Attempt.accuracy).label("accuracy"),
        )
        .group_by("day")
        .all()
    )
    attempt_by_day = {row.day: row for row in attempt_rows}

    # ---- 按日聚合：新收入生词数 ----
    vocab_rows = (
        db.query(
            func.date(Vocab.created_at, "localtime").label("day"),
            func.count(Vocab.id).label("n"),
        )
        .group_by("day")
        .all()
    )
    vocab_by_day = {row.day: row.n for row in vocab_rows}

    daily = [
        DailyPoint(
            date=d,
            attempts=(attempt_by_day[d].attempts if d in attempt_by_day else 0),
            accuracy=(
                round(attempt_by_day[d].accuracy, 4)
                if d in attempt_by_day and attempt_by_day[d].accuracy is not None
                else 0.0
            ),
            new_vocab=vocab_by_day.get(d, 0),
        )
        for d in date_seq
    ]

    # ---- KPI：今天 + 连续天数 ----
    today_iso = today.isoformat()
    today_row = attempt_by_day.get(today_iso)
    kpi = KpiOut(
        today_attempts=today_row.attempts if today_row else 0,
        today_accuracy=(
            round(today_row.accuracy, 4)
            if today_row is not None and today_row.accuracy is not None
            else 0.0
        ),
        today_new_vocab=vocab_by_day.get(today_iso, 0),
        streak_days=0,
    )
    # 从今天向前数连续有听写的天数；今天为 0 → 立刻中断 → streak=0。
    for d in reversed(date_seq):
        row = attempt_by_day.get(d)
        if row is not None and row.attempts > 0:
            kpi.streak_days += 1
        else:
            break

    # ---- 课程完成度：按 media 分组，去重统计 ----
    course_rows = (
        db.query(
            Media.id.label("media_id"),
            Media.title.label("title"),
            func.count(func.distinct(Sentence.id)).label("total"),
            func.count(func.distinct(Attempt.sentence_id)).label("attempted"),
        )
        .outerjoin(Sentence, Sentence.media_id == Media.id)
        .outerjoin(Attempt, Attempt.sentence_id == Sentence.id)
        .group_by(Media.id)
        .all()
    )
    courses: list[CourseProgressOut] = []
    for row in course_rows:
        total = row.total or 0
        attempted = row.attempted or 0
        pct = round(attempted / total * 100, 1) if total else 0.0
        courses.append(
            CourseProgressOut(
                media_id=row.media_id,
                title=row.title,
                total=total,
                attempted=attempted,
                pct=pct,
            )
        )
    courses.sort(key=lambda c: c.pct, reverse=True)
    courses = courses[:10]

    # ---- 最近听写：JOIN 句子取原文，按时间倒序 6 条 ----
    recent_rows = (
        db.query(Attempt, Sentence.text_en)
        .join(Sentence, Attempt.sentence_id == Sentence.id)
        .order_by(Attempt.created_at.desc())
        .limit(6)
        .all()
    )
    recent = [
        RecentAttemptOut(
            sentence_text=text_en or "",
            created_at=attempt.created_at,
            accuracy=attempt.accuracy,
        )
        for attempt, text_en in recent_rows
    ]

    # ---- 生词两态（Donut 数据源） ----
    vocab_total = _count(db, Vocab)
    vocab_mastered = (
        db.query(func.count(Vocab.id)).filter(Vocab.mastered.is_(True)).scalar() or 0
    )

    return OverviewOut(
        days=days,
        daily=daily,
        kpi=kpi,
        courses=courses,
        recent=recent,
        vocab=VocabStatsOut(total=vocab_total, mastered=vocab_mastered),
    )

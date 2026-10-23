"""学习数据聚合（听写记录 → 句子 / 媒体维度的统计，M3 / FR-A4）。

`attempts` 表只存最原始的一次次提交，这里把它折叠成前端需要的
「尝试次数 / 最佳正确率 / 上次正确率 / 是否已掌握」。
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import Attempt, Sentence


@dataclass
class SentenceStat:
    """单句的听写统计。"""

    attempt_count: int = 0
    best_accuracy: float = 0.0
    last_accuracy: float | None = None
    last_input: str = ""
    mastered: bool = False

    def as_dict(self) -> dict:
        return {
            "attempt_count": self.attempt_count,
            "best_accuracy": self.best_accuracy,
            "last_accuracy": self.last_accuracy,
            "last_input": self.last_input,
            "mastered": self.mastered,
        }


def _fold(rows: list[Attempt]) -> SentenceStat:
    """把某句的全部尝试折叠成统计（`rows` 需按 id 升序）。"""
    stat = SentenceStat()
    if not rows:
        return stat
    stat.attempt_count = len(rows)
    stat.best_accuracy = round(max(r.accuracy for r in rows), 1)
    stat.mastered = any(r.is_correct for r in rows)
    latest = rows[-1]
    stat.last_accuracy = round(latest.accuracy, 1)
    stat.last_input = latest.input
    return stat


def sentence_stats(db: Session, sentence_id: int, user_id: int) -> SentenceStat:
    """单句统计（提交听写后即时返回，避免前端再拉一次详情）。

    Args:
        user_id: 只统计该用户的听写记录（多用户隔离）。
    """
    rows = (
        db.query(Attempt)
        .filter(Attempt.sentence_id == sentence_id, Attempt.user_id == user_id)
        .order_by(Attempt.id)
        .all()
    )
    return _fold(rows)


def media_stats(db: Session, media_id: int, user_id: int) -> dict[int, SentenceStat]:
    """某个媒体下所有句子的统计（key = sentence_id，无记录的句不出现在结果里）。

    Args:
        user_id: 只统计该用户的听写记录（多用户隔离）。
    """
    rows = (
        db.query(Attempt)
        .join(Sentence, Sentence.id == Attempt.sentence_id)
        .filter(Sentence.media_id == media_id, Attempt.user_id == user_id)
        .order_by(Attempt.id)
        .all()
    )
    grouped: dict[int, list[Attempt]] = {}
    for attempt in rows:
        grouped.setdefault(attempt.sentence_id, []).append(attempt)
    return {sid: _fold(items) for sid, items in grouped.items()}


def summary(sentence_count: int, stats: dict[int, SentenceStat]) -> dict:
    """媒体级听写进度汇总。"""
    attempted = len(stats)
    return {
        "sentences": sentence_count,
        "attempted": attempted,
        "mastered": sum(1 for s in stats.values() if s.mastered),
        "total_attempts": sum(s.attempt_count for s in stats.values()),
        "avg_best_accuracy": (
            round(sum(s.best_accuracy for s in stats.values()) / attempted, 1)
            if attempted
            else 0.0
        ),
    }

"""学习统计单测（`services/study.py`）。

`study.py` 分两层：
- **纯函数层**：`_fold`（把某句的全部尝试折叠成统计）、`summary`（媒体级汇总）、
  `SentenceStat.as_dict` —— 只读对象属性，无需 DB；
- **DB 层**：`sentence_stats` / `media_stats` —— 需要会话，用 conftest 的临时库。

统计口径（照实现）：`attempt_count`/`best_accuracy`（round 1 位）/`mastered`（曾出现
一次 is_correct）/`last_accuracy`+`last_input`（**按 id 升序的最后一条**）。
"""

from __future__ import annotations

from app.models import Attempt, Media, Sentence
from app.services import study


def _attempt(sentence_id: int, input_text: str, accuracy: float, is_correct: bool) -> Attempt:
    """构造一个未持久化的 Attempt 对象（不写库）。"""
    return Attempt(
        sentence_id=sentence_id,
        input=input_text,
        accuracy=accuracy,
        is_correct=is_correct,
    )


# ---------------------------------------------------------------------------
# 纯函数层
# ---------------------------------------------------------------------------
class TestFold:
    def test_empty_rows_yields_defaults(self):
        stat = study._fold([])
        assert stat.attempt_count == 0
        assert stat.best_accuracy == 0.0
        assert stat.last_accuracy is None
        assert stat.last_input == ""
        assert stat.mastered is False

    def test_attempt_count(self):
        rows = [
            _attempt(1, "a", 50.0, False),
            _attempt(1, "b", 100.0, True),
            _attempt(1, "c", 80.0, False),
        ]
        assert study._fold(rows).attempt_count == 3

    def test_best_accuracy_is_max_rounded(self):
        rows = [
            _attempt(1, "a", 66.666, False),
            _attempt(1, "b", 91.234, False),
        ]
        assert study._fold(rows).best_accuracy == 91.2

    def test_mastered_true_when_any_correct(self):
        rows = [
            _attempt(1, "a", 50.0, False),
            _attempt(1, "b", 100.0, True),
            _attempt(1, "c", 80.0, False),
        ]
        assert study._fold(rows).mastered is True

    def test_mastered_false_when_none_correct(self):
        rows = [
            _attempt(1, "a", 50.0, False),
            _attempt(1, "b", 80.0, False),
        ]
        assert study._fold(rows).mastered is False

    def test_last_reflects_final_row(self):
        rows = [
            _attempt(1, "first", 50.0, False),
            _attempt(1, "second", 60.0, False),
            _attempt(1, "latest", 88.84, False),
        ]
        stat = study._fold(rows)
        assert stat.last_accuracy == 88.8
        assert stat.last_input == "latest"

    def test_as_dict_shape(self):
        stat = study._fold([_attempt(1, "x", 100.0, True)])
        assert stat.as_dict() == {
            "attempt_count": 1,
            "best_accuracy": 100.0,
            "last_accuracy": 100.0,
            "last_input": "x",
            "mastered": True,
        }


class TestSummary:
    def test_empty_stats(self):
        result = study.summary(10, {})
        assert result == {
            "sentences": 10,
            "attempted": 0,
            "mastered": 0,
            "total_attempts": 0,
            "avg_best_accuracy": 0.0,
        }

    def test_aggregates_across_sentences(self):
        stats = {
            1: study.SentenceStat(attempt_count=3, best_accuracy=100.0, mastered=True),
            2: study.SentenceStat(attempt_count=2, best_accuracy=80.0, mastered=False),
        }
        result = study.summary(7, stats)
        assert result["sentences"] == 7
        assert result["attempted"] == 2
        assert result["mastered"] == 1
        assert result["total_attempts"] == 5
        assert result["avg_best_accuracy"] == 90.0

    def test_avg_best_accuracy_rounded(self):
        stats = {
            1: study.SentenceStat(best_accuracy=66.7),
            2: study.SentenceStat(best_accuracy=66.8),
            3: study.SentenceStat(best_accuracy=50.0),
        }
        # (66.7 + 66.8 + 50.0) / 3 = 61.1666... → 61.2
        assert study.summary(3, stats)["avg_best_accuracy"] == 61.2


# ---------------------------------------------------------------------------
# DB 层（临时库）
# ---------------------------------------------------------------------------
def _seed_media_with_attempts(db) -> tuple[Media, Sentence, Sentence]:
    media = Media(title="demo", file_path="/tmp/demo.mp3", type="audio")
    db.add(media)
    db.commit()

    s1 = Sentence(media_id=media.id, idx=0, text_en="hello world")
    s2 = Sentence(media_id=media.id, idx=1, text_en="good bye")
    db.add_all([s1, s2])
    db.commit()

    db.add_all(
        [
            Attempt(sentence_id=s1.id, input="a", accuracy=50.0, is_correct=False),
            Attempt(sentence_id=s1.id, input="b", accuracy=100.0, is_correct=True),
            Attempt(sentence_id=s1.id, input="c", accuracy=80.0, is_correct=False),
            Attempt(sentence_id=s2.id, input="d", accuracy=20.0, is_correct=False),
        ]
    )
    db.commit()
    return media, s1, s2


class TestDbLayer:
    def test_sentence_stats(self, db_session):
        _media, s1, _s2 = _seed_media_with_attempts(db_session)
        stat = study.sentence_stats(db_session, s1.id)
        assert stat.attempt_count == 3
        assert stat.best_accuracy == 100.0
        assert stat.last_accuracy == 80.0
        assert stat.last_input == "c"
        assert stat.mastered is True

    def test_sentence_stats_no_rows(self, db_session):
        media = Media(title="empty", file_path="/tmp/e.mp3")
        db_session.add(media)
        db_session.commit()
        s = Sentence(media_id=media.id, idx=0, text_en="x")
        db_session.add(s)
        db_session.commit()

        stat = study.sentence_stats(db_session, s.id)
        assert stat.attempt_count == 0
        assert stat.last_accuracy is None

    def test_media_stats_groups_by_sentence(self, db_session):
        media, s1, s2 = _seed_media_with_attempts(db_session)
        stats = study.media_stats(db_session, media.id)
        assert set(stats.keys()) == {s1.id, s2.id}
        assert stats[s1.id].attempt_count == 3
        assert stats[s2.id].attempt_count == 1
        assert stats[s2.id].mastered is False

    def test_media_stats_excludes_untouched_sentences(self, db_session):
        media, s1, _s2 = _seed_media_with_attempts(db_session)
        s3 = Sentence(media_id=media.id, idx=2, text_en="never attempted")
        db_session.add(s3)
        db_session.commit()

        stats = study.media_stats(db_session, media.id)
        assert s3.id not in stats

"""`GET /api/stats/overview` 单测（P2 · 统计页聚合）。

覆盖 ARCH §6.1 的聚合口径：
- 空库全零（HTTP 200 非 404）
- `daily` 0 填充长度恒等于 `days`
- `streak_days` 边界（今天无听写 → 0）
- `courses.pct` 计算（0–100，total=0 → 0，按 pct desc）
- `recent` 按 created_at 倒序、LIMIT 6
- `vocab` 两态计数（total / mastered）

隔离策略：会话级测试库是共享的（其它测试模块也会写 media/sentence/attempt/vocab），
因此**每个用例先清空学习相关表**（`wipe_learning`），再种入本用例的哨兵数据，
对端点做**绝对断言**——比「基线 + delta」更直观，也不受其它模块残留干扰。

时区口径：端点用 `func.date(created_at, 'localtime')`（SQLite 把列当 UTC 再转本地），
测试里种子数据写入 **naive UTC** 时间，并用 Python 的 `astimezone()` 算出同一本地日，
两边一致、确定性可复现。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models import Attempt, Category, Media, Note, Sentence, Vocab


@pytest.fixture()
def wipe_learning(db_session):
    """清空学习相关表（子表在前，避免外键约束）。"""
    for model in (Attempt, Note, Vocab, Sentence, Media, Category):
        db_session.query(model).delete()
    db_session.commit()
    return db_session


def _local_today_iso() -> str:
    """与端点 `date.today()` 同一口径的本地日字符串。"""
    return datetime.now(timezone.utc).astimezone().date().isoformat()


def _utc_days_ago(days: int) -> datetime:
    """返回「本地 today 往前 days 天」中午对应的 naive UTC 时间（避开午夜边界）。"""
    local_now = datetime.now(timezone.utc).astimezone()
    target = (local_now - timedelta(days=days)).replace(hour=12, minute=0, second=0, microsecond=0)
    return target.astimezone(timezone.utc).replace(tzinfo=None)


def test_overview_empty_db_returns_zeroes(wipe_learning, authed_client):
    res = authed_client.get("/api/stats/overview")
    assert res.status_code == 200
    body = res.json()

    assert body["days"] == 14
    assert len(body["daily"]) == 14
    assert all(p["attempts"] == 0 and p["accuracy"] == 0.0 and p["new_vocab"] == 0 for p in body["daily"])
    assert body["kpi"] == {
        "today_attempts": 0,
        "today_accuracy": 0.0,
        "today_new_vocab": 0,
        "streak_days": 0,
    }
    assert body["courses"] == []
    assert body["recent"] == []
    assert body["vocab"] == {"total": 0, "mastered": 0}


def test_daily_zero_fill_length_equals_days(wipe_learning, db_session, authed_client):
    media = Media(title="demo", file_path="/tmp/demo.mp3", type="audio")
    db_session.add(media)
    db_session.commit()
    sentence = Sentence(media_id=media.id, idx=0, text_en="hello")
    db_session.add(sentence)
    db_session.commit()

    today_utc = _utc_days_ago(0)
    db_session.add(
        Attempt(sentence_id=sentence.id, input="hi", accuracy=0.8, is_correct=False, created_at=today_utc)
    )
    db_session.add(Vocab(word="hello", translation="你好", mastered=False, created_at=today_utc))
    db_session.commit()

    res = authed_client.get("/api/stats/overview?days=30")
    assert res.status_code == 200
    body = res.json()
    assert body["days"] == 30
    assert len(body["daily"]) == 30

    today_iso = _local_today_iso()
    non_zero = [p for p in body["daily"] if p["attempts"] > 0 or p["new_vocab"] > 0]
    # 只有「今天」有点，其余 29 天显式 0
    assert len(non_zero) == 1
    assert non_zero[0]["date"] == today_iso
    assert non_zero[0]["attempts"] == 1
    assert non_zero[0]["new_vocab"] == 1
    assert abs(non_zero[0]["accuracy"] - 0.8) < 1e-6


def test_streak_today_zero_yields_zero(wipe_learning, db_session, authed_client):
    media = Media(title="demo", file_path="/tmp/demo.mp3", type="audio")
    db_session.add(media)
    db_session.commit()
    sentence = Sentence(media_id=media.id, idx=0, text_en="hello")
    db_session.add(sentence)
    db_session.commit()
    # 只造「昨天」的听写，今天没有 → streak 应为 0
    db_session.add(
        Attempt(sentence_id=sentence.id, input="hi", accuracy=1.0, is_correct=True, created_at=_utc_days_ago(1))
    )
    db_session.commit()

    res = authed_client.get("/api/stats/overview")
    body = res.json()
    assert body["kpi"]["streak_days"] == 0
    assert body["kpi"]["today_attempts"] == 0


def test_streak_counts_consecutive_days(wipe_learning, db_session, authed_client):
    media = Media(title="demo", file_path="/tmp/demo.mp3", type="audio")
    db_session.add(media)
    db_session.commit()
    sentence = Sentence(media_id=media.id, idx=0, text_en="hello")
    db_session.add(sentence)
    db_session.commit()
    for days_ago in (0, 1, 2):
        db_session.add(
            Attempt(sentence_id=sentence.id, input="x", accuracy=0.5, is_correct=False, created_at=_utc_days_ago(days_ago))
        )
    # 第 3 天断档（跳过 days_ago=3），故连续段只有今天/昨天/前天 = 3
    db_session.commit()

    res = authed_client.get("/api/stats/overview")
    body = res.json()
    assert body["kpi"]["streak_days"] == 3
    assert body["kpi"]["today_attempts"] == 1


def test_courses_pct_and_order(wipe_learning, db_session, authed_client):
    # media A：2 句练过 1 句 → pct 50；media B：2 句全练过 → pct 100（应排第一）
    a = Media(title="A", file_path="/tmp/a.mp3", type="audio")
    b = Media(title="B", file_path="/tmp/b.mp3", type="audio")
    db_session.add_all([a, b])
    db_session.commit()

    a1 = Sentence(media_id=a.id, idx=0, text_en="a1")
    a2 = Sentence(media_id=a.id, idx=1, text_en="a2")
    b1 = Sentence(media_id=b.id, idx=0, text_en="b1")
    b2 = Sentence(media_id=b.id, idx=1, text_en="b2")
    db_session.add_all([a1, a2, b1, b2])
    db_session.commit()

    db_session.add(Attempt(sentence_id=a1.id, input="x", accuracy=1.0, is_correct=True, created_at=_utc_days_ago(0)))
    db_session.add(Attempt(sentence_id=b1.id, input="x", accuracy=1.0, is_correct=True, created_at=_utc_days_ago(0)))
    db_session.add(Attempt(sentence_id=b2.id, input="x", accuracy=1.0, is_correct=True, created_at=_utc_days_ago(0)))
    db_session.commit()

    res = authed_client.get("/api/stats/overview")
    courses = res.json()["courses"]
    assert len(courses) == 2
    assert courses[0]["media_id"] == b.id
    assert courses[0]["total"] == 2
    assert courses[0]["attempted"] == 2
    assert courses[0]["pct"] == 100.0
    assert courses[1]["media_id"] == a.id
    assert courses[1]["pct"] == 50.0


def test_courses_empty_media_pct_zero(wipe_learning, db_session, authed_client):
    a = Media(title="empty", file_path="/tmp/e.mp3", type="audio")
    db_session.add(a)
    db_session.commit()
    res = authed_client.get("/api/stats/overview")
    courses = res.json()["courses"]
    assert len(courses) == 1
    assert courses[0]["total"] == 0
    assert courses[0]["attempted"] == 0
    assert courses[0]["pct"] == 0.0


def test_recent_sorted_desc_limit_six(wipe_learning, db_session, authed_client):
    media = Media(title="demo", file_path="/tmp/demo.mp3", type="audio")
    db_session.add(media)
    db_session.commit()
    sentence = Sentence(media_id=media.id, idx=0, text_en="recent sentence")
    db_session.add(sentence)
    db_session.commit()

    base = _utc_days_ago(0).replace(hour=0, minute=0, second=0, microsecond=0)
    for i in range(8):
        db_session.add(
            Attempt(sentence_id=sentence.id, input=f"x{i}", accuracy=0.1 * i, is_correct=False, created_at=base + timedelta(minutes=i))
        )
    db_session.commit()

    res = authed_client.get("/api/stats/overview")
    recent = res.json()["recent"]
    assert len(recent) == 6
    assert recent[0]["sentence_text"] == "recent sentence"
    # 最新一条 accuracy = 0.1*7 = 0.7
    assert abs(recent[0]["accuracy"] - 0.7) < 1e-6
    # 倒序：created_at 递减
    stamps = [r["created_at"] for r in recent]
    assert stamps == sorted(stamps, reverse=True)


def test_vocab_two_state_counts(wipe_learning, db_session, authed_client):
    db_session.add(Vocab(word="a", mastered=True, created_at=_utc_days_ago(0)))
    db_session.add(Vocab(word="b", mastered=False, created_at=_utc_days_ago(0)))
    db_session.add(Vocab(word="c", mastered=False, created_at=_utc_days_ago(0)))
    db_session.commit()

    res = authed_client.get("/api/stats/overview")
    assert res.json()["vocab"] == {"total": 3, "mastered": 1}

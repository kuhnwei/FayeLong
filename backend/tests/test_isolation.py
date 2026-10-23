"""多用户数据隔离测试（v1.16.2）。

验证：用户 A 的学习数据（生词 / 笔记 / 听写 / 统计）对用户 B **不可见、不可改**，
（IDOR 校验点：vocab `_get_or_404` / note `_note_of` / attempt 列表 / stats 聚合）。
"""

from __future__ import annotations

from app.db import SessionLocal
from app.models import Attempt, Media, Note, Sentence, User, Vocab
from app.services import auth as auth_service


def _make_user(username: str) -> int:
    db = SessionLocal()
    try:
        salt = auth_service.new_salt()
        user = User(
            username=username,
            salt=salt,
            iterations=200_000,
            password_hash=auth_service.hash_password("pw-12345678", salt, 200_000),
            role="user",
            is_active=True,
            token_version=0,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user.id
    finally:
        db.close()


def _mint(client, uid: int) -> None:
    db = SessionLocal()
    try:
        secret = auth_service.get_secret(db)
        token = auth_service.issue_token(uid, secret, 600, 0)
    finally:
        db.close()
    client.cookies.set(auth_service.COOKIE_NAME, token)


def _seed_sentence(db, media_title: str) -> int:
    media = Media(title=media_title, file_path="/tmp/x.mp3", type="audio")
    db.add(media)
    db.commit()
    sentence = Sentence(media_id=media.id, idx=0, text_en="hello world")
    db.add(sentence)
    db.commit()
    return sentence.id


class TestIsolation:
    def test_vocab_invisible_across_users(self, client, authed_uid, db_session):
        # 用户 B 建生词
        b_id = _make_user("isolation-b")
        db_session.add(Vocab(user_id=b_id, word="hello"))
        db_session.commit()

        # 用户 A（authed_uid）看不到 B 的生词
        _mint(client, authed_uid)
        resp = client.get("/api/vocab")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_vocab_update_other_user_404(self, client, authed_uid, db_session):
        b_id = _make_user("isolation-b2")
        vocab = Vocab(user_id=b_id, word="hello")
        db_session.add(vocab)
        db_session.commit()

        _mint(client, authed_uid)
        # A 直接按 id 改 B 的生词 → 404（IDOR 校验）
        resp = client.patch(f"/api/vocab/{vocab.id}", json={"mastered": True})
        assert resp.status_code == 404

    def test_note_invisible_across_users(self, client, authed_uid, db_session):
        b_id = _make_user("isolation-b3")
        sid = _seed_sentence(db_session, "note-media")
        db_session.add(Note(sentence_id=sid, user_id=b_id, content="B 的笔记"))
        db_session.commit()

        _mint(client, authed_uid)
        # A 读同一句的笔记 → 空（每用户每句一条）
        resp = client.get(f"/api/notes/{sid}")
        assert resp.status_code == 200
        assert resp.json()["exists"] is False
        assert resp.json()["content"] == ""

    def test_attempt_history_invisible_across_users(self, client, authed_uid, db_session):
        b_id = _make_user("isolation-b4")
        sid = _seed_sentence(db_session, "attempt-media")
        db_session.add(Attempt(sentence_id=sid, user_id=b_id, input="hi", accuracy=100.0, is_correct=True))
        db_session.commit()

        _mint(client, authed_uid)
        resp = client.get(f"/api/sentences/{sid}/attempts")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_stats_isolated_per_user(self, client, authed_uid, db_session):
        b_id = _make_user("isolation-b5")
        db_session.add(Vocab(user_id=b_id, word="hello"))
        db_session.commit()

        _mint(client, authed_uid)
        resp = client.get("/api/stats")
        assert resp.status_code == 200
        # A 的生词统计不含 B 的数据
        assert resp.json()["vocab"]["total"] == 0

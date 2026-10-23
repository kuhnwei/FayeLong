"""「易听错」标记的多用户隔离测试（v1.16.2）。

验证：个人标记从共享的 `sentences.marks` 迁到 `sentence_marks` 后，
① 按用户隔离（A 的标记 B 看不到）；② 管理员改原文会清空**所有用户**的标记。
"""

from __future__ import annotations

from app.db import SessionLocal
from app.models import Media, Sentence, SentenceMark, User
from app.services import auth as auth_service


def _make_user(username: str, role: str = "user") -> int:
    db = SessionLocal()
    try:
        salt = auth_service.new_salt()
        user = User(
            username=username,
            salt=salt,
            iterations=200_000,
            password_hash=auth_service.hash_password("pw-12345678", salt, 200_000),
            role=role,
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


def _seed_media(db) -> tuple[int, int]:
    media = Media(title="marks", file_path="/tmp/m.mp3", type="audio")
    db.add(media)
    db.commit()
    sentence = Sentence(media_id=media.id, idx=0, text_en="hello world today")
    db.add(sentence)
    db.commit()
    return media.id, sentence.id


class TestMarksIsolation:
    def test_marks_scoped_to_user(self, client, authed_uid, db_session):
        media_id, sid = _seed_media(db_session)
        b_id = _make_user("marks-b")

        # A 保存标记
        _mint(client, authed_uid)
        resp = client.put(f"/api/sentences/{sid}/marks", json={"marks": [[0, 1]]})
        assert resp.status_code == 200
        assert resp.json()["marks"] == [[0, 1]]

        # B 读同一句的媒体详情 → 该句 marks 为空
        _mint(client, b_id)
        detail = client.get(f"/api/media/{media_id}").json()
        b_sentence = next(s for s in detail["sentences"] if s["id"] == sid)
        assert b_sentence["marks"] == []

        # A 读回来 → 仍是自己的标记
        _mint(client, authed_uid)
        detail_a = client.get(f"/api/media/{media_id}").json()
        a_sentence = next(s for s in detail_a["sentences"] if s["id"] == sid)
        assert a_sentence["marks"] == [[0, 1]]

    def test_content_edit_clears_all_users_marks(self, client, authed_uid, db_session):
        media_id, sid = _seed_media(db_session)
        b_id = _make_user("marks-b2")
        admin_id = _make_user("marks-admin", role="admin")

        # A 与 B 都保存标记
        _mint(client, authed_uid)
        client.put(f"/api/sentences/{sid}/marks", json={"marks": [[0, 1]]})
        _mint(client, b_id)
        client.put(f"/api/sentences/{sid}/marks", json={"marks": [[0, 0]]})

        # 铸管理员牌后改原文 → 所有用户的标记被清空（词下标漂移）
        _mint(client, admin_id)
        resp = client.patch(f"/api/sentences/{sid}", json={"text_en": "a completely new sentence"})
        assert resp.status_code == 200

        remaining = (
            db_session.query(SentenceMark).filter(SentenceMark.sentence_id == sid).count()
        )
        assert remaining == 0

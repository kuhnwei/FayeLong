"""管理员接口测试（v1.16.2 多用户）。

覆盖 `api/admin.py` 的：用户 CRUD、软删除保留数据、启停/改角色、重置密码、
最后一个管理员保护、非管理员 403、学习统计对比。
"""

from __future__ import annotations

from app.models import Attempt, Media, Note, Sentence, Vocab
from app.services import auth as auth_service

PASSWORD = "password123"


def _create(admin_client, username, password=PASSWORD, role="user"):
    return admin_client.post(
        "/api/admin/users",
        json={"username": username, "password": password, "role": role},
    )


class TestAdminAuth:
    def test_regular_user_forbidden(self, authed_client):
        resp = authed_client.get("/api/admin/users")
        assert resp.status_code == 403

    def test_unauthenticated_forbidden(self, client):
        resp = client.get("/api/admin/users")
        assert resp.status_code == 401


class TestAdminUsers:
    def test_list_includes_admin_and_created(self, admin_client):
        resp = admin_client.get("/api/admin/users")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        # 列表项含角色与统计摘要
        first = body["items"][0]
        assert "stats" in first
        assert "attempts_total" in first["stats"]

    def test_create_user_then_login(self, admin_client, client):
        resp = _create(admin_client, "alice")
        assert resp.status_code == 201
        assert resp.json()["role"] == "user"
        assert resp.json()["is_active"] is True

        # 新用户能用 admin 指定的密码登录
        client.cookies.clear()
        login = client.post(
            "/api/auth/login", json={"username": "alice", "password": PASSWORD}
        )
        assert login.status_code == 200
        assert login.json()["role"] == "user"

    def test_create_duplicate_username_conflict(self, admin_client):
        _create(admin_client, "bob")
        resp = _create(admin_client, "bob")
        assert resp.status_code == 409

    def test_create_rejects_short_password(self, admin_client):
        resp = admin_client.post(
            "/api/admin/users", json={"username": "carol", "password": "short"}
        )
        assert resp.status_code == 400


class TestAdminMutation:
    def test_disable_and_reenable(self, admin_client):
        uid = _create(admin_client, "dave").json()["id"]
        resp = admin_client.patch(f"/api/admin/users/{uid}", json={"is_active": False})
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False

        resp = admin_client.patch(f"/api/admin/users/{uid}", json={"is_active": True})
        assert resp.json()["is_active"] is True

    def test_soft_delete_keeps_data(self, admin_client, db_session):
        uid = _create(admin_client, "erin").json()["id"]
        # 给该用户种学习数据（vocab 无外键，可直接写）
        db_session.add(Vocab(user_id=uid, word="hello"))
        db_session.commit()

        resp = admin_client.delete(f"/api/admin/users/{uid}")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True

        # 数据保留（软删除不物理删行）
        from sqlalchemy import func
        assert db_session.query(func.count(Vocab.id)).filter(Vocab.user_id == uid).scalar() == 1

    def test_reset_password(self, admin_client, client):
        uid = _create(admin_client, "frank").json()["id"]
        resp = admin_client.post(
            f"/api/admin/users/{uid}/reset-password",
            json={"new_password": "brandnewpass99"},
        )
        assert resp.status_code == 200

        client.cookies.clear()
        assert client.post(
            "/api/auth/login", json={"username": "frank", "password": "brandnewpass99"}
        ).status_code == 200


class TestAdminGuardrails:
    def test_cannot_disable_self(self, admin_client):
        me = admin_client.get("/api/auth/status").json()
        resp = admin_client.patch(f"/api/admin/users/{me['id']}", json={"is_active": False})
        assert resp.status_code == 400

    def test_cannot_delete_self(self, admin_client):
        me = admin_client.get("/api/auth/status").json()
        resp = admin_client.delete(f"/api/admin/users/{me['id']}")
        assert resp.status_code == 400

    def test_cannot_demote_self(self, admin_client):
        me = admin_client.get("/api/auth/status").json()
        resp = admin_client.patch(f"/api/admin/users/{me['id']}", json={"role": "user"})
        assert resp.status_code == 400


class TestAdminStats:
    def test_single_user_stats(self, admin_client, authed_uid, db_session):
        media = Media(title="t", file_path="/tmp/t.mp3", type="audio")
        db_session.add(media)
        db_session.commit()
        sentence = Sentence(media_id=media.id, idx=0, text_en="hello")
        db_session.add(sentence)
        db_session.commit()
        db_session.add(Attempt(sentence_id=sentence.id, user_id=authed_uid, input="hi", accuracy=90.0, is_correct=True))
        db_session.add(Vocab(user_id=authed_uid, word="hello", mastered=True))
        db_session.commit()

        resp = admin_client.get(f"/api/admin/users/{authed_uid}/stats")
        assert resp.status_code == 200
        body = resp.json()
        assert body["attempts_total"] == 1
        assert body["vocab_total"] == 1
        assert body["vocab_mastered"] == 1

    def test_compare_returns_all_users(self, admin_client, db_session):
        resp = admin_client.get("/api/admin/users/compare")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        # 每个用户都有统计摘要
        assert all("stats" in item for item in body["items"])

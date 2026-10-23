"""API 层测试 · 登录与账号（P0-6 之二）。

覆盖 `api/auth.py` 的完整门禁生命周期：
- 首次 `POST /auth/setup` 建号（仅当无账号）；
- 登录成功 / 密码错误 / 未初始化；
- 改密（需已登录 + 校验当前密码，改后旧密码失效）；
- 登出清 cookie；
- **cookie 失效后受保护接口 401**（守卫为默认拒绝的中间件）。
"""

from __future__ import annotations

import pytest

from app.db import SessionLocal
from app.models import Attempt, Note, PracticeSession, Response, SentenceMark, User, Vocab
from app.services import auth as auth_service

#: 满足最短长度（8）的测试口令。
PASSWORD = "password123"
NEW_PASSWORD = "newpassword1"


@pytest.fixture(autouse=True)
def _reset_auth_state(app_client):
    """每个用例前：清 cookie + 清账号表 + 清登录节流，保证互相独立。

    先清带 `user_id` 外键的子表（多用户后 attempts/notes/vocab/sentence_marks/
    practice_sessions 引用 users），再清 users —— 否则 `DELETE FROM users` 会因
    NO ACTION 外键被拒（其它测试模块留下的学习数据仍引用着用户）。
    """
    app_client.cookies.clear()
    db = SessionLocal()
    try:
        for model in (Attempt, Note, Vocab, SentenceMark, Response, PracticeSession, User):
            db.query(model).delete()
        db.commit()
    finally:
        db.close()
    auth_service._failures.clear()
    yield
    app_client.cookies.clear()
    auth_service._failures.clear()


def _setup(client, username="faye", password=PASSWORD):
    return client.post(
        "/api/auth/setup", json={"username": username, "password": password}
    )


def _login(client, username="faye", password=PASSWORD):
    return client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------
class TestStatus:
    def test_needs_setup_when_no_account(self, client):
        resp = client.get("/api/auth/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["needs_setup"] is True
        assert body["authenticated"] is False
        assert body["username"] is None
        assert body["min_password_length"] == 8

    def test_authenticated_after_login(self, client):
        _setup(client)
        body = client.get("/api/auth/status").json()
        assert body["needs_setup"] is False
        assert body["authenticated"] is True
        assert body["username"] == "faye"


# ---------------------------------------------------------------------------
# setup
# ---------------------------------------------------------------------------
class TestSetup:
    def test_creates_account_and_issues_session(self, client):
        resp = _setup(client)
        assert resp.status_code == 200
        body = resp.json()
        assert body == {
            "needs_setup": False,
            "authenticated": True,
            "username": "faye",
            "min_password_length": 8,
            "id": 1,
            "role": "admin",      # 首次 setup 建的是管理员
            "is_active": True,
        }
        assert auth_service.COOKIE_NAME in client.cookies
        # 建号后即可访问受保护接口
        assert client.get("/api/media").status_code == 200

    def test_rejected_when_account_exists(self, client):
        _setup(client)
        resp = client.post(
            "/api/auth/setup", json={"username": "intruder", "password": PASSWORD}
        )
        assert resp.status_code == 409

    def test_rejects_short_password(self, client):
        resp = client.post(
            "/api/auth/setup", json={"username": "faye", "password": "short"}
        )
        assert resp.status_code == 400

    def test_rejects_blank_username(self, client):
        resp = client.post(
            "/api/auth/setup", json={"username": "   ", "password": PASSWORD}
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# login / logout
# ---------------------------------------------------------------------------
class TestLoginLogout:
    def test_login_success(self, client):
        _setup(client)
        client.cookies.clear()
        resp = _login(client)
        assert resp.status_code == 200
        assert resp.json()["authenticated"] is True
        assert auth_service.COOKIE_NAME in client.cookies

    def test_login_wrong_password(self, client):
        _setup(client)
        client.cookies.clear()
        resp = _login(client, password="wrongpassword")
        assert resp.status_code == 401
        assert resp.json()["detail"] == "用户名或密码不正确"

    def test_login_wrong_username(self, client):
        _setup(client)
        client.cookies.clear()
        resp = _login(client, username="someone-else")
        assert resp.status_code == 401

    def test_login_before_setup(self, client):
        resp = _login(client)
        assert resp.status_code == 409

    def test_logout_clears_session(self, client):
        _setup(client)
        assert client.get("/api/media").status_code == 200

        resp = client.post("/api/auth/logout")
        assert resp.status_code == 200
        assert resp.json()["authenticated"] is False
        assert client.get("/api/media").status_code == 401


# ---------------------------------------------------------------------------
# 改密
# ---------------------------------------------------------------------------
class TestChangePassword:
    def test_requires_login(self, client):
        _setup(client)
        client.cookies.clear()
        resp = client.post(
            "/api/auth/password",
            json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        )
        assert resp.status_code == 401

    def test_wrong_current_password(self, client):
        _setup(client)
        resp = client.post(
            "/api/auth/password",
            json={"current_password": "nope-1234567", "new_password": NEW_PASSWORD},
        )
        assert resp.status_code == 400

    def test_new_password_too_short(self, client):
        _setup(client)
        resp = client.post(
            "/api/auth/password",
            json={"current_password": PASSWORD, "new_password": "short"},
        )
        assert resp.status_code == 400

    def test_successful_change_invalidates_old_password(self, client):
        _setup(client)
        resp = client.post(
            "/api/auth/password",
            json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        )
        assert resp.status_code == 200

        client.cookies.clear()
        assert _login(client, password=NEW_PASSWORD).status_code == 200

        client.cookies.clear()
        assert _login(client, password=PASSWORD).status_code == 401


# ---------------------------------------------------------------------------
# 多用户（v1.16.2）
# ---------------------------------------------------------------------------
def _create_user(username: str, password: str, *, role: str = "user", is_active: bool = True) -> int:
    """直接落库建一个用户（管理员 API 在 G3 才实现，这里绕过 API 造数据）。"""
    db = SessionLocal()
    try:
        salt = auth_service.new_salt()
        user = User(
            username=username,
            salt=salt,
            iterations=200_000,
            password_hash=auth_service.hash_password(password, salt, 200_000),
            role=role,
            is_active=is_active,
            token_version=0,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user.id
    finally:
        db.close()


class TestMultiUser:
    def test_two_users_login_independently(self, client):
        _setup(client, username="admin1")  # 建 admin
        _create_user("alice", PASSWORD)     # 建普通用户
        client.cookies.clear()

        resp = _login(client, username="admin1")
        assert resp.status_code == 200
        assert resp.json()["role"] == "admin"
        assert resp.json()["id"] == 1

        client.cookies.clear()
        resp = _login(client, username="alice")
        assert resp.status_code == 200
        assert resp.json()["role"] == "user"
        assert resp.json()["id"] == 2

    def test_disabled_account_cannot_login(self, client):
        _setup(client, username="admin1")
        _create_user("alice", PASSWORD, is_active=False)
        client.cookies.clear()

        resp = _login(client, username="alice")
        assert resp.status_code == 403

    def test_disabled_account_old_cookie_invalidated(self, client):
        _setup(client, username="admin1")
        uid = _create_user("alice", PASSWORD)
        client.cookies.clear()
        assert _login(client, username="alice").status_code == 200

        # 管理员停用 alice（is_active=False + bump token_version）。
        db = SessionLocal()
        try:
            user = db.get(User, uid)
            user.is_active = False
            auth_service.bump_token_version(db, user)
            db.commit()
        finally:
            db.close()

        # alice 的旧 cookie 立即失效（守卫回查 is_active + token_version）。
        assert client.get("/api/media").status_code == 401

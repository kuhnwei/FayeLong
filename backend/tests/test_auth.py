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
from app.models import User
from app.services import auth as auth_service

#: 满足最短长度（8）的测试口令。
PASSWORD = "password123"
NEW_PASSWORD = "newpassword1"


@pytest.fixture(autouse=True)
def _reset_auth_state(app_client):
    """每个用例前：清 cookie + 清账号表 + 清登录节流，保证互相独立。"""
    app_client.cookies.clear()
    db = SessionLocal()
    try:
        db.query(User).delete()
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

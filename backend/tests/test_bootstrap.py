"""管理员账号自动初始化测试（v1.16.2）。

验证 `services/bootstrap.py::ensure_admin_user` 的三条分支：
空库跳过、有普通用户无 admin 时自动建 admin、已有 admin 幂等退出。
"""

from __future__ import annotations

import pytest

from app.db import SessionLocal
from app.models import Attempt, Note, PracticeSession, Response, SentenceMark, User, Vocab
from app.services import auth as auth_service
from app.services import bootstrap


@pytest.fixture(autouse=True)
def _clean(db_session):
    """每个用例前清空用户与学习子表（session 级库共享，防止 username 唯一冲突）。"""
    for model in (Attempt, Note, Vocab, SentenceMark, Response, PracticeSession, User):
        db_session.query(model).delete()
    db_session.commit()
    yield


def _make_user(username: str, role: str = "user") -> None:
    db = SessionLocal()
    try:
        salt = auth_service.new_salt()
        db.add(
            User(
                username=username,
                salt=salt,
                iterations=200_000,
                password_hash=auth_service.hash_password("pw-12345678", salt, 200_000),
                role=role,
                is_active=True,
                token_version=0,
            )
        )
        db.commit()
    finally:
        db.close()


def _count(db) -> int:
    return db.query(User).count()


def _admin_exists(db) -> bool:
    return db.query(User).filter(User.role == auth_service.ROLE_ADMIN).first() is not None


class TestBootstrap:
    def test_empty_db_skips(self, db_session):
        bootstrap.ensure_admin_user()
        assert _count(db_session) == 0

    def test_legacy_db_creates_admin(self, db_session):
        _make_user("legacy-user", role="user")  # 模拟迁移后的老库唯一普通用户
        bootstrap.ensure_admin_user()

        assert _admin_exists(db_session)
        admin = db_session.query(User).filter(User.username == "admin").first()
        assert admin is not None
        assert admin.role == "admin"
        assert admin.is_active is True

    def test_existing_admin_is_noop(self, db_session):
        _make_user("legacy-user", role="user")
        bootstrap.ensure_admin_user()
        assert _count(db_session) == 2

        # 再次调用 → 幂等，不新增
        bootstrap.ensure_admin_user()
        assert _count(db_session) == 2

    def test_username_admin_collision_warns_and_skips(self, db_session):
        _make_user("admin", role="user")  # 已有名为 admin 的普通用户
        bootstrap.ensure_admin_user()
        # 不覆盖、不新增 admin
        assert _count(db_session) == 1
        assert not _admin_exists(db_session)

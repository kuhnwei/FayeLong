"""管理员账号自动初始化（v1.16.2）。

迁移后的老库场景：库里有普通用户（旧唯一账号），但没有管理员。这里自动创建
`admin` 账号，初始密码随机生成并打印到控制台 / 日志，首次登录建议改密。
"""

from __future__ import annotations

import logging

from app.db import SessionLocal
from app.models import User
from app.services import auth as auth_service

logger = logging.getLogger(__name__)


def ensure_admin_user() -> None:
    """保证库里至少有一个管理员（幂等，web 进程启动时调用）。

    逻辑：
    - 全新空库 → 直接返回，交给 `/api/auth/setup`（首次引导建 admin，用户自选密码）；
    - 已有任意 admin → 幂等退出；
    - 已存在名为 `admin` 的普通用户 → 警告跳过（避免覆盖/冲突）；
    - 否则（迁移后的老库：有普通用户但无 admin）→ 创建 `admin`，随机密码打印。
    """
    db = SessionLocal()
    try:
        if auth_service.count_users(db) == 0:
            return
        if db.query(User).filter(User.role == auth_service.ROLE_ADMIN).first() is not None:
            return
        if db.query(User).filter(User.username == "admin").first() is not None:
            logger.warning("已存在名为 admin 的普通用户，跳过自动建号，请手动指定管理员")
            return

        password = auth_service.new_admin_password()
        salt = auth_service.new_salt()
        iterations = 200_000
        user = User(
            username="admin",
            salt=salt,
            iterations=iterations,
            password_hash=auth_service.hash_password(password, salt, iterations),
            role=auth_service.ROLE_ADMIN,
            is_active=True,
            token_version=0,
        )
        db.add(user)
        try:
            db.commit()
        except Exception:  # noqa: BLE001  并发首启时另一进程可能已建好
            db.rollback()
            logger.info("创建 admin 时发现已存在（并发首启），跳过")
            return

        # 双保险：print 到 stdout（systemd StandardOutput 落盘）+ logger.warning。
        print(
            f"[FayeLong] 已创建管理员账号：admin  初始密码：{password}  （首次登录请改密）"
        )
        logger.warning("已创建管理员账号 admin，初始密码：%s（首次登录请改密）", password)
    finally:
        db.close()

"""管理员接口（v1.16.2 多用户）：用户管理 + 学习统计对比。

全部端点挂 `/api/admin/*`（**绝不**挂 `/api/auth/*` —— 后者是全局公开前缀，
挂上去会绕过登录门禁）。所有端点依赖 `require_admin`（非管理员 → 403）。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.auth import require_admin
from app.core.config import settings
from app.db import get_db
from app.models import User
from app.schemas.admin import (
    AdminPasswordReset,
    AdminUserCreate,
    AdminUserList,
    AdminUserOut,
    AdminUserSummary,
    AdminUserUpdate,
)
from app.services import admin_stats
from app.services import auth as auth_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _check_password_shape(password: str) -> None:
    minimum = settings.auth_min_password_length
    if len(password) < minimum:
        raise HTTPException(status_code=400, detail=f"密码至少 {minimum} 位")


def _get_or_404(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    return user


def _is_last_active_admin(db: Session, exclude_id: int) -> bool:
    """除了 `exclude_id` 之外，是否已经没有其它「可用管理员」。"""
    return (
        db.query(User)
        .filter(
            User.role == auth_service.ROLE_ADMIN,
            User.is_active.is_(True),
            User.id != exclude_id,
        )
        .first()
        is None
    )


def _to_out(db: Session, user: User) -> AdminUserOut:
    return AdminUserOut(
        id=user.id,
        username=user.username,
        role=user.role,
        is_active=bool(user.is_active),
        created_at=user.created_at,
        last_login_at=user.last_login_at,
        stats=AdminUserSummary(**admin_stats.user_summary(db, user.id)),
    )


@router.get("/users", response_model=AdminUserList)
def list_users(
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AdminUserList:
    """用户列表（含每人的学习统计摘要，供对比）。"""
    users = db.query(User).order_by(User.id).all()
    return AdminUserList(items=[_to_out(db, u) for u in users], total=len(users))


@router.get("/users/compare", response_model=AdminUserList)
def compare_users(
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AdminUserList:
    """多用户学习状态对比（与 `/users` 同口径，语义化别名）。"""
    users = db.query(User).order_by(User.id).all()
    return AdminUserList(items=[_to_out(db, u) for u in users], total=len(users))


@router.get("/users/{user_id}/stats", response_model=AdminUserSummary)
def get_user_stats(
    user_id: int,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AdminUserSummary:
    """单个用户的详细学习统计。"""
    _get_or_404(db, user_id)
    return AdminUserSummary(**admin_stats.user_summary(db, user_id))


@router.post("/users", response_model=AdminUserOut, status_code=201)
def create_user(
    payload: AdminUserCreate,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AdminUserOut:
    """创建用户（默认普通用户，可显式建管理员）。"""
    username = payload.username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="用户名不能为空")
    _check_password_shape(payload.password)

    if auth_service.get_by_username(db, username) is not None:
        raise HTTPException(status_code=409, detail=f"用户名「{username}」已存在")

    salt = auth_service.new_salt()
    iterations = 200_000
    user = User(
        username=username,
        salt=salt,
        iterations=iterations,
        password_hash=auth_service.hash_password(payload.password, salt, iterations),
        role=payload.role,
        is_active=True,
        token_version=0,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info("管理员已创建用户：%s（role=%s）", user.username, user.role)
    return _to_out(db, user)


@router.patch("/users/{user_id}", response_model=AdminUserOut)
def update_user(
    user_id: int,
    payload: AdminUserUpdate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AdminUserOut:
    """启停 / 改角色。停用或降级会让该用户的旧会话立即失效。"""
    target = _get_or_404(db, user_id)

    if payload.is_active is not None:
        if not payload.is_active and target.id == admin.id:
            raise HTTPException(status_code=400, detail="不能停用自己的账号")
        if not payload.is_active and target.role == auth_service.ROLE_ADMIN and _is_last_active_admin(db, target.id):
            raise HTTPException(status_code=409, detail="不能停用最后一个管理员")
        target.is_active = payload.is_active

    if payload.role is not None:
        if payload.role != auth_service.ROLE_ADMIN and target.id == admin.id:
            raise HTTPException(status_code=400, detail="不能把自己的账号降级为普通用户")
        if (
            payload.role != auth_service.ROLE_ADMIN
            and target.role == auth_service.ROLE_ADMIN
            and _is_last_active_admin(db, target.id)
        ):
            raise HTTPException(status_code=409, detail="不能降级最后一个管理员")
        target.role = payload.role

    # 任何变更都 bump token_version：被停用/降级的用户旧 cookie 立即失效。
    auth_service.bump_token_version(db, target)
    db.commit()
    db.refresh(target)
    logger.info("管理员更新用户 %s：role=%s is_active=%s", target.username, target.role, target.is_active)
    return _to_out(db, target)


@router.post("/users/{user_id}/reset-password", response_model=dict)
def reset_password(
    user_id: int,
    payload: AdminPasswordReset,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """重置密码（admin 指定新密码）；重置后旧会话立即失效。"""
    target = _get_or_404(db, user_id)
    _check_password_shape(payload.new_password)

    target.salt = auth_service.new_salt()
    target.password_hash = auth_service.hash_password(
        payload.new_password, target.salt, target.iterations
    )
    auth_service.bump_token_version(db, target)
    db.commit()
    logger.info("管理员重置了用户 %s 的密码", target.username)
    return {"id": target.id, "username": target.username, "reset": True}


@router.delete("/users/{user_id}", status_code=200)
def delete_user(
    user_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """软删除用户（`is_active=false`，数据保留）；旧会话立即失效。"""
    target = _get_or_404(db, user_id)
    if target.id == admin.id:
        raise HTTPException(status_code=400, detail="不能删除自己的账号")
    if target.role == auth_service.ROLE_ADMIN and _is_last_active_admin(db, target.id):
        raise HTTPException(status_code=409, detail="不能删除最后一个管理员")

    target.is_active = False
    auth_service.bump_token_version(db, target)
    db.commit()
    logger.info("管理员软删除了用户 %s（数据保留）", target.username)
    return {"id": target.id, "username": target.username, "deleted": True}

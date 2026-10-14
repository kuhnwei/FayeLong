"""登录与账号接口（v1.12 单账号门禁）。

- `GET  /api/auth/status`    前端启动时问「要初始化吗 / 我登录了吗」
- `POST /api/auth/setup`     **仅当还没有账号时**可用 —— 首次访问引导创建，建完即锁定
- `POST /api/auth/login`     校验并下发会话 cookie
- `POST /api/auth/logout`    清 cookie
- `POST /api/auth/password`  改密码（需已登录）

`/api/auth/*` 在全局守卫里是公开前缀，其余接口默认要求登录。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import get_db
from app.models import User
from app.schemas.auth import AuthStatus, Credentials, PasswordChange
from app.services import auth as auth_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


# --------------------------- 内部工具 ---------------------------

def _client_key(request: Request) -> str:
    """节流用的客户端标识。线上经 Caddy 反代，真实 IP 在 X-Forwarded-For 里。"""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _check_password_shape(password: str) -> None:
    minimum = settings.auth_min_password_length
    if len(password) < minimum:
        raise HTTPException(
            status_code=400,
            detail=f"密码至少 {minimum} 位（这台服务在公网，别用弱口令）",
        )


def _status_of(user: User | None, needs_setup: bool) -> AuthStatus:
    return AuthStatus(
        needs_setup=needs_setup,
        authenticated=user is not None,
        username=user.username if user else None,
        min_password_length=settings.auth_min_password_length,
    )


def current_user(request: Request, db: Session) -> User | None:
    """从 cookie 解出当前登录用户。"""
    token = request.cookies.get(auth_service.COOKIE_NAME)
    if not token:
        return None
    uid = auth_service.verify_token(token, auth_service.read_secret(db))
    if uid is None:
        return None
    return db.get(User, uid)


def _set_session(response: Response, user_id: int, secret: bytes) -> None:
    ttl = settings.auth_session_days * 86400
    response.set_cookie(
        auth_service.COOKIE_NAME,
        auth_service.issue_token(user_id, secret, ttl),
        max_age=ttl,
        httponly=True,      # 前端 JS 读不到，防 XSS 窃取
        samesite="lax",     # 跨站请求不带 cookie，防 CSRF
        path="/",
    )


# --------------------------- 接口 ---------------------------

@router.get("/status", response_model=AuthStatus)
def auth_status(request: Request, db: Session = Depends(get_db)) -> AuthStatus:
    """鉴权状态。前端据此决定渲染「首次设置」「登录页」还是应用本体。"""
    user = auth_service.first_user(db)
    mine = current_user(request, db)
    return _status_of(mine, needs_setup=user is None)


@router.post("/setup", response_model=AuthStatus)
def setup(
    payload: Credentials,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> AuthStatus:
    """首次初始化账号。已存在账号时一律拒绝（防止公网上被抢占/重置）。"""
    if auth_service.first_user(db) is not None:
        raise HTTPException(status_code=409, detail="账号已存在，不能重复初始化")

    username = payload.username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="用户名不能为空")
    _check_password_shape(payload.password)

    salt = auth_service.new_salt()
    iterations = 200_000
    user = User(
        username=username,
        salt=salt,
        iterations=iterations,
        password_hash=auth_service.hash_password(payload.password, salt, iterations),
        last_login_at=auth_service.utcnow(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    _set_session(response, user.id, auth_service.get_secret(db))
    logger.info("已初始化站点账号：%s", user.username)
    return _status_of(user, needs_setup=False)


@router.post("/login", response_model=AuthStatus)
def login(
    payload: Credentials,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> AuthStatus:
    """登录。失败次数过多会临时封禁该来源 IP。"""
    key = _client_key(request)
    remaining = auth_service.throttle_remaining(key)
    if remaining:
        raise HTTPException(
            status_code=429,
            detail=f"登录失败次数过多，请 {remaining} 秒后再试",
        )

    user = auth_service.first_user(db)
    if user is None:
        raise HTTPException(status_code=409, detail="尚未初始化账号，请先设置用户名与密码")

    # 两个判断都算完再合并，保证「用户名错」与「密码错」耗时一致
    username_ok = payload.username.strip() == user.username
    password_ok = auth_service.verify_password(payload.password, user)
    if not (username_ok and password_ok):
        auth_service.record_failure(key)
        logger.warning("登录失败：user=%s from=%s", payload.username, key)
        raise HTTPException(status_code=401, detail="用户名或密码不正确")

    auth_service.clear_failures(key)
    user.last_login_at = auth_service.utcnow()
    db.commit()
    _set_session(response, user.id, auth_service.get_secret(db))
    return _status_of(user, needs_setup=False)


@router.post("/logout", response_model=AuthStatus)
def logout(response: Response, db: Session = Depends(get_db)) -> AuthStatus:
    """退出登录：只清 cookie（token 无状态，服务端无需额外作废）。"""
    response.delete_cookie(auth_service.COOKIE_NAME, path="/")
    user = auth_service.first_user(db)
    return _status_of(None, needs_setup=user is None)


@router.post("/password", response_model=AuthStatus)
def change_password(
    payload: PasswordChange,
    request: Request,
    db: Session = Depends(get_db),
) -> AuthStatus:
    """修改密码。需已登录且知道当前密码。"""
    user = current_user(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="未登录或登录已过期，请重新登录")
    if not auth_service.verify_password(payload.current_password, user):
        raise HTTPException(status_code=400, detail="当前密码不正确")
    _check_password_shape(payload.new_password)

    # 换盐重算：旧 cookie 里只有 uid 与过期时间，不依赖旧密码，改密后仍有效
    user.salt = auth_service.new_salt()
    user.password_hash = auth_service.hash_password(
        payload.new_password, user.salt, user.iterations
    )
    db.commit()
    logger.info("已修改站点账号密码：%s", user.username)
    return _status_of(user, needs_setup=False)

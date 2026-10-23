"""站点访问控制：单账号门禁 + 首次访问引导创建（v1.12）。

三个设计取舍，改动前请先读懂：

1. **零新增依赖**。密码用标准库 `hashlib.pbkdf2_hmac` 派生，不引入 passlib/bcrypt。
   这个项目要交付到「没有开发环境的 Windows 笔记本」，能不加依赖就不加；
   PBKDF2-HMAC-SHA256 加盐迭代对本站这种单账号门禁完全够用。
2. **签名 cookie 而非服务端 session**。token 里带 `uid` 与过期时间，用 HMAC-SHA256 签名，
   服务端只验签、不存状态。两个好处：重启不掉线；`data/` 整体迁移时登录态跟着走
   （内存 session 会重启即全员掉线）。
3. **签名密钥随 `data/` 迁移**。首先生成后写入 `settings` 表。密钥一变旧 cookie 全失效，
   放进数据库才能保证换机搬迁后登录态不作废。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import Setting, User

#: 会话 cookie 名。前端不需要读它（HttpOnly），只用于浏览器自动携带。
COOKIE_NAME = "fayelong_session"

#: `settings` 表里存放签名密钥的键
SECRET_KEY = "auth.secret"

#: 用户角色（v1.16.2 多用户）
ROLE_ADMIN = "admin"
ROLE_USER = "user"

_ALGO = "sha256"
_DEFAULT_ITERATIONS = 200_000

# 登录失败节流（进程内，够用；本站是单进程单账号）
_MAX_FAILURES = 8
_WINDOW_SECONDS = 300
_failures: dict[str, list[float]] = {}


# --------------------------- 密码 ---------------------------

def new_salt() -> str:
    """生成 16 字节随机盐（十六进制）。"""
    return secrets.token_hex(16)


def hash_password(password: str, salt: str, iterations: int = _DEFAULT_ITERATIONS) -> str:
    """PBKDF2-HMAC-SHA256 派生，返回十六进制摘要。"""
    derived = hashlib.pbkdf2_hmac(_ALGO, password.encode("utf-8"), bytes.fromhex(salt), iterations)
    return derived.hex()


def verify_password(password: str, user: User) -> bool:
    """恒定时比较，避免通过响应时间侧信道猜密码。

    注意：**无论用户名对不对都要调用本函数**，否则响应快慢会泄露用户名是否存在。
    """
    candidate = hash_password(password, user.salt, user.iterations)
    return hmac.compare_digest(candidate, user.password_hash)


def utcnow() -> datetime:
    """SQLite 的 CURRENT_TIMESTAMP 存的是 UTC，这里保持一致（naive UTC）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_admin_password() -> str:
    """为自动创建的管理员生成一次性初始密码（打印到控制台，首次登录改密）。"""
    return secrets.token_urlsafe(12)


# --------------------------- 账号 ---------------------------

def count_users(db: Session) -> int:
    """用户总数（用于判断「是否还需要初始化引导」）。"""
    return db.query(User).count()


def get_by_username(db: Session, username: str) -> User | None:
    """按用户名查用户（多用户登录）。"""
    return db.query(User).filter(User.username == username).first()


def dummy_user() -> User:
    """供「用户名不存在」时做恒定时比较的假用户（不落库）。

    login 里即使查无此人也走一遍 `verify_password`，避免响应时间泄露用户名
    是否存在（侧信道）。
    """
    return User(
        username="",
        salt="00" * 16,
        password_hash="0" * 64,
        iterations=_DEFAULT_ITERATIONS,
    )


# --------------------------- 会话 token ---------------------------

def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def read_secret(db: Session) -> bytes | None:
    """只读签名密钥；尚未生成时返回 None（守卫用，绝不产生写操作）。"""
    row = db.get(Setting, SECRET_KEY)
    if row is None or not row.value:
        return None
    try:
        return bytes.fromhex(row.value)
    except ValueError:  # 键被外部改坏时视为无密钥，强制重新登录
        return None


def get_secret(db: Session) -> bytes:
    """读取签名密钥，缺失则生成并落库。"""
    existing = read_secret(db)
    if existing is not None:
        return existing
    value = secrets.token_hex(32)
    row = db.get(Setting, SECRET_KEY)
    if row is None:
        db.add(Setting(key=SECRET_KEY, value=value))
    else:
        row.value = value
    db.commit()
    return bytes.fromhex(value)


def issue_token(user_id: int, secret: bytes, ttl_seconds: int, token_version: int = 0) -> str:
    """签发 `base64(payload).base64(hmac)` 形式的会话 token。

    Args:
        token_version: 会话吊销版本号。改密 / 重置 / 停用 / 软删时 +1，旧 cookie
            携带的旧版本号会在守卫处被拒，实现「即时失效」。
    """
    payload = {"uid": user_id, "exp": int(time.time()) + ttl_seconds, "ver": token_version}
    body = _b64e(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = _b64e(hmac.new(secret, body.encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{signature}"


def verify_token(token: str, secret: bytes | None) -> tuple[int, int] | None:
    """验签并检查过期，通过返回 ``(user_id, token_version)``，否则 None。

    迁移前（单用户门禁）签发的旧 cookie 没有 ``ver`` 字段，这里按 0 兜底，
    避免一升级就全员掉线；旧 cookie 只在管理员对该用户做了禁用/重置后才失效。
    """
    if not token or secret is None or "." not in token:
        return None
    body, _, signature = token.partition(".")
    expected = _b64e(hmac.new(secret, body.encode("ascii"), hashlib.sha256).digest())
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        payload = json.loads(_b64d(body))
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    uid, exp = payload.get("uid"), payload.get("exp")
    if not isinstance(uid, int) or not isinstance(exp, int):
        return None
    if exp < int(time.time()):
        return None
    ver = payload.get("ver", 0)
    if not isinstance(ver, int):
        return None
    return uid, ver


def bump_token_version(db: Session, user: User) -> None:
    """让该用户所有已签发的旧 cookie 立即失效（改密/重置/停用/软删时调用）。"""
    user.token_version = (user.token_version or 0) + 1


# --------------------------- 登录节流 ---------------------------

def throttle_remaining(key: str) -> int:
    """剩余封禁秒数；0 表示可以继续尝试。"""
    now = time.time()
    hits = [t for t in _failures.get(key, []) if now - t < _WINDOW_SECONDS]
    _failures[key] = hits
    if len(hits) < _MAX_FAILURES:
        return 0
    return int(_WINDOW_SECONDS - (now - hits[0])) + 1


def record_failure(key: str) -> None:
    now = time.time()
    hits = [t for t in _failures.get(key, []) if now - t < _WINDOW_SECONDS]
    hits.append(now)
    _failures[key] = hits


def clear_failures(key: str) -> None:
    _failures.pop(key, None)


__all__ = [
    "COOKIE_NAME",
    "ROLE_ADMIN",
    "ROLE_USER",
    "hash_password",
    "new_salt",
    "verify_password",
    "utcnow",
    "new_admin_password",
    "count_users",
    "get_by_username",
    "dummy_user",
    "read_secret",
    "get_secret",
    "issue_token",
    "verify_token",
    "bump_token_version",
    "throttle_remaining",
    "record_failure",
    "clear_failures",
]

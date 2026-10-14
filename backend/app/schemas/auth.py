"""登录与账号相关的请求 / 响应模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class AuthStatus(BaseModel):
    """前端启动时最先拉取的鉴权状态。"""

    needs_setup: bool
    authenticated: bool
    username: str | None = None
    #: 密码最短长度由后端下发，避免前后端各写一份规则而漂移
    min_password_length: int = 8


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=256)


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)

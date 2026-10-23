"""管理员接口的请求 / 响应模型（v1.16.2 多用户）。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class AdminUserCreate(BaseModel):
    """创建普通/管理员用户（仅 admin 可调）。"""

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)
    role: Literal["admin", "user"] = "user"


class AdminUserUpdate(BaseModel):
    """启停 / 改角色（字段均可选）。"""

    is_active: bool | None = None
    role: Literal["admin", "user"] | None = None


class AdminPasswordReset(BaseModel):
    """重置密码（admin 指定新密码）。"""

    new_password: str = Field(min_length=1, max_length=256)


class AdminUserSummary(BaseModel):
    """单个用户的学习统计摘要（全部按 `user_id` 聚合）。"""

    attempts_total: int = 0
    attempts_avg_accuracy: float | None = None
    attempted_sentences: int = 0
    mastered_sentences: int = 0
    vocab_total: int = 0
    vocab_mastered: int = 0
    notes_count: int = 0
    sessions_total: int = 0
    streak_days: int = 0


class AdminUserOut(BaseModel):
    """用户列表项（含统计摘要，供对比）。"""

    id: int
    username: str
    role: str
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None
    stats: AdminUserSummary


class AdminUserList(BaseModel):
    items: list[AdminUserOut]
    total: int

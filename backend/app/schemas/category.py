"""媒体库分类相关的请求 / 响应模型（规格 §3.1）。

字段名已冻结，不得改动。`media_count` 由服务端聚合得出；
「未分类」不是真实分类，其数量单列在 `CategoryListResponse.uncategorized_count`。
"""

from datetime import datetime
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator

#: 分类名长度上限（字符数，strip 后）。
NAME_MAX_LENGTH = 32


def _check_name(value: Any) -> Any:
    """`mode="before"` 校验：先 strip 再按字符数校验（规格 §2.1）。

    —— 为什么必须在**字段约束之前**跑：规格 §3.1 冻结了「空名 / 超长 → 400」，
    而 Pydantic 的 `max_length` 约束失败会被 FastAPI 转成 **422**，与契约（400）冲突。
    这里在字段长度约束之前抛出 `HTTPException(400)`，既保留 `max_length=NAME_MAX_LENGTH`
    的声明（OpenAPI / 兜底），又让超长输入得到契约要求的 400。
    非字符串（类型错误）交回 Pydantic 处理，保持标准的 422 类型错误行为。
    """
    if not isinstance(value, str):
        return value
    name = value.strip()
    if not name:
        raise HTTPException(status_code=400, detail="分类名不能为空")
    if len(name) > NAME_MAX_LENGTH:
        raise HTTPException(
            status_code=400, detail=f"分类名不能超过 {NAME_MAX_LENGTH} 个字符"
        )
    return name


class CategoryOut(BaseModel):
    """单个分类。"""

    id: int
    name: str
    sort_order: int
    media_count: int           # 该分类下素材数（COUNT(media.id) WHERE category_id=id）
    created_at: datetime


class CategoryListResponse(BaseModel):
    """分类列表 + 「未分类」计数。"""

    items: list[CategoryOut]
    total: int                 # 真实分类数（不含「未分类」）
    uncategorized_count: int   # category_id IS NULL 的素材数


class CategoryCreate(BaseModel):
    """新建分类。"""

    name: str = Field(..., max_length=NAME_MAX_LENGTH)

    _check_name = field_validator("name", mode="before")(_check_name)


class CategoryUpdate(BaseModel):
    """重命名分类（本轮只允许改 name）。"""

    name: str = Field(..., max_length=NAME_MAX_LENGTH)

    _check_name = field_validator("name", mode="before")(_check_name)


class CategoryReorder(BaseModel):
    """提交整份分类顺序。ids 必须是当前全部分类 id 的完整有序集合。"""

    ids: list[int]

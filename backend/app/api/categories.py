"""媒体库分类接口（规格 §3.1）。

单层、互斥分类：每个素材至多属于一个分类，`media.category_id IS NULL` 即「未分类」。
「未分类」不是真实记录，因此不在这里的列表里，也不可增删改。

两条实现要点（规格 §3.1 明确要求，勿改）：
1. `{category_id}` 路径参数**必须**标注为 `int`（生成 `[0-9]+` 正则），
   否则字面量 `order` 会被 `[^/]+` 吞掉；
2. `PATCH /order` **声明在** `PATCH /{category_id}` **之前**注册（顺序双保险）。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Category, Media
from app.schemas.category import (
    NAME_MAX_LENGTH,
    CategoryCreate,
    CategoryListResponse,
    CategoryOut,
    CategoryReorder,
    CategoryUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/categories", tags=["categories"])


# --------------------------- 内部工具 ---------------------------


def _clean_name(raw: str) -> str:
    """strip 后校验分类名长度（规格 §2.1：1–32 字符）。返回清洗后的名字。"""
    name = raw.strip()
    if not name:
        raise HTTPException(status_code=400, detail="分类名不能为空")
    if len(name) > NAME_MAX_LENGTH:
        raise HTTPException(
            status_code=400, detail=f"分类名不能超过 {NAME_MAX_LENGTH} 个字符"
        )
    return name


def _name_taken(db: Session, name: str, *, exclude_id: int | None = None) -> bool:
    """忽略大小写判重（`BBC` 与 `bbc` 视为同名），避免同一分类被拆成多条。"""
    query = db.query(Category.id).filter(func.lower(Category.name) == name.lower())
    if exclude_id is not None:
        query = query.filter(Category.id != exclude_id)
    return query.first() is not None


def _media_count(db: Session, category_id: int) -> int:
    return (
        db.query(func.count(Media.id))
        .filter(Media.category_id == category_id)
        .scalar()
        or 0
    )


def _counts_by_category(db: Session) -> dict[int, int]:
    rows = (
        db.query(Media.category_id, func.count(Media.id))
        .filter(Media.category_id.isnot(None))
        .group_by(Media.category_id)
        .all()
    )
    return {cid: count for cid, count in rows if cid is not None}


def _uncategorized_count(db: Session) -> int:
    return (
        db.query(func.count(Media.id))
        .filter(Media.category_id.is_(None))
        .scalar()
        or 0
    )


def _to_out(category: Category, media_count: int) -> CategoryOut:
    return CategoryOut(
        id=category.id,
        name=category.name,
        sort_order=category.sort_order,
        media_count=media_count,
        created_at=category.created_at,
    )


def _list_response(db: Session) -> CategoryListResponse:
    """按 `sort_order ASC, id ASC` 返回全部分类 + 「未分类」计数。"""
    rows = (
        db.query(Category).order_by(Category.sort_order.asc(), Category.id.asc()).all()
    )
    counts = _counts_by_category(db)
    items = [_to_out(c, counts.get(c.id, 0)) for c in rows]
    return CategoryListResponse(
        items=items,
        total=len(items),
        uncategorized_count=_uncategorized_count(db),
    )


def _get_or_404(db: Session, category_id: int) -> Category:
    category = db.get(Category, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="分类不存在")
    return category


# --------------------------- 端点 ---------------------------
# 注意：`/order` 必须声明在 `/{category_id}` 之前（顺序双保险）。


@router.get("", response_model=CategoryListResponse)
def list_categories(db: Session = Depends(get_db)) -> CategoryListResponse:
    """全部分类（含每个分类的素材数）+ 「未分类」素材数。"""
    return _list_response(db)


@router.post("", response_model=CategoryOut, status_code=201)
def create_category(
    payload: CategoryCreate,
    db: Session = Depends(get_db),
) -> CategoryOut:
    """新建分类。`sort_order = COALESCE(MAX(sort_order), -1) + 1`（空表首个得 0）。"""
    name = _clean_name(payload.name)
    if _name_taken(db, name):
        raise HTTPException(status_code=409, detail=f"已存在同名分类「{name}」")

    next_order = (
        db.query(func.coalesce(func.max(Category.sort_order), -1) + 1).scalar() or 0
    )
    category = Category(name=name, sort_order=next_order)
    db.add(category)
    try:
        db.commit()
    except IntegrityError as exc:  # DB 层 UNIQUE 兜底（并发下的极小概率）
        db.rollback()
        raise HTTPException(status_code=409, detail=f"已存在同名分类「{name}」") from exc
    db.refresh(category)
    logger.info("已新建分类 %s：%s", category.id, category.name)
    return _to_out(category, 0)


@router.patch("/order", response_model=CategoryListResponse)
def reorder_categories(
    payload: CategoryReorder,
    db: Session = Depends(get_db),
) -> CategoryListResponse:
    """按提交的 ids 顺序重写 `sort_order`（0 基）。

    `ids` 必须是当前**全部分类 id 的完整有序集合**：不得有未知 id、不得缺项、不得重复，
    否则 400。
    """
    submitted = list(payload.ids)
    current_ids = [row[0] for row in db.query(Category.id).all()]
    current_set = set(current_ids)

    if len(submitted) != len(set(submitted)):
        raise HTTPException(status_code=400, detail="ids 中存在重复项")
    if set(submitted) != current_set:
        raise HTTPException(
            status_code=400, detail="ids 必须且只能包含当前全部分类的 id（不得缺项或多出未知 id）"
        )

    for order, category_id in enumerate(submitted):
        db.query(Category).filter(Category.id == category_id).update(
            {Category.sort_order: order}
        )
    db.commit()
    logger.info("已重排 %d 个分类", len(submitted))
    return _list_response(db)


@router.patch("/{category_id}", response_model=CategoryOut)
def update_category(
    category_id: int,          # ★ 必须为 int，否则会吞掉字面量 `order`
    payload: CategoryUpdate,
    db: Session = Depends(get_db),
) -> CategoryOut:
    """重命名分类（本轮只允许改 name）。"""
    category = _get_or_404(db, category_id)
    name = _clean_name(payload.name)
    if _name_taken(db, name, exclude_id=category.id):
        raise HTTPException(status_code=409, detail=f"已存在同名分类「{name}」")

    category.name = name
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"已存在同名分类「{name}」") from exc
    db.refresh(category)
    logger.info("已重命名分类 %s → %s", category.id, category.name)
    return _to_out(category, _media_count(db, category.id))


@router.delete("/{category_id}")
def delete_category(category_id: int, db: Session = Depends(get_db)) -> dict:
    """删除分类：先把旗下素材退回「未分类」，再删分类行；**不删任何素材**。

    显式 `UPDATE media SET category_id=NULL` 而不依赖 DB 级联 —— 即使某条连接未开
    FK，回落语义也正确；DB 级 `ON DELETE SET NULL` 只作第二道防线。
    """
    category = _get_or_404(db, category_id)
    released = (
        db.query(Media)
        .filter(Media.category_id == category.id)
        .update({Media.category_id: None}, synchronize_session=False)
    )
    db.delete(category)
    db.commit()
    logger.info("已删除分类 %s（%s），%d 个素材回落未分类", category_id, category.name, released)
    return {"id": category_id, "name": category.name, "released": released}

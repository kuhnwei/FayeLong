"""生词本接口（M4 / FR-S7 · FR-A5）。

- `GET    /api/vocab`          列表（可按是否已掌握筛选、按关键词搜索）
- `POST   /api/vocab`          加入生词本（幂等：同词重复添加会补全信息并提示）
- `PATCH  /api/vocab/{id}`     修改释义 / 上下文 / 标记已掌握
- `DELETE /api/vocab/{id}`     删除生词
- `GET    /api/vocab/export`   导出整个生词本为 Markdown（浏览器下载）

生词去重以「归一化后的单词（或原型）」为键，避免同一词反复收藏。
"""

from __future__ import annotations

import logging
import urllib.parse
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Media, Vocab
from app.schemas.vocab import VocabCreate, VocabListResponse, VocabOut, VocabUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vocab", tags=["vocab"])


def _key(word: str | None, lemma: str | None) -> str:
    """去重键：优先原型，其次原词（均归一化小写）。"""
    return (lemma or word or "").strip().lower()


def _titles(db: Session, media_ids: list[int]) -> dict[int, str]:
    ids = [mid for mid in {*media_ids} if mid]
    if not ids:
        return {}
    rows = db.query(Media.id, Media.title).filter(Media.id.in_(ids)).all()
    return {row[0]: row[1] for row in rows}


def serialize(row: Vocab, title: str | None = None, duplicated: bool = False) -> VocabOut:
    return VocabOut(
        id=row.id,
        word=row.word,
        lemma=row.lemma,
        phonetic=row.phonetic,
        translation=row.translation,
        media_id=row.media_id,
        sentence_id=row.sentence_id,
        context=row.context,
        mastered=row.mastered,
        created_at=row.created_at,
        media_title=title,
        duplicated=duplicated,
    )


def _fetch(db: Session, mastered: bool | None, q: str | None) -> list[Vocab]:
    query = db.query(Vocab)
    if mastered is not None:
        query = query.filter(Vocab.mastered.is_(mastered))
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(
            Vocab.word.ilike(like)
            | Vocab.lemma.ilike(like)
            | Vocab.translation.ilike(like)
        )
    return query.order_by(Vocab.id.desc()).all()


# --------------------------- 导出（须在 /{id} 之前定义）---------------------------


def _to_markdown(rows: list[Vocab], titles: dict[int, str]) -> str:
    total = len(rows)
    mastered = sum(1 for row in rows if row.mastered)
    lines = [
        "# 生词本",
        "",
        f"> 导出时间：{datetime.now():%Y-%m-%d %H:%M}　｜　共 {total} 个　｜　已掌握 {mastered} 个",
        "",
    ]
    if not rows:
        lines.append("_（生词本为空）_")
        return "\n".join(lines) + "\n"

    lines += [
        "| 单词 | 音标 | 释义 | 上下文 | 来源 | 掌握 |",
        "| --- | --- | --- | --- | --- | :---: |",
    ]

    def cell(text: str | None) -> str:
        value = (text or "").replace("|", "\\|").replace("\n", " ").strip()
        return value or "—"

    for row in rows:
        lines.append(
            "| {word} | {phonetic} | {translation} | {context} | {source} | {mastered} |".format(
                word=cell(row.lemma or row.word or ""),
                phonetic=cell(row.phonetic),
                translation=cell(row.translation),
                context=cell(row.context),
                source=cell(titles.get(row.media_id or -1)),
                mastered="✔" if row.mastered else "",
            )
        )
    return "\n".join(lines) + "\n"


@router.get("/export")
def export_vocab(
    mastered: bool | None = Query(default=None),
    db: Session = Depends(get_db),
) -> Response:
    """导出整个生词本为 Markdown 文件。"""
    rows = _fetch(db, mastered=mastered, q=None)
    titles = _titles(db, [row.media_id or 0 for row in rows])
    body = _to_markdown(rows, titles)
    filename = f"生词本-{datetime.now():%Y%m%d-%H%M}.md"
    quoted = urllib.parse.quote(filename)
    logger.info("导出 %d 个生词为 Markdown", len(rows))
    return Response(
        content=body,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quoted}"},
    )


# --------------------------- 增删改查 ---------------------------


@router.get("", response_model=VocabListResponse)
def list_vocab(
    mastered: bool | None = Query(default=None, description="按是否已掌握筛选"),
    q: str | None = Query(default=None, description="按单词 / 释义搜索"),
    db: Session = Depends(get_db),
) -> VocabListResponse:
    rows = _fetch(db, mastered=mastered, q=q)
    titles = _titles(db, [row.media_id or 0 for row in rows])
    return VocabListResponse(
        items=[serialize(row, titles.get(row.media_id or -1)) for row in rows],
        total=len(rows),
        mastered=sum(1 for row in rows if row.mastered),
    )


@router.post("", response_model=VocabOut, status_code=201)
def create_vocab(payload: VocabCreate, db: Session = Depends(get_db)) -> VocabOut:
    """把一个生词加入生词本（同一词重复添加不会产生第二条）。"""
    word = (payload.word or "").strip()
    lemma = (payload.lemma or "").strip() or None
    if not word:
        raise HTTPException(status_code=400, detail="单词不能为空")

    # 去重：按归一化键（原型优先）匹配，覆盖大小写差异。生词本规模很小，直接扫。
    key = _key(word, lemma)
    existing = next(
        (row for row in db.query(Vocab).all() if _key(row.word, row.lemma) == key),
        None,
    )

    if existing is not None:
        # 幂等：补全可能缺失的字段，返回已有记录
        changed = False
        for field in ("phonetic", "translation", "context"):
            if not getattr(existing, field) and getattr(payload, field):
                setattr(existing, field, getattr(payload, field))
                changed = True
        if existing.media_id is None and payload.media_id:
            existing.media_id, changed = payload.media_id, True
        if existing.sentence_id is None and payload.sentence_id:
            existing.sentence_id, changed = payload.sentence_id, True
        if changed:
            db.commit()
            db.refresh(existing)
        titles = _titles(db, [existing.media_id or 0])
        return serialize(existing, titles.get(existing.media_id or -1), duplicated=True)

    row = Vocab(
        word=word[:128],
        lemma=lemma[:128] if lemma else None,
        phonetic=(payload.phonetic or None),
        translation=(payload.translation or None),
        media_id=payload.media_id,
        sentence_id=payload.sentence_id,
        context=(payload.context or None),
        mastered=False,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    titles = _titles(db, [row.media_id or 0])
    logger.info("加入生词本：%s（id=%s）", row.word, row.id)
    return serialize(row, titles.get(row.media_id or -1))


def _get_or_404(db: Session, vocab_id: int) -> Vocab:
    row = db.get(Vocab, vocab_id)
    if row is None:
        raise HTTPException(status_code=404, detail="生词不存在")
    return row


@router.patch("/{vocab_id}", response_model=VocabOut)
def update_vocab(
    vocab_id: int,
    payload: VocabUpdate,
    db: Session = Depends(get_db),
) -> VocabOut:
    row = _get_or_404(db, vocab_id)
    if payload.translation is not None:
        row.translation = payload.translation.strip() or None
    if payload.context is not None:
        row.context = payload.context.strip() or None
    if payload.mastered is not None:
        row.mastered = payload.mastered
    db.commit()
    db.refresh(row)
    titles = _titles(db, [row.media_id or 0])
    return serialize(row, titles.get(row.media_id or -1))


@router.delete("/{vocab_id}", status_code=204)
def delete_vocab(vocab_id: int, db: Session = Depends(get_db)) -> Response:
    row = _get_or_404(db, vocab_id)
    db.delete(row)
    db.commit()
    logger.info("已删除生词：%s（id=%s）", row.word, vocab_id)
    return Response(status_code=204)

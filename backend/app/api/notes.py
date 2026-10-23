"""句子笔记接口（M4 / FR-S8）。

每句至多一条笔记：
- `GET /api/notes/{sentenceId}`  读取（没有则返回空内容）
- `PUT /api/notes/{sentenceId}`  保存（内容为空等价于删除）

笔记汇总导出（按媒体）属 M5。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.db import get_db
from app.models import Note, Sentence, User
from app.schemas.note import NoteOut, NoteUpsert

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/notes", tags=["notes"])


def _require_sentence(db: Session, sentence_id: int) -> Sentence:
    sentence = db.get(Sentence, sentence_id)
    if sentence is None:
        raise HTTPException(status_code=404, detail="句子不存在")
    return sentence


def _note_of(db: Session, sentence_id: int, user_id: int) -> Note | None:
    return (
        db.query(Note)
        .filter(Note.sentence_id == sentence_id, Note.user_id == user_id)
        .first()
    )


@router.get("/{sentence_id}", response_model=NoteOut)
def get_note(
    sentence_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NoteOut:
    """读取某句的笔记。"""
    _require_sentence(db, sentence_id)
    row = _note_of(db, sentence_id, user.id)
    if row is None:
        return NoteOut(sentence_id=sentence_id, content="", exists=False)
    return NoteOut(
        sentence_id=sentence_id,
        content=row.content,
        updated_at=row.updated_at,
        exists=True,
    )


@router.put("/{sentence_id}", response_model=NoteOut)
def save_note(
    sentence_id: int,
    payload: NoteUpsert,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NoteOut:
    """保存某句的笔记（upsert；内容为空则删除该笔记）。"""
    _require_sentence(db, sentence_id)
    content = (payload.content or "").strip()
    row = _note_of(db, sentence_id, user.id)

    if not content:
        if row is not None:
            db.delete(row)
            db.commit()
            logger.info("已清空笔记：sentence=%s", sentence_id)
        return NoteOut(sentence_id=sentence_id, content="", exists=False)

    if row is None:
        row = Note(sentence_id=sentence_id, user_id=user.id, content=content)
        db.add(row)
    else:
        row.content = content
    db.commit()
    db.refresh(row)
    return NoteOut(
        sentence_id=sentence_id,
        content=row.content,
        updated_at=row.updated_at,
        exists=True,
    )

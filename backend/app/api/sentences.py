"""句子编辑接口（M2 / FR-M6）。

识别结果难免有偏差，这里提供人工校对闭环：
- `PATCH  /api/sentences/{id}`          编辑原文 / 翻译 / 调整时间边界
- `POST   /api/sentences/{id}/split`    在指定时间点拆成两句
- `POST   /api/sentences/{id}/merge`    与相邻句合并
- `POST   /api/sentences/{id}/retranslate`  单句重新翻译

所有写操作都会：① 重排 `idx`；② 同步修正切片文件名与内容；
③ 返回该媒体的完整详情，前端直接整体刷新。
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.media import serialize_detail
from app.core.paths import MediaError, audio_wav_path
from app.db import get_db
from app.models import Media, Sentence
from app.schemas.media import (
    MediaDetailOut,
    SentenceMergeIn,
    SentenceSplitIn,
    SentenceUpdate,
)
from app.services import clip as clip_service
from app.services import marks as marks_service
from app.services import translate as translate_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sentences", tags=["sentences"])


def _get_sentence(db: Session, sentence_id: int) -> Sentence:
    sentence = db.get(Sentence, sentence_id)
    if sentence is None:
        raise HTTPException(status_code=404, detail="句子不存在")
    return sentence


def _get_media(db: Session, sentence: Sentence) -> Media:
    media = db.get(Media, sentence.media_id)
    if media is None:
        raise HTTPException(status_code=404, detail="所属媒体不存在")
    return media


def _audio_of(media: Media) -> Path:
    """标准音频路径（切片重建的来源）。"""
    path = Path(media.audio_path) if media.audio_path else audio_wav_path(media.id)
    if not path.is_file():
        raise HTTPException(status_code=409, detail="标准音频已丢失，无法重建切片")
    return path


def _cut(db: Session, media: Media, sentence: Sentence) -> None:
    """重切某一句的切片（失败不阻断编辑，仅记录）。"""
    try:
        target = clip_service.cut_clip_auto(
            _audio_of(media), media.id, sentence.idx,
            sentence.start_ms, sentence.end_ms,
        )
        sentence.clip_path = str(target)
    except (MediaError, HTTPException) as exc:
        logger.warning("重建切片失败 sentence=%s: %s", sentence.id, exc)
        sentence.clip_path = None


def _reindex(db: Session, media_id: int) -> list[Sentence]:
    """按时间顺序重排 idx，并同步重命名切片文件（两阶段，避免互相覆盖）。"""
    rows = (
        db.query(Sentence)
        .filter(Sentence.media_id == media_id)
        .order_by(Sentence.start_ms, Sentence.id)
        .all()
    )

    # 阶段一：所有切片先改名为临时名，腾出目标文件名
    pending: list[tuple[Sentence, Path, str]] = []
    for row in rows:
        if not row.clip_path:
            continue
        old = Path(row.clip_path)
        if not old.is_file():
            row.clip_path = None
            continue
        tmp = old.with_name(f".tmp-{row.id}{old.suffix}")
        try:
            old.replace(tmp)
        except OSError:
            row.clip_path = None
            continue
        pending.append((row, tmp, old.suffix))

    # 阶段二：按新的 idx 落到最终文件名
    for new_idx, row in enumerate(rows):
        row.idx = new_idx
    for row, tmp, suffix in pending:
        final = clip_service.clip_path(media_id, row.idx, suffix)
        try:
            tmp.replace(final)
            row.clip_path = str(final)
        except OSError:
            row.clip_path = None

    db.commit()
    return rows


def _split_text(text: str, ratio: float) -> tuple[str, str]:
    """按时间比例在词边界切分文本。"""
    words = (text or "").split()
    if len(words) < 2:
        return text.strip(), ""
    cut = min(max(1, round(len(words) * ratio)), len(words) - 1)
    return " ".join(words[:cut]), " ".join(words[cut:])


# --------------------------- 编辑 ---------------------------


@router.patch("/{sentence_id}", response_model=MediaDetailOut)
def update_sentence(
    sentence_id: int,
    payload: SentenceUpdate,
    db: Session = Depends(get_db),
) -> MediaDetailOut:
    """编辑单句（原文 / 翻译 / 时间边界）。"""
    sentence = _get_sentence(db, sentence_id)
    media = _get_media(db, sentence)
    touched_time = False

    if payload.text_en is not None:
        new_en = payload.text_en.strip()
        # 原文变了 → 易听错标记的词下标会漂移，直接作废（宁可丢标记也不错位高亮）
        if new_en != sentence.text_en:
            sentence.marks = ""
        sentence.text_en = new_en
        sentence.is_edited = True
    if payload.text_zh is not None:
        sentence.text_zh = payload.text_zh.strip()
        sentence.is_edited = True
    if payload.start_ms is not None and payload.start_ms != sentence.start_ms:
        sentence.start_ms = max(0, payload.start_ms)
        touched_time = True
    if payload.end_ms is not None and payload.end_ms != sentence.end_ms:
        sentence.end_ms = max(sentence.start_ms + 100, payload.end_ms)
        touched_time = True
    if payload.marks is not None:
        # 整体替换；`dump` 内部做归并 + 夹取，越界区间自动丢弃
        sentence.marks = marks_service.dump(payload.marks, sentence.text_en)

    db.commit()
    if touched_time:
        _cut(db, media, sentence)
        _reindex(db, media.id)
    db.refresh(sentence)
    return serialize_detail(db, media)


@router.post("/{sentence_id}/split", response_model=MediaDetailOut)
def split_sentence(
    sentence_id: int,
    payload: SentenceSplitIn,
    db: Session = Depends(get_db),
) -> MediaDetailOut:
    """在 `at_ms` 处把一句拆成两句。"""
    sentence = _get_sentence(db, sentence_id)
    media = _get_media(db, sentence)

    at_ms = payload.at_ms
    if not (sentence.start_ms + 100 <= at_ms <= sentence.end_ms - 100):
        raise HTTPException(
            status_code=400,
            detail=f"切分点需位于 {sentence.start_ms + 100}~{sentence.end_ms - 100} ms 之间",
        )

    ratio = (at_ms - sentence.start_ms) / max(1, sentence.end_ms - sentence.start_ms)
    left_default, right_default = _split_text(sentence.text_en, ratio)
    left_text = (payload.text_left or left_default).strip()
    right_text = (payload.text_right or right_default).strip()

    original_end = sentence.end_ms
    sentence.end_ms = at_ms
    sentence.text_en = left_text
    sentence.is_edited = True
    sentence.text_zh = ""
    sentence.marks = ""

    right = Sentence(
        media_id=media.id,
        idx=sentence.idx + 1,
        start_ms=at_ms,
        end_ms=original_end,
        text_en=right_text,
        text_zh="",
        is_edited=True,
    )
    db.add(right)
    db.commit()

    # 重新翻译被拆分的两句（原文变了）
    for item in (sentence, right):
        result = translate_service.translate(item.text_en)
        item.text_zh = result["text"] or ""
    db.commit()

    rows = _reindex(db, media.id)
    for item in rows:
        if item.id in (sentence.id, right.id):
            _cut(db, media, item)
    db.commit()
    return serialize_detail(db, media)


@router.post("/{sentence_id}/merge", response_model=MediaDetailOut)
def merge_sentence(
    sentence_id: int,
    payload: SentenceMergeIn,
    db: Session = Depends(get_db),
) -> MediaDetailOut:
    """与相邻句合并（默认向后合并）。"""
    sentence = _get_sentence(db, sentence_id)
    media = _get_media(db, sentence)

    candidates = (
        db.query(Sentence)
        .filter(Sentence.media_id == media.id, Sentence.id != sentence.id)
        .order_by(Sentence.start_ms)
        .all()
    )
    if payload.direction == "next":
        others = [s for s in candidates if s.start_ms >= sentence.end_ms or s.idx > sentence.idx]
        neighbor = others[0] if others else None
        first, second = sentence, neighbor
    else:
        others = [s for s in reversed(candidates) if s.idx < sentence.idx]
        neighbor = others[0] if others else None
        first, second = neighbor, sentence

    if neighbor is None:
        raise HTTPException(status_code=400, detail="没有可合并的相邻句")

    first.start_ms = min(first.start_ms, second.start_ms)
    first.end_ms = max(first.end_ms, second.end_ms)
    first.text_en = f"{first.text_en.strip()} {second.text_en.strip()}".strip()
    first.text_zh = f"{first.text_zh.strip()} {second.text_zh.strip()}".strip()
    first.is_edited = True
    first.marks = ""  # 原文拼接后词下标全部作废

    # 先删掉被并入句的切片文件
    if second.clip_path:
        Path(second.clip_path).unlink(missing_ok=True)

    db.delete(second)
    db.commit()

    rows = _reindex(db, media.id)
    _cut(db, media, first)
    db.commit()
    return serialize_detail(db, media)


@router.post("/{sentence_id}/retranslate", response_model=MediaDetailOut)
def retranslate_sentence(
    sentence_id: int,
    db: Session = Depends(get_db),
) -> MediaDetailOut:
    """单句重新翻译（在线引擎 + 缓存）。"""
    sentence = _get_sentence(db, sentence_id)
    media = _get_media(db, sentence)
    result = translate_service.translate(sentence.text_en)
    if not result["text"]:
        raise HTTPException(status_code=502, detail="翻译引擎暂不可用，请稍后重试")
    sentence.text_zh = result["text"]
    db.commit()
    return serialize_detail(db, media)

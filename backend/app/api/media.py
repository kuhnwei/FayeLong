"""媒体导入与播放接口（M1）+ 处理进度与切片（M2）。

- 上传：浏览器选择文件 → multipart → 落地媒体库 → 后台处理
- 导入：扫描收件箱（data/media/audio）→ 批量入库 → 后台处理
- 播放：`/stream` 支持 HTTP Range，供 <audio> 拖动进度、变速、循环
- 进度：`/progress` 以 SSE 推送「转码→识别→翻译→切片」进度（前端另有轮询兜底）
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import INBOX_DIR, STATUS_PENDING, SUPPORTED_EXT
from app.core.files import file_response, guess_mime
from app.core.paths import clips_dir
from app.db import SessionLocal, get_db
from app.models import Media, Note, Sentence
from app.schemas.dictation import DictationSummary
from app.schemas.media import (
    ImportRequest,
    InboxItem,
    InboxResponse,
    MediaDetailOut,
    MediaListResponse,
    MediaOut,
    MediaUpdate,
    ProgressEvent,
    SentenceOut,
)
from app.schemas.note import MediaNoteItem, MediaNotesResponse
from app.services import media as media_service
from app.services import study as study_service
from app.services.study import SentenceStat

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/media", tags=["media"])

_SUPPORTED_HINT = "、".join(sorted(ext.lstrip(".") for ext in SUPPORTED_EXT))

# 阶段中文名（SSE / 轮询展示用）
STAGE_LABEL = {
    "pending": "排队中",
    "transcoding": "转码中",
    "ready": "等待识别",
    "asr": "识别中",
    "translating": "翻译中",
    "clipping": "切片中",
    "done": "已完成",
    "failed": "处理失败",
}


# --------------------------- 序列化 ---------------------------


def serialize(media: Media, sentence_count: int = 0) -> MediaOut:
    has_audio = bool(media.audio_path and Path(media.audio_path).is_file())
    return MediaOut(
        id=media.id,
        title=media.title,
        type=media.type,
        original_name=media.original_name,
        duration_ms=media.duration_ms,
        size_bytes=media.size_bytes,
        status=media.status,
        progress=media.progress,
        error=media.error,
        origin=media.origin,
        created_at=media.created_at,
        has_audio=has_audio,
        stream_url=f"/api/media/{media.id}/stream",
        sentence_count=sentence_count,
    )


def sentence_out(media_id: int, sentence: Sentence, stat: SentenceStat | None = None) -> SentenceOut:
    stats = (stat.as_dict() if stat else {})
    return SentenceOut(
        id=sentence.id,
        idx=sentence.idx,
        start_ms=sentence.start_ms,
        end_ms=sentence.end_ms,
        text_en=sentence.text_en,
        text_zh=sentence.text_zh,
        is_edited=sentence.is_edited,
        clip_url=(
            f"/api/media/{media_id}/clips/{sentence.idx}"
            if sentence.clip_path and Path(sentence.clip_path).is_file()
            else None
        ),
        **stats,
    )


def _sentences_of(db: Session, media_id: int) -> list[Sentence]:
    return (
        db.query(Sentence)
        .filter(Sentence.media_id == media_id)
        .order_by(Sentence.idx)
        .all()
    )


def serialize_detail(db: Session, media: Media) -> MediaDetailOut:
    """媒体详情（含句子列表与听写统计）——多处复用（媒体详情 / 句子编辑后刷新）。"""
    sentences = _sentences_of(db, media.id)
    stats = study_service.media_stats(db, media.id)
    base = serialize(media, sentence_count=len(sentences))
    return MediaDetailOut(
        **base.model_dump(),
        sentences=[sentence_out(media.id, s, stats.get(s.id)) for s in sentences],
        dictation=DictationSummary(
            **study_service.summary(len(sentences), stats)
        ),
    )


def _get_or_404(db: Session, media_id: int) -> Media:
    media = db.get(Media, media_id)
    if media is None:
        raise HTTPException(status_code=404, detail="媒体不存在")
    return media


def _validate_ext(name: str) -> str:
    ext = Path(name).suffix.lower()
    if ext not in SUPPORTED_EXT:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型「{ext or '未知'}」，支持：{_SUPPORTED_HINT}",
        )
    return ext


def _register(db: Session, *, title: str, original_name: str, origin: str,
              source_ref: str | None) -> Media:
    media = Media(
        title=title[:255] or "未命名",
        original_name=original_name[:255],
        type="audio",
        file_path="",
        status=STATUS_PENDING,
        progress=0,
        origin=origin,
        source_ref=source_ref,
    )
    db.add(media)
    db.commit()
    db.refresh(media)
    return media


# --------------------------- 上传 / 导入 ---------------------------


@router.post("", response_model=MediaOut, status_code=201)
async def upload_media(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> MediaOut:
    """上传一个音频 / 视频文件（视频仅取音轨）。"""
    filename = Path(file.filename or "").name
    if not filename:
        raise HTTPException(status_code=400, detail="未获取到文件名")
    ext = _validate_ext(filename)

    media = _register(
        db,
        title=Path(filename).stem,
        original_name=filename,
        origin="upload",
        source_ref=None,
    )

    await _persist_upload(db, media, file, ext)
    media_service.enqueue(media.id)
    logger.info("已接收上传：%s（media=%s, %.1f MB）",
                filename, media.id, media.size_bytes / 1024 / 1024)
    return serialize(media)


async def _persist_upload(db: Session, media: Media, file: UploadFile, ext: str) -> None:
    """把上传流写入媒体库目录；失败则回滚记录。"""
    destination = media_service.media_dir(media.id) / f"original{ext}"
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("wb") as out:
            shutil.copyfileobj(file.file, out, 1024 * 1024)
    except OSError as exc:
        db.delete(media)
        db.commit()
        media_service.delete_media_files(media.id)
        raise HTTPException(status_code=500, detail=f"保存文件失败：{exc}") from exc
    finally:
        await file.close()

    media.file_path = str(destination)
    media.size_bytes = destination.stat().st_size
    db.commit()
    db.refresh(media)


@router.get("/inbox", response_model=InboxResponse)
def get_inbox(db: Session = Depends(get_db)) -> InboxResponse:
    """列出收件箱里的素材（用户直接把文件放进该目录即可）。"""
    items = media_service.scan_inbox(db)
    return InboxResponse(
        inbox_dir=str(INBOX_DIR),
        items=[InboxItem(**item) for item in items],
    )


@router.post("/import", response_model=MediaListResponse, status_code=201)
def import_from_inbox(
    payload: ImportRequest,
    db: Session = Depends(get_db),
) -> MediaListResponse:
    """从收件箱导入；不传 files 则导入全部尚未导入的受支持文件。"""
    available = {item["path"]: item for item in media_service.scan_inbox(db)}
    if payload.files:
        targets = payload.files
    else:
        targets = [
            path
            for path, item in available.items()
            if item["supported"] and not item["imported"]
        ]

    created: list[MediaOut] = []
    skipped: list[str] = []
    for path_str in targets:
        info = available.get(path_str)
        source = Path(path_str)
        if info is None or not source.is_file():
            skipped.append(f"{Path(path_str).name}（文件不存在）")
            continue
        if not info["supported"]:
            skipped.append(f"{source.name}（格式不支持）")
            continue
        if info["imported"]:
            skipped.append(f"{source.name}（已导入）")
            continue

        media = _register(
            db,
            title=source.stem,
            original_name=source.name,
            origin="inbox",
            source_ref=str(source.resolve()),
        )
        try:
            destination = media_service.copy_into_library(media.id, source)
        except OSError as exc:
            db.delete(media)
            db.commit()
            skipped.append(f"{source.name}（复制失败：{exc}）")
            continue

        media.file_path = str(destination)
        media.size_bytes = destination.stat().st_size
        db.commit()
        db.refresh(media)
        media_service.enqueue(media.id)
        created.append(serialize(media))

    if skipped:
        logger.info("导入跳过 %d 个文件：%s", len(skipped), "；".join(skipped[:10]))

    return MediaListResponse(items=created, total=len(created))


# --------------------------- 列表 / 详情 ---------------------------


@router.get("", response_model=MediaListResponse)
def list_media(db: Session = Depends(get_db)) -> MediaListResponse:
    rows = db.query(Media).order_by(Media.id.desc()).all()
    counts = dict(
        db.query(Sentence.media_id, func.count(Sentence.id))
        .group_by(Sentence.media_id)
        .all()
    )
    items = [serialize(m, sentence_count=counts.get(m.id, 0)) for m in rows]
    return MediaListResponse(items=items, total=len(items))


@router.get("/{media_id}", response_model=MediaDetailOut)
def get_media(media_id: int, db: Session = Depends(get_db)) -> MediaDetailOut:
    media = _get_or_404(db, media_id)
    return serialize_detail(db, media)


@router.patch("/{media_id}", response_model=MediaOut)
def update_media(
    media_id: int,
    payload: MediaUpdate,
    db: Session = Depends(get_db),
) -> MediaOut:
    media = _get_or_404(db, media_id)
    if payload.title is not None:
        title = payload.title.strip()
        if title:
            media.title = title[:255]
    db.commit()
    db.refresh(media)
    return serialize(media)


@router.post("/{media_id}/retry", response_model=MediaOut)
def retry_media(media_id: int, db: Session = Depends(get_db)) -> MediaOut:
    """重新处理（失败重试 / 手动重跑转码）。"""
    media = _get_or_404(db, media_id)
    if not Path(media.file_path).is_file():
        raise HTTPException(status_code=409, detail="原始文件已丢失，请删除后重新导入")
    media.status = STATUS_PENDING
    media.progress = 0
    media.error = None
    db.commit()
    db.refresh(media)
    media_service.enqueue(media_id)
    return serialize(media)


@router.delete("/{media_id}", status_code=204)
def delete_media(media_id: int, db: Session = Depends(get_db)) -> Response:
    media = _get_or_404(db, media_id)
    db.delete(media)          # ORM 级联删除句子 / 笔记 / 听写记录
    db.commit()
    media_service.delete_media_files(media_id)
    logger.info("已删除媒体 %s（%s）", media_id, media.title)
    return Response(status_code=204)


@router.post("/{media_id}/retranscribe", response_model=MediaOut)
def retranscribe_media(media_id: int, db: Session = Depends(get_db)) -> MediaOut:
    """重新识别（保留已转码音频，只重跑 识别→翻译→切片）。

    注意：会按识别结果重建句表，原有句子笔记与听写记录将一并清除。
    """
    media = _get_or_404(db, media_id)
    audio = Path(media.audio_path) if media.audio_path else None
    if audio is None or not audio.is_file():
        raise HTTPException(status_code=409, detail="标准音频尚未就绪，请先「重新处理」")
    media.status = STATUS_PENDING
    media.progress = 0
    media.error = None
    db.commit()
    db.refresh(media)
    media_service.enqueue_retranscribe(media_id)
    logger.info("媒体 %s 已重新排队识别", media_id)
    return serialize(media, sentence_count=len(_sentences_of(db, media_id)))


@router.get("/{media_id}/progress")
def media_progress(
    media_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """以 SSE 推送处理进度，直到 `done` / `failed` 后自动结束。"""
    _get_or_404(db, media_id)

    async def event_stream():
        elapsed = 0.0
        interval = 0.5
        max_seconds = 60 * 60  # 兜底上限，避免连接长期悬挂
        while elapsed < max_seconds:
            if await request.is_disconnected():
                break
            session = SessionLocal()
            try:
                media = session.get(Media, media_id)
                if media is None:
                    break
                count = (
                    session.query(func.count(Sentence.id))
                    .filter(Sentence.media_id == media_id)
                    .scalar()
                    or 0
                )
                event = ProgressEvent(
                    media_id=media.id,
                    status=media.status,
                    progress=media.progress,
                    stage=STAGE_LABEL.get(media.status, media.status),
                    error=media.error,
                    sentence_count=count,
                    done=media.status in ("done", "failed"),
                )
            finally:
                session.close()

            yield f"data: {json.dumps(event.model_dump(), ensure_ascii=False)}\n\n"
            if event.done:
                break
            await asyncio.sleep(interval)
            elapsed += interval

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # 关掉可能的代理缓冲
            "Connection": "keep-alive",
        },
    )


@router.get("/{media_id}/clips/{idx}")
def get_clip(
    media_id: int,
    idx: int,
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    """取某一句的音频切片（支持 Range，便于单句循环与拖动）。"""
    _get_or_404(db, media_id)
    sentence = (
        db.query(Sentence)
        .filter(Sentence.media_id == media_id, Sentence.idx == idx)
        .first()
    )
    if sentence is None or not sentence.clip_path:
        raise HTTPException(status_code=404, detail="该句暂无音频切片")
    path = Path(sentence.clip_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="切片文件已丢失，可执行「重新处理」重建")
    return file_response(path, request, content_type=guess_mime(path))


@router.delete("/{media_id}/clips", status_code=200)
def clear_clips(media_id: int, db: Session = Depends(get_db)) -> dict:
    """清理切片以回收磁盘（学习页仍可整段播放）。"""
    media = _get_or_404(db, media_id)
    from app.services import clip as clip_service

    clip_service.clear_clips(media_id)
    for sentence in _sentences_of(db, media_id):
        sentence.clip_path = None
    db.commit()
    logger.info("已清理媒体 %s 的音频切片", media_id)
    return {"media_id": media.id, "cleared": True, "clips_dir": str(clips_dir(media_id))}


# --------------------------- 笔记汇总（M5 / FR-A6）---------------------------


def _notes_of(db: Session, media_id: int) -> list[tuple[Note, Sentence]]:
    """该媒体下所有「已有笔记」的句子（按句序）。"""
    return (
        db.query(Note, Sentence)
        .join(Sentence, Sentence.id == Note.sentence_id)
        .filter(Sentence.media_id == media_id)
        .order_by(Sentence.idx)
        .all()
    )


@router.get("/{media_id}/notes", response_model=MediaNotesResponse)
def list_media_notes(media_id: int, db: Session = Depends(get_db)) -> MediaNotesResponse:
    """某个媒体的句子笔记汇总（供学习页「笔记」面板）。"""
    media = _get_or_404(db, media_id)
    rows = _notes_of(db, media_id)
    stats = study_service.media_stats(db, media_id)
    sentence_count = (
        db.query(func.count(Sentence.id)).filter(Sentence.media_id == media_id).scalar() or 0
    )

    items: list[MediaNoteItem] = []
    for note, sentence in rows:
        stat = stats.get(sentence.id)
        items.append(
            MediaNoteItem(
                sentence_id=sentence.id,
                idx=sentence.idx,
                text_en=sentence.text_en,
                text_zh=sentence.text_zh,
                content=note.content,
                updated_at=note.updated_at,
                attempt_count=stat.attempt_count if stat else 0,
                best_accuracy=stat.best_accuracy if stat else 0.0,
                mastered=stat.mastered if stat else False,
            )
        )

    return MediaNotesResponse(
        media_id=media.id,
        title=media.title,
        total=len(items),
        sentence_count=sentence_count,
        items=items,
    )


def _notes_markdown(
    media: Media,
    rows: list[tuple[Note, Sentence]],
    stats: dict[int, SentenceStat],
    sentence_count: int,
) -> str:
    """把某媒体的笔记汇总成 Markdown（原文 / 翻译 / 听写概要 / 笔记）。"""

    def clean(text: str | None) -> str:
        return (text or "").replace("\r", "").strip()

    lines = [
        f"# {media.title} · 句子笔记",
        "",
        f"> 导出时间：{datetime.now():%Y-%m-%d %H:%M}　｜　"
        f"共 {len(rows)} 条笔记 / 全篇 {sentence_count} 句",
        "",
    ]

    if not rows:
        lines.append("_（该媒体还没有任何句子笔记）_")
        return "\n".join(lines) + "\n"

    for note, sentence in rows:
        stat = stats.get(sentence.id)
        lines.append(f"## #{sentence.idx + 1}")
        lines.append("")
        lines.append(clean(sentence.text_en) or "_（无原文）_")
        lines.append("")
        if clean(sentence.text_zh):
            lines.append(f"- 翻译：{clean(sentence.text_zh)}")
        if stat and stat.attempt_count:
            tag = "已掌握" if stat.mastered else "未掌握"
            lines.append(
                f"- 听写：最佳 {stat.best_accuracy:g}%　｜　练过 {stat.attempt_count} 次　｜　{tag}"
            )
        lines.append(f"- 笔记：{clean(note.content) or '_（空）_'}")
        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


@router.get("/{media_id}/notes/export")
def export_media_notes(media_id: int, db: Session = Depends(get_db)) -> Response:
    """导出某个媒体的句子笔记为 Markdown 文件（浏览器下载）。"""
    media = _get_or_404(db, media_id)
    rows = _notes_of(db, media_id)
    stats = study_service.media_stats(db, media_id)
    sentence_count = (
        db.query(func.count(Sentence.id)).filter(Sentence.media_id == media_id).scalar() or 0
    )
    body = _notes_markdown(media, rows, stats, sentence_count)

    safe_title = "".join(ch for ch in media.title if ch not in '\\/:*?"<>|').strip() or "未命名"
    filename = f"{safe_title}-笔记-{datetime.now():%Y%m%d-%H%M}.md"
    logger.info("导出媒体 %s 的 %d 条笔记为 Markdown", media_id, len(rows))
    return Response(
        content=body,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


# --------------------------- 播放 ---------------------------


@router.get("/{media_id}/stream")
def stream_media(media_id: int, request: Request, db: Session = Depends(get_db)) -> Response:
    """流式播放：优先转码后的标准音频；转码完成前回退播放原始音频文件。"""
    media = _get_or_404(db, media_id)

    candidates: list[Path] = []
    if media.audio_path:
        candidates.append(Path(media.audio_path))
    if media.file_path and media.type == "audio":
        candidates.append(Path(media.file_path))

    for path in candidates:
        if path.is_file():
            return file_response(
                path,
                request,
                content_type=guess_mime(path),
                filename=media.original_name or path.name,
            )

    raise HTTPException(status_code=409, detail="音频尚未就绪，请稍候")

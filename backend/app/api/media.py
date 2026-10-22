"""媒体导入与播放接口（M1）+ 处理进度与切片（M2）。

- 上传：浏览器选择文件 → multipart → 落地媒体库 → 后台处理
- 导入：扫描收件箱（data/media/audio）→ 批量入库 → 后台处理
- 播放：`/stream` 支持 HTTP Range，供 <audio> 拖动进度、变速、循环
- 进度：`/progress` 以 SSE 推送「转码→识别→翻译→切片」进度（前端另有轮询兜底）

职责边界（P3-4 领域分层收口）
=============================
本模块**只做协议转换**：入参解析（`Depends` / Pydantic）→ 调 `services.media_ops`
→ 序列化成响应模型 / 构造 `Response`。领域规则（登记、落盘、去重导入、批量归类、
删除级联、重跑校验、进度聚合、取流选路、笔记导出格式）全部在
:mod:`app.services.media_ops` 里，那里**不 import fastapi**。

留在本层的三样东西，都属于「协议形状」而非领域规则：

1. `serialize()` / `serialize_detail()` / `sentence_out()` —— 响应映射
   （`app/api/sentences.py` 也复用 `serialize_detail`）；
2. `STAGE_LABEL` —— SSE / 轮询展示用的中文阶段名；
3. SSE 分帧（`data: {...}\\n\\n`）与 `file_response()`（Range 切片在
   `core/files.py`，那是 HTTP 协议细节，不是业务规则）。
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.config import INBOX_DIR
from app.core.files import file_response, guess_mime
from app.db import SessionLocal, get_db
from app.models import Media, Sentence
from app.schemas.dictation import DictationSummary
from app.schemas.media import (
    BatchCategoryRequest,
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
from app.services import marks as marks_service
from app.services import media as media_service
from app.services import media_ops
from app.services import study as study_service
from app.services.study import SentenceStat

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/media", tags=["media"])

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


# --------------------------- 领域错误 → HTTP ---------------------------


@contextmanager
def _domain_errors() -> Iterator[None]:
    """把 `media_ops` 的领域错误翻译成 **原样** 的 `HTTPException`。

    Notes:
        `status_code` 与 `detail` 由领域层给出，这里只做类型转换 —— 文案一个字都
        不改（21 个 `test_media_flow` 用例、`scripts/verify_*.mjs` 与前端都依赖）。
        `from None` 是为了不让「领域异常 → HTTP 异常」的链式 traceback 污染日志。
    """
    try:
        yield
    except media_ops.MediaOpsError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from None


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
        category_id=media.category_id,
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
        marks=marks_service.load(sentence.marks),
        **stats,
    )


def serialize_detail(db: Session, media: Media) -> MediaDetailOut:
    """媒体详情（含句子列表与听写统计）——多处复用（媒体详情 / 句子编辑后刷新）。"""
    sentences = media_ops.sentences_of(db, media.id)
    stats = study_service.media_stats(db, media.id)
    base = serialize(media, sentence_count=len(sentences))
    return MediaDetailOut(
        **base.model_dump(),
        sentences=[sentence_out(media.id, s, stats.get(s.id)) for s in sentences],
        dictation=DictationSummary(
            **study_service.summary(len(sentences), stats)
        ),
    )


# --------------------------- 上传 / 导入 ---------------------------


@router.post("", response_model=MediaOut, status_code=201)
async def upload_media(
    file: UploadFile = File(...),
    category_id: int | None = Form(None),
    db: Session = Depends(get_db),
) -> MediaOut:
    """上传一个音频 / 视频文件（视频仅取音轨）；可选指定分类。"""
    try:
        with _domain_errors():
            media = media_ops.register_upload(
                db, file.file, file.filename, category_id
            )
    finally:
        # 上传流必须关闭：成功、校验失败、落盘失败三种路径都要收尾，
        # 否则大文件会在临时目录里留下 SpooledTemporaryFile。
        await file.close()
    return serialize(media)


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
    with _domain_errors():
        created, _skipped = media_ops.import_inbox(db, payload.files, payload.category_id)
    items = [serialize(media) for media in created]
    return MediaListResponse(items=items, total=len(items))


@router.post("/batch-category")
def batch_set_category(
    payload: BatchCategoryRequest,
    db: Session = Depends(get_db),
) -> dict:
    """批量把素材移动到某个分类（`category_id=null` = 移到「未分类」）。

    - `ids` 为空 → 400；`category_id` 指向的分类不存在 → 404。
    - `ids` 中不存在的媒体 id 不报错，收进 `missing` 回报，便于前端提示「N 个已失效」。
    """
    with _domain_errors():
        return media_ops.set_category_batch(db, payload.ids, payload.category_id)


# --------------------------- 列表 / 详情 ---------------------------


@router.get("", response_model=MediaListResponse)
def list_media(
    category_id: str | None = None,
    db: Session = Depends(get_db),
) -> MediaListResponse:
    """素材列表。可选 `category_id` 过滤：

    - 缺省 → 不加条件（保持既有「全部」行为，契约兼容）
    - 字面量 `none` → 只看「未分类」（`category_id IS NULL`）
    - 整数串 → 只看该分类
    - 其他非法值 → 400
    """
    with _domain_errors():
        rows = media_ops.list_media(db, category_id)
    items = [serialize(media, sentence_count=count) for media, count in rows]
    return MediaListResponse(items=items, total=len(items))


@router.get("/{media_id}", response_model=MediaDetailOut)
def get_media(media_id: int, db: Session = Depends(get_db)) -> MediaDetailOut:
    with _domain_errors():
        media = media_ops.get_media_or_404(db, media_id)
    return serialize_detail(db, media)


@router.patch("/{media_id}", response_model=MediaOut)
def update_media(
    media_id: int,
    payload: MediaUpdate,
    db: Session = Depends(get_db),
) -> MediaOut:
    # 区分「未传」与「传了 null」：null 表示移到「未分类」（Pydantic v2）
    with _domain_errors():
        media = media_ops.update_media(
            db,
            media_id,
            title=payload.title,
            category_id=payload.category_id,
            category_given="category_id" in payload.model_fields_set,
        )
    return serialize(media)


@router.post("/{media_id}/retry", response_model=MediaOut)
def retry_media(media_id: int, db: Session = Depends(get_db)) -> MediaOut:
    """重新处理（失败重试 / 手动重跑转码）。"""
    with _domain_errors():
        media = media_ops.retry_media(db, media_id)
    return serialize(media)


@router.delete("/{media_id}", status_code=204)
def delete_media(media_id: int, db: Session = Depends(get_db)) -> Response:
    with _domain_errors():
        media_ops.delete_with_files(db, media_id)
    return Response(status_code=204)


@router.post("/{media_id}/retranscribe", response_model=MediaOut)
def retranscribe_media(media_id: int, db: Session = Depends(get_db)) -> MediaOut:
    """重新识别（保留已转码音频，只重跑 识别→翻译→切片）。

    注意：会按识别结果重建句表，原有句子笔记与听写记录将一并清除。
    """
    with _domain_errors():
        media = media_ops.retranscribe(db, media_id)
    return serialize(media, sentence_count=len(media_ops.sentences_of(db, media_id)))


@router.get("/{media_id}/progress")
def media_progress(
    media_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """以 SSE 推送处理进度，直到 `done` / `failed` 后自动结束。"""
    with _domain_errors():
        media_ops.get_media_or_404(db, media_id)

    async def event_stream():
        elapsed = 0.0
        interval = 0.5
        max_seconds = 60 * 60  # 兜底上限，避免连接长期悬挂
        while elapsed < max_seconds:
            if await request.is_disconnected():
                break
            session = SessionLocal()
            try:
                snapshot = media_ops.progress_snapshot(session, media_id)
                if snapshot is None:
                    break
                event = ProgressEvent(
                    media_id=snapshot["media_id"],
                    status=snapshot["status"],
                    progress=snapshot["progress"],
                    stage=STAGE_LABEL.get(snapshot["status"], snapshot["status"]),
                    error=snapshot["error"],
                    sentence_count=snapshot["sentence_count"],
                    done=snapshot["done"],
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
    with _domain_errors():
        path = media_ops.resolve_clip(db, media_id, idx)
    return file_response(path, request, content_type=guess_mime(path))


@router.delete("/{media_id}/clips", status_code=200)
def clear_clips(media_id: int, db: Session = Depends(get_db)) -> dict:
    """清理切片以回收磁盘（学习页仍可整段播放）。"""
    with _domain_errors():
        clips_dir_path = media_ops.clear_clips(db, media_id)
    return {"media_id": media_id, "cleared": True, "clips_dir": clips_dir_path}


# --------------------------- 笔记汇总（M5 / FR-A6）---------------------------


@router.get("/{media_id}/notes", response_model=MediaNotesResponse)
def list_media_notes(media_id: int, db: Session = Depends(get_db)) -> MediaNotesResponse:
    """某个媒体的句子笔记汇总（供学习页「笔记」面板）。"""
    with _domain_errors():
        media = media_ops.get_media_or_404(db, media_id)
    rows = media_ops.notes_of(db, media_id)
    stats = study_service.media_stats(db, media_id)
    sentence_count = media_ops.count_sentences(db, media_id)

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


@router.get("/{media_id}/notes/export")
def export_media_notes(media_id: int, db: Session = Depends(get_db)) -> Response:
    """导出某个媒体的句子笔记为 Markdown 文件（浏览器下载）。"""
    with _domain_errors():
        body, filename = media_ops.export_notes_markdown(db, media_id)
    return Response(
        content=body,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


# --------------------------- 播放 ---------------------------


@router.get("/{media_id}/stream")
def stream_media(media_id: int, request: Request, db: Session = Depends(get_db)) -> Response:
    """流式播放：优先转码后的标准音频；转码完成前回退播放原始音频文件。"""
    with _domain_errors():
        path, download_name = media_ops.open_stream(db, media_id)
    return file_response(
        path,
        request,
        content_type=guess_mime(path),
        filename=download_name,
    )

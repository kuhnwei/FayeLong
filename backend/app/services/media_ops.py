"""媒体库领域操作层（P3-4 领域分层收口）。

为什么单独一个模块而不是塞进 `services/media.py`
================================================
`services/media.py`（852 行）已经承载**处理流水线**：ffprobe 探测 → ffmpeg 转码 →
识别 → 翻译 → 切片，以及 4 个 stage 的 job/fencing 逻辑。它跑在 **worker 进程**里，
是 CPU/IO 池的热路径。而本模块承载的是**用户请求侧的媒体库领域规则**：登记、落盘、
导入、批量归类、删除、重跑、进度快照、播放取流、笔记导出。

两类东西的生命周期与调用者完全不同（一个是 job handler、一个是 HTTP 请求），
混在一个文件里会让「改流水线」和「改接口语义」互相踩。因此：

* `services/media.py` —— 素材**怎么被处理**（worker 侧，stage 链）
* `services/media_ops.py` —— 素材**怎么被管理**（web 侧，请求 → 领域动作）

分层约定
========
* 本模块**只依赖** domain / 持久层：`models` / `db` / `core.paths` / `services.*`。
  **绝不 import `fastapi`**（不出现 `HTTPException` / `UploadFile` / `Request`），
  因此可以被 worker、脚本、测试直接调用。
* 领域错误用 :class:`MediaOpsError` 及其子类表达（带 `status_code` + `detail`），
  由 `api/media.py` 统一翻译成 `HTTPException`。**`detail` 文案是与前端的既有约定，
  一个字都不许改**（21 个 `test_media_flow` 用例与 `scripts/verify_*.mjs` 依赖它）。
* 响应**形状**（Pydantic 序列化、SSE 事件、`Response` 头部）属于协议层，
  留在 `api/media.py`；本模块只返回 ORM 对象 / 原始值 / dict。

行为零变化是本阶段的硬要求，因此这里刻意保留了几处「看起来可以更优雅」的写法
（例如 `list_media` 的 counts 查询不随过滤条件收窄、`register_media` 每次单独 commit），
它们都是既有行为的一部分（前者前端靠它拿全量句子数，后者被上传失败清理路径依赖）。
"""
from __future__ import annotations

import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import STATUS_PENDING, SUPPORTED_EXT
from app.core.paths import clips_dir, media_dir
from app.models import Category, Media, Note, Sentence, SentenceMark
from app.services import jobs as jobs_service
from app.services import media as media_service
from app.services import study as study_service
from app.services.study import SentenceStat

logger = logging.getLogger(__name__)

__all__ = [
    "MediaOpsError",
    "BadRequestError",
    "NotFoundError",
    "ConflictError",
    "StorageFailure",
    "SUPPORTED_HINT",
    "register_upload",
    "register_media",
    "persist_upload",
    "import_inbox",
    "set_category_batch",
    "list_media",
    "get_media_or_404",
    "ensure_category",
    "validate_ext",
    "update_media",
    "retry_media",
    "delete_with_files",
    "retranscribe",
    "progress_snapshot",
    "resolve_clip",
    "clear_clips",
    "notes_of",
    "count_sentences",
    "sentences_of",
    "export_notes_markdown",
    "open_stream",
]


# --------------------------- 领域错误 ---------------------------


class MediaOpsError(Exception):
    """媒体库领域的可预期错误（由 API 层翻译成 HTTP 响应）。

    Attributes:
        detail: 面向用户的中文原因（**必须与既有文案逐字一致**）。
        status_code: 应返回的 HTTP 状态码。
    """

    status_code: int = 400

    def __init__(self, detail: str, status_code: int | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        if status_code is not None:
            self.status_code = status_code


class BadRequestError(MediaOpsError):
    """客户端参数非法（400）。"""

    status_code = 400


class NotFoundError(MediaOpsError):
    """目标对象不存在（404）。"""

    status_code = 404


class ConflictError(MediaOpsError):
    """当前状态不允许该操作（409）。"""

    status_code = 409


class StorageFailure(MediaOpsError):
    """落盘 / 复制失败（500）。"""

    status_code = 500


#: 上传格式提示里给用户看的扩展名清单（`mp3、wav、…`）。
SUPPORTED_HINT = "、".join(sorted(ext.lstrip(".") for ext in SUPPORTED_EXT))


# --------------------------- 基础查询 / 校验 ---------------------------


def get_media_or_404(db: Session, media_id: int) -> Media:
    """按 id 取媒体；不存在 → :class:`NotFoundError`（404「媒体不存在」）。"""
    media = db.get(Media, media_id)
    if media is None:
        raise NotFoundError("媒体不存在")
    return media


def ensure_category(db: Session, category_id: int | None) -> None:
    """写库前校验目标分类存在（非 null 时）；不存在 → 404「分类不存在」。"""
    if category_id is not None and db.get(Category, category_id) is None:
        raise NotFoundError("分类不存在")


def validate_ext(name: str) -> str:
    """校验文件名后缀是否受支持，返回小写后缀（含点）。不支持 → 400。

    Args:
        name: 文件名（或路径，取 `suffix`）。

    Returns:
        形如 `".mp3"` 的小写后缀。

    Raises:
        BadRequestError: 后缀不在 `SUPPORTED_EXT` 里。
    """
    ext = Path(name).suffix.lower()
    if ext not in SUPPORTED_EXT:
        raise BadRequestError(
            f"不支持的文件类型「{ext or '未知'}」，支持：{SUPPORTED_HINT}"
        )
    return ext


def sentences_of(db: Session, media_id: int) -> list[Sentence]:
    """某媒体的句子，按 `idx` 升序。

    Notes:
        `services/media.py::_sentences_of` 是同语义的 stage 私有 helper
        （worker 热路径内部用）。刻意**不**把它改成调用本函数：那需要反向依赖，
        会在 `services.media ⇄ services.media_ops` 之间制造循环 import。
        两者语义必须保持一致（都按 `idx` 升序、都按 `media_id` 过滤）。
    """
    return (
        db.query(Sentence)
        .filter(Sentence.media_id == media_id)
        .order_by(Sentence.idx)
        .all()
    )


def count_sentences(db: Session, media_id: int) -> int:
    """某媒体的句子条数。"""
    return int(
        db.query(func.count(Sentence.id))
        .filter(Sentence.media_id == media_id)
        .scalar()
        or 0
    )


def notes_of(db: Session, media_id: int, user_id: int) -> list[tuple[Note, Sentence]]:
    """该媒体下当前用户所有「已有笔记」的句子（按句序）。"""
    return (
        db.query(Note, Sentence)
        .join(Sentence, Sentence.id == Note.sentence_id)
        .filter(Sentence.media_id == media_id, Note.user_id == user_id)
        .order_by(Sentence.idx)
        .all()
    )


def marks_map(db: Session, user_id: int, sentence_ids: list[int]) -> dict[int, str]:
    """批量取某用户在这些句子上的「易听错」标记 ranges（key = sentence_id）。"""
    if not sentence_ids:
        return {}
    rows = (
        db.query(SentenceMark.sentence_id, SentenceMark.ranges)
        .filter(
            SentenceMark.user_id == user_id,
            SentenceMark.sentence_id.in_(sentence_ids),
        )
        .all()
    )
    return {sid: ranges for sid, ranges in rows}


# --------------------------- 登记 / 落盘 ---------------------------


def register_media(
    db: Session,
    *,
    title: str,
    original_name: str,
    origin: str,
    source_ref: str | None,
    category_id: int | None = None,
) -> Media:
    """登记一条媒体记录（**状态契约**在此集中定义：`pending` / progress 0）。

    Args:
        db: 会话。
        title: 展示标题（超 255 截断；空串回落到「未命名」）。
        original_name: 原始文件名（超 255 截断）。
        origin: `upload` / `inbox`。
        source_ref: 收件箱来源的绝对路径（上传为 `None`）。
        category_id: 目标分类，`None` = 未分类。

    Returns:
        已 commit + refresh 的 `Media`。
    """
    media = Media(
        title=title[:255] or "未命名",
        original_name=original_name[:255],
        type="audio",
        file_path="",
        status=STATUS_PENDING,
        progress=0,
        origin=origin,
        source_ref=source_ref,
        category_id=category_id,
    )
    db.add(media)
    db.commit()
    db.refresh(media)
    return media


def persist_upload(db: Session, media: Media, stream: BinaryIO, ext: str) -> None:
    """把上传流写入媒体库目录；失败则回滚记录并清理已落地的半成品。

    Args:
        db: 会话。
        media: 已登记的媒体（用它的 id 定位目录）。
        stream: 二进制流（`UploadFile.file`）。
        ext: 已校验的后缀（含点）。

    Raises:
        StorageFailure: 落盘失败（500「保存文件失败：…」）。
    """
    destination = media_dir(media.id) / f"original{ext}"
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("wb") as out:
            shutil.copyfileobj(stream, out, 1024 * 1024)
    except OSError as exc:
        db.delete(media)
        db.commit()
        media_service.delete_media_files(media.id)
        raise StorageFailure(f"保存文件失败：{exc}") from exc

    media.file_path = str(destination)
    media.size_bytes = destination.stat().st_size
    db.commit()
    db.refresh(media)


def register_upload(
    db: Session,
    stream: BinaryIO,
    filename: str | None,
    category_id: int | None,
) -> Media:
    """上传一个文件的完整领域动作：校验 → 登记 → 落盘 → 入队。

    Args:
        db: 会话。
        stream: 二进制流。
        filename: 客户端提供的文件名（可能含路径，只取 basename）。
        category_id: 目标分类，`None` = 未分类。

    Returns:
        已落盘并入队的 `Media`。

    Raises:
        BadRequestError: 无文件名 / 后缀不支持。
        NotFoundError: 分类不存在。
        StorageFailure: 落盘失败。
    """
    safe_name = Path(filename or "").name
    if not safe_name:
        raise BadRequestError("未获取到文件名")
    ext = validate_ext(safe_name)
    ensure_category(db, category_id)

    media = register_media(
        db,
        title=Path(safe_name).stem,
        original_name=safe_name,
        origin="upload",
        source_ref=None,
        category_id=category_id,
    )
    persist_upload(db, media, stream, ext)
    media_service.enqueue(media.id)
    logger.info(
        "已接收上传：%s（media=%s, %.1f MB）",
        safe_name, media.id, media.size_bytes / 1024 / 1024,
    )
    return media


# --------------------------- 收件箱导入 ---------------------------


def import_inbox(
    db: Session,
    files: list[str] | None,
    category_id: int | None,
) -> tuple[list[Media], list[str]]:
    """从收件箱导入素材（去重 + 逐条登记 + 落盘 + 入队）。

    Args:
        db: 会话。
        files: 指定要导入的绝对路径；`None` / 空 = 全部「受支持且未导入」的文件。
        category_id: 本次导入的素材统一归入该分类，`None` = 未分类。

    Returns:
        `(成功导入的媒体列表, 跳过原因文案列表)`。

    Raises:
        NotFoundError: 分类不存在。
    """
    ensure_category(db, category_id)
    available = {item["path"]: item for item in media_service.scan_inbox(db)}
    if files:
        targets = files
    else:
        targets = [
            path
            for path, item in available.items()
            if item["supported"] and not item["imported"]
        ]

    created: list[Media] = []
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

        media = register_media(
            db,
            title=source.stem,
            original_name=source.name,
            origin="inbox",
            source_ref=str(source.resolve()),
            category_id=category_id,
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
        created.append(media)

    if skipped:
        logger.info("导入跳过 %d 个文件：%s", len(skipped), "；".join(skipped[:10]))

    return created, skipped


# --------------------------- 归类 ---------------------------


def set_category_batch(
    db: Session,
    ids: list[int],
    category_id: int | None,
) -> dict[str, Any]:
    """批量把素材移动到某个分类（`category_id=None` = 移到「未分类」）。

    Args:
        db: 会话。
        ids: 媒体 id 列表（内部去重但保留顺序）。
        category_id: 目标分类。

    Returns:
        `{"updated": n, "category_id": id|None, "missing": [不存在的 id]}`。

    Raises:
        BadRequestError: `ids` 为空（400「ids 不能为空」）。
        NotFoundError: 分类不存在。
    """
    if not ids:
        raise BadRequestError("ids 不能为空")
    ensure_category(db, category_id)

    unique_ids = list(dict.fromkeys(ids))  # 去重但保留顺序
    existing = {
        row[0]
        for row in db.query(Media.id).filter(Media.id.in_(unique_ids)).all()
    }
    missing = [mid for mid in unique_ids if mid not in existing]

    updated = 0
    if existing:
        updated = (
            db.query(Media)
            .filter(Media.id.in_(list(existing)))
            .update({Media.category_id: category_id}, synchronize_session=False)
        )
        db.commit()
    logger.info(
        "批量归类：updated=%d, category_id=%s, missing=%d",
        updated, category_id, len(missing),
    )
    return {"updated": updated, "category_id": category_id, "missing": missing}


def update_media(
    db: Session,
    media_id: int,
    *,
    title: str | None = None,
    category_id: int | None = None,
    category_given: bool = False,
) -> Media:
    """PATCH 单条媒体：改标题 / 归类。

    Args:
        db: 会话。
        media_id: 媒体 id。
        title: 新标题；`None` = 不改（传空串/全空白时保持原标题，既有行为）。
        category_id: 目标分类。
        category_given: 客户端**是否显式传了** `category_id`（含显式 `null`）。
            用来区分「未传」与「传 null = 移到未分类」。

    Returns:
        已 commit + refresh 的 `Media`。

    Raises:
        NotFoundError: 媒体或分类不存在。
    """
    media = get_media_or_404(db, media_id)
    if title is not None:
        clean = title.strip()
        if clean:
            media.title = clean[:255]
    if category_given:
        ensure_category(db, category_id)
        media.category_id = category_id
    db.commit()
    db.refresh(media)
    return media


# --------------------------- 列表 / 状态流转 ---------------------------


def list_media(
    db: Session,
    category_id: str | None = None,
) -> list[tuple[Media, int]]:
    """素材列表（含每条的句子数）。

    Args:
        db: 会话。
        category_id: 过滤条件（原始查询串）：
            * `None` → 不加条件（保持既有「全部」行为，契约兼容）
            * 字面量 `none` → 只看「未分类」（`category_id IS NULL`）
            * 整数串 → 只看该分类
            * 其他非法值 → 400

    Returns:
        `[(media, sentence_count)]`，按 `id` 倒序。

    Raises:
        BadRequestError: `category_id` 既不是整数也不是 `none`。
    """
    query = db.query(Media)
    if category_id is not None:
        if category_id == "none":
            query = query.filter(Media.category_id.is_(None))
        else:
            try:
                target = int(category_id)
            except (TypeError, ValueError):
                raise BadRequestError(
                    "category_id 需为整数，或字面量 none（未分类）"
                ) from None
            query = query.filter(Media.category_id == target)

    rows = query.order_by(Media.id.desc()).all()
    # ⚠️ 句子数刻意**不**随过滤条件收窄：前端用它显示「N 句」，与分类无关。
    counts = dict(
        db.query(Sentence.media_id, func.count(Sentence.id))
        .group_by(Sentence.media_id)
        .all()
    )
    return [(row, counts.get(row.id, 0)) for row in rows]


def retry_media(db: Session, media_id: int) -> Media:
    """重新处理（失败重试 / 手动重跑转码）。

    Args:
        db: 会话。
        media_id: 媒体 id。

    Returns:
        已重置为 `pending` 并入队的 `Media`。

    Raises:
        NotFoundError: 媒体不存在。
        ConflictError: 原始文件已丢失（409）。
    """
    media = get_media_or_404(db, media_id)
    if not Path(media.file_path).is_file():
        raise ConflictError("原始文件已丢失，请删除后重新导入")
    media.status = STATUS_PENDING
    media.progress = 0
    media.error = None
    db.commit()
    db.refresh(media)
    media_service.enqueue(media_id)
    return media


def retranscribe(db: Session, media_id: int) -> Media:
    """重新识别（保留已转码音频，只重跑 识别 → 翻译 → 切片）。

    Args:
        db: 会话。
        media_id: 媒体 id。

    Returns:
        已重置为 `pending` 并入队的 `Media`。

    Raises:
        NotFoundError: 媒体不存在。
        ConflictError: 标准音频尚未就绪（409）。
    """
    media = get_media_or_404(db, media_id)
    audio = Path(media.audio_path) if media.audio_path else None
    if audio is None or not audio.is_file():
        raise ConflictError("标准音频尚未就绪，请先「重新处理」")
    media.status = STATUS_PENDING
    media.progress = 0
    media.error = None
    db.commit()
    db.refresh(media)
    media_service.enqueue_retranscribe(media_id)
    logger.info("媒体 %s 已重新排队识别", media_id)
    return media


def delete_with_files(db: Session, media_id: int) -> None:
    """删除媒体：DB 行（级联句/笔记/听写）+ 任务行 + 磁盘目录，一步不漏。

    Args:
        db: 会话。
        media_id: 媒体 id。

    Raises:
        NotFoundError: 媒体不存在。

    Notes:
        `jobs.ref_id` 是**多态引用、刻意不加外键**（DD-001 §3.2）→ 任务行必须
        在这里由应用层清理，且与 `db.delete(media)` 在**同一事务**里提交。
        执行中的 job 行被删后，其线程下一次写回 `rowcount=0` → 自动自杀
        （因此不需要 `cancelled` 状态）。
    """
    media = get_media_or_404(db, media_id)
    db.delete(media)          # ORM 级联删除句子 / 笔记 / 听写记录
    jobs_service.purge_for_media(db, media_id)
    db.commit()
    media_service.delete_media_files(media_id)
    logger.info("已删除媒体 %s（%s）", media_id, media.title)


# --------------------------- 切片 ---------------------------


def clear_clips(db: Session, media_id: int) -> str:
    """清理切片以回收磁盘（学习页仍可整段播放）。

    Args:
        db: 会话。
        media_id: 媒体 id。

    Returns:
        该媒体的切片目录（字符串，供响应体回报）。

    Raises:
        NotFoundError: 媒体不存在。
    """
    get_media_or_404(db, media_id)
    from app.services import clip as clip_service

    clip_service.clear_clips(media_id)
    for sentence in sentences_of(db, media_id):
        sentence.clip_path = None
    db.commit()
    logger.info("已清理媒体 %s 的音频切片", media_id)
    return str(clips_dir(media_id))


def resolve_clip(db: Session, media_id: int, idx: int) -> Path:
    """定位某一句的切片文件（供 Range 响应）。

    Args:
        db: 会话。
        media_id: 媒体 id。
        idx: 句子序号（0 基）。

    Returns:
        已确认存在的切片路径。

    Raises:
        NotFoundError: 媒体不存在 / 该句无切片 / 切片文件丢失（文案不同）。
    """
    get_media_or_404(db, media_id)
    sentence = (
        db.query(Sentence)
        .filter(Sentence.media_id == media_id, Sentence.idx == idx)
        .first()
    )
    if sentence is None or not sentence.clip_path:
        raise NotFoundError("该句暂无音频切片")
    path = Path(sentence.clip_path)
    if not path.is_file():
        raise NotFoundError("切片文件已丢失，可执行「重新处理」重建")
    return path


# --------------------------- 进度 / 播放 ---------------------------


#: 终态（进度轮询据此结束）。
TERMINAL_STATUSES: tuple[str, ...] = ("done", "failed")


def progress_snapshot(db: Session, media_id: int) -> dict[str, Any] | None:
    """聚合一次进度快照（SSE 每一帧 / 轮询兜底共用）。

    Args:
        db: 会话。
        media_id: 媒体 id。

    Returns:
        含 `media_id / status / progress / error / sentence_count / done` 的 dict；
        媒体已不存在时返回 `None`（调用方据此结束流）。
    """
    media = db.get(Media, media_id)
    if media is None:
        return None
    return {
        "media_id": media.id,
        "status": media.status,
        "progress": media.progress,
        "error": media.error,
        "sentence_count": count_sentences(db, media_id),
        "done": media.status in TERMINAL_STATUSES,
    }


def open_stream(db: Session, media_id: int) -> tuple[Path, str]:
    """定位可播放的音频文件（优先转码后的标准音频，回退原始文件）。

    Args:
        db: 会话。
        media_id: 媒体 id。

    Returns:
        `(路径, 建议的下载/内联文件名)`。Range 切分本身不在这里做
        —— 那是协议层的事，见 `core/files.py::file_response`。

    Raises:
        NotFoundError: 媒体不存在。
        ConflictError: 音频尚未就绪（409）。
    """
    media = get_media_or_404(db, media_id)

    candidates: list[Path] = []
    if media.audio_path:
        candidates.append(Path(media.audio_path))
    if media.file_path and media.type == "audio":
        candidates.append(Path(media.file_path))

    for path in candidates:
        if path.is_file():
            return path, (media.original_name or path.name)

    raise ConflictError("音频尚未就绪，请稍候")


# --------------------------- 笔记导出 ---------------------------


def notes_markdown(
    media: Media,
    rows: list[tuple[Note, Sentence]],
    stats: dict[int, SentenceStat],
    sentence_count: int,
) -> str:
    """把某媒体的笔记汇总成 Markdown（原文 / 翻译 / 听写概要 / 笔记）。

    Args:
        media: 媒体。
        rows: `(note, sentence)` 列表（按句序）。
        stats: 句子 id → 听写统计。
        sentence_count: 全篇句子数。

    Returns:
        Markdown 正文（末尾恰好一个换行）。
    """

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


def export_notes_markdown(db: Session, media_id: int, user_id: int) -> tuple[str, str]:
    """导出某媒体的句子笔记（正文 + 文件名）。

    Args:
        db: 会话。
        media_id: 媒体 id。
        user_id: 只导出该用户的笔记（多用户隔离）。

    Returns:
        `(markdown 正文, 下载文件名)`。文件名已剔除 Windows 非法字符。

    Raises:
        NotFoundError: 媒体不存在。
    """
    media = get_media_or_404(db, media_id)
    rows = notes_of(db, media_id, user_id)
    stats = study_service.media_stats(db, media_id, user_id)
    sentence_count = count_sentences(db, media_id)
    body = notes_markdown(media, rows, stats, sentence_count)

    safe_title = "".join(ch for ch in media.title if ch not in '\\/:*?"<>|').strip() or "未命名"
    filename = f"{safe_title}-笔记-{datetime.now():%Y%m%d-%H%M}.md"
    logger.info("导出媒体 %s 的 %d 条笔记为 Markdown", media_id, len(rows))
    return body, filename

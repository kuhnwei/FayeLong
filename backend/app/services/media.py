"""媒体处理服务：ffprobe 探测 → ffmpeg 转码 →（M2 起：识别 / 翻译 / 切片）。

M1 负责把用户导入的音视频统一转成「16kHz 单声道 wav」，此后所有下游处理
（ASR / 切片）都基于这一份标准音频，避免格式差异带来的问题。
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

from app.core.config import (
    INBOX_DIR,
    PROGRESS_ASR,
    PROGRESS_CLIP,
    PROGRESS_TRANSCODE,
    PROGRESS_TRANSLATE,
    STATUS_ASR,
    STATUS_CLIPPING,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_TRANSCODING,
    STATUS_TRANSLATING,
    SUPPORTED_EXT,
    UNFINISHED_STATUSES,
    settings,
)
from app.core.paths import (
    MediaError,
    audio_wav_path,
    clips_dir,
    media_dir,
)
from app.core.tasks import submit
from app.core.tools import ffmpeg_path, ffprobe_path
from app.db import SessionLocal
from app.models import Media, Sentence

logger = logging.getLogger(__name__)

ProgressCb = Callable[[int], None]

__all__ = [
    "MediaError",
    "media_dir",
    "audio_wav_path",
    "clips_dir",
    "probe",
    "transcode_to_wav",
    "copy_into_library",
    "delete_media_files",
    "process_media",
    "retranscribe_media",
    "enqueue",
    "requeue_unfinished",
    "scan_inbox",
]


# --------------------------- 探测 ---------------------------


def probe(path: Path) -> dict:
    """用 ffprobe 读取时长 / 类型 / 编码信息。"""
    exe = ffprobe_path()
    if not exe:
        raise MediaError("未找到 ffprobe，无法解析媒体信息")

    cmd = [
        exe,
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired as exc:
        raise MediaError("媒体探测超时（文件可能损坏）") from exc
    except OSError as exc:
        raise MediaError(f"无法启动 ffprobe：{exc}") from exc

    if proc.returncode != 0:
        detail = (proc.stderr or "").strip().splitlines()
        raise MediaError(f"无法解析该文件：{detail[-1] if detail else '未知错误'}")

    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise MediaError("媒体探测结果解析失败") from exc

    streams = data.get("streams") or []
    fmt = data.get("format") or {}

    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
    video_streams = [
        s
        for s in streams
        if s.get("codec_type") == "video"
        and (s.get("disposition") or {}).get("attached_pic", 0) != 1  # 排除封面图
    ]
    if not audio_streams:
        raise MediaError("该文件不含音频轨道，无法用于听力学习")

    duration = 0.0
    for candidate in (fmt.get("duration"), *(s.get("duration") for s in audio_streams)):
        try:
            duration = float(candidate)
            break
        except (TypeError, ValueError):
            continue

    return {
        "duration_ms": int(round(duration * 1000)),
        "type": "video" if video_streams else "audio",
        "has_video": bool(video_streams),
        "format": fmt.get("format_name", ""),
        "audio_codec": audio_streams[0].get("codec_name"),
        "size_bytes": int(fmt.get("size") or path.stat().st_size),
    }


# --------------------------- 转码 ---------------------------


def transcode_to_wav(
    src: Path,
    dst: Path,
    duration_ms: int = 0,
    on_progress: ProgressCb | None = None,
) -> None:
    """把任意音视频转成 16kHz 单声道 wav，并通过回调上报进度（0-100）。"""
    exe = ffmpeg_path()
    if not exe:
        raise MediaError("未找到 ffmpeg，无法转码")

    dst.parent.mkdir(parents=True, exist_ok=True)

    cmd = [exe, "-y", "-hide_banner", "-loglevel", "error", "-nostdin"]
    if settings.ffmpeg_threads > 0:
        cmd += ["-threads", str(settings.ffmpeg_threads)]
    cmd += [
        "-i", str(src),
        "-vn",                                     # 视频只取音轨（FR-M2）
        "-ac", str(settings.transcode_channels),
        "-ar", str(settings.transcode_sample_rate),
        "-c:a", "pcm_s16le",
        "-progress", "pipe:1",
        "-nostats",
        str(dst),
    ]

    # 进度走 stdout，错误信息写临时文件（避免管道缓冲区互锁）
    err_file = tempfile.TemporaryFile()
    try:
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=err_file,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except OSError as exc:
            raise MediaError(f"无法启动 ffmpeg：{exc}") from exc

        last_reported = -1
        try:
            for line in proc.stdout or []:
                key, _, value = line.strip().partition("=")
                if key not in ("out_time_us", "out_time_ms"):
                    continue
                try:
                    # ffmpeg 的 out_time_ms 实际也是微秒
                    out_ms = int(value) / 1000
                except ValueError:
                    continue
                if duration_ms > 0:
                    pct = max(1, min(99, int(out_ms / duration_ms * 100)))
                    if pct != last_reported and on_progress:
                        last_reported = pct
                        on_progress(pct)
            proc.wait()
        finally:
            if proc.stdout:
                proc.stdout.close()

        err_file.seek(0)
        message = err_file.read().decode("utf-8", "replace").strip()
    finally:
        err_file.close()

    if proc.returncode != 0:
        raise MediaError(f"转码失败：{message[:300] or 'ffmpeg 异常退出'}")
    if not dst.is_file() or dst.stat().st_size == 0:
        raise MediaError("转码结果为空，源文件可能损坏")


# --------------------------- 落地到媒体库 ---------------------------


def copy_into_library(media_id: int, src: Path) -> Path:
    """把原始文件复制进媒体库目录（不改动收件箱里的用户文件）。"""
    directory = media_dir(media_id)
    directory.mkdir(parents=True, exist_ok=True)
    dst = directory / f"original{src.suffix.lower()}"
    shutil.copy2(src, dst)
    return dst


def delete_media_files(media_id: int) -> None:
    """删除某媒体的全部文件（原文件 / 转码音频 / 切片）。"""
    directory = media_dir(media_id)
    if directory.exists():
        shutil.rmtree(directory, ignore_errors=True)


# --------------------------- 处理流程（M1 转码 → M2 识别/翻译/切片）---------------------------


def _scale(percent: int, span: tuple[int, int]) -> int:
    """把 0-100 的局部进度映射到整体进度区间。"""
    low, high = span
    value = low + (high - low) * max(0, min(100, percent)) / 100
    return max(low, min(high, int(round(value))))


def _mark_failed(media_id: int, message: str) -> None:
    db = SessionLocal()
    try:
        media = db.get(Media, media_id)
        if media is not None:
            media.status = STATUS_FAILED
            media.progress = 0
            media.error = (message or "处理失败")[:500]
            db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.exception("写入失败状态出错: media=%s", media_id)
    finally:
        db.close()


class _Progress:
    """把「阶段局部进度」映射为「媒体整体进度」并落库，带写库节流。"""

    def __init__(self, db, media: Media, span: tuple[int, int]) -> None:
        self._db = db
        self._media = media
        self._span = span
        self._last = -1

    def __call__(self, percent: int) -> None:
        overall = _scale(percent, self._span)
        if overall - self._last < 2:      # 控制写库频率
            return
        self._last = overall
        self._media.progress = overall
        self._db.commit()


def _set_stage(db, media: Media, status: str, progress: int) -> None:
    media.status = status
    media.progress = progress
    media.error = None
    db.commit()


def _ensure_audio(db, media: Media) -> Path:
    """确保标准音频存在（已存在则跳过转码，便于失败后从识别阶段重跑）。"""
    dst = audio_wav_path(media.id)
    if dst.is_file() and dst.stat().st_size > 0 and media.audio_path == str(dst):
        return dst

    src = Path(media.file_path)
    if not src.is_file():
        raise MediaError(f"源文件不存在：{src.name}")

    info = probe(src)
    media.duration_ms = info["duration_ms"] or media.duration_ms
    media.type = info["type"]
    media.size_bytes = info["size_bytes"] or media.size_bytes
    _set_stage(db, media, STATUS_TRANSCODING, _scale(1, PROGRESS_TRANSCODE))

    transcode_to_wav(src, dst, media.duration_ms, _Progress(db, media, PROGRESS_TRANSCODE))
    media.audio_path = str(dst)
    media.progress = _scale(100, PROGRESS_TRANSCODE)
    db.commit()
    logger.info(
        "媒体 %s 转码完成：%s（%.1fs，%s）",
        media.id, media.title, media.duration_ms / 1000, info["type"],
    )
    return dst


def _persist_sentences(db, media_id: int, sentences) -> list[Sentence]:
    """重建句表（先清空旧句，再按序写入）。"""
    db.query(Sentence).filter(Sentence.media_id == media_id).delete(
        synchronize_session=False
    )
    db.flush()

    rows: list[Sentence] = []
    for index, item in enumerate(sentences):
        row = Sentence(
            media_id=media_id,
            idx=index,
            start_ms=item.start_ms,
            end_ms=item.end_ms,
            text_en=item.text,
            text_zh="",
            clip_path=None,
            is_edited=False,
        )
        db.add(row)
        rows.append(row)
    db.commit()
    return rows


def _run_recognition(db, media: Media, audio: Path) -> None:
    """识别 → 翻译 → 切片（M2 主流程）。"""
    # 延迟导入：未安装 ML 依赖时不影响转码/播放
    from app.services import asr as asr_service
    from app.services import clip as clip_service
    from app.services import translate as translate_service

    _set_stage(db, media, STATUS_ASR, _scale(1, PROGRESS_ASR))
    sentences, info = asr_service.transcribe(
        audio,
        duration_ms=media.duration_ms,
        on_progress=_Progress(db, media, PROGRESS_ASR),
    )
    if not sentences:
        raise MediaError("未识别到任何语音内容，请确认音频中有英文人声")

    rows = _persist_sentences(db, media.id, sentences)
    media.progress = _scale(100, PROGRESS_ASR)
    db.commit()
    logger.info("媒体 %s 识别完成：%d 句", media.id, len(rows))

    # ---- 逐句在线翻译（带缓存与限速）----
    _set_stage(db, media, STATUS_TRANSLATING, PROGRESS_TRANSLATE[0])
    total = len(rows)
    failed = 0
    for index, row in enumerate(rows):
        result = translate_service.translate(row.text_en)
        if result["text"]:
            row.text_zh = result["text"]
        else:
            failed += 1
        if index < total - 1:
            translate_service.sleep_between()
        media.progress = _scale(int((index + 1) / total * 100), PROGRESS_TRANSLATE)
        if index % 5 == 0 or index == total - 1:
            db.commit()
    db.commit()
    if failed:
        logger.warning("媒体 %s 有 %d/%d 句翻译失败（保留空译文待人工补）", media.id, failed, total)

    # ---- 逐句裁剪音频切片（FR-A1）----
    _set_stage(db, media, STATUS_CLIPPING, PROGRESS_CLIP[0])
    clip_service.clear_clips(media.id)
    for index, row in enumerate(rows):
        target = clip_service.cut_clip_auto(
            audio, media.id, row.idx, row.start_ms, row.end_ms
        )
        row.clip_path = str(target)
        media.progress = _scale(int((index + 1) / total * 100), PROGRESS_CLIP)
        if index % 10 == 0 or index == total - 1:
            db.commit()
    db.commit()

    media.status = STATUS_DONE
    media.progress = 100
    media.error = None
    db.commit()
    logger.info("媒体 %s 处理完成：%d 句，切片就绪", media.id, total)


def _run(media_id: int, from_recognition: bool = False) -> None:
    db = SessionLocal()
    try:
        media = db.get(Media, media_id)
        if media is None:
            logger.warning("媒体 %s 不存在，跳过处理", media_id)
            return

        media.error = None
        db.commit()

        if from_recognition:
            audio = Path(media.audio_path or audio_wav_path(media_id))
            if not audio.is_file():
                raise MediaError("标准音频丢失，请执行「重新处理」")
        else:
            audio = _ensure_audio(db, media)

        _run_recognition(db, media, audio)
    finally:
        db.close()


def process_media(media_id: int) -> None:
    """媒体处理入口（在线程池中执行）：转码 → 识别 → 翻译 → 切片。"""
    try:
        _run(media_id)
    except Exception as exc:  # noqa: BLE001  统一转成 failed 状态
        logger.exception("媒体 %s 处理失败", media_id)
        _mark_failed(media_id, str(exc))


def retranscribe_media(media_id: int) -> None:
    """只重跑识别/翻译/切片（保留已转码音频），用于模型升级或重新识别。"""
    try:
        _run(media_id, from_recognition=True)
    except Exception as exc:  # noqa: BLE001
        logger.exception("媒体 %s 重新识别失败", media_id)
        _mark_failed(media_id, str(exc))


def enqueue(media_id: int) -> None:
    """把媒体加入处理队列（完整流程）。"""
    submit(process_media, media_id)


def enqueue_retranscribe(media_id: int) -> None:
    """把「重新识别」任务加入队列。"""
    submit(retranscribe_media, media_id)


def requeue_unfinished() -> int:
    """服务启动时把上次未完成的任务重新排队（异常退出后的自愈）。"""
    db = SessionLocal()
    try:
        rows = (
            db.query(Media)
            .filter(Media.status.in_(UNFINISHED_STATUSES))
            .all()
        )
        ids = [m.id for m in rows]
        for media in rows:
            media.status = STATUS_PENDING
            media.progress = 0
        db.commit()
    finally:
        db.close()

    for media_id in ids:
        enqueue(media_id)
    if ids:
        logger.info("重启恢复：重新排队 %d 个未完成的媒体任务", len(ids))
    return len(ids)


# --------------------------- 收件箱 ---------------------------


def scan_inbox(db) -> list[dict]:
    """列出收件箱（data/media/audio）中的素材，并标记是否已导入。

    已导入的判定：媒体表的 source_ref 记录了该文件的绝对路径。
    """
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    imported: set[str] = {
        row[0]
        for row in db.query(Media.source_ref).filter(Media.source_ref.isnot(None)).all()
        if row[0]
    }

    items: list[dict] = []
    for entry in sorted(INBOX_DIR.iterdir()):
        if not entry.is_file():
            continue
        if entry.name.startswith("."):
            continue
        ext = entry.suffix.lower()
        stat = entry.stat()
        items.append(
            {
                "name": entry.name,
                "path": str(entry.resolve()),
                "ext": ext,
                "supported": ext in SUPPORTED_EXT,
                "size_bytes": stat.st_size,
                "imported": str(entry.resolve()) in imported,
            }
        )
    return items

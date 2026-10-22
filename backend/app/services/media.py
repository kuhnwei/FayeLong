"""媒体处理服务：ffprobe 探测 → ffmpeg 转码 → 识别 → 翻译 → 切片。

P3-2 / P3-3 起本模块被**拆成 4 个 stage**（每个 stage 是 `jobs` 表里的一个 job）
================================================================================
::

    KIND_TRANSCODE (CPU) → KIND_ASR (CPU) → KIND_TRANSLATE (IO) → KIND_CLIP (CPU)

为什么要拆：一条 `process_media()` 里既有 CPU 活（ffmpeg / whisper / 切片）又有
网络 IO（在线翻译）。若整条链占**一个** CPU 池槽位，长 ASR 期间同池的其它媒体
全部排队，G3-③「ASR 不阻塞翻译」物理上不可能通过（DD-001 §5.2）。

拆分后的不变量（改动前务必逐条核对）
====================================
1. **每个 stage 必须幂等**：转码 `-y` 覆盖写、识别先删后建、翻译只 UPDATE、
   切片先 clear 再重切。重试从**本 stage 开头**重跑，不会累积脏数据。
2. **链条衔接在 job 完成路径里做**（`jobs_service.finish_ok(next_kind=...)`），
   且与 `jobs→done` **同一次 commit** —— 否则两次提交之间崩溃 = 任务凭空消失。
3. **`media.status` 的取值/语义/进度区间一个都不许变**：
   `pending→transcoding→(ready)→asr→translating→clipping→done | failed`，
   进度区间 0-20 / 20-70 / 70-90 / 90-100。前端与契约都依赖它。
4. **两条轴一起收敛**：stage 正常完成时 media 由 stage 自己写、job 由 runner 写；
   失败且到终态时 `media` 与 `jobs` 在**同一 Session 一次 commit** 里双写。
5. `requeue_unfinished()` **签名与 `enqueue()` 调用方式保持**，但返回条数的口径
   在 P4 收紧为「**实际重新入队**的条数」：已有活跃 job 的媒体**跳过**（不改
   `media.status`、不入队）。P3-2 之后 worker 能活过 web 重启，旧的「重启即全部
   重置」前提已不成立（详见该函数 docstring）。

⚠️ 已知影响（DD-001 §9 R5，本阶段**刻意不修**）
==============================================
`stage_asr` 重跑会 `_persist_sentences()` 先 DELETE 再重建句表，句子 id 变化
→ `attempts` / `notes` 的 `ON DELETE CASCADE` 会连带删掉该媒体的听写记录与笔记。
这与现状完全一致（`retranscribe` 一直如此），拆 stage 已把影响面从「整条链」缩到
「asr 单阶段」。修它属于**改业务逻辑**（要做 id 迁移），另起任务；这里只在代码里
留下注释与 ERROR 日志，不静默。
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator

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
from app.core.tools import ffmpeg_path, ffprobe_path
from app.db import SessionLocal
from app.models import Attempt, Job, Media, Sentence
from app.services import jobs as jobs_service
from app.services.jobs import JobCtx

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
    "stage_transcode",
    "stage_asr",
    "stage_translate",
    "stage_clip",
    "process_media",
    "retranscribe_media",
    "enqueue",
    "enqueue_retranscribe",
    "mark_terminal_failure",
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
    """把任意音视频转成 16kHz 单声道 wav，并通过回调上报进度（0-100）。

    Notes:
        P3-2 起 `on_progress` 可能**抛异常**（`JobAborted`：本执行者已被回收）。
        因此这里必须保证「无论如何都收割 ffmpeg 子进程」—— 否则会留下一个还在往
        目标文件写的孤儿 ffmpeg（Windows 上还会一直锁着该文件），下一次重试的
        `-y` 覆盖写就会失败。
    """
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
            # 进度回调抛异常时（fencing 失效）也不能留下孤儿 ffmpeg
            if proc.poll() is None:
                proc.kill()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:  # pragma: no cover - 极端情况
                    logger.error("ffmpeg 未能被收割（pid=%s）", proc.pid)

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


# --------------------------- 进度 / 状态助手 ---------------------------


def _scale(percent: int, span: tuple[int, int]) -> int:
    """把 0-100 的局部进度映射到整体进度区间。"""
    low, high = span
    value = low + (high - low) * max(0, min(100, percent)) / 100
    return max(low, min(high, int(round(value))))


class _Progress:
    """把「阶段局部进度」映射为「媒体整体进度」并落库，带写库节流。

    Args:
        db: 会话。
        media: 媒体对象。
        span: 该阶段在整体进度里占的区间（如 `(20, 70)`）。
        job: 可选 `JobCtx`。给了就在**同一次 commit** 里顺手续租 + 存活自检
            （DD-001 §6 T03 ②：进度写与续租同一次 commit，零额外写）。

    Raises:
        JobAborted: 续租时 `rowcount == 0`，即本执行者已被回收/换人/删行。
            此时**不 commit**，由 `with job.session()` 回滚掉这次 media 进度写。
    """

    def __init__(
        self,
        db,
        media: Media,
        span: tuple[int, int],
        job: JobCtx | None = None,
    ) -> None:
        self._db = db
        self._media = media
        self._span = span
        self._job = job
        self._last = -1

    def __call__(self, percent: int) -> None:
        overall = _scale(percent, self._span)
        if overall - self._last < 2:      # 控制写库频率
            return
        self._last = overall
        self._media.progress = overall
        if self._job is not None:
            alive = jobs_service.touch(
                self._db, self._job.job_id, self._job.my_attempt, self._job.worker_id
            )
            if not alive:
                raise jobs_service.JobAborted(
                    f"{self._job.label()} 租约续期失败，停止执行"
                )
        self._db.commit()


def _set_stage(db, media: Media, status: str, progress: int) -> None:
    media.status = status
    media.progress = progress
    media.error = None
    db.commit()


@contextmanager
def _stage_session(ctx: JobCtx | None) -> Iterator:
    """stage 的会话：给了 `JobCtx` 就用它的（异常即回滚），否则自建一个。

    Notes:
        用 `JobCtx.session()` 的意义：`JobAborted` 抛出的那一刻，当前未提交的
        media 写会整体回滚 —— 这就是「老的执行者复活后写坏数据」的拦截点。
    """
    if ctx is None:
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()
        return
    with ctx.session() as db:
        yield db


def _ensure_audio(db, media: Media, job: JobCtx | None = None) -> Path:
    """确保标准音频存在（已存在则跳过转码，便于失败后从识别阶段重跑）。

    幂等性（重试安全）：`wav` 已存在且 `media.audio_path` 指向它 → 直接返回；
    否则 `ffmpeg -y` 覆盖写同一路径。
    """
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

    transcode_to_wav(
        src, dst, media.duration_ms, _Progress(db, media, PROGRESS_TRANSCODE, job=job)
    )
    media.audio_path = str(dst)
    media.progress = _scale(100, PROGRESS_TRANSCODE)
    db.commit()
    logger.info(
        "媒体 %s 转码完成：%s（%.1fs，%s）",
        media.id, media.title, media.duration_ms / 1000, info["type"],
    )
    return dst


def _persist_sentences(db, media_id: int, sentences) -> list[Sentence]:
    """重建句表（先清空旧句，再按序写入）。

    ⚠️ 已知影响（DD-001 §9 R5）：句子 id 会全部变化 → `attempts` / `notes` 的
    `ON DELETE CASCADE` 会连带删掉该媒体的听写记录与笔记。这是**现状既有行为**
    （`retranscribe` 一直如此），本阶段刻意不修（修它要按 `text_en` 迁移 id，
    属改业务逻辑）。调用方（`stage_asr`）在重试时会打 ERROR 日志提示影响面。
    """
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


def _sentences_of(db, media_id: int) -> list[Sentence]:
    """某媒体的句子，按 `idx` 升序。"""
    return (
        db.query(Sentence)
        .filter(Sentence.media_id == media_id)
        .order_by(Sentence.idx.asc())
        .all()
    )


def _count_attempts(db, media_id: int) -> int:
    """某媒体已有的听写记录条数（只用于「重试会删数据」的告警判断）。"""
    return int(
        db.query(Attempt.id)
        .join(Sentence, Sentence.id == Attempt.sentence_id)
        .filter(Sentence.media_id == media_id)
        .count()
    )


# --------------------------- 四个 stage ---------------------------


def stage_transcode(media_id: int, ctx: JobCtx | None = None) -> None:
    """CPU 池。转码 stage：把源文件转成 16kHz 单声道 wav。

    Args:
        media_id: 媒体 id。
        ctx: 执行上下文（同步兼容路径为 `None`）。

    Notes:
        **不在这里入队下一 stage**：链式推进统一由 `jobs_service.finish_ok()`
        在「jobs→done」的同一事务里做（否则两次提交之间崩溃 = 任务消失）。
    """
    if ctx is not None:
        ctx.check_alive()
    with _stage_session(ctx) as db:
        media = db.get(Media, media_id)
        if media is None:
            logger.warning("媒体 %s 不存在（已删除），转码 stage 跳过", media_id)
            return
        media.error = None
        db.commit()
        _ensure_audio(db, media, job=ctx)
        db.commit()


def stage_asr(media_id: int, ctx: JobCtx | None = None) -> None:
    """CPU 池。识别 stage：faster-whisper 转写并**重建**句表。

    Args:
        media_id: 媒体 id。
        ctx: 执行上下文。

    Raises:
        MediaError: 标准音频丢失 / 未识别到任何语音。
    """
    if ctx is not None:
        ctx.check_alive()
    with _stage_session(ctx) as db:
        media = db.get(Media, media_id)
        if media is None:
            logger.warning("媒体 %s 不存在（已删除），识别 stage 跳过", media_id)
            return

        audio = Path(media.audio_path or audio_wav_path(media_id))
        if not audio.is_file():
            raise MediaError("标准音频丢失，请执行「重新处理」")

        # ⚠️ R5 告警：本 stage 会重建句表 → 该媒体的听写记录/笔记会被 CASCADE 删除。
        # 现状既有行为，本阶段不修（见模块 docstring）。
        attempt_no = 0 if ctx is None else int(ctx.my_attempt)
        if attempt_no >= 2:
            lost = _count_attempts(db, media_id)
            if lost:
                logger.error(
                    "媒体 %s 的识别阶段正在重试（attempt=%d），重建句表将删除 %d 条"
                    "听写记录与相关笔记（已知影响，DD-001 §9 R5）",
                    media_id, attempt_no, lost,
                )

        _set_stage(db, media, STATUS_ASR, _scale(1, PROGRESS_ASR))

        # 延迟导入：未安装 ML 依赖时不影响转码/播放
        from app.services import asr as asr_service

        sentences, _info = asr_service.transcribe(
            audio,
            duration_ms=media.duration_ms,
            on_progress=_Progress(db, media, PROGRESS_ASR, job=ctx),
        )
        if not sentences:
            raise MediaError("未识别到任何语音内容，请确认音频中有英文人声")

        rows = _persist_sentences(db, media.id, sentences)
        media.progress = _scale(100, PROGRESS_ASR)
        db.commit()
        logger.info("媒体 %s 识别完成：%d 句", media.id, len(rows))


def stage_translate(media_id: int, ctx: JobCtx | None = None) -> None:
    """IO 池。翻译 stage：逐句在线翻译，只 UPDATE `text_zh`（幂等）。

    Args:
        media_id: 媒体 id。
        ctx: 执行上下文。

    Raises:
        MediaError: 没有可翻译的句子（除零防护）。

    Notes:
        **刻意不把句子扇出到 IO 池**：免费引擎按 IP 限流，按句并发会大面积 429；
        `translate_service` 的 `translations` 缓存 + `sleep_between()` 限流是刻意的
        串行设计。IO 池的价值是「不同媒体 / 不同 kind 之间并行」。
    """
    if ctx is not None:
        ctx.check_alive()
    with _stage_session(ctx) as db:
        media = db.get(Media, media_id)
        if media is None:
            logger.warning("媒体 %s 不存在（已删除），翻译 stage 跳过", media_id)
            return

        rows = _sentences_of(db, media_id)
        if not rows:                                        # all-zero 除零防护
            raise MediaError("没有可翻译的句子")

        from app.services import translate as translate_service

        _set_stage(db, media, STATUS_TRANSLATING, PROGRESS_TRANSLATE[0])
        total, failed = len(rows), 0
        for index, row in enumerate(rows):
            # ★ fencing 自检（每句一次，复用同一会话，很便宜）
            if ctx is not None:
                ctx.ensure_alive(db)
            result = translate_service.translate(row.text_en)
            if result["text"]:
                row.text_zh = result["text"]
            else:
                failed += 1
            if index < total - 1:
                translate_service.sleep_between()            # 保留 150ms 限流
            media.progress = _scale(int((index + 1) / total * 100), PROGRESS_TRANSLATE)
            if index % 5 == 0 or index == total - 1:
                db.commit()
        db.commit()
        if failed:
            logger.warning(
                "媒体 %s 有 %d/%d 句翻译失败（保留空译文待人工补）", media_id, failed, total
            )


def stage_clip(media_id: int, ctx: JobCtx | None = None) -> None:
    """CPU 池。切片 stage：逐句切音频并把媒体推进到 `done`。

    Args:
        media_id: 媒体 id。
        ctx: 执行上下文。

    Notes:
        幂等：先 `clear_clips()` 再逐句 `cut_clip_auto()`（覆盖写同一路径）。
        **`media → done` 在这里写**：它是链尾，且必须在 job 写 `done` 之前落库
        （worker 随后才在另一事务里把 job 置 done）。
    """
    if ctx is not None:
        ctx.check_alive()
    with _stage_session(ctx) as db:
        media = db.get(Media, media_id)
        if media is None:
            logger.warning("媒体 %s 不存在（已删除），切片 stage 跳过", media_id)
            return

        audio = Path(media.audio_path or audio_wav_path(media_id))
        if not audio.is_file():
            raise MediaError("标准音频丢失，请执行「重新处理」")

        rows = _sentences_of(db, media_id)
        if not rows:
            raise MediaError("没有可切片的句子")

        from app.services import clip as clip_service

        _set_stage(db, media, STATUS_CLIPPING, PROGRESS_CLIP[0])
        clip_service.clear_clips(media.id)
        total = len(rows)
        for index, row in enumerate(rows):
            if ctx is not None and index % 10 == 0:
                ctx.ensure_alive(db)
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


# --------------------------- 同步兼容包装（不经池） ---------------------------


def process_media(media_id: int) -> None:
    """同步跑完整链（转码 → 识别 → 翻译 → 切片），**不经池、不产出 job**。

    Args:
        media_id: 媒体 id。

    Notes:
        P3-2 起生产路径改由 `enqueue()` → `jobs` → worker 驱动。本函数只为
        「手工排错 / 老测试」保留：函数名与签名不能删（`__all__` 里有它）。
    """
    try:
        stage_transcode(media_id)
        stage_asr(media_id)
        stage_translate(media_id)
        stage_clip(media_id)
    except Exception as exc:  # noqa: BLE001  统一转成 failed 状态
        logger.exception("媒体 %s 处理失败", media_id)
        _mark_failed(media_id, str(exc))


def retranscribe_media(media_id: int) -> None:
    """同步重跑「识别 → 翻译 → 切片」（保留已转码音频），不经池。

    Args:
        media_id: 媒体 id。
    """
    try:
        stage_asr(media_id)
        stage_translate(media_id)
        stage_clip(media_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("媒体 %s 重新识别失败", media_id)
        _mark_failed(media_id, str(exc))


# --------------------------- 两条轴的失败写回 ---------------------------


def mark_terminal_failure(
    media_id: int,
    message: str,
    job_id: int | None = None,
    worker_id: str | None = None,
    attempts: int | None = None,
) -> None:
    """终态失败：**同一 Session 一次 commit** 里同时写 `media` 与 `jobs`。

    Args:
        media_id: 媒体 id。
        message: 失败原因（截断 500 字）。
        job_id: 可选；给了就同时把该 job 置 `failed`（DD-001 §4.2 第 5 行）。
        worker_id: job 的 fencing token 之一（**claim 时的快照值**）。
        attempts: job 的 fencing token 之一（**claim 时的快照值**）。

    Notes:
        * 两轴必须一起提交：只失败一边会让用户看到「进度条停在 60% 但任务已经
          没了」或者「任务说失败但界面还在转圈」，两种都无从排错。
        * **写 media 之前先做 job 轴的 fencing**：`force_failed()` 带
          `WHERE id=? AND attempts=? AND worker_id=?`，返回 `False` 说明本执行者
          已被回收（行现在是别人的）。此时**连 media 也不许动** —— 否则会出现
          「用户看到 failed，而新执行者还在跑，它随后写回又被 fence 丢掉」，
          两轴互相矛盾。这是 worker 侧 `_fence(job)` 修复的另一半：fence 只做在
          写回入口是不够的，**两条轴都要被同一张 fence 保护**。
        * `job_id is None`（老同步路径 `_mark_failed(media_id, "…")`）不做 fencing，
          直接写 media 轴。
    """
    db = SessionLocal()
    try:
        if job_id is not None:
            fenced_ok = jobs_service.force_failed(
                db,
                int(job_id),
                message,
                worker_id=worker_id,
                attempts=attempts,
            )
            if not fenced_ok:
                db.rollback()
                logger.warning(
                    "media %s 的终态失败写回被 fencing 拒绝（job=%s worker=%s attempt=%s），"
                    "media 轴一并放弃（本执行者已被回收）",
                    media_id, job_id, worker_id, attempts,
                )
                return
        media = db.get(Media, media_id)
        if media is not None:
            media.status = STATUS_FAILED
            media.progress = 0
            media.error = (message or "处理失败")[:500]
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.exception("写入失败状态出错: media=%s job=%s", media_id, job_id)
    finally:
        db.close()


def _mark_failed(media_id: int, message: str, job: Job | None = None) -> None:
    """把媒体置为 `failed`（可选同时把 job 置 failed，同一事务）。

    Args:
        media_id: 媒体 id。
        message: 失败原因。
        job: 可选 `Job`（终态失败时传，实现「两轴一起失败」）。
    """
    mark_terminal_failure(
        media_id,
        message,
        job_id=getattr(job, "id", None),
        worker_id=getattr(job, "worker_id", None),
        attempts=getattr(job, "attempts", None),
    )


# --------------------------- 入队 / 重启自愈 ---------------------------


def enqueue(media_id: int) -> None:
    """把媒体加入处理队列（完整流程）。

    Args:
        media_id: 媒体 id。

    Notes:
        入队只是插一条 `pending` job，**不触发任何执行**；执行权由 worker 的
        原子 claim 取得。重复入队因 `uq_jobs_active` 天然 no-op。
    """
    jobs_service.enqueue(jobs_service.KIND_TRANSCODE, media_id)


def enqueue_retranscribe(media_id: int) -> None:
    """把「重新识别」任务加入队列（从 `asr` 阶段开始）。

    Args:
        media_id: 媒体 id。
    """
    jobs_service.enqueue(jobs_service.KIND_ASR, media_id)


def _has_active_job(db, media_id: int) -> bool:
    """该媒体是否已有活跃 job（`pending` / `running`）。

    Args:
        db: 会话（复用调用方的那一个，不另开连接）。
        media_id: 媒体 id。

    Returns:
        `True` = 队列里已经有一条会处理该媒体的任务。

    Notes:
        口径与 `jobs.purge_for_media()` 一致：**`kind LIKE 'media_%'`** + `ref_id`。
        刻意不用 `Job.kind.in_(MEDIA_KINDS)`：将来若有新的 media 子 kind 只加进
        `MEDIA_KINDS` 而忘了改这里，`requeue_unfinished()` 就会重新踩上
        「与运行中 worker 重叠」的坑。前缀匹配与「删媒体时按前缀清理」是同一把尺子。
    """
    return (
        db.query(Job.id)
        .filter(
            Job.kind.like("media_%"),
            Job.ref_id == int(media_id),
            Job.status.in_(jobs_service.ACTIVE_STATUSES),
        )
        .first()
        is not None
    )


def requeue_unfinished() -> int:
    """服务启动时把上次未完成的任务重新排队（异常退出后的自愈）。

    Returns:
        **实际重新入队**的媒体条数（因已有活跃 job 而跳过的不计）。

    Notes:
        P4 挂账 A3/A2 的修法（行为已按裁决调整，签名与 `enqueue()` 调用方式不变）：

        * **已有活跃 job 就跳过** —— 不改 `media.status`、不入队。
          为什么必须跳：P3-2 之后 worker 能活过 web 重启，「web 重启 ⇒ 执行线程
          随之消失」这个旧前提**不再成立**。此刻若照旧把 `media.status` 重置成
          `pending` 并额外入队一条 `media_transcode`（跨 kind 不撞
          `uq_jobs_active`），用户会看到进度条跳回 0，而 worker 手上那条
          `media_asr` 还在跑。旧实现在代码注释里记为「可自愈、不丢数据」，但那
          只是因为它恰好幂等，不代表它是对的。
        * 返回「**实际入队**条数」而不是「扫到的未完成条数」：调用方（`main.py`
          的 lifespan）与运维脚本都把它当日志计数用，把跳过算进来会让「重启恢复
          了 N 个任务」变成假话。
        * `enqueue()` 仍是唯一入队入口（`uq_jobs_active` 的幂等语义由它保证）。
    """
    db = SessionLocal()
    try:
        rows = db.query(Media).filter(Media.status.in_(UNFINISHED_STATUSES)).all()
        requeued_ids: list[int] = []
        skipped = 0
        for media in rows:
            if _has_active_job(db, media.id):
                # 跳过：worker 可能正在跑这条媒体，重置进度只会让 UI 回退
                skipped += 1
                continue
            media.status = STATUS_PENDING
            media.progress = 0
            requeued_ids.append(media.id)
        db.commit()
    finally:
        db.close()

    for media_id in requeued_ids:
        enqueue(media_id)
    if requeued_ids:
        logger.info("重启恢复：重新排队 %d 个未完成的媒体任务", len(requeued_ids))
    if skipped:
        logger.info(
            "重启恢复：跳过 %d 个已有活跃任务的媒体（worker 仍在跑，不重置进度）", skipped
        )
    return len(requeued_ids)


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

"""句子级音频切片（FR-A1 / §7.5）。

- 按每句 `start_ms / end_ms` 用 ffmpeg 裁剪出独立音频，落到
  `data/media/library/<id>/clips/<idx>.<ext>`；
- 学习页「播放本句 / 单句循环」直接加载切片，避免长音频拖动误差；
- 首尾各留 `clip_padding_ms` 空白，防止把首尾音切掉；
- 输出优先 mp3（体积小），若当前 ffmpeg 不支持 mp3 编码则自动回退 wav。
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path

from app.core.config import settings
from app.core.paths import MediaError, clips_dir
from app.core.tools import ffmpeg_path

logger = logging.getLogger(__name__)


def clip_path(media_id: int, idx: int, ext: str | None = None) -> Path:
    """切片文件路径；`ext` 缺省用配置的输出格式。"""
    suffix = (ext or settings.clip_format).lstrip(".")
    return clips_dir(media_id) / f"{idx}.{suffix}"


def _run_ffmpeg(cmd: list[str]) -> str:
    """执行 ffmpeg，返回 stderr 文本；非 0 退出抛 MediaError。"""
    err_file = tempfile.TemporaryFile()
    try:
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=err_file,
            )
        except OSError as exc:
            raise MediaError(f"无法启动 ffmpeg：{exc}") from exc
        proc.wait()
        err_file.seek(0)
        message = err_file.read().decode("utf-8", "replace").strip()
    finally:
        err_file.close()

    if proc.returncode != 0:
        raise MediaError(message[-300:] or "ffmpeg 切片异常退出")
    return message


def cut_clip(
    src: Path,
    dst: Path,
    start_ms: int,
    end_ms: int,
    pad_ms: int | None = None,
) -> None:
    """把 `src` 的 [start_ms, end_ms] 区间裁成 `dst`。"""
    exe = ffmpeg_path()
    if not exe:
        raise MediaError("未找到 ffmpeg，无法生成音频切片")

    pad = settings.clip_padding_ms if pad_ms is None else pad_ms
    begin = max(0.0, (start_ms - pad) / 1000)
    span = max(0.05, (end_ms - start_ms + pad * 2) / 1000)

    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        exe, "-y", "-hide_banner", "-loglevel", "error", "-nostdin",
        # 输入侧 seek：wav 无关键帧，定位精确且更快
        "-ss", f"{begin:.3f}",
        "-t", f"{span:.3f}",
        "-i", str(src),
        "-vn",
        "-ac", "1",
        "-ar", str(settings.transcode_sample_rate),
    ]
    suffix = dst.suffix.lower().lstrip(".")
    if suffix in ("mp3", "aac", "m4a", "opus", "ogg"):
        cmd += ["-c:a", {"mp3": "libmp3lame", "m4a": "aac"}.get(suffix, suffix),
                "-b:a", settings.clip_bitrate]
    else:
        cmd += ["-c:a", "pcm_s16le"]
    cmd.append(str(dst))

    _run_ffmpeg(cmd)

    if not dst.is_file() or dst.stat().st_size == 0:
        raise MediaError("切片结果为空，源音频可能损坏")


def cut_clip_auto(src: Path, media_id: int, idx: int,
                  start_ms: int, end_ms: int) -> Path:
    """裁剪切片，mp3 编码不可用时自动回退为 wav。"""
    preferred = clip_path(media_id, idx)
    try:
        cut_clip(src, preferred, start_ms, end_ms)
        return preferred
    except MediaError as exc:
        if preferred.suffix.lower() != ".mp3":
            raise
        logger.warning("mp3 切片失败，回退 wav：%s", exc)
        fallback = clip_path(media_id, idx, "wav")
        cut_clip(src, fallback, start_ms, end_ms)
        return fallback


def clear_clips(media_id: int) -> None:
    """删除某媒体的全部切片（重建前先清理）。"""
    directory = clips_dir(media_id)
    if not directory.is_dir():
        return
    for item in directory.iterdir():
        if item.is_file():
            item.unlink(missing_ok=True)

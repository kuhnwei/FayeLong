"""媒体路径约定与错误基类。

单独成模块是为了让 `services/asr.py`、`services/clip.py`、`services/media.py`
三者都能引用，而不产生循环依赖。
"""

from __future__ import annotations

from pathlib import Path

from app.core.config import INBOX_DIR, LIBRARY_DIR


class MediaError(RuntimeError):
    """媒体处理相关的可预期错误（对外展示中文原因）。"""


def media_dir(media_id: int) -> Path:
    """某个媒体的私有目录：library/<id>/ 。"""
    return LIBRARY_DIR / str(media_id)


def audio_wav_path(media_id: int) -> Path:
    """标准化音频（16kHz 单声道 wav）。"""
    return media_dir(media_id) / "audio.wav"


def original_path(media_id: int, ext: str) -> Path:
    """媒体库内的原始文件路径。"""
    return media_dir(media_id) / f"original{ext.lower()}"


def clips_dir(media_id: int) -> Path:
    """句子音频切片目录。"""
    return media_dir(media_id) / "clips"


__all__ = [
    "MediaError",
    "INBOX_DIR",
    "media_dir",
    "audio_wav_path",
    "original_path",
    "clips_dir",
]

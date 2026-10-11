"""外部可执行文件（ffmpeg / ffprobe）路径解析。

优先使用随包分发的便携版二进制，找不到再回退到系统 PATH。
这样在没有开发环境、也没装 ffmpeg 的笔记本上也能直接工作。
"""

import os
import shutil
from functools import lru_cache
from pathlib import Path

from app.core.config import BASE_DIR, ROOT_DIR


def _candidate_dirs() -> list[Path]:
    dirs: list[Path] = []
    env_dir = os.environ.get("FAYELONG_FFMPEG_DIR")
    if env_dir:
        dirs.append(Path(env_dir))
    dirs.extend(
        [
            ROOT_DIR / "tools" / "ffmpeg",   # 开发环境：项目内自带
            BASE_DIR / "tools" / "ffmpeg",
            ROOT_DIR / "runtime" / "ffmpeg",  # 打包环境：运行时目录
            ROOT_DIR / "ffmpeg",
            Path(__file__).resolve().parent.parent / "bin",
        ]
    )
    return dirs


@lru_cache(maxsize=None)
def resolve_tool(name: str) -> str | None:
    """返回 ffmpeg/ffprobe 的可执行文件绝对路径，找不到返回 None。"""
    exe_name = f"{name}.exe" if os.name == "nt" else name
    for directory in _candidate_dirs():
        candidate = directory / exe_name
        if candidate.is_file():
            return str(candidate)
    return shutil.which(name)


def ffmpeg_path() -> str | None:
    return resolve_tool("ffmpeg")


def ffprobe_path() -> str | None:
    return resolve_tool("ffprobe")


def has_ffmpeg() -> bool:
    return ffmpeg_path() is not None

"""首次运行引导：按需下载大体积学习资源（语音识别模型 / 离线词典）。

「轻量交付包」不带 `data/models/`（约 460MB）与 `data/dict/`（约 810MB），
首次启动时由本脚本从国内镜像拉取；「全量包」已内置，本脚本会自动跳过。

可单独执行（排错 / 手动补资源）::

    runtime\\python\\python.exe scripts\\bootstrap.py            # 缺什么下什么
    runtime\\python\\python.exe scripts\\bootstrap.py --model    # 只下模型
    runtime\\python\\python.exe scripts\\bootstrap.py --dict     # 只下词库
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent        # <解压目录>/scripts
ROOT = HERE.parent                            # <解压目录>
for _path in (str(ROOT), str(HERE)):
    if _path not in sys.path:
        sys.path.insert(0, _path)


def _utf8_console() -> None:
    """重定向到管道 / 文件时改用 UTF-8；真实控制台交给 Python 默认处理。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream.isatty():
                continue
        except (AttributeError, ValueError):
            pass
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError, OSError):
            pass


def model_ready() -> bool:
    from app.core.config import whisper_model_dir

    return (whisper_model_dir() / "model.bin").is_file()


def dict_ready() -> bool:
    from app.services.dict import available

    return available()


def download_model() -> bool:
    """下载 faster-whisper small 模型（镜像 + 断点续传）。"""
    from app.core.config import whisper_model_dir
    from app.services import asr as asr_service
    from app.services.asr import AsrError

    target = whisper_model_dir()
    print(f"[模型] 目标目录：{target}")
    state = {"last": -10, "start": time.time()}

    def on_progress(percent: int) -> None:
        if percent - state["last"] < 2 and percent != 100:
            return
        state["last"] = percent
        filled = int(percent / 100 * 28)
        bar = "█" * filled + "·" * (28 - filled)
        elapsed = time.time() - state["start"]
        speed = ""
        if elapsed > 1:
            speed = f"  已用 {elapsed:.0f}s"
        print(f"\r  [{bar}] {percent:3d}%{speed}", end="", flush=True)

    try:
        asr_service.download_model(on_progress=on_progress)
    except (AsrError, OSError) as exc:
        print(f"\n[模型] 下载失败：{exc}")
        return False
    print()
    print("[模型] 完成 ✓")
    return True


def download_dict() -> bool:
    """下载并安装 ECDICT 词库（多镜像回退 + 断点续传）。"""
    print("[词典] 开始下载 ECDICT 词库（约 810MB，视网速需数分钟）")
    try:
        import fetch_dict
    except ImportError as exc:
        print(f"[词典] 找不到安装脚本 fetch_dict.py：{exc}")
        return False
    # fetch_dict.install 内部已有镜像回退 / 断点续传 / 进度显示
    return fetch_dict.install(force=False) == 0


def bootstrap(need_model: bool = True, need_dict: bool = True) -> bool:
    """下载缺失的资源；返回是否全部就绪。"""
    _utf8_console()
    ok = True

    if need_model and not model_ready():
        ok = download_model() and ok
    elif need_model:
        print("[模型] 已就绪，跳过")

    if need_dict and not dict_ready():
        print()
        ok = download_dict() and ok
    elif need_dict:
        print("[词典] 已就绪，跳过")

    print()
    if ok:
        print("学习资源已就绪，可以开始使用。")
    else:
        print("部分资源未就绪：仍可正常启动网站，播放与播放器可用；")
        print("语音识别 / 查词会在资源补齐后生效（重新运行本脚本即可）。")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="下载 FayeLong 所需的学习资源")
    parser.add_argument("--model", action="store_true", help="只下载语音识别模型")
    parser.add_argument("--dict", action="store_true", help="只下载离线词典")
    args = parser.parse_args()

    need_model = args.model or not (args.model or args.dict)
    need_dict = args.dict or not (args.model or args.dict)
    return 0 if bootstrap(need_model=need_model, need_dict=need_dict) else 1


if __name__ == "__main__":
    sys.exit(main())

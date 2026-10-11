"""把目录打包成 zip（UTF-8 文件名 + 进度显示）。

为什么不用 `tar.exe -a -c -f x.zip`：Windows 自带的 bsdtar 会把中文文件名按
**本机 ANSI 代码页（GBK）** 写进 zip，且不设置「UTF-8 文件名」标志位（bit 11）。
结果是在中文 Windows 上用资源管理器解压看着正常，但用 7-Zip / macOS / Linux /
非中文 Windows 解压就会变成乱码。

Python 的 `zipfile` 会把非 ASCII 名按 UTF-8 写入并置上 bit 11，
各大解压工具都认这个标准，跨平台一致。

用法::

    python zipdir.py <源目录> <输出zip> [--root FayeLong]
"""

from __future__ import annotations

import argparse
import sys
import time
import zipfile
from pathlib import Path


def _fmt(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024 or unit == "GB":
            return f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} GB"


def build_zip(source: Path, target: Path, arc_root: str | None = None) -> int:
    if not source.is_dir():
        print(f"[XX] 源目录不存在：{source}")
        return 1

    arc_root = arc_root or source.name
    files = sorted(p for p in source.rglob("*") if p.is_file())
    if not files:
        print(f"[XX] 源目录为空：{source}")
        return 1

    total = sum(p.stat().st_size for p in files)
    print(f"  · 待压缩 {len(files)} 个文件，共 {_fmt(total)}")
    print(f"  · 输出 {target}")

    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()

    done = 0
    started = time.time()
    last_tick = 0.0

    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in files:
            rel = path.relative_to(source).as_posix()
            archive.write(path, f"{arc_root}/{rel}")
            done += path.stat().st_size

            now = time.time()
            if now - last_tick >= 1.0 or done >= total:
                last_tick = now
                pct = done / total * 100 if total else 100
                elapsed = now - started
                speed = done / elapsed if elapsed > 0 else 0
                bar = "█" * int(pct / 100 * 24)
                print(
                    f"\r  [{bar:<24}] {pct:5.1f}%  {_fmt(done)} / {_fmt(total)}"
                    f"  {_fmt(speed)}/s  {elapsed:.0f}s",
                    end="",
                    flush=True,
                )
    print()
    size = target.stat().st_size
    ratio = size / total * 100 if total else 0
    print(f"  [OK] 完成：{target.name}（{_fmt(size)}，压缩率 {ratio:.0f}%，"
          f"耗时 {time.time() - started:.0f}s）")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="UTF-8 文件名安全的 zip 打包")
    parser.add_argument("source", help="源目录")
    parser.add_argument("target", help="输出 zip 路径")
    parser.add_argument("--root", default=None, help="zip 内的顶层目录名（默认取源目录名）")
    args = parser.parse_args()
    return build_zip(Path(args.source), Path(args.target), args.root)


if __name__ == "__main__":
    sys.exit(main())

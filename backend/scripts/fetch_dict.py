"""下载并安装 ECDICT 词库（M4 / FR-S6）。

ECDICT（https://github.com/skywind3000/ECDICT）是免费开源的英汉词典数据库，
本项目的「单词查词」完全依赖它离线工作，不调用任何付费接口。

安装结果：`data/dict/ecdict.db`（SQLite，28 万词条），并写入
`data/dict/ecdict.meta.json` 记录来源与安装信息。

用法（在 backend 目录下）：
    .venv\\Scripts\\python.exe scripts\\fetch_dict.py          # 已安装则跳过
    .venv\\Scripts\\python.exe scripts\\fetch_dict.py --force   # 强制重新下载
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import DICT_DIR  # noqa: E402

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

ZIP_NAME = "ecdict-sqlite-28.zip"
DB_NAME = "ecdict.db"
META_NAME = "ecdict.meta.json"
RELEASE_PATH = "skywind3000/ECDICT/releases/download/1.0.28/{zip_name}"

# 下载源：优先官方 GitHub，失败自动换公共加速镜像
SOURCES = [
    f"https://github.com/{RELEASE_PATH}",
    f"https://ghfast.top/https://github.com/{RELEASE_PATH}",
    f"https://ghproxy.net/https://github.com/{RELEASE_PATH}",
    f"https://gh.llkk.cc/https://github.com/{RELEASE_PATH}",
]


def _format_size(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024 or unit == "GB":
            return f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} GB"


def _download(url: str, target: Path) -> int:
    """流式下载（带进度与断点续传），返回最终字节数。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    start = partial.stat().st_size if partial.is_file() else 0

    headers = {"User-Agent": UA}
    if start:
        headers["Range"] = f"bytes={start}-"

    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as resp:
        if start and resp.status != 206:      # 服务端不支持续传则重下
            start = 0
        total = int(resp.headers.get("Content-Length") or 0) + start
        mode = "ab" if start else "wb"
        done = start
        last = 0.0
        with partial.open(mode) as out:
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                now = time.time()
                if now - last > 0.4:           # 控制刷新频率
                    last = now
                    if total:
                        pct = done / total * 100
                        print(
                            f"\r  下载中 {pct:5.1f}%  "
                            f"{_format_size(done)} / {_format_size(total)}",
                            end="",
                            flush=True,
                        )
                    else:
                        print(f"\r  下载中 {_format_size(done)}", end="", flush=True)
    if total:
        print()
    partial.replace(target)
    return target.stat().st_size


def _extract_db(zip_path: Path, destination: Path) -> Path:
    """从压缩包中取出词库 db，安装为 destination。"""
    with zipfile.ZipFile(zip_path) as archive:
        members = [
            name for name in archive.namelist()
            if name.lower().endswith(".db") and not name.startswith("__MACOSX")
        ]
        if not members:
            raise RuntimeError(f"压缩包 {zip_path.name} 中没有找到 .db 词库文件")
        # 优先取体积最大的那个（真正的词库）
        members.sort(key=lambda name: archive.getinfo(name).file_size, reverse=True)
        chosen = members[0]
        print(f"  解压词库：{chosen}（{_format_size(archive.getinfo(chosen).file_size)}）")
        tmp = destination.with_suffix(".db.tmp")
        with archive.open(chosen) as src, tmp.open("wb") as out:
            shutil.copyfileobj(src, out, 1024 * 1024)
    tmp.replace(destination)
    return destination


def _count_entries(db_path: Path) -> int:
    """统计词条数（用于自检展示）。"""
    import sqlite3
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            return int(conn.execute("SELECT COUNT(*) FROM stardict").fetchone()[0])
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        print(f"  （统计词条数失败：{exc}）")
        return 0


def install(force: bool = False) -> int:
    DICT_DIR.mkdir(parents=True, exist_ok=True)
    db_path = DICT_DIR / DB_NAME
    tmp_dir = DICT_DIR / "tmp"
    zip_path = tmp_dir / ZIP_NAME

    if db_path.is_file() and not force:
        print(f"词库已安装：{db_path}（{_format_size(db_path.stat().st_size)}）")
        print("如需重新下载，请加 --force")
        return 0

    # 1) 下载（复用已存在的完整压缩包）
    if not (zip_path.is_file() and zip_path.stat().st_size > 1_000_000):
        errors: list[str] = []
        for url in SOURCES:
            print(f"尝试下载源：{url}")
            try:
                size = _download(url, zip_path)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                print(f"  失败：{exc}")
                errors.append(f"{url} -> {exc}")
                continue
            print(f"  完成：{zip_path.name}（{_format_size(size)}）")
            break
        else:
            print("全部下载源均失败：")
            for line in errors:
                print(f"  - {line}")
            return 1
    else:
        print(f"复用已下载的压缩包：{zip_path}（{_format_size(zip_path.stat().st_size)}）")

    # 2) 解压安装
    print("安装词库 …")
    try:
        _extract_db(zip_path, db_path)
    except (zipfile.BadZipFile, RuntimeError, OSError) as exc:
        print(f"安装失败：{exc}")
        return 1

    entries = _count_entries(db_path)
    meta = {
        "source": SOURCES[0],
        "release": "1.0.28",
        "file": DB_NAME,
        "entries": entries,
        "size_bytes": db_path.stat().st_size,
        "installed_at": datetime.now().isoformat(timespec="seconds"),
    }
    (DICT_DIR / META_NAME).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 3) 清理临时压缩包（保留目录以免重复下载逻辑复杂）
    zip_path.unlink(missing_ok=True)
    try:
        tmp_dir.rmdir()
    except OSError:
        pass

    print(f"完成：{db_path}")
    print(f"  词条数：{entries}，体积：{_format_size(meta['size_bytes'])}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="下载并安装 ECDICT 词库")
    parser.add_argument("--force", action="store_true", help="已安装也重新下载")
    args = parser.parse_args()
    return install(force=args.force)


if __name__ == "__main__":
    raise SystemExit(main())

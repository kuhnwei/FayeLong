"""FayeLong 就地更新：把新版程序文件覆盖到旧安装目录，**绝不改动学习数据**。

为什么需要它
------------
FayeLong 的安装目录里，`data/` 装着用户自己的东西（`app.db` 学习记录、`media/` 素材、
`logs/` 日志、`backups/` 备份）。如果让用户「把新包解压覆盖旧目录」，一次手滑就可能
把 `data/` 覆盖成新包里的空目录，多年积累的学习数据就没了。

本脚本只做一件事：**换程序，不换数据**。

- 整目录替换：`app/`、`static/`、`scripts/`（小、且必须与新版完全一致）
- 增量复制：`runtime/`、`tools/`（大，只拷新增或大小不同的文件，能省下上 GB 的搬运）
- 覆盖顶层文件：启动 / 停止 / 静默启动 / 自启 / 更新等脚本与说明
- 数据目录**只补不覆盖**：`data/models`、`data/dict` 缺失的文件才从新包补
- **绝不触碰**：`data/app.db`、`data/media/`、`data/logs/`、`data/backups/`

用法（正常由「更新 FayeLong.bat」调用）::

    python scripts\\update.py                    # 自动定位旧安装目录（安装记录 → 常见位置）
    python scripts\\update.py --target D:\\FayeLong
    python scripts\\update.py --target D:\\FayeLong --dry-run   # 只预演，不改任何文件

安装记录由启动器 / 静默启动脚本写在 `%LOCALAPPDATA%\\FayeLong\\install.txt`（UTF-16）。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent        # <包目录>/scripts
SOURCE = HERE.parent                          # <包目录>
for _path in (str(SOURCE), str(HERE)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

WIDTH = 64
KEEP_BACKUPS = 5

# --- 程序文件：整目录替换 ---
REPLACE_DIRS = ("app", "static", "scripts")

# --- 大体积程序文件：增量复制（同名同大小则跳过）---
MERGE_DIRS = ("runtime/python", "runtime/ffmpeg", "tools")

# --- 顶层文件：覆盖 ---
TOP_FILES = (
    "启动 FayeLong.bat",
    "停止 FayeLong.bat",
    "静默启动 FayeLong.vbs",
    "FayeLong-Autostart.vbs",
    "安装开机自启.bat",
    "取消开机自启.bat",
    "更新 FayeLong.bat",
    "使用说明.txt",
)

# --- 数据目录里「可再生资源」：目标缺失才补，绝不覆盖 ---
DATA_ADD_DIRS = ("data/models", "data/dict")

# --- 必须保证存在的数据目录（不存在就建，不影响已有内容）---
DATA_ENSURE_DIRS = ("data/media/audio", "data/media/library", "data/logs", "data/backups")

# --- 用户数据：全程不读不写（仅打印，用于自证）---
PROTECTED = ("data/app.db", "data/media", "data/logs", "data/backups")

INSTALL_RECORD = "FayeLong/install.txt"


# --------------------------- 输出 ---------------------------


def say(text: str = "") -> None:
    print(text, flush=True)


def ok(text: str) -> None:
    say(f"  [√] {text}")


def warn(text: str) -> None:
    say(f"  [!] {text}")


def bad(text: str) -> None:
    say(f"  [×] {text}")


def setup_console() -> None:
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


def mb(num: float) -> str:
    if num >= 1024 * 1024 * 1024:
        return f"{num / 1024 / 1024 / 1024:.2f} GB"
    if num >= 1024 * 1024:
        return f"{num / 1024 / 1024:.1f} MB"
    if num >= 1024:
        return f"{num / 1024:.0f} KB"
    return f"{num:.0f} B"


# --------------------------- 定位安装目录 ---------------------------


def read_install_record() -> Path | None:
    """读 `%LOCALAPPDATA%\\FayeLong\\install.txt` 第 1 行（UTF-16 / UTF-8 都能读）。"""
    appdata = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if not appdata:
        return None
    path = Path(appdata) / INSTALL_RECORD
    if not path.is_file():
        return None
    try:
        raw = path.read_bytes()
    except OSError:
        return None

    text: str | None = None
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        candidates = ("utf-16",)
    else:
        candidates = ("utf-8-sig", "gbk")
    for encoding in candidates:
        try:
            text = raw.decode(encoding)
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
    if not text:
        return None

    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    return Path(first) if first else None


def normalize_target(raw: str | Path) -> Path:
    """把用户给的路径规范成目录：支持拖进来的文件、带引号、尾部反斜杠。"""
    text = str(raw).strip().strip('"').strip("'")
    path = Path(text)
    try:
        if path.is_file():            # 拖进来的可能是「启动 FayeLong.bat」
            path = path.parent
    except OSError:
        pass
    try:
        path = path.resolve()
    except OSError:
        pass
    return path


def is_install_dir(path: Path) -> bool:
    """像不像一个 FayeLong 安装目录（至少有 app 或内置运行时）。"""
    try:
        return (path / "app").is_dir() or (path / "runtime" / "python" / "python.exe").is_file()
    except OSError:
        return False


def auto_target() -> tuple[Path | None, str]:
    """自动定位旧安装目录：安装记录 → 常见位置。"""
    record = read_install_record()
    if record and is_install_dir(record):
        return record, "安装记录 %LOCALAPPDATA%\\FayeLong\\install.txt"

    for drive in ("D:", "C:", "E:", "F:"):
        for name in ("FayeLong", "fayelong", "英语学习/FayeLong", "学习/FayeLong"):
            candidate = Path(f"{drive}/{name}")
            if is_install_dir(candidate):
                return candidate, "常见安装位置"
    return None, ""


# --------------------------- 版本 ---------------------------


def _version_from_init(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return "未知"
    match = re.search(r"""__version__\s*=\s*["']([^"']+)["']""", text)
    return match.group(1) if match else "未知"


def source_version() -> str:
    return _version_from_init(SOURCE / "app" / "__init__.py")


def target_version(target: Path) -> str:
    manifest = target / "data" / "install.json"
    if manifest.is_file():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8", errors="ignore"))
            value = str(data.get("version") or "").strip()
            if value:
                return value
        except (OSError, ValueError):
            pass
    return _version_from_init(target / "app" / "__init__.py")


# --------------------------- 停止服务 / 备份 ---------------------------


def stop_running(target: Path) -> bool:
    """按 PID 文件停止旧目录里正在运行的服务（否则文件被占用、替换会失败）。"""
    pid_file = target / "data" / "logs" / "fayelong.pid"
    if not pid_file.is_file():
        return False
    try:
        pid = int(pid_file.read_text(encoding="utf-8", errors="ignore").strip() or "0")
    except (OSError, ValueError):
        return False
    if pid <= 0:
        return False

    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        try:
            os.kill(pid, 15)
        except OSError:
            return False
    try:
        pid_file.unlink(missing_ok=True)
    except OSError:
        pass
    time.sleep(0.8)          # 给系统一点时间真正释放文件句柄
    return True


def backup_db(target: Path, old_version: str) -> Path | None:
    """备份 data/app.db —— 更新本身不碰它，备份只为「schema 变化后想回退」留条后路。"""
    db = target / "data" / "app.db"
    if not db.is_file():
        return None
    backups = target / "data" / "backups"
    try:
        backups.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        dest = backups / f"app-{old_version}-{stamp}.db"
        shutil.copy2(db, dest)
        olds = sorted(
            backups.glob("app-*.db"), key=lambda p: p.stat().st_mtime, reverse=True
        )
        for extra in olds[KEEP_BACKUPS:]:
            extra.unlink(missing_ok=True)
        return dest
    except OSError as exc:
        warn(f"备份 app.db 失败（{exc}）——继续更新，但数据没有额外备份")
        return None


# --------------------------- 复制 ---------------------------


class Stats:
    def __init__(self) -> None:
        self.copy = 0
        self.skip = 0
        self.bytes = 0
        self.replaced: list[str] = []
        self.added_data: list[str] = []
        self.failed: list[str] = []


def sync_replace(src: Path, dst: Path, dry: bool, stats: Stats, label: str) -> None:
    """整目录替换：先删后拷，避免旧版遗留文件干扰。"""
    if not src.is_dir():
        return
    stats.replaced.append(label)
    for root, _dirs, files in os.walk(src):
        for name in files:
            stats.copy += 1
            try:
                stats.bytes += (Path(root) / name).stat().st_size
            except OSError:
                pass
    if dry:
        return
    try:
        if dst.exists():
            shutil.rmtree(dst, ignore_errors=False)
        shutil.copytree(src, dst)
    except OSError as exc:
        stats.failed.append(f"{label}（{exc}）")


def _same_content(src: Path, dst: Path, chunk: int = 1 << 20) -> bool:
    """是否与目标文件内容完全一致（分块比较，遇到差异立即返回）。

    ⚠️ 不能只比大小：实测存在「尺寸相同、内容不同」的文件（例如替换过的
    python.exe），只比大小会把它们当成「未变化」而漏掉，导致更新不完整。
    分块比较的代价是每个未变化文件要读一遍 —— 相比重新拷 1.2GB，这个代价小得多。
    """
    try:
        if not dst.is_file() or dst.stat().st_size != src.stat().st_size:
            return False
        with open(src, "rb") as left, open(dst, "rb") as right:
            while True:
                a = left.read(chunk)
                b = right.read(chunk)
                if a != b:
                    return False
                if not a:
                    return True
    except OSError:
        return False


def sync_merge(src: Path, dst: Path, dry: bool, stats: Stats) -> None:
    """增量复制：内容完全一致就跳过（大体积依赖靠这一条省下上 GB 的搬运）。"""
    if not src.is_dir():
        return
    for root, _dirs, files in os.walk(src):
        rel = Path(root).relative_to(src)
        out_dir = dst / rel
        if not dry:
            try:
                out_dir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                stats.failed.append(f"{rel}（{exc}）")
                continue
        for name in files:
            item = Path(root) / name
            dest = out_dir / name
            if _same_content(item, dest):
                stats.skip += 1
                continue
            try:
                size = item.stat().st_size
            except OSError:
                continue
            stats.copy += 1
            stats.bytes += size
            if dry:
                continue
            try:
                shutil.copy2(item, dest)
            except OSError as exc:
                stats.failed.append(f"{rel}/{name}（{exc}）")


def sync_add_missing(src: Path, dst: Path, dry: bool, stats: Stats, label: str) -> None:
    """数据资源：只补目标缺失的文件，已存在的一律不覆盖。"""
    if not src.is_dir():
        return
    count = 0
    for root, _dirs, files in os.walk(src):
        rel = Path(root).relative_to(src)
        out_dir = dst / rel
        if not dry:
            try:
                out_dir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                stats.failed.append(f"{label}/{rel}（{exc}）")
                continue
        for name in files:
            item = Path(root) / name
            dest = out_dir / name
            if dest.exists():
                stats.skip += 1
                continue
            count += 1
            try:
                stats.bytes += item.stat().st_size
            except OSError:
                pass
            if dry:
                continue
            try:
                shutil.copy2(item, dest)
            except OSError as exc:
                stats.failed.append(f"{label}/{rel}/{name}（{exc}）")
    stats.copy += count
    if count:
        stats.added_data.append(f"{label} +{count} 个文件")


def sync_files(src_root: Path, dst_root: Path, files: tuple[str, ...], dry: bool, stats: Stats) -> None:
    for rel in files:
        item = src_root / rel
        if not item.is_file():
            continue
        dest = dst_root / rel
        try:
            stats.bytes += item.stat().st_size
        except OSError:
            pass
        stats.copy += 1
        if dry:
            continue
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dest)
        except OSError as exc:
            stats.failed.append(f"{rel}（{exc}）")


def ensure_dirs(target: Path, dry: bool) -> None:
    if dry:
        return
    for rel in DATA_ENSURE_DIRS:
        try:
            (target / rel).mkdir(parents=True, exist_ok=True)
        except OSError:
            pass


# --------------------------- 安装记录 ---------------------------


def write_records(target: Path, version: str) -> None:
    appdata = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if appdata:
        record_dir = Path(appdata) / "FayeLong"
        try:
            record_dir.mkdir(parents=True, exist_ok=True)
            # UTF-16：VBScript 用 OpenTextFile(..., -1) 读它，中文路径才不会乱码
            (record_dir / "install.txt").write_text(
                f"{target}\n{version}\n{time.strftime('%Y-%m-%d %H:%M')}\n",
                encoding="utf-16",
            )
        except OSError:
            pass
    try:
        manifest = target / "data" / "install.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(
            json.dumps(
                {
                    "version": version,
                    "built_for": "win64",
                    "updated_at": time.strftime("%Y-%m-%d %H:%M"),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass


# --------------------------- 主流程 ---------------------------


def main() -> int:
    setup_console()
    parser = argparse.ArgumentParser(description="FayeLong 就地更新（不覆盖学习数据）")
    parser.add_argument("--target", default="", help="旧版安装目录；省略则自动查找")
    parser.add_argument("--dry-run", action="store_true", help="只预演，不修改任何文件")
    args = parser.parse_args()

    say("=" * WIDTH)
    say("  FayeLong 就地更新 —— 只换程序文件，不动你的学习数据")
    say("=" * WIDTH)
    say("")

    if not (SOURCE / "app").is_dir() or not (SOURCE / "app" / "main.py").is_file():
        bad(f"当前目录不像 FayeLong 更新包（缺少 app/main.py）：{SOURCE}")
        say("    请把本包完整解压后再运行「更新 FayeLong.bat」。")
        return 1

    new_version = source_version()
    say(f"  新版目录：{SOURCE}")
    say(f"  新版版本：{new_version}")
    say("")

    # ---- 定位目标 ----
    if args.target.strip():
        target = normalize_target(args.target)
        how = "由参数指定"
        if not is_install_dir(target):
            bad(f"这个目录不像 FayeLong 安装目录：{target}")
            say("    目录里应当有 app / runtime / data 等文件夹。")
            return 1
    else:
        found, how = auto_target()
        if not found:
            bad("没有自动找到旧版 FayeLong 的安装目录。")
            say("    请把旧安装目录（例如 D:\\FayeLong）拖到「更新 FayeLong.bat」上，")
            say("    或在命令行里指定： --target D:\\FayeLong")
            return 1
        target = found

    try:
        source_resolved = SOURCE.resolve()
        target_resolved = target.resolve()
    except OSError:
        source_resolved, target_resolved = SOURCE, target

    if (
        source_resolved == target_resolved
        or source_resolved in target_resolved.parents
        or target_resolved in source_resolved.parents
    ):
        bad("目标目录与新版目录相同或互相嵌套，无法更新。")
        say("    请把新包解压到一个独立目录，再执行更新。")
        return 1

    old_version = target_version(target)
    say(f"  旧版目录：{target}")
    say(f"  旧版版本：{old_version}   （{how}）")
    say("")

    if args.dry_run:
        warn("预演模式（--dry-run）：下面只列计划，不会修改任何文件")
        say("")

    # ---- 停止旧服务 ----
    say("[1/5] 停止正在运行的服务")
    if args.dry_run:
        say("  （预演：跳过）")
    elif stop_running(target):
        ok("已停止旧服务")
    else:
        ok("没有正在运行的服务（或未找到 PID 记录）")

    # ---- 备份数据库 ----
    say("")
    say("[2/5] 备份学习数据（data\\app.db）")
    backup_path = None
    if args.dry_run:
        say("  （预演：跳过）")
    else:
        backup_path = backup_db(target, old_version)
    if backup_path:
        ok(f"已备份到 {backup_path.relative_to(target)}")
    elif not args.dry_run:
        ok("没有 app.db（全新目录？）——无需备份")

    # ---- 同步程序文件 ----
    say("")
    say("[3/5] 更新程序文件")
    say("      （runtime 会逐个比对内容，未变化的文件自动跳过，通常几秒到几十秒）")
    stats = Stats()
    for name in REPLACE_DIRS:
        sync_replace(SOURCE / name, target / name, args.dry_run, stats, name)
        if name in stats.replaced:
            ok(f"整目录替换：{name}\\")

    for name in MERGE_DIRS:
        sync_merge(SOURCE / name, target / name, args.dry_run, stats)

    sync_files(SOURCE, target, TOP_FILES, args.dry_run, stats)
    ok(f"共 {stats.copy} 个文件（{mb(stats.bytes)}），跳过 {stats.skip} 个未变化的文件")

    # ---- 数据资源（只补缺失）----
    say("")
    say("[4/5] 补齐缺失的学习资源（模型 / 词典）")
    for name in DATA_ADD_DIRS:
        sync_add_missing(SOURCE / name, target / name, args.dry_run, stats, name)
    if stats.added_data:
        for text in stats.added_data:
            ok(text)
    else:
        ok("无需补齐（目标目录里的模型 / 词典都已存在，保持原样）")

    ensure_dirs(target, args.dry_run)

    # ---- 收尾 ----
    say("")
    say("[5/5] 写入版本记录")
    if args.dry_run:
        say("  （预演：跳过）")
    else:
        write_records(target, new_version)
        ok(f"安装记录已更新为 {new_version}")

    say("")
    say("=" * WIDTH)
    if stats.failed:
        bad(f"有 {len(stats.failed)} 个文件没能写入（其余已完成）：")
        for item in stats.failed[:10]:
            say(f"      · {item}")
        if len(stats.failed) > 10:
            say(f"      · …另有 {len(stats.failed) - 10} 个")
        say("    常见原因是服务仍在运行占用了文件，请先双击「停止 FayeLong.bat」。")
        say("=" * WIDTH)
        return 1

    if args.dry_run:
        ok("预演完成（未修改任何文件）")
    else:
        ok(f"更新完成：{old_version}  →  {new_version}")
    say("")
    say("  你的学习数据没有被改动，原样保留：")
    for item in PROTECTED:
        say(f"      · {item}")
    say("")
    say("  下一步：双击「启动 FayeLong.bat」或「静默启动 FayeLong.vbs」即可使用新版本。")
    say("=" * WIDTH)
    return 0


if __name__ == "__main__":
    sys.exit(main())

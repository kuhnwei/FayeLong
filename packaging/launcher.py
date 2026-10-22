"""FayeLong 一键启动器（交付包专用）。

被 `启动 FayeLong.bat` 调用，负责把「小白用户的一次双击」翻译成一连串可靠动作：

1. **自检**：确认自带 Python 运行时、依赖、便携 ffmpeg 是否齐备，缺失时给出中文提示；
2. **补资源**：模型 / 词库缺失时询问是否现在下载（轻量交付包首次运行走这里）；
3. **选端口**：默认 8000，被占用则自动向后找空闲端口；若发现已有 FayeLong 在跑，直接打开浏览器；
4. **启动服务**：在同进程内拉起 Uvicorn（控制台实时打印进度，日志同时落到 `data/logs/`），
   **并另起一个 worker 子进程**（`worker_entry.py` → `app.worker`，**不是** `-m`：
   交付包的 embeddable Python 忽略 `PYTHONPATH`，`-m` 会找不到 `app` 包）执行
   转码/识别/翻译/切片；退出时按 pid 优雅停止子进程（`fayelong.pid` 树杀 +
   worker 侧 `--parent-pid` 自杀兜底）；
5. **开浏览器**：端口可连通后自动打开默认浏览器。

命令行（供排错 / 自动化使用）::

    runtime\\python\\python.exe launcher.py                # 正常启动（带控制台窗口）
    runtime\\python\\python.exe launcher.py --check        # 只自检，不起服务
    runtime\\python\\python.exe launcher.py --no-browser   # 不自动开浏览器
    runtime\\python\\python.exe launcher.py --port 8010    # 指定端口
    runtime\\python\\pythonw.exe launcher.py --silent      # 静默启动（无窗口，输出进日志）

**静默启动**：用 `pythonw.exe` 运行或显式加 `--silent` 时，本进程没有控制台，
所有输出（含 Uvicorn 日志与未捕获异常）改写到 `data/logs/console.log`，
服务在后台运行；停止服务用 `停止 FayeLong.bat`（按进程号结束）。
开机自启与「静默启动」快捷方式都走这条路。
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

# 本文件位于 <解压目录>/scripts/launcher.py
HERE = Path(__file__).resolve().parent        # <解压目录>/scripts
ROOT = HERE.parent                            # <解压目录>
for _path in (str(ROOT), str(HERE)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

BANNER_WIDTH = 52
DEFAULT_PORT = 8000
PORT_SCAN = 20
APP_MARK = "FayeLong"

DATA_DIR = ROOT / "data"
LOG_DIR = DATA_DIR / "logs"
CONSOLE_LOG = LOG_DIR / "console.log"
CONSOLE_LOG_MAX = 2 * 1024 * 1024          # 超过则轮转为 console.log.1

#: 本进程（web / uvicorn）的 pid 文件 —— 也是 worker 的「父进程存活」判据。
PID_FILE = LOG_DIR / "fayelong.pid"
#: worker 子进程的 pid 文件（「停止 FayeLong.bat」的二次兜底用）。
WORKER_PID_FILE = LOG_DIR / "worker.pid"
#: worker 子进程的 stdout/stderr（它自己还会写 data/logs/worker.log）。
WORKER_CONSOLE_LOG = LOG_DIR / "worker.out"
#: worker 的启动垫片（与 launcher.py 同在 scripts\ 下）。
#: ⚠️ **不能**用 `python -m app.worker`：交付包的 embeddable Python 会忽略
#: `PYTHONPATH`（`_pth` 隔离模式），`-m` 在打包形态下必然 `No module named 'app'`。
#: 详见 packaging/worker_entry.py 的模块 docstring。
WORKER_ENTRY = HERE / "worker_entry.py"

# 安装位置记录：开机自启脚本与「更新」脚本靠它定位安装目录
_APPDATA = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
INSTALL_RECORD_DIR = Path(_APPDATA) / APP_MARK
INSTALL_RECORD_FILE = INSTALL_RECORD_DIR / "install.txt"

# 启动所必需的核心依赖（缺失说明交付包不完整）
REQUIRED_DEPS = ("fastapi", "uvicorn", "sqlalchemy", "pydantic", "pydantic_settings")


# --------------------------- 静默启动 ---------------------------


def wants_silent(explicit: bool = False) -> bool:
    """是否静默运行。

    - 显式 `--silent`；
    - 或者**根本没有控制台**（`pythonw.exe` 下的 `sys.stdout` / `sys.stderr` 是 `None`）——
      这时自动静默，免得把输出丢到空气里。
    """
    if explicit:
        return True
    return sys.stdout is None or sys.stderr is None


def redirect_stdio_to_log() -> Path | None:
    """把标准输出 / 错误接到 `data/logs/console.log`（超过 2MB 先轮转）。

    静默模式下没有控制台，Uvicorn 的日志与任何未捕获异常都必须落到文件里，
    否则用户遇到问题将完全无迹可查。
    """
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        if CONSOLE_LOG.is_file() and CONSOLE_LOG.stat().st_size > CONSOLE_LOG_MAX:
            backup = LOG_DIR / "console.log.1"
            backup.unlink(missing_ok=True)
            CONSOLE_LOG.replace(backup)
        stream = open(CONSOLE_LOG, "a", encoding="utf-8", errors="replace", buffering=1)
    except OSError:
        return None
    sys.stdout = stream
    sys.stderr = stream
    return CONSOLE_LOG


def remember_install(version: str) -> None:
    """记录安装目录与版本。

    - `%LOCALAPPDATA%\\FayeLong\\install.txt`：第 1 行安装目录（绝对路径）、
      第 2 行版本、第 3 行时间。给「开机自启」与「更新」脚本用，**与 data/ 是否迁移无关**。
      ⚠️ 编码必须是 **UTF-16**（带 BOM）：VBScript 用 `OpenTextFile(..., -1)` 读它，
      Python 两侧也都按 UTF-16 写 —— 这样中文用户名 / 中文路径都不会乱码。
    - `<安装目录>\\data\\install.json`：只记版本与时间（**不记路径**），
      这样把 `data/` 整体拷到别的机器 / 目录后，版本信息依然正确。

    写入失败不影响启动。
    """
    stamp = time.strftime("%Y-%m-%d %H:%M")
    try:
        INSTALL_RECORD_DIR.mkdir(parents=True, exist_ok=True)
        INSTALL_RECORD_FILE.write_text(
            f"{ROOT}\n{version}\n{stamp}\n", encoding="utf-16"
        )
    except OSError:
        pass
    try:
        manifest = DATA_DIR / "install.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(
            json.dumps(
                {"version": version, "built_for": "win64", "updated_at": stamp},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass


# --------------------------- 输出 ---------------------------


def _use_utf8_console() -> None:
    """让中文提示在任何入口下都不乱码。

    - 输出到**真实控制台**（双击 .bat 的正常情形）：不干预。Python 在 Windows 上
      直接调用控制台 Unicode API，中文一定能正常显示，与 `chcp` 无关。
    - 输出被**重定向到管道 / 文件**（构建脚本、自动化）：统一改用 UTF-8，
      调用方按 UTF-8 解码即可，跨环境行为一致。
    """
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


def say(text: str = "") -> None:
    print(text, flush=True)


def ok(text: str) -> None:
    say(f"  [√] {text}")


def warn(text: str) -> None:
    say(f"  [!] {text}")


def bad(text: str) -> None:
    say(f"  [×] {text}")


def banner() -> None:
    try:
        from app import __version__

        version = f"v{__version__}"
    except Exception:  # noqa: BLE001  取不到版本不该影响启动
        version = ""
    say("=" * BANNER_WIDTH)
    say(f"  FayeLong 英语学习网站   {version}")
    say("=" * BANNER_WIDTH)
    say("")


# --------------------------- 自检 ---------------------------


def check_runtime() -> list[str]:
    """检查自带运行时与依赖，返回「致命问题」列表（空表示可以启动）。"""
    say("[1/4] 检查运行环境")
    fatal: list[str] = []

    ok(f"Python 运行时：{sys.version.split()[0]}（{Path(sys.executable).parent}）")

    missing: list[str] = []
    for name in REQUIRED_DEPS:
        try:
            __import__(name)
        except Exception:  # noqa: BLE001
            missing.append(name)
    if missing:
        bad(f"缺少依赖：{', '.join(missing)}")
        fatal.append("依赖不完整，交付包可能损坏，请重新解压或重新构建")
    else:
        ok("运行依赖：fastapi / uvicorn / sqlalchemy / pydantic 已就绪")

    return fatal


def check_resources() -> tuple[list[str], list[str]]:
    """检查外部工具与大体积资源，返回 (致命问题, 可下载项)。"""
    say("")
    say("[2/4] 检查音视频工具与学习资源")
    fatal: list[str] = []
    optional: list[str] = []

    from app.core.config import DICT_DIR, ensure_dirs, whisper_model_dir
    from app.core.tools import ffmpeg_path, ffprobe_path
    from app.services.dict import DB_NAME, available as dict_ready

    ensure_dirs()

    ffmpeg, ffprobe = ffmpeg_path(), ffprobe_path()
    if ffmpeg and ffprobe:
        ok(f"ffmpeg / ffprobe：{Path(ffmpeg).parent}")
    else:
        bad("未找到便携版 ffmpeg / ffprobe")
        fatal.append(
            "ffmpeg 缺失：请确认交付包完整（runtime/ffmpeg 目录），"
            "或执行 packaging/fetch-ffmpeg.ps1 重新下载"
        )

    from app.services import asr as asr_service

    if asr_service.deps_available():
        ok("语音识别引擎：faster-whisper 已安装")
    else:
        bad("未安装 faster-whisper")
        optional.append("asr")

    model_dir = whisper_model_dir()
    if (model_dir / "model.bin").is_file():
        size = sum(f.stat().st_size for f in model_dir.glob("*") if f.is_file())
        ok(f"语音识别模型：{model_dir.name}（{_mb(size)}）")
    else:
        warn(f"语音识别模型缺失（{model_dir}）——届时导入素材将无法自动识别")
        optional.append("model")

    if dict_ready():
        db = DICT_DIR / DB_NAME
        ok(f"离线词典：ECDICT（{_mb(db.stat().st_size)}）")
    else:
        warn(f"离线词典缺失（{DICT_DIR}）——查词功能将不可用（可回退在线释义）")
        optional.append("dict")

    return fatal, optional


def _mb(num: int) -> str:
    return f"{num / 1024 / 1024:.1f} MB"


def offer_download(optional: list[str], auto_yes: bool = False, silent: bool = False) -> None:
    """模型 / 词库缺失时，询问用户是否现在下载。

    静默模式（无控制台）下没法提问 —— 直接跳过，提示用户改用
    `启动 FayeLong.bat` 或加 `--yes` 自动下载。
    """
    if not optional:
        return
    say("")
    warn("检测到缺失的学习资源：现在补齐最省事，跳过也可以（网站仍能正常启动）")
    if auto_yes:
        answer = "y"
    elif silent:
        warn("静默模式无法交互询问，已自动跳过；如需下载请用「启动 FayeLong.bat」启动一次")
        return
    else:
        try:
            answer = input("  是否现在自动下载？(y/N) ").strip().lower()
        except (EOFError, OSError, RuntimeError):
            # 无 stdin（管道已关闭 / pythonw）时按「跳过」处理，绝不能卡死
            answer = "n"
    if answer not in ("y", "yes"):
        say("  已跳过。之后重新双击启动脚本仍会提示。")
        return

    from bootstrap import bootstrap

    say("")
    bootstrap(need_model="model" in optional, need_dict="dict" in optional)


# --------------------------- 端口 ---------------------------


def port_in_use(port: int) -> bool:
    """判断端口是否已被占用。

    两个信号叠加，缺一不可：

    1. **连接测试**：端口上有监听程序时 `connect` 会立即成功；
    2. **绑定测试**：端口被「绑定了但还没 listen」的程序占着时，连接会被拒绝，
       但 `bind` 会失败。

    ⚠️ 绑定测试**绝不能**设置 `SO_REUSEADDR` —— 在 Windows 上该选项会允许
    两个进程绑同一端口（历史上多次踩坑的经典陷阱），从而把「已占用」误判为
    「空闲」，随后 Uvicorn 启动时才会报 10048 失败。
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            return True
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return True
    return False


def port_is_free(port: int) -> bool:
    return not port_in_use(port)


def existing_fayelong(port: int) -> bool:
    """该端口上是否已经跑着一个 FayeLong（避免重复启动两个实例）。"""
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/health", timeout=1.5
        ) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return APP_MARK in str(data.get("app", ""))
    except (urllib.error.URLError, ValueError, OSError, TimeoutError):
        return False


class PortBusy(RuntimeError):
    """启动瞬间端口被抢占（Uvicorn 绑定失败）。"""


def _is_addr_in_use(exc: OSError) -> bool:
    winerror = getattr(exc, "winerror", None)
    return exc.errno in (98, 10048) or winerror in (98, 10048)


def pick_port(preferred: int) -> tuple[int | None, int | None]:
    """返回 (可用端口, 已在运行的端口)，两者必有一个为 None。"""
    for port in range(preferred, preferred + PORT_SCAN):
        if port_is_free(port):
            return port, None
        if existing_fayelong(port):
            return None, port
    return None, None


# --------------------------- 启动 ---------------------------


def open_browser_later(port: int, timeout: float = 30.0) -> None:
    """等端口能接受连接后再打开浏览器（避免打开过早显示「无法访问」）。"""
    url = f"http://127.0.0.1:{port}"
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                say("")
                say(f"浏览器即将打开：{url}")
                try:
                    webbrowser.open(url)
                except Exception as exc:  # noqa: BLE001
                    warn(f"自动打开浏览器失败（{exc}），请手动访问 {url}")
                return
        time.sleep(0.4)
    warn(f"服务启动较慢，请手动访问 {url}")


def _app_root() -> Path:
    """`app` 包所在目录（开发环境是 `backend/`，打包环境就是解压根目录）。"""
    if (ROOT / "app").is_dir():
        return ROOT
    if (ROOT / "backend" / "app").is_dir():
        return ROOT / "backend"
    return ROOT


def start_worker(silent: bool) -> subprocess.Popen | None:
    """起一个独立的 worker 子进程（P3-2 起 web 进程默认不执行长任务）。

    Args:
        silent: 静默模式（`pythonw` / `--silent`）。为真时传 `CREATE_NO_WINDOW`，
            保证**不弹任何黑窗**；`pythonw.exe` 本身没有控制台，但
            `python.exe --silent` 会有，所以两种情形都要覆盖。

    Returns:
        子进程句柄；若 `FAYELONG_WEB_INPROC_WORKER=on`（单进程回滚模式）则 `None`。

    Notes:
        * **绝不调用 `input()`**：静默模式下没有 stdin，`input()` 会抛
          `RuntimeError: input(): lost sys.stdin`，进程直接死且**没有任何提示**
          （历史坑）。
        * **必须经 `worker_entry.py` 启动**（不是 `-m app.worker`）：交付包用
          embeddable Python，`_pth` 隔离模式会忽略 `PYTHONPATH`、且 `sys.path` 的
          `.` 指向 `runtime\\python\\` 目录 —— 直接 `-m` 实测报
          `ModuleNotFoundError: No module named 'app'`，worker 起不来，只剩 web
          进程内降级（G3-④ 的双进程就不成立）。垫片缺失时（极老的交付包）
          回退到 `-m` 并告警，绝不因此不启动。
        * `--parent-pid` 让 worker 自己盯着 `fayelong.pid`：launcher 被任务管理器
          杀掉、`taskkill /T` 又没走时，worker 会在 5s 内自行退出，不会变成抢任务
          的孤儿（DD-001 §9 R9）。
        * stdout/stderr 落到 `data/logs/worker.out`：worker 崩溃时才有人在现场
          （它自己的 `worker.log` 只覆盖 handler 内部日志，进程级 traceback 在
          这里）。
    """
    mode = str(os.environ.get("FAYELONG_WEB_INPROC_WORKER") or "auto").strip().lower()
    if mode == "on":
        ok("FAYELONG_WEB_INPROC_WORKER=on：不另起 worker 进程（单进程模式）")
        return None

    app_root = _app_root()
    env = {
        **os.environ,
        # 打包版保持 auto：worker 万一崩了，web 侧 5s 后会接管，
        # 用户看到的是「慢」而不是「永远排队中」（DD-001 §9 R8）。
        "FAYELONG_WEB_INPROC_WORKER": "auto",
        "PYTHONPATH": os.pathsep.join(
            [str(app_root)] + ([os.environ["PYTHONPATH"]] if os.environ.get("PYTHONPATH") else [])
        ),
        "PYTHONUNBUFFERED": "1",
    }

    creationflags = 0
    if os.name == "nt" and silent:
        creationflags = subprocess.CREATE_NO_WINDOW

    worker_args = ["--parent-pid", str(os.getpid())]
    if WORKER_ENTRY.is_file():
        command = [sys.executable, str(WORKER_ENTRY), *worker_args]
    else:
        # 老交付包（没有垫片）回退：开发环境 venv 里 `-m` 是可用的。
        warn("未找到 scripts/worker_entry.py，回退到 python -m app.worker")
        command = [sys.executable, "-m", "app.worker", *worker_args]

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        console_log = open(WORKER_CONSOLE_LOG, "a", encoding="utf-8", errors="replace")
    except OSError as exc:  # noqa: BLE001  日志打不开不该阻止服务启动
        warn(f"无法写入 worker 的 stdout 日志（{exc}），退化为继承父进程输出")
        console_log = subprocess.DEVNULL  # type: ignore[assignment]

    try:
        process = subprocess.Popen(
            command,
            cwd=str(app_root),
            env=env,
            stdout=console_log,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )
    except OSError as exc:
        warn(f"启动 worker 子进程失败（{exc}）；web 进程会在 5s 后自行接管任务")
        return None

    try:
        WORKER_PID_FILE.write_text(str(process.pid), encoding="ascii")
    except OSError:
        pass
    ok(f"任务执行进程已启动（pid {process.pid}，日志 data/logs/worker.log）")

    # 崩溃只告警一次、**不自动重启**：崩溃循环比「慢一点」更难排查（DD-001 §9 R8）。
    def _watch() -> None:
        try:
            code = process.wait()
        except Exception:  # noqa: BLE001
            return
        warn(
            f"任务执行进程已退出（code={code}）。详见 data/logs/worker.log；"
            "web 进程会在 5s 内接管未完成的任务（只是慢一些）"
        )

    threading.Thread(target=_watch, name="worker-watch", daemon=True).start()
    return process


def stop_worker(process: subprocess.Popen | None) -> None:
    """停掉 worker 子进程：`terminate` → 等 5s → `kill`，并清理 pid 文件。"""
    if process is not None and process.poll() is None:
        try:
            process.terminate()
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
                process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                pass
        except OSError:
            pass
    try:
        WORKER_PID_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def run_server(port: int, open_browser: bool, silent: bool = False) -> int:
    import uvicorn

    from app import __version__
    from app.core.config import DB_PATH, INBOX_DIR

    pid_file = PID_FILE
    worker_proc: subprocess.Popen | None = None
    say("")
    say("[4/4] 启动本地服务")
    ok(f"服务地址：http://127.0.0.1:{port}")
    ok(f"数据目录：{DB_PATH.parent}")
    ok(f"投放素材：{INBOX_DIR}")
    ok(f"运行日志：{LOG_DIR / 'app.log'}（任务执行：worker.log）")
    say("")
    say("-" * BANNER_WIDTH)
    if silent:
        say("  静默模式：服务在后台运行，没有控制台窗口。")
        say(f"  停止服务：双击「停止 FayeLong.bat」（当前进程号 {os.getpid()}）")
    else:
        say("  服务运行中。窗口**不要关闭**；按 Ctrl+C 或直接关窗口即停止服务。")
    say("-" * BANNER_WIDTH)
    say("")

    if open_browser:
        threading.Thread(
            target=open_browser_later, args=(port,), daemon=True
        ).start()

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        pid_file.write_text(str(os.getpid()), encoding="ascii")
    except OSError as exc:  # noqa: BLE001  PID 文件只是给「停止」脚本用的便利
        warn(f"写入 PID 文件失败（{exc}），可用窗口 Ctrl+C 停止服务")

    # ⚠️ 顺序很重要：pid 文件写好之后再起 worker —— worker 的 `--parent-pid`
    # 守护线程会读这个文件，抢在写入之前检查会把健康的 worker 误杀。
    worker_proc = start_worker(silent)

    try:
        uvicorn.run(
            "app.main:app",
            host="127.0.0.1",
            port=port,
            log_level="info",
            access_log=False,
        )
    except KeyboardInterrupt:
        pass
    except OSError as exc:
        if _is_addr_in_use(exc):
            raise PortBusy(str(port)) from exc
        raise
    finally:
        stop_worker(worker_proc)
        try:
            pid_file.unlink(missing_ok=True)
        except OSError:
            pass

    say("")
    say(f"FayeLong {__version__} 已停止。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="FayeLong 一键启动器")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="首选端口（默认 8000）")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    parser.add_argument("--check", action="store_true", help="只做环境自检，不启动服务")
    parser.add_argument("--yes", action="store_true", help="资源缺失时自动下载，不询问")
    parser.add_argument(
        "--silent",
        action="store_true",
        help="静默模式：无控制台窗口，输出写入 data/logs/console.log（pythonw 下自动生效）",
    )
    args = parser.parse_args()

    # 必须最先做：一旦没有控制台，就得先把标准流接上日志文件，
    # 否则后面所有输出（含 Uvicorn 日志）都会静默丢失。
    silent = wants_silent(args.silent)
    if silent:
        redirect_stdio_to_log()

    _use_utf8_console()

    banner()
    if silent:
        say("（静默模式：以下输出同时写入 data/logs/console.log）")
        say("")

    fatal = check_runtime()
    if not fatal:
        fatal2, optional = check_resources()
        fatal += fatal2
    else:
        optional = []

    if fatal:
        say("")
        say("=" * BANNER_WIDTH)
        bad("环境自检未通过，无法启动：")
        for item in fatal:
            say(f"      · {item}")
        say("=" * BANNER_WIDTH)
        return 1

    if args.check:
        say("")
        ok("环境自检通过（--check 模式，未启动服务）")
        return 0

    offer_download(optional, auto_yes=args.yes, silent=silent)

    say("")
    say("[3/4] 选择服务端口")
    port, running = pick_port(args.port)
    if running is not None:
        warn(f"检测到 FayeLong 已在 http://127.0.0.1:{running} 运行，直接打开浏览器")
        if not args.no_browser:
            try:
                webbrowser.open(f"http://127.0.0.1:{running}")
            except Exception:  # noqa: BLE001
                pass
        return 0
    if port is None:
        bad(f"端口 {args.port}~{args.port + PORT_SCAN - 1} 都被占用")
        say("      请关闭占用端口的程序，或用 --port 指定其它端口")
        return 1
    if port != args.port:
        warn(f"端口 {args.port} 被占用，改用 {port}")
    else:
        ok(f"端口 {port} 可用")

    # 记下安装位置与版本，供「开机自启」「更新」脚本定位（失败不影响启动）
    try:
        from app import __version__ as _version
    except Exception:  # noqa: BLE001
        _version = "0.0.0"
    remember_install(_version)

    # 探测与真正绑定之间仍有极小的时间窗，被抢占时自动向后换端口重试
    for attempt in range(PORT_SCAN + 1):
        try:
            return run_server(port, open_browser=not args.no_browser, silent=silent)
        except PortBusy:
            if attempt >= PORT_SCAN:
                break
            warn(f"端口 {port} 在启动瞬间被其它程序抢占，改试 {port + 1}")
            port += 1

    bad("连续多个端口都无法绑定，请检查是否有安全软件限制监听端口")
    return 1


if __name__ == "__main__":
    sys.exit(main())

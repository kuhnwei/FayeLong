#!/usr/bin/env python
"""起一个**完全隔离**的后端：临时根 + `data/` 的副本，**绝不碰真实 `data/`**。

为什么需要：P2 剩下的页面里有**上传 / 批量移动 / 删除 / 拆分合并**这类破坏性操作，
在真实库上跑验证是不可接受的。本脚本用「副本库 + 补丁路径」起一个独立端口的后端，
让浏览器验证跑在它上面。

做法（与 `backend/tests/conftest.py` 同一招，已验证可行）：
- 在**任何 `app.*` import 之前**，用 `setattr` 把 `app.core.config` 的 8 个路径常量
  重指向临时根，**再** `import app.main` 并 `uvicorn.run`。
  （`core/config.py` 的路径是模块级常量、不读环境变量；`db.py` 在 import 时即
  `create_engine(DB_PATH)`，所以必须 import 前打补丁。）

⚠️ 体积与写入边界：
- `data/models/`（whisper 模型）与 `data/dict/`（ECDICT 811 MB）**不复制**，
  而是**直接指回真实目录**（只读用途：验证里不做转码/识别/查词，不会写它们）。
- `data/media/library/` 一律落到临时根 —— 隔离实例**绝不会**往真实媒体库写东西。

用法
----
    # 默认：复制真实 data/app.db 一份，起在 8010
    python scripts/run_isolated_backend.py

    # 空库（用来测「首次初始化建号」流程）
    python scripts/run_isolated_backend.py --fresh

    # 指定端口 / 临时根（便于复现与脚本引用）
    python scripts/run_isolated_backend.py --port 8010 --root /tmp/fayelong-iso
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
BACKEND_DIR = REPO_ROOT / "backend"
REAL_DATA = (REPO_ROOT / "data").resolve()

#: 落在临时根里的目录（会被创建）。
_TEMP_DIR_NAMES = ("MEDIA_DIR", "INBOX_DIR", "LIBRARY_DIR", "LOG_DIR")
#: 指回真实目录、**只读**用途的目录（不复制、不创建）。
_READONLY_REAL_NAMES = ("MODELS_DIR", "DICT_DIR")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="隔离后端（临时根 + data 副本）")
    parser.add_argument("--port", type=int, default=8010, help="监听端口（默认 8010，别占 8000）")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--root", default=None, help="临时根目录（默认新建 mkdtemp）")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--copy", action="store_true", help="从真实 data/app.db 复制一份（默认）")
    mode.add_argument("--fresh", action="store_true", help="空库（测首次初始化）")
    args = parser.parse_args(argv)

    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))

    # ---- 关键：import app.main 之前打补丁 ----
    import app.core.config as config  # noqa: PLC0415  （只 import config，安全）

    root = Path(args.root).resolve() if args.root else Path(tempfile.mkdtemp(prefix="fayelong-iso-"))
    data = root / "data"

    mapping = {
        "DATA_DIR": data,
        "MEDIA_DIR": data / "media",
        "INBOX_DIR": data / "media" / "audio",
        "LIBRARY_DIR": data / "media" / "library",
        "LOG_DIR": data / "logs",
        "DB_PATH": data / "app.db",
        # 巨大目录 → 只读指回真实目录，绝不复制
        "MODELS_DIR": REAL_DATA / "models",
        "DICT_DIR": REAL_DATA / "dict",
    }
    for name, path in mapping.items():
        setattr(config, name, path)

    # 只在临时根下建目录；MODELS_DIR / DICT_DIR 只校验存在，不创建（避免误写真实 data/）
    for name in _TEMP_DIR_NAMES:
        Path(getattr(config, name)).mkdir(parents=True, exist_ok=True)
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    for name in _READONLY_REAL_NAMES:
        p = Path(getattr(config, name))
        if not p.is_dir():
            sys.stderr.write(f"[iso] 警告：{name}={p} 不存在（只读用途，缺少也不影响登录验证）\n")

    # ---- 安全护栏：DB / 媒体库 / 日志 绝不能落在真实 data/ 下 ----
    for name in ("DATA_DIR", "MEDIA_DIR", "INBOX_DIR", "LIBRARY_DIR", "LOG_DIR", "DB_PATH"):
        p = Path(getattr(config, name)).resolve()
        try:
            p.relative_to(REAL_DATA)
        except ValueError:
            continue
        sys.stderr.write(f"[iso] 危险：{name} 落在真实 data/ 下：{p}\n")
        return 2

    # ---- 库：副本 或 空库 ----
    if args.fresh:
        db_note = "空库（由 init_db 建表，users 为空 → needs_setup=true）"
    else:
        src = REAL_DATA / "app.db"
        if not src.is_file():
            sys.stderr.write(f"[iso] 真实库不存在，无法复制：{src}\n")
            return 2
        shutil.copy2(src, config.DB_PATH)
        db_note = f"复制自 {src}"

    # ---- import app.main（此时所有路径常量已被重定向）----
    import app.main as app_main  # noqa: PLC0415

    print("[iso] ================= 隔离后端 =================", flush=True)
    print(f"[iso] 临时根(root) : {root}", flush=True)
    print(f"[iso] 库(app.db)   : {config.DB_PATH}  ({db_note})", flush=True)
    print(f"[iso] 媒体库       : {config.LIBRARY_DIR}", flush=True)
    print(f"[iso] 日志         : {config.LOG_DIR}", flush=True)
    print(f"[iso] models(只读) : {config.MODELS_DIR}", flush=True)
    print(f"[iso] dict(只读)   : {config.DICT_DIR}", flush=True)
    print(f"[iso] 监听         : http://{args.host}:{args.port}", flush=True)
    print(f"[iso] 真实 data/   : {REAL_DATA}  —— 未被写入（DB/媒体库/日志均在临时根）", flush=True)
    print("[iso] ===========================================", flush=True)

    import uvicorn  # noqa: PLC0415

    uvicorn.run(app_main.app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

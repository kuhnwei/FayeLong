"""FayeLong 任务执行进程的启动垫片（打包版必需）。

为什么不能直接 `python -m app.worker`
=====================================
交付包用的是 **Windows embeddable Python**（`runtime\\python`）。它的 `python313._pth`
把解释器变成「隔离模式」，有两处后果直接打在 `-m app.worker` 上：

1. **`PYTHONPATH` 环境变量被忽略** —— 隔离模式下 `site` 不会读环境变量
   （`_pth` 里那行 `import site` 只负责把 `Lib\\site-packages` 挂上），
   所以 `launcher.start_worker()` 里精心设置的 `PYTHONPATH=<安装根>` 在打包形态下
   完全无效（在开发环境的 venv 里却有效 —— 这是最容易「本地全绿、交付包崩」的地方）；
2. **`sys.path` 里的 `.` 指向 `runtime\\python\\` 目录**，不是当前工作目录，
   所以 `cwd=<安装根>` 也不会让 `app` 包被找到。

实测（P3-6 双进程验证，`python.exe -m app.worker` 的 stdout 原文）：:

    python.exe: Error while finding module specification for 'app.worker'
    (ModuleNotFoundError: No module named 'app')

后果：worker 进程起不来 → web 进程在 5s 后按 `FAYELONG_WEB_INPROC_WORKER=auto`
降级为进程内执行。功能「看起来还能用」，但 **G3-④ 要求的双进程分离在交付包上
根本不成立**（长 ASR 会占住 web 的事件循环/线程池，「关掉网页也不影响处理」
这一条设计目标丢失）。

本文件做的事
============
就是 `launcher.py` 开头那段 sys.path 自举的「worker 版」：先用 `__file__` 定位
安装根（兼容两种目录布局），再以 **与 `-m` 完全一致** 的语义启动 `app.worker`：

* `runpy.run_module("app.worker", run_name="__main__", alter_sys=True)`
  → 模块内 `__name__ == "__main__"`、`sys.argv` 原样（`--parent-pid` 正常解析）、
  `SystemExit` 退出码原样透传、日志里 logger 名与 `-m` 时逐字相同。
* **不引入任何交互**（`input()` 在 `pythonw` 下会 `RuntimeError`，见 worker.py 的说明）。

开发环境同样走本文件（`packaging/worker_entry.py`）：`launcher.py` 只有一条代码
路径，避免「开发用 `-m`、交付包用垫片」这种两套行为。
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

#: `packaging/worker_entry.py`（开发）或 `<安装根>\scripts\worker_entry.py`（交付包）。
HERE = Path(__file__).resolve().parent
#: 安装根 / 仓库根。
ROOT = HERE.parent


def bootstrap_paths() -> list[str]:
    """返回需要塞进 `sys.path` 的目录（顺序即优先级）。

    兼容两种布局：

    * 交付包：`<安装根>/app` 存在 → 加 `<安装根>`；
    * 开发仓库：`<仓库根>/backend/app` 存在 → 加 `<仓库根>/backend`；
    * 始终加入脚本目录（`bootstrap` / `update` 等平级模块要靠它）。
    """
    paths: list[str] = []
    if (ROOT / "app").is_dir():
        paths.append(str(ROOT))
    if (ROOT / "backend" / "app").is_dir():
        paths.append(str(ROOT / "backend"))
    paths.append(str(HERE))
    return paths


def main() -> int:
    """以 `__main__` 语义运行 `app.worker`（其内部会 `raise SystemExit(main())`）。"""
    for path in reversed(bootstrap_paths()):
        if path not in sys.path:
            sys.path.insert(0, path)

    runpy.run_module("app.worker", run_name="__main__", alter_sys=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

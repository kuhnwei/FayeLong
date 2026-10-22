"""日志配置。

控制台 + 文件双写：
- 控制台：启动窗口里直接看到进度，适合「双击启动」后的排错；
- 文件：默认 `data/logs/app.log`（单文件超过 2MB 自动轮转，最多保留 5 份），
  用户遇到问题可以直接把该文件发来排查。

⚠️ P3-2 起**两个进程绝不共用一个日志文件**
==========================================
web 进程写 `app.log`，独立 worker 进程写 `worker.log`（`setup_logging(filename=...)`）。
原因：两个进程同时对同一个文件跑 `RotatingFileHandler`，在 Windows 上轮转时要
`os.rename` 一个仍被另一个进程打开的文件 → `PermissionError`，且轮转结果会互相
覆盖（日志丢一段，排错时最有用的那段正好没了）。

⚠️ P3-5 起任务 id 自动贯穿（`job_id`）
======================================
`jobs` 表把一条媒体的处理拆成 4 个 stage job，一条日志到底属于哪个任务必须一眼
可见，否则「同一媒体重试 3 次」的日志会混成一团。实现三件套：

1. :data:`job_id_var` —— `contextvars.ContextVar`，**默认 `None`**；
2. :class:`JobIdFilter` —— 把当前上下文的 `job_id` 注入 `LogRecord.job_id`；
3. :class:`JobAwareFormatter` —— **有** `job_id` 时用带标记的格式，**没有**时用
   原来的格式（逐字不变，见 :data:`_FORMAT`）。

为什么用 `contextvars` 而不是 `threading.local` 或「给 logger 加前缀」：
* `threading.local` 在 `asyncio` / 线程池复用下不可组合，且 SSE 协程里会串味；
* 给 `logger` 加前缀（`logger.getChild("job.12")`）会污染 `%(name)s`，破坏按
  logger 名过滤的能力，且 `getChild` 出来的 logger 需逐条传播，容易漏。

⚠️ **两个必须守住的坑**（都是 contextvars + 线程池的经典陷阱）
=============================================================
1. **必须 reset**：`ContextVar.set()` 的副作用是「线程级」的。`ThreadPoolExecutor`
   会复用线程 —— 如果只在 `_execute` 开头 `set()` 而不 `reset()`，下一个任务
   （可能属于完全不同的媒体）的日志会带上**上一条任务**的 job_id。因此
   :func:`job_log_context` 用 `try/finally` + `token` 保证复位，嵌套调用也能正确
   恢复到外层值。
2. **contextvars 不跨线程自动传播**：`concurrent.futures.ThreadPoolExecutor.submit`
   **不会**把提交方的 context 复制给工作线程（与 `asyncio.to_thread` 不同）。
   本项目的做法是在**工作线程内部**（`worker._PoolRunner._execute`）用
   :func:`job_log_context` 包住整段执行 —— 设置与复位都发生在同一个线程里，
   因此**不需要** `copy_context().run(...)`。这样也避免了「提交时拷贝上下文」
   那套写法在任务被取消 / 线程池拒绝时出现的复位漏洞。
"""

from __future__ import annotations

import contextvars
import logging
import sys
from contextlib import contextmanager
from collections.abc import Iterator
from logging.handlers import RotatingFileHandler

from app.core.config import LOG_DIR

#: 无 job_id 时的日志格式（**逐字保持 P3-2 及以前的样子，一个空格都不许动**）。
_FORMAT = "[%(asctime)s] %(levelname)s %(name)s: %(message)s"

#: 有 job_id 时的格式：只在 `%(name)s:` 之后插入一个 `[job:N]` 标记，其余完全一致。
_FORMAT_WITH_JOB = "[%(asctime)s] %(levelname)s %(name)s: [job:%(job_id)s] %(message)s"

_MAX_BYTES = 2 * 1024 * 1024
_BACKUPS = 5

#: 默认日志文件名（web 进程）。
DEFAULT_LOG_FILENAME = "app.log"

#: worker 进程的日志文件名（与 web 严格分开，见模块 docstring）。
WORKER_LOG_FILENAME = "worker.log"

#: 当前上下文的 job id（`None` = 不属于任何任务，例如启动日志 / 健康检查）。
#: 值统一用 `str`，避免 int/str 混用导致 `%(job_id)s` 之外的比较出现意外。
job_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "job_id", default=None
)


def current_job_id() -> str | None:
    """返回当前上下文的 job id（没有则 `None`）。"""
    return job_id_var.get()


@contextmanager
def job_log_context(job_id: int | str | None) -> Iterator[None]:
    """在该上下文内让所有日志带上 `[job:<id>]` 标记。

    Args:
        job_id: 任务 id；`None` 表示「显式清空」（等价于不进入本上下文）。

    Yields:
        无。

    Notes:
        `token` + `finally` 是**必须**的复位动作：线程池复用线程时，漏掉 reset
        会让下一条任务的日志继承上一条的 job_id（见模块 docstring 的坑 1）。
        嵌套使用时 `reset(token)` 会恢复到外层值，不会把外层标记也清掉。
    """
    token = job_id_var.set(None if job_id is None else str(job_id))
    try:
        yield
    finally:
        job_id_var.reset(token)


class JobIdFilter(logging.Filter):
    """把当前上下文的 `job_id` 注入每条 `LogRecord`。

    Notes:
        挂在 **handler** 上而不是 logger 上：logger 上的 filter 只对「直接打在该
        logger 上」的记录生效，子 logger 的 `propagate` 不会经过父 logger 的
        filter（这是 `logging` 模块的既定行为，很容易记错）。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.job_id = current_job_id()
        return True


class JobAwareFormatter(logging.Formatter):
    """按「有没有 job_id」选择两种格式。

    Notes:
        无 job_id 时走 `self._plain.format(record)`，格式串与 P3-2 及以前**完全相同**
        —— 这是「加可观测性不能改变既有日志形状」的硬要求，也让已有的日志分析/
        用户截图对照不被破坏。
    """

    def __init__(
        self,
        fmt: str = _FORMAT,
        job_fmt: str = _FORMAT_WITH_JOB,
        datefmt: str | None = None,
    ) -> None:
        super().__init__(fmt, datefmt)
        self._plain = logging.Formatter(fmt, datefmt)
        self._with_job = logging.Formatter(job_fmt, datefmt)

    def format(self, record: logging.LogRecord) -> str:
        formatter = (
            self._with_job if getattr(record, "job_id", None) else self._plain
        )
        return formatter.format(record)


def setup_logging(level: int = logging.INFO, filename: str = DEFAULT_LOG_FILENAME) -> None:
    """初始化根日志器（重复调用无副作用）。

    Args:
        level: 日志级别。
        filename: 日志文件名（落在 `config.LOG_DIR` 下）。worker 必须传
            :data:`WORKER_LOG_FILENAME`，**不要**与 web 共用 `app.log`。

    Notes:
        「已有 handler 就返回」既让本函数可以被 lifespan / worker 各自安全调用，
        也避免了测试里重复添加 handler。副作用：同一进程内改 `filename` 不会生效
        —— 一个进程只该有一条日志流水，这是刻意的。

        早退分支里**不**追加 handler、也不动别人的 handler：pytest / uvicorn
        可能已经装了自己的 handler，硬加 filter 会改变它们的输出形状。
    """
    if logging.getLogger().handlers:
        return

    root = logging.getLogger()
    root.setLevel(level)
    formatter = JobAwareFormatter(_FORMAT, _FORMAT_WITH_JOB)
    job_filter = JobIdFilter()

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    console.addFilter(job_filter)
    root.addHandler(console)

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            LOG_DIR / filename,
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUPS,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(job_filter)
        root.addHandler(file_handler)
    except OSError as exc:  # noqa: BLE001  日志目录不可写不应导致服务起不来
        root.warning("无法写入日志文件（%s），仅输出到控制台", exc)

"""后台任务执行器：池与执行器注册（P3-2 起调度权已移交 `services/jobs.py`）。

历史与现状
==========
P3-2 之前，`services/media.enqueue()` 直接 `submit(process_media, media_id)`，
把整条 `transcode→asr→translate→clip` 链丢进**一个**线程池。这条链里既有
CPU 活（ffmpeg / whisper）又有网络 IO（在线翻译），单池会让长 ASR 占满槽位，
G3-③「ASR 不阻塞翻译」物理上不可能通过。

现在：
* **生产路径**不再调用本模块 —— 入队走 `jobs_service.enqueue()`，执行走
  `app.worker`（独立进程或 web 进程内的降级 worker）。
* 本模块保留 `submit()` / `shutdown()` 的**名字与语义**，因为 `app/main.py`
  的 lifespan 仍在调 `shutdown_tasks()`；保留它也让「回滚到旧行为」有一条现成的路。
* `new_executor(name, size)` 只是给 `worker._PoolRunner` 提供带名字的线程池工厂，
  **不含任何业务逻辑**（池该认领什么 kind 属于 `services/jobs.py` 的 `KIND_POOL`）。
"""

import logging
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable

logger = logging.getLogger(__name__)

#: 池名（与 `services/jobs.py` 的同名常量保持一致，这里只做再导出免得循环 import）。
POOL_CPU = "cpu"
POOL_IO = "io"

#: 旧的「单池」执行器（仅为向后兼容保留，懒创建）。
_legacy_executor: ThreadPoolExecutor | None = None


def new_executor(name: str, size: int) -> ThreadPoolExecutor:
    """创建并返回一个具名线程池（调用方负责 `shutdown()`）。

    Args:
        name: 池名（`cpu` / `io`），只用于线程名前缀，便于日志与排错。
        size: 线程数，至少 1。

    Returns:
        新建的 `ThreadPoolExecutor`。

    Notes:
        这里**不登记**全局表：池的生命周期归创建者（`worker._PoolRunner`）所有。
        若登记并由 `shutdown()` 统一关，web 进程内的降级 worker 停止时会与
        `stop_inproc_worker()` 重复关闭同一个池。
    """
    return ThreadPoolExecutor(
        max_workers=max(1, int(size)),
        thread_name_prefix=f"fayelong-{name}",
    )


def get_executor() -> ThreadPoolExecutor:
    """旧的单池执行器（懒创建）。

    Notes:
        仅供 `submit()` 的向后兼容使用；生产路径已不再经过它。
    """
    global _legacy_executor
    if _legacy_executor is None:
        # 刻意**不再读** `settings.worker_threads`（DD-001 §5.4：该字段已废弃，
        # 任何容量决策都不许再依赖它）。这里只是一个向后兼容的 2 线程池。
        _legacy_executor = ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="fayelong",
        )
        logger.warning(
            "旧的后台任务线程池被创建（2 线程）：生产路径应走 jobs + worker，"
            "这条路径只为向后兼容保留"
        )
    return _legacy_executor


def submit(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Future:
    """提交一个后台任务到**旧的单池**（已废弃，仅为兼容保留）。

    Args:
        fn: 目标函数。
        *args: 位置参数。
        **kwargs: 关键字参数。

    Returns:
        `Future`。
    """

    def _runner() -> Any:
        try:
            return fn(*args, **kwargs)
        except Exception:  # noqa: BLE001  兜底，防止线程池任务静默丢失
            logger.exception("后台任务执行失败: %s", getattr(fn, "__name__", fn))
            raise

    return get_executor().submit(_runner)


def shutdown(wait: bool = False) -> None:
    """关闭旧的单池执行器（重复调用无副作用）。"""
    global _legacy_executor
    if _legacy_executor is not None:
        _legacy_executor.shutdown(wait=wait, cancel_futures=True)
        _legacy_executor = None

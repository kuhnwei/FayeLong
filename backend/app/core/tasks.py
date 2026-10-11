"""后台任务线程池。

媒体转码、语音识别、翻译都是耗时的同步任务，统一丢到线程池执行，
避免阻塞 FastAPI 的事件循环。
"""

import logging
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable

from app.core.config import settings

logger = logging.getLogger(__name__)

_executor: ThreadPoolExecutor | None = None


def get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(
            max_workers=max(1, settings.worker_threads),
            thread_name_prefix="fayelong",
        )
        logger.info("后台任务线程池已启动（%d 线程）", settings.worker_threads)
    return _executor


def submit(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Future:
    """提交一个后台任务。任务内部异常会被记录，不会中断服务。"""

    def _runner() -> Any:
        try:
            return fn(*args, **kwargs)
        except Exception:  # noqa: BLE001  兜底，防止线程池任务静默丢失
            logger.exception("后台任务执行失败: %s", getattr(fn, "__name__", fn))
            raise

    return get_executor().submit(_runner)


def shutdown(wait: bool = False) -> None:
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=wait, cancel_futures=True)
        _executor = None

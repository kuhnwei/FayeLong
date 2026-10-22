"""FastAPI 应用入口。

同时承担两个职责：
1. 提供 `/api/*` 接口；
2. 托管前端构建产物（单端口部署，目标机器无需 Node）。
"""

from contextlib import asynccontextmanager
import logging
import threading
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api import (
    attempts,
    auth as auth_api,
    categories,
    dict as dict_api,
    health,
    media,
    notes,
    papers,
    question_types as question_types_api,
    sentences,
    sessions,
    stats,
    vocab,
)
from app.core.config import ensure_dirs, settings, static_dir
from app.core.logging import setup_logging
from app.core.tasks import shutdown as shutdown_tasks
from app.db import SessionLocal, init_db
from app.services import auth as auth_service
from app.services import jobs as jobs_service
from app.services.media import requeue_unfinished

logger = logging.getLogger(__name__)

#: web 进程内降级 worker 的小池容量。
#: 刻意小于独立 worker（`job_cpu_threads` / `job_io_threads`）：它只是「独立 worker
#: 没起来」时的安全网，不该和真正的 worker 抢核（DD-001 §1 决策 1）。
_INPROC_CPU_THREADS = 1
_INPROC_IO_THREADS = 2

#: `auto` 模式的观察窗口：等这么久还没有在线 worker 才接管。
_INPROC_AUTO_DELAY_SEC = 5.0

#: 进程内降级 worker（`None` = 没起）。
_inproc_worker: Any = None
#: `auto` 模式的延时器（退出时必须取消，否则 lifespan 结束后还会起线程）。
_inproc_timer: threading.Timer | None = None


def _has_online_worker() -> bool:
    """`workers` 表里是否有在线的心跳行（`auto` 模式的判定依据）。"""
    db = SessionLocal()
    try:
        return bool(jobs_service.online_workers(db))
    finally:
        db.close()


def _start_inproc_worker() -> None:
    """在 web 进程内起一个降级 worker（小池，`mode="web-inproc"`）。"""
    global _inproc_worker
    if _inproc_worker is not None:
        return
    # 延迟导入：`app.worker` 会连带 import 各 stage 模块，放在模块顶层会让
    # 「只跑 API」的进程也背上这些依赖（虽然它们本来就是必需的，但延迟导入能让
    # `python -c "import app.main"` 的失败面更小，排错更快）。
    from app.worker import Worker

    _inproc_worker = Worker(
        cpu_threads=_INPROC_CPU_THREADS,
        io_threads=_INPROC_IO_THREADS,
        mode="web-inproc",
        recover=False,      # 恢复扫描交给独立 worker；web 内降级不抢这份职责
    )
    _inproc_worker.start()
    logger.warning(
        "web 进程已降级为进程内执行者（cpu=%d io=%d）；"
        "独立 worker 上线后重启 web 即可让位",
        _INPROC_CPU_THREADS,
        _INPROC_IO_THREADS,
    )


def maybe_start_inproc_worker() -> None:
    """按 `FAYELONG_WEB_INPROC_WORKER` 三态决定是否在本进程执行任务。

    * `off`：什么都不做（云端 / 已部署独立 worker）；
    * `on`：无条件起（整体退回「单进程全干」的旧行为，也是回滚开关）；
    * `auto`：延迟 :data:`_INPROC_AUTO_DELAY_SEC` 秒后再判一次 `workers` 表，
      仍无在线 worker 才起 —— 这样「独立 worker 已经起来了」时不会白占线程。
    """
    global _inproc_timer
    mode = str(settings.web_inproc_worker or "").strip().lower()
    if mode not in ("off", "auto", "on"):
        logger.warning("未知的 FAYELONG_WEB_INPROC_WORKER=%r，按 auto 处理", mode)
        mode = "auto"

    if mode == "off":
        logger.info("web 进程不执行任务（FAYELONG_WEB_INPROC_WORKER=off）")
        return
    if mode == "on":
        _start_inproc_worker()
        return

    def _deferred() -> None:
        if _inproc_worker is not None:
            return
        try:
            if _has_online_worker():
                logger.info("检测到在线 worker，web 进程不做进程内执行")
                return
        except Exception:  # noqa: BLE001  数据库抖动不应让 web 起不来
            logger.warning("检查在线 worker 失败，按「无 worker」处理", exc_info=True)
        logger.warning(
            "未检测到独立 worker 进程，web 进程降级为进程内执行"
            "（FAYELONG_WEB_INPROC_WORKER=auto）"
        )
        _start_inproc_worker()

    _inproc_timer = threading.Timer(_INPROC_AUTO_DELAY_SEC, _deferred)
    _inproc_timer.daemon = True
    _inproc_timer.start()


def stop_inproc_worker() -> None:
    """停掉进程内降级 worker（幂等；lifespan 退出时调用）。"""
    global _inproc_worker, _inproc_timer
    if _inproc_timer is not None:
        _inproc_timer.cancel()
        _inproc_timer = None
    if _inproc_worker is not None:
        try:
            _inproc_worker.stop()
        except Exception:  # noqa: BLE001  退出路径不应抛异常
            logger.warning("停止进程内 worker 时出错", exc_info=True)
        _inproc_worker = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_dirs()
    setup_logging()
    init_db()
    requeue_unfinished()  # 重启后自动续做未完成的媒体任务
    maybe_start_inproc_worker()  # auto/on 时降级为进程内执行者
    yield
    stop_inproc_worker()
    shutdown_tasks()


app = FastAPI(
    title=settings.app_name,
    version=__version__,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------- 全局登录门禁（v1.12）---------------------------

#: 无需登录即可访问的接口：登录相关接口 + 健康检查（给外部拨测/监控用）
PUBLIC_API_PREFIXES = ("/api/auth/",)
PUBLIC_API_PATHS = frozenset({"/api/health"})


def _is_public_api(path: str) -> bool:
    return path in PUBLIC_API_PATHS or path.startswith(PUBLIC_API_PREFIXES)


def _unauthorized() -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={"detail": "未登录或登录已过期，请重新登录"},
    )


@app.middleware("http")
async def guard_api(request: Request, call_next):
    """除公开接口外，所有 `/api/*` 必须带有效会话。

    为什么用中间件而不是给每个路由加 `Depends`：路由会不断新增，
    「默认拒绝」才不会因为漏加一个依赖而开出一个洞。
    前端静态资源不拦 —— 拦截点在接口层，SPA 会自己渲染登录页。
    """
    path = request.url.path
    if request.method == "OPTIONS" or not path.startswith("/api/") or _is_public_api(path):
        return await call_next(request)

    token = request.cookies.get(auth_service.COOKIE_NAME)
    if not token:
        return _unauthorized()

    db = SessionLocal()
    try:
        # 只读密钥，避免未登录请求产生写操作
        secret = auth_service.read_secret(db)
    finally:
        db.close()

    if auth_service.verify_token(token, secret) is None:
        return _unauthorized()
    return await call_next(request)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """兜底异常处理：记录完整栈，只向前端返回可读的短消息。

    避免把内部堆栈暴露给页面，同时保证前端一定能拿到 JSON `detail`，
    不会出现「后端挂了但界面一片空白」的情况。
    """
    logger.exception("未捕获异常：%s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "服务器内部错误，请查看后端日志或重试"},
    )


app.include_router(health.router)
app.include_router(auth_api.router)
app.include_router(question_types_api.router)
app.include_router(papers.router)
app.include_router(sessions.router)
app.include_router(media.router)
app.include_router(categories.router)
app.include_router(sentences.router)
app.include_router(attempts.router)
app.include_router(dict_api.router)
app.include_router(vocab.router)
app.include_router(notes.router)
app.include_router(stats.router)


# --------------------------- 前端静态托管 ---------------------------

_static = static_dir()

if _static is not None:
    _assets = _static / "assets"
    if _assets.is_dir():
        app.mount("/assets", StaticFiles(directory=_assets), name="assets")

    _index = _static / "index.html"

    @app.get("/", include_in_schema=False, response_model=None)
    def spa_index():
        return FileResponse(_index)

    @app.get("/{full_path:path}", include_in_schema=False, response_model=None)
    def spa_fallback(full_path: str):
        """SPA 回退：静态资源直接返回，其余路径一律交给前端路由处理。"""
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)

        candidate = (_static / full_path).resolve()
        try:
            candidate.relative_to(_static.resolve())
        except ValueError:
            return JSONResponse({"detail": "Not Found"}, status_code=404)

        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_index)

else:

    @app.get("/")
    def root() -> dict:
        return {
            "app": settings.app_name,
            "version": __version__,
            "docs": "/docs",
            "hint": "前端尚未构建：在 frontend-vue 目录执行 npm run build 后即可单端口访问",
        }

"""FastAPI 应用入口。

同时承担两个职责：
1. 提供 `/api/*` 接口；
2. 托管前端构建产物（单端口部署，目标机器无需 Node）。
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api import attempts, dict as dict_api, health, media, notes, sentences, vocab
from app.core.config import ensure_dirs, settings, static_dir
from app.core.logging import setup_logging
from app.core.tasks import shutdown as shutdown_tasks
from app.db import init_db
from app.services.media import requeue_unfinished


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    ensure_dirs()
    init_db()
    requeue_unfinished()  # 重启后自动续做未完成的媒体任务
    yield
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

app.include_router(health.router)
app.include_router(media.router)
app.include_router(sentences.router)
app.include_router(attempts.router)
app.include_router(dict_api.router)
app.include_router(vocab.router)
app.include_router(notes.router)


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
            "hint": "前端尚未构建：在 frontend 目录执行 npm run build 后即可单端口访问",
        }

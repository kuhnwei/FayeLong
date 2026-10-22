"""健康检查与系统自检接口。"""

import logging
import shutil

from fastapi import APIRouter
from sqlalchemy import func

from app import __version__
from app.core.config import DATA_DIR, DB_PATH, INBOX_DIR, settings
from app.core.tools import ffmpeg_path, ffprobe_path
from app.db import SessionLocal
from app.models import Media
from app.services import asr as asr_service
from app.services import dict as dict_service
from app.services import jobs as jobs_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["system"])

_PLAYABLE = ("ready", "asr", "translating", "clipping", "done")


def _worker_block() -> dict:
    """`worker` 块：独立 worker 是否在线（P3-2 起的自检项）。

    Notes:
        `last_heartbeat_at` 必须显式 `.isoformat()` 成字符串：本端点有 `-> dict`
        返回注解，FastAPI 会按 `Dict[str, Any]` 序列化，裸 `datetime` 混进 dict 会
        在序列化阶段炸（或在别的版本里变成难以预期的格式）。
    """
    db = SessionLocal()
    try:
        return jobs_service.worker_snapshot(db)
    finally:
        db.close()


def _jobs_block() -> dict:
    """`jobs` 块：按 status 的计数（4 个键恒存在，便于前端/拨测直接读）。"""
    db = SessionLocal()
    try:
        return jobs_service.counts_by_status(db)
    finally:
        db.close()


def _disk_block() -> dict:
    """`disk` 块：`data/` 所在磁盘的余量（P3-5）。

    为什么单独一块而不是塞进 `checks`：`checks` 里全是布尔自检项，而磁盘余量是
    四个数值（拨测要直接读 `free_percent` 做阈值告警，混在 `checks` 里会被误解成
    「是否为真」）。字段一律用字节（int）+ 百分比（float，保留 1 位）。

    Notes:
        * 用 `shutil.disk_usage(DATA_DIR)`（stdlib，不新增依赖）：素材、切片、模型、
          日志、sqlite 全在 `DATA_DIR` 下，所以**这个目录所在卷**的余量就是唯一相关
          的余量；分别统计各子目录只会给人「还有空间」的错觉。
        * `DATA_DIR` 还不存在时（极端：lifespan 尚未 `ensure_dirs()`）向上找第一个
          存在的祖先再测，绝不让自检接口 500。
        * 已用 + 可用不一定等于总量（保留块 / 文件系统开销），这是 `disk_usage` 的
          既有语义，不要「修正」成 `total - free`。
    """
    path = DATA_DIR
    while not path.exists() and path.parent != path:
        path = path.parent
    usage = shutil.disk_usage(path)
    total = int(usage.total)
    free = int(usage.free)
    free_percent = round(free / total * 100, 1) if total else 0.0
    return {
        "total": total,
        "used": int(usage.used),
        "free": free,
        "free_percent": free_percent,
    }


@router.get("/health")
def health() -> dict:
    """返回服务状态、关键依赖自检结果与数据目录位置。"""
    media_total = 0
    media_ready = 0
    try:
        db = SessionLocal()
        try:
            media_total = db.query(func.count(Media.id)).scalar() or 0
            media_ready = (
                db.query(func.count(Media.id))
                .filter(Media.status.in_(_PLAYABLE))
                .scalar()
                or 0
            )
        finally:
            db.close()
    except Exception:  # noqa: BLE001  自检接口不应因统计失败而报错
        logger.warning("统计媒体数量失败", exc_info=True)

    # P3-2 新增两块（DD-001 §1 决策 7）。
    # ⚠️ 本端点**没有 response_model**，因此往 dict 里加字段不会改变 OpenAPI
    #    schema（契约 34/42 不变）。加字段后必须现场跑 `node scripts/check-contract.mjs`
    #    证实；若变了说明有人给本端点加了 response_model，要改回去而不是改基线。
    # ⚠️ 整体包在 try/except 里：自检接口不能因为统计失败而 500。
    try:
        worker_block = _worker_block()
    except Exception:  # noqa: BLE001
        logger.warning("统计 worker 状态失败", exc_info=True)
        worker_block = {"online": False, "count": 0, "mode": "unknown", "last_heartbeat_at": None}
    try:
        jobs_block = _jobs_block()
    except Exception:  # noqa: BLE001
        logger.warning("统计任务状态失败", exc_info=True)
        jobs_block = {"pending": 0, "running": 0, "done": 0, "failed": 0}
    try:
        disk_block = _disk_block()
    except Exception:  # noqa: BLE001
        logger.warning("统计磁盘余量失败", exc_info=True)
        disk_block = {"total": 0, "used": 0, "free": 0, "free_percent": 0.0}

    asr_info = asr_service.status()
    dict_info = dict_service.status()

    return {
        "status": "ok",
        "app": settings.app_name,
        "version": __version__,
        "checks": {
            "database": DB_PATH.exists(),
            "ffmpeg": ffmpeg_path() is not None,
            "ffprobe": ffprobe_path() is not None,
            "asr": asr_info["installed"],
            # 「whisper 模型就绪」= `asr_service.status()["ready"]`，它直接判
            # `data/models/<model>/model.bin` 是否存在（`asr_service.model_ready()`）。
            # 与 `asr`（依赖是否装上）是两件事：装了依赖但模型没下载 → asr=True,
            # asr_model=False。**不要**在这里再加一个同义字段。
            "asr_model": asr_info["ready"],
            "dict": dict_info["installed"],
        },
        "config": {
            "whisper_model": settings.whisper_model,
            "translate_engines": settings.translate_engines,
        },
        "asr": asr_info,
        "dict": dict_info,
        "paths": {
            "data_dir": str(DATA_DIR),
            "inbox_dir": str(INBOX_DIR),
            "db": str(DB_PATH),
        },
        "media": {
            "total": media_total,
            "ready": media_ready,
        },
        "worker": worker_block,
        "jobs": jobs_block,
        "disk": disk_block,
    }

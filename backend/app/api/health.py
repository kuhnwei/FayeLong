"""健康检查与系统自检接口。"""

import logging

from fastapi import APIRouter
from sqlalchemy import func

from app import __version__
from app.core.config import DATA_DIR, DB_PATH, INBOX_DIR, settings
from app.core.tools import ffmpeg_path, ffprobe_path
from app.db import SessionLocal
from app.models import Media
from app.services import asr as asr_service
from app.services import dict as dict_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["system"])

_PLAYABLE = ("ready", "asr", "translating", "clipping", "done")


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
    }

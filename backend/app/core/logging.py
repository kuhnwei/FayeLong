"""日志配置。

控制台 + 文件双写：
- 控制台：启动窗口里直接看到进度，适合「双击启动」后的排错；
- 文件：`data/logs/app.log`（单文件超过 2MB 自动轮转，最多保留 5 份），
  用户遇到问题可以直接把该文件发来排查。
"""

import logging
import sys
from logging.handlers import RotatingFileHandler

from app.core.config import LOG_DIR

_FORMAT = "[%(asctime)s] %(levelname)s %(name)s: %(message)s"
_MAX_BYTES = 2 * 1024 * 1024
_BACKUPS = 5


def setup_logging(level: int = logging.INFO) -> None:
    """初始化根日志器（重复调用无副作用）。"""
    if logging.getLogger().handlers:
        return

    root = logging.getLogger()
    root.setLevel(level)
    formatter = logging.Formatter(_FORMAT)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    root.addHandler(console)

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            LOG_DIR / "app.log",
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUPS,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError as exc:  # noqa: BLE001  日志目录不可写不应导致服务起不来
        root.warning("无法写入日志文件（%s），仅输出到控制台", exc)

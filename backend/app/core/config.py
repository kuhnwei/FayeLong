"""全局配置与路径约定。

数据目录统一到项目根下的 `data/`（FR-D5：拷贝该目录即完成学习数据迁移）。
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 代码包所在目录：
#   开发环境  <项目>/backend/app/core/config.py → parents[2] = <项目>/backend
#   打包环境  <解压目录>/app/core/config.py      → parents[2] = <解压目录>
BASE_DIR = Path(__file__).resolve().parents[2]
# 项目根目录（开发环境取 backend/ 的上一级；打包环境解压目录本身就是根）
_DEV_MARKERS = ("requirements.txt", "requirements-ml.txt")
ROOT_DIR = (
    BASE_DIR.parent
    if any((BASE_DIR / name).is_file() for name in _DEV_MARKERS)
    else BASE_DIR
)

# ---------------- 运行时数据根（唯一，拷贝即迁移）----------------
DATA_DIR = ROOT_DIR / "data"
MEDIA_DIR = DATA_DIR / "media"           # 媒体根目录
INBOX_DIR = MEDIA_DIR / "audio"          # ★ 收件箱：用户投放原始素材，供扫描导入
LIBRARY_DIR = MEDIA_DIR / "library"      # 系统管理：每个媒体一个子目录（原文件 + 转码 wav + 切片）
MODELS_DIR = DATA_DIR / "models"         # whisper 模型
DICT_DIR = DATA_DIR / "dict"             # ECDICT 词库
LOG_DIR = DATA_DIR / "logs"
DB_PATH = DATA_DIR / "app.db"

# 前端构建产物（单端口部署时由后端托管）
STATIC_CANDIDATES = (
    ROOT_DIR / "frontend" / "dist",      # 开发环境
    ROOT_DIR / "static",                 # 打包环境
)

# ---------------- 支持的媒体格式（FR-M1 / FR-M2）----------------
SUPPORTED_AUDIO_EXT = {
    ".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg", ".opus", ".wma",
}
SUPPORTED_VIDEO_EXT = {
    ".mp4", ".mkv", ".mov", ".webm", ".avi", ".flv", ".m4v", ".ts",
}
SUPPORTED_EXT = SUPPORTED_AUDIO_EXT | SUPPORTED_VIDEO_EXT

# 状态机（FR-M5）：M1 走完 pending→transcoding→ready，M2 继续 asr→translating→clipping→done
STATUS_PENDING = "pending"
STATUS_TRANSCODING = "transcoding"
STATUS_READY = "ready"
STATUS_ASR = "asr"
STATUS_TRANSLATING = "translating"
STATUS_CLIPPING = "clipping"
STATUS_DONE = "done"
STATUS_FAILED = "failed"

# 未完成（服务重启需要重新排队）的状态
UNFINISHED_STATUSES = (
    STATUS_PENDING,
    STATUS_TRANSCODING,
    STATUS_READY,
    STATUS_ASR,
    STATUS_TRANSLATING,
    STATUS_CLIPPING,
)
# 音频已就绪、可播放的状态
AUDIO_READY_STATUSES = (
    STATUS_READY,
    STATUS_ASR,
    STATUS_TRANSLATING,
    STATUS_CLIPPING,
    STATUS_DONE,
)

# 处理进度分区间（对应 FR-M5「解码→识别→翻译→切片」）
PROGRESS_TRANSCODE = (0, 20)
PROGRESS_ASR = (20, 70)
PROGRESS_TRANSLATE = (70, 90)
PROGRESS_CLIP = (90, 100)


class Settings(BaseSettings):
    """应用配置，可通过环境变量（前缀 FAYELONG_）或 backend/.env 覆盖。"""

    app_name: str = "FayeLong 英语学习网站"
    host: str = "127.0.0.1"
    port: int = 8000

    # 语音识别
    whisper_model: str = "small"
    whisper_language: str = "en"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    whisper_beam_size: int = 5
    whisper_vad: bool = True                    # Silero VAD 过滤静音，减少幻听
    whisper_word_timestamps: bool = True        # 词级时间戳（句子切分更稳）
    # 模型仓库（HuggingFace）；国内直连不通，默认走镜像
    whisper_repo: str = "Systran/faster-whisper-{model}"
    hf_endpoint: str = "https://hf-mirror.com"  # 留空则用官方 huggingface.co

    # 句子切分（FR-M6 / §7.2）
    segment_min_ms: int = 700        # 短于此的句子与下一句合并
    segment_max_ms: int = 15000      # 超过此长度强制切分
    segment_max_chars: int = 180     # 超过此字符数强制切分

    # 音频切片（FR-A1）
    clip_padding_ms: int = 120       # 切片前后留白，避免截断首尾音
    clip_bitrate: str = "64k"        # mp3 码率（语音足够）

    # 听写校验（FR-S3 / §9.3）
    dictation_ignore_case: bool = True          # 忽略大小写
    dictation_ignore_punctuation: bool = True   # 忽略标点
    dictation_pass_accuracy: float = 100.0      # 达到该正确率视为「已掌握」

    # 词典（M4 / FR-S6）：ECDICT 离线词库；未收录时可选用在线翻译兜底
    dict_online_fallback: bool = True           # 词库未收录时用在线引擎给个参考释义

    # 翻译：免费在线引擎链（按顺序回退），均为免密钥服务
    #   youdao   -> 有道公开演示接口（质量较好）
    #   mymemory -> MyMemory 翻译记忆库（配额兜底）
    translate_engines: list[str] = ["youdao", "mymemory"]
    translate_target: str = "zh"
    translate_timeout: float = 12.0
    translate_delay_ms: int = 150  # 逐句请求间隔，避免触发限流
    mymemory_email: str = ""  # 可选：填写邮箱可提升 MyMemory 配额

    # 音频转码 / 切片
    clip_format: str = "mp3"
    transcode_sample_rate: int = 16000   # ASR 友好
    transcode_channels: int = 1
    ffmpeg_threads: int = 0              # 0 = 让 ffmpeg 自行决定

    # 后台任务并发（转码线程数，避免吃满 CPU）
    worker_threads: int = 2

    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    model_config = SettingsConfigDict(
        env_prefix="FAYELONG_",
        env_file=str(BASE_DIR / ".env"),
        extra="ignore",
    )


settings = Settings()


def ensure_dirs() -> None:
    """确保运行时目录存在。"""
    for directory in (
        DATA_DIR,
        MEDIA_DIR,
        INBOX_DIR,
        LIBRARY_DIR,
        MODELS_DIR,
        DICT_DIR,
        LOG_DIR,
    ):
        directory.mkdir(parents=True, exist_ok=True)


def static_dir() -> Path | None:
    """返回可用的前端静态目录（不存在则 None）。"""
    for candidate in STATIC_CANDIDATES:
        if (candidate / "index.html").is_file():
            return candidate
    return None


def whisper_model_dir(model: str | None = None) -> Path:
    """某个 whisper 模型的本地目录：`data/models/faster-whisper-<规格>`。"""
    name = model or settings.whisper_model
    return MODELS_DIR / f"faster-whisper-{name}"


def whisper_repo_id(model: str | None = None) -> str:
    """HuggingFace 仓库 id，例如 Systran/faster-whisper-small。"""
    return settings.whisper_repo.format(model=model or settings.whisper_model)

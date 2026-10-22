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

    # 登录门禁（v1.12）：单账号 + 首次访问引导创建
    auth_session_days: int = 30                 # 会话有效期（天）
    auth_min_password_length: int = 8           # 密码最短长度（公网部署建议不要调低）

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
    #: ⚠️ deprecated：P3-2 起**不再被任何代码读取**（调度权已交给 `jobs` + 独立
    #: worker）。保留字段只为兼容仍设置它的旧部署脚本（云端 unit 曾设 1）。
    #: 容量决策改看 `job_cpu_threads` / `job_io_threads`。
    worker_threads: int = 2

    # ---------------- P3-2 调度（DD-001 §5.4）----------------
    # CPU 池线程数：0 = 自动（max(1, os.cpu_count() or 1)）。
    # 云端 2 vCPU 必须显式设 1 —— 否则会取 2，与 ASR 抢核（见 deploy/linux/*.service）。
    job_cpu_threads: int = 0
    # IO 池线程数：翻译/未来批改。免费引擎按 IP 限流，4 已是上限，不要调大。
    job_io_threads: int = 4
    # 池循环轮询间隔（有活时）
    job_poll_interval_ms: int = 500
    # 空闲退避上限
    job_idle_max_ms: int = 2000
    # worker 级心跳间隔（一次 UPDATE，可忽略）
    job_heartbeat_interval_sec: int = 10
    # worker 判死阈值（3× 间隔，容忍一次 GC/调度抖动）
    job_worker_ttl_sec: int = 30
    # job 租约续期间隔（ticker 一条 UPDATE 续本进程所有 running job）
    job_lease_interval_sec: int = 20
    # job 判僵死阈值（6× 间隔，给长时间 ASR 留足余量）
    job_lease_ttl_sec: int = 120
    # 尝试上限（claim 即 +1，故最多被尝试 3 次，可防「反复把 worker 搞 OOM」的
    # 无限重启循环）
    job_max_attempts: int = 3
    # web 进程是否执行任务：off / auto / on（小写三值，见 DD-001 §1 决策 1）
    #   off  = 云端 / 明确部署了独立 worker 时
    #   auto = 开发与打包交付包（安全网：worker 不在线时 web 5s 后接管）
    #   on   = 整体退回「单进程全干」的旧行为（回滚开关）
    web_inproc_worker: str = "auto"

    # ---------------- P4-4 写作批改（外部服务，**默认关闭**）----------------
    #: 批改来源：off | openai_compat。
    #:   off           = **默认值**：零付费、离线可用。写作题交卷后仍会判分，
    #:                   但结果走「参考范文 + 评分标准 + 自评清单」的降级路径
    #:                   （status='degraded'），**绝不阻塞交卷**。
    #:   openai_compat = 任何兼容 OpenAI `/chat/completions` 的服务（官方/自建/代理）。
    #: ⚠️ 这是全站**唯一**可能产生费用的开关，默认必须是 off（ADR-001 §6 Q6）。
    grading_provider: str = "off"
    #: `openai_compat` 的基址（不含 `/chat/completions`）。
    grading_base_url: str = "https://api.openai.com/v1"
    #: API Key。**只从环境变量来**（`FAYELONG_GRADING_API_KEY`），
    #: 不写 `data/`、不写数据库、不进日志（日志一律走 provider.mask_secret）。
    grading_api_key: str = ""
    grading_model: str = "gpt-4o-mini"
    #: 单次外部调用超时（秒）。超时即降级，不重试 —— 重试会把「慢」放大成「卡死」。
    grading_timeout_sec: float = 30.0
    #: 单次生成上限（token），防止一次批改吃掉整月预算。
    grading_max_tokens: int = 900
    #: 每日外部调用上限（按 UTC 日计）。超出直接走降级并写明原因。
    #: 个人自用规模下的硬闸：**宁可少批几篇，也不让账单失控**。
    grading_daily_max: int = 200

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

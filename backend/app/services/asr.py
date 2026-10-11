"""语音识别服务（本地 faster-whisper，FR-M3）。

设计要点
--------
- **延迟导入**：`faster_whisper` 只在真正识别时才 import，因此未安装 ML 依赖时
  后端仍能正常启动（M1 的导入/播放不受影响），`/api/health` 会如实报告不可用。
- **模型单例**：模型加载很慢（数百 MB），进程内缓存，按 (规格/设备/精度) 为键。
- **模型本地优先**：优先使用 `data/models/faster-whisper-<规格>/`；
  缺失时经 `settings.hf_endpoint`（默认 hf-mirror 镜像）下载，符合 FR-D3/FR-D4。
- **句子切分**：以 whisper 词级时间戳为基础，按句末标点切分 + 超长强制切分
  + 过短合并（§7.2），产出带 `start_ms / end_ms` 的句子。
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import threading
import urllib.request
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from app.core.config import settings, whisper_model_dir, whisper_repo_id
from app.core.tools import ffmpeg_path

logger = logging.getLogger(__name__)

ProgressCb = Callable[[int], None]

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# 句末标点（含中文省略号与常见收尾符号）
_SENTENCE_END = ".!?…"
# 尾部需要剥离的引号/括号，避免 `said "go."` 判不出句末
_TRAILING = "\"'\u201d\u2019)]}"


class AsrError(RuntimeError):
    """语音识别相关的可预期错误（对外展示中文原因）。"""


@dataclass
class Word:
    """词级时间戳。"""

    text: str
    start_ms: int
    end_ms: int


@dataclass
class RawSegment:
    """whisper 原始分段。"""

    start_ms: int
    end_ms: int
    text: str
    words: list[Word] = field(default_factory=list)


@dataclass
class Sentence:
    """切分后的句子（写库单元）。"""

    start_ms: int
    end_ms: int
    text: str


# --------------------------- 音频读取 ---------------------------
#
# 说明：faster-whisper 传入「文件路径」时会走 PyAV 解码，而 PyAV 的
# `av.open(metadata_errors=...)` 参数在新版本中已被移除，导致不同版本组合
# 下报 TypeError。我们的标准音频固定是 16kHz / 单声道 / 16bit wav，直接自行
# 解码成 numpy 数组交给模型，既绕开该兼容性问题，也省去一次重复解码。


def _read_wav_fast(path: Path):
    """用标准库读取规范化的 wav（16k / 单声道 / s16）。"""
    import numpy as np

    with wave.open(str(path), "rb") as handle:
        if (
            handle.getframerate() != settings.transcode_sample_rate
            or handle.getnchannels() != 1
            or handle.getsampwidth() != 2
        ):
            raise ValueError("非标准音频格式")
        frames = handle.readframes(handle.getnframes())
    return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0


def _read_via_ffmpeg(path: Path):
    """用 ffmpeg 解码为 16k 单声道 s16le 原始流（兜底路径）。"""
    import numpy as np

    exe = ffmpeg_path()
    if not exe:
        raise AsrError("未找到 ffmpeg，无法读取音频")
    cmd = [
        exe, "-v", "error", "-nostdin", "-i", str(path),
        "-f", "s16le", "-acodec", "pcm_s16le",
        "-ac", "1", "-ar", str(settings.transcode_sample_rate), "-",
    ]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        detail = (proc.stderr or b"").decode("utf-8", "replace").strip()
        raise AsrError(f"音频解码失败：{detail[-200:] or 'ffmpeg 异常退出'}")
    return np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def load_audio_array(path: Path):
    """把音频读成模型可用的 float32 单声道数组。"""
    try:
        return _read_wav_fast(path)
    except Exception as exc:  # noqa: BLE001  非规范 wav 时走 ffmpeg 兜底
        logger.debug("标准库读取 wav 失败（%s），改用 ffmpeg 解码", exc)
    return _read_via_ffmpeg(path)


# --------------------------- 依赖与模型可用性 ---------------------------

_MODEL_LOCK = threading.Lock()
_MODEL = None
_MODEL_KEY: tuple | None = None


def deps_available() -> bool:
    """faster-whisper 是否已安装。"""
    try:
        import faster_whisper  # noqa: F401
    except Exception:  # noqa: BLE001  缺依赖不应让自检接口崩溃
        return False
    return True


def model_ready(model: str | None = None) -> bool:
    """模型文件是否已就绪（ctranslate2 的核心权重为 model.bin）。"""
    return (whisper_model_dir(model) / "model.bin").is_file()


def status() -> dict:
    """供 `/api/health` 展示的自检信息。"""
    directory = whisper_model_dir()
    return {
        "installed": deps_available(),
        "ready": model_ready(),
        "model": settings.whisper_model,
        "dir": str(directory),
        "endpoint": settings.hf_endpoint or "https://huggingface.co",
    }


# --------------------------- 模型准备 ---------------------------

# 只下载推理需要的文件（其余如 README / .git 忽略）
_MODEL_SUFFIXES = (".json", ".txt", ".bin")
_DOWNLOAD_TIMEOUT = 30.0


def _endpoint() -> str:
    return (settings.hf_endpoint or "https://huggingface.co").rstrip("/")


def _fetch_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(request, timeout=_DOWNLOAD_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _remote_size(url: str) -> int:
    """用 HEAD 取文件大小（失败返回 0）。"""
    try:
        request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": _UA})
        with urllib.request.urlopen(request, timeout=_DOWNLOAD_TIMEOUT) as resp:
            return int(resp.headers.get("Content-Length") or 0)
    except Exception:  # noqa: BLE001  拿不到大小不影响下载
        return 0


def _list_repo_files(repo_id: str) -> list[str]:
    """列出仓库中需要下载的模型文件。

    直接走镜像的 REST 接口（`/api/models/<repo>`），不依赖 huggingface_hub
    的版本与参数变化，便于在任意镜像上工作。
    """
    data = _fetch_json(f"{_endpoint()}/api/models/{repo_id}")
    siblings = data.get("siblings") or []
    names = [item.get("rfilename", "") for item in siblings]
    return [
        name
        for name in names
        if name
        and name.endswith(_MODEL_SUFFIXES)
        and not Path(name).name.startswith(".")
    ]


def _download_file(url: str, target: Path, on_bytes) -> None:
    """流式下载单个文件，边下边回报字节数（支持断点续传）。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    start = partial.stat().st_size if partial.is_file() else 0

    headers = {"User-Agent": _UA}
    if start:
        headers["Range"] = f"bytes={start}-"

    request = urllib.request.Request(url, headers=headers)
    mode = "ab" if start else "wb"
    with urllib.request.urlopen(request, timeout=_DOWNLOAD_TIMEOUT) as resp:
        if start and resp.status != 206:      # 服务端不支持续传则重下
            start, mode = 0, "wb"
        with partial.open(mode) as out:
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                out.write(chunk)
                on_bytes(len(chunk))
    partial.replace(target)


def download_model(on_progress: ProgressCb | None = None,
                   model: str | None = None) -> Path:
    """从镜像仓库下载模型到 `data/models/`，按字节回报进度。"""
    destination = whisper_model_dir(model)
    repo_id = whisper_repo_id(model)
    destination.mkdir(parents=True, exist_ok=True)
    logger.info("开始下载 whisper 模型：%s → %s（镜像 %s）",
                repo_id, destination, _endpoint())

    try:
        files = _list_repo_files(repo_id)
    except Exception as exc:  # noqa: BLE001
        raise AsrError(
            f"无法访问模型仓库 {repo_id}（镜像 {_endpoint()}）：{exc}"
        ) from exc
    if not files:
        raise AsrError(f"模型仓库 {repo_id} 中没有可下载的文件")

    base = f"{_endpoint()}/{repo_id}/resolve/main"
    sizes = {name: _remote_size(f"{base}/{name}") for name in files}
    total_bytes = sum(sizes.values())
    done_bytes = 0
    fallback_step = 100 / len(files) if not total_bytes else 0

    for index, name in enumerate(files):
        target = destination / name
        size = sizes.get(name, 0)

        if target.is_file() and size and target.stat().st_size == size:
            done_bytes += size                       # 已下载完成，跳过
            continue

        def _on_bytes(count: int, _size=size) -> None:
            nonlocal done_bytes
            done_bytes += count
            if on_progress and total_bytes:
                on_progress(min(99, int(done_bytes / total_bytes * 100)))

        try:
            _download_file(f"{base}/{name}", target, _on_bytes)
        except Exception as exc:  # noqa: BLE001
            raise AsrError(f"下载模型文件 {name} 失败：{exc}") from exc

        if not total_bytes and on_progress:
            on_progress(min(99, int((index + 1) * fallback_step)))

    if not model_ready(model):
        raise AsrError("模型下载完成但缺少权重文件（model.bin），请重试")
    if on_progress:
        on_progress(100)
    logger.info("whisper 模型已就绪：%s", destination)
    return destination


def load_model(on_progress: ProgressCb | None = None, model: str | None = None):
    """加载（并缓存）whisper 模型。"""
    global _MODEL, _MODEL_KEY

    key = (
        model or settings.whisper_model,
        settings.whisper_device,
        settings.whisper_compute_type,
    )
    with _MODEL_LOCK:
        if _MODEL is not None and _MODEL_KEY == key:
            return _MODEL

        directory = whisper_model_dir(model)
        if not (directory / "model.bin").is_file():
            logger.info("本地未找到模型，开始自动下载")
            download_model(on_progress, model)

        try:
            from faster_whisper import WhisperModel
        except Exception as exc:  # noqa: BLE001
            raise AsrError(
                "未安装 faster-whisper；请执行 "
                "pip install -r backend/requirements-ml.txt"
            ) from exc

        try:
            _MODEL = WhisperModel(
                str(directory),
                device=settings.whisper_device,
                compute_type=settings.whisper_compute_type,
                local_files_only=True,
            )
        except Exception as exc:  # noqa: BLE001
            raise AsrError(f"加载语音识别模型失败：{exc}") from exc

        _MODEL_KEY = key
        logger.info("whisper 模型已加载（%s / %s / %s）", *key)
        return _MODEL


def unload_model() -> None:
    """释放模型（切换规格或排查问题时使用）。"""
    global _MODEL, _MODEL_KEY
    with _MODEL_LOCK:
        _MODEL = None
        _MODEL_KEY = None


# --------------------------- 转写 ---------------------------


def _to_words(raw_words) -> list[Word]:
    words: list[Word] = []
    for item in raw_words or []:
        text = getattr(item, "word", "") or ""
        start = getattr(item, "start", None)
        end = getattr(item, "end", None)
        if start is None or end is None:
            continue
        words.append(Word(text, int(start * 1000), int(end * 1000)))
    return words


def transcribe(
    audio_path: Path,
    duration_ms: int = 0,
    on_progress: ProgressCb | None = None,
    model: str | None = None,
) -> tuple[list[Sentence], dict]:
    """把标准音频转写为句子列表。

    返回 `(sentences, info)`，`info` 含 `language` / `duration_ms`。
    """
    engine = load_model(model=model)

    try:
        audio = load_audio_array(audio_path)
    except AsrError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise AsrError(f"无法读取音频文件：{exc}") from exc

    if audio.size == 0:
        raise AsrError("音频内容为空，无法识别")

    try:
        segment_iter, info = engine.transcribe(
            audio,
            language=settings.whisper_language or None,
            beam_size=settings.whisper_beam_size,
            vad_filter=settings.whisper_vad,
            word_timestamps=settings.whisper_word_timestamps,
            condition_on_previous_text=False,
        )
    except Exception as exc:  # noqa: BLE001
        raise AsrError(f"语音识别失败：{exc}") from exc

    total_s = (duration_ms / 1000) if duration_ms else float(
        getattr(info, "duration", 0) or 0
    )

    raw: list[RawSegment] = []
    try:
        for segment in segment_iter:  # 生成器：边识别边报进度
            raw.append(
                RawSegment(
                    start_ms=int(segment.start * 1000),
                    end_ms=int(segment.end * 1000),
                    text=(segment.text or "").strip(),
                    words=_to_words(getattr(segment, "words", None)),
                )
            )
            if on_progress and total_s > 0:
                on_progress(min(99, max(1, int(segment.end / total_s * 100))))
    except Exception as exc:  # noqa: BLE001
        raise AsrError(f"语音识别中断：{exc}") from exc

    sentences = build_sentences(raw)
    info_out = {
        "language": getattr(info, "language", settings.whisper_language),
        "language_probability": float(getattr(info, "language_probability", 0) or 0),
        "duration_ms": int(total_s * 1000) if total_s else duration_ms,
        "segments": len(raw),
    }
    logger.info(
        "识别完成：%d 个原始分段 → %d 个句子（语言 %s）",
        len(raw), len(sentences), info_out["language"],
    )
    return sentences, info_out


# --------------------------- 句子切分 ---------------------------


def _ends_sentence(token: str) -> bool:
    text = (token or "").strip()
    while text and text[-1] in _TRAILING:
        text = text[:-1]
    return bool(text) and text[-1] in _SENTENCE_END


def _join_words(words: list[Word]) -> str:
    parts: list[str] = []
    for index, word in enumerate(words):
        piece = word.text or ""
        if index == 0:
            parts.append(piece.strip())
        elif piece.startswith(" ") or not piece:
            parts.append(piece)
        else:
            parts.append(" " + piece)
    return "".join(parts).strip()


def _merge_short(units: list[Sentence], min_ms: int, max_ms: int) -> list[Sentence]:
    """把过短的句子并入下一句（避免出现「Yes.」这种碎片）。"""
    merged: list[Sentence] = []
    for unit in units:
        if merged:
            prev = merged[-1]
            prev_duration = prev.end_ms - prev.start_ms
            combined = unit.end_ms - prev.start_ms
            if prev_duration < min_ms and combined <= max_ms:
                prev.end_ms = unit.end_ms
                prev.text = f"{prev.text} {unit.text}".strip()
                continue
        merged.append(unit)

    # 末句仍过短则并入前一句
    if len(merged) >= 2 and (merged[-1].end_ms - merged[-1].start_ms) < min_ms:
        last = merged.pop()
        merged[-1].end_ms = last.end_ms
        merged[-1].text = f"{merged[-1].text} {last.text}".strip()
    return merged


def build_sentences(raw: list[RawSegment], model: str | None = None) -> list[Sentence]:
    """按 §7.2 的策略把原始分段整理成句子。"""
    min_ms = settings.segment_min_ms
    max_ms = settings.segment_max_ms
    max_chars = settings.segment_max_chars

    units: list[Sentence] = []
    for segment in raw:
        if not segment.words:
            text = (segment.text or "").strip()
            if text:
                units.append(Sentence(segment.start_ms, segment.end_ms, text))
            continue

        buffer: list[Word] = []
        for word in segment.words:
            buffer.append(word)
            text = _join_words(buffer)
            duration = buffer[-1].end_ms - buffer[0].start_ms
            if (
                _ends_sentence(word.text)
                or duration >= max_ms
                or len(text) >= max_chars
            ):
                units.append(Sentence(buffer[0].start_ms, buffer[-1].end_ms, text))
                buffer = []
        if buffer:
            units.append(
                Sentence(buffer[0].start_ms, buffer[-1].end_ms, _join_words(buffer))
            )

    # 清掉空白句
    units = [u for u in units if u.text.strip()]
    return _merge_short(units, min_ms, max_ms)


def split_text_sentences(text: str) -> list[str]:
    """纯文本按句末标点切分（人工编辑时校验用）。"""
    parts = re.split(r"(?<=[.!?\u2026])\s+", (text or "").strip())
    return [p.strip() for p in parts if p.strip()]

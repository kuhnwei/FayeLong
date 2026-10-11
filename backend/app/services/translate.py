"""在线翻译服务：多免费引擎 + 本地缓存 + 自动回退。

设计要点（对应设计文档 §7.3）：
- 全部使用**免密钥**的免费在线接口，开箱即用，无需注册。
- 引擎按 settings.translate_engines 顺序尝试，前一个失败自动换下一个。
- 结果写入 translations 表缓存，同一句不重复请求，节省免费额度。
- 逐句请求之间加间隔，避免触发限流。
- 全部引擎失败时返回 None，由上层保留空翻译并要求人工填写（FR-M6）。
"""

import hashlib
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

from app.core.config import settings
from app.db import SessionLocal
from app.models import Translation

logger = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _cache_key(text: str, src: str, tgt: str) -> str:
    raw = f"{src}|{tgt}|{text}".encode("utf-8")
    return hashlib.sha1(raw).hexdigest()


def _post_form(url: str, data: dict, timeout: float) -> dict:
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": _UA,
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get_json(url: str, timeout: float) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


# --------------------------- 具体引擎实现 ---------------------------


def _youdao(text: str, src: str, tgt: str) -> str | None:
    """有道公开演示接口。"""
    data = _post_form(
        "https://aidemo.youdao.com/trans",
        {"q": text, "from": "en", "to": "zh-CHS"},
        settings.translate_timeout,
    )
    if data.get("errorCode") != "0":
        return None
    parts = data.get("translation") or []
    result = "".join(parts).strip()
    return result or None


def _mymemory(text: str, src: str, tgt: str) -> str | None:
    """MyMemory 翻译记忆库，无需密钥。"""
    params = {"q": text, "langpair": f"{src}|zh-CN"}
    if settings.mymemory_email:
        params["de"] = settings.mymemory_email
    url = "https://api.mymemory.translated.net/get?" + urllib.parse.urlencode(params)
    data = _get_json(url, settings.translate_timeout)
    if str(data.get("responseStatus")) != "200":
        return None
    result = (data.get("responseData") or {}).get("translatedText", "").strip()
    # MyMemory 出错时会返回提示语而非译文
    if not result or "MYMEMORY WARNING" in result.upper():
        return None
    return result


_ENGINES: dict[str, Callable[[str, str, str], str | None]] = {
    "youdao": _youdao,
    "mymemory": _mymemory,
}


# --------------------------- 对外接口 ---------------------------


def _read_cache(key: str) -> str | None:
    db = SessionLocal()
    try:
        row = db.get(Translation, key)
        return row.target_text if row else None
    finally:
        db.close()


def _write_cache(key: str, src_text: str, tgt_text: str, engine: str) -> None:
    db = SessionLocal()
    try:
        if db.get(Translation, key) is None:
            db.add(
                Translation(
                    key=key,
                    source_text=src_text,
                    target_text=tgt_text,
                    engine=engine,
                )
            )
            db.commit()
    except Exception:  # 缓存失败不影响主流程
        db.rollback()
        logger.warning("写入翻译缓存失败", exc_info=True)
    finally:
        db.close()


def translate(text: str, src: str = "en", tgt: str | None = None) -> dict:
    """翻译单句。

    返回 {"text": 译文或 None, "engine": 引擎名或 None, "cached": bool}
    """
    text = (text or "").strip()
    if not text:
        return {"text": "", "engine": None, "cached": False}

    tgt = tgt or settings.translate_target
    key = _cache_key(text, src, tgt)

    cached = _read_cache(key)
    if cached is not None:
        return {"text": cached, "engine": "cache", "cached": True}

    for name in settings.translate_engines:
        engine = _ENGINES.get(name)
        if engine is None:
            logger.warning("未知翻译引擎: %s", name)
            continue
        try:
            result = engine(text, src, tgt)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            logger.warning("翻译引擎 %s 请求失败: %s", name, exc)
            continue
        if result:
            _write_cache(key, text, result, name)
            return {"text": result, "engine": name, "cached": False}
        logger.warning("翻译引擎 %s 返回空结果，尝试下一个", name)

    return {"text": None, "engine": None, "cached": False}


def sleep_between(delay_ms: int | None = None) -> None:
    """逐句请求之间的限速等待（供批量流程调用）。"""
    delay = (settings.translate_delay_ms if delay_ms is None else delay_ms) / 1000
    if delay > 0:
        time.sleep(delay)


def translate_batch(texts: list[str], delay_ms: int | None = None) -> list[dict]:
    """批量逐句翻译，句间自动限速。"""
    results: list[dict] = []
    for index, text in enumerate(texts):
        results.append(translate(text))
        if index < len(texts) - 1:
            sleep_between(delay_ms)
    return results

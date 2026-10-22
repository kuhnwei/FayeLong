"""写作批改的**外部服务抽象**（ADR-001 §7.1 的第 3/4/5 条约束）。

为什么要把 provider 抽成一个 Protocol
====================================
1. **可注入**：测试绝不能发真实网络请求（也付不起那个钱）。注入点是一个模块级
   工厂（:func:`set_provider_factory`），测试塞一个计数用的 fake，就能断言
   「同内容第二次不再调用」「provider 只被调用 1 次」。
2. **默认可关**：`FAYELONG_GRADING_PROVIDER=off`（默认）时返回
   :class:`OffProvider`，它**永远抛** :class:`ProviderUnavailable` ——
   调用方据此走「参考范文 + 评分标准」的降级路径。这样「零付费」是默认行为，
   而不是需要用户去关的功能。
3. **不泄漏密钥**：Key 只从 `Settings`（环境变量）来，本模块提供
   :func:`mask_secret` 供所有日志使用；异常消息在抛出前经过 :func:`scrub`
   洗一遍，确保**即使第三方库把 key 塞进异常文本**也不会落进日志。

零新依赖
========
外部调用用标准库 `urllib.request`：`requirements.txt` 里没有 `httpx`
（它只在 `requirements-dev.txt`，因为 TestClient 需要），生产环境不保证有。
多引一个运行时依赖只为省 15 行代码，不值得 —— 况且 `off` 是默认值，
这条路在生产上**大多数时候根本不会执行**。
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from app.core.config import settings

__all__ = [
    "GradingProvider",
    "OffProvider",
    "OpenAICompatProvider",
    "ProviderError",
    "ProviderGrade",
    "ProviderUnavailable",
    "mask_secret",
    "reset_provider_factory",
    "resolve_provider",
    "scrub",
    "set_provider_factory",
]

logger = logging.getLogger(__name__)

#: 打码后可见的尾部字符数（够运维确认「换没换 key」，不足以还原）。
_MASK_KEEP = 4


class ProviderUnavailable(RuntimeError):
    """外部批改不可用（关闭 / 未配置 / 超配额 / 未知 provider）。

    **它是降级信号，不是错误**：调用方捕获后必须返回「参考范文 + 评分标准」，
    绝不能让交卷失败（ADR-001 §7.1 第 3 条）。
    """


class ProviderError(RuntimeError):
    """外部服务调用失败（网络 / HTTP / 响应格式）。同样是降级信号。"""


@dataclass(frozen=True)
class ProviderGrade:
    """一次外部批改的原始结果（不含 IELTS 语义，纯数值 + 文本）。

    Attributes:
        score: 得分（口径由 prompt 里的满分决定）。
        max_score: 满分（回填自调用方，防止 provider 自说自话）。
        feedback: 评语（Markdown/纯文本都可以，前端按纯文本渲染）。
        tokens: 本次消耗的 token 数（用于成本统计；未知时 0）。
        model: 实际使用的模型名（记录用，便于复现）。
    """

    score: float
    max_score: float
    feedback: str
    tokens: int = 0
    model: str = ""


class GradingProvider(Protocol):
    """批改服务契约（结构化类型，不要求继承）。"""

    #: 名字（写进 detail，便于区分「谁批的」）
    name: str

    def grade(self, *, prompt: str, max_tokens: int) -> ProviderGrade:
        """执行一次批改。

        Args:
            prompt: 完整提示词（题型负责构造，provider 不解读 IELTS 语义）。
            max_tokens: 单次生成上限。

        Returns:
            批改结果。

        Raises:
            ProviderUnavailable: 服务未启用 / 未配置 / 超出配额。
            ProviderError: 网络 / HTTP / 响应格式错误。
        """
        ...


# ---------------------------------------------------------------------------
# 打码（所有日志与异常文案的**唯一**出口）
# ---------------------------------------------------------------------------


def mask_secret(value: str | None) -> str:
    """把密钥打码成可安全落日志的形式。

    Args:
        value: 原始密钥。

    Returns:
        `""`（未配置）/ `"***"`（太短，不露任何字符）/ `"sk-***abcd"`（可见首 3 + 尾 4）。

    Notes:
        短于 8 字符时**一个字符都不露** —— 短串里露 4 位等于露一半。
    """
    text = value or ""
    if not text:
        return ""
    if len(text) < 8:
        return "***"
    return f"{text[:3]}***{text[-_MASK_KEEP:]}"


def scrub(text: str | None, secret: str | None = None) -> str:
    """把文本里可能出现的密钥替换成打码形式（异常消息落日志前的最后一道闸）。

    Args:
        text: 待清洗文本。
        secret: 需要抹掉的原始密钥（默认取当前配置里的 key）。

    Returns:
        清洗后的文本（最多 300 字，避免把整段响应体灌进日志）。
    """
    raw = text or ""
    key = secret if secret is not None else (settings.grading_api_key or "")
    if key:
        raw = raw.replace(key, mask_secret(key))
    return raw[:300]


# ---------------------------------------------------------------------------
# 两种实现
# ---------------------------------------------------------------------------


class OffProvider:
    """默认实现：**永远不可用**。

    Notes:
        刻意不返回「0 分」之类的假结果：那会让「关掉付费批改」看起来像
        「批改完成但很差」。抛 `ProviderUnavailable` 才能让上层产出明确标注
        `mode='degraded'` 的参考范文包。
    """

    name = "off"

    def grade(self, *, prompt: str, max_tokens: int) -> ProviderGrade:
        """总是抛 :class:`ProviderUnavailable`（reason=`provider_off`）。"""
        raise ProviderUnavailable("provider_off")


class OpenAICompatProvider:
    """兼容 OpenAI `/chat/completions` 的批改客户端（标准库实现，零新依赖）。

    Attributes:
        base_url: 基址（不含 `/chat/completions`）。
        model: 模型名。
        timeout: 单次超时（秒）。
        api_key: 密钥（**只存在于内存**，绝不落库/落日志）。
    """

    name = "openai_compat"

    #: 系统提示词：要求返回**严格 JSON**，便于解析（也便于 mock 断言）。
    SYSTEM_PROMPT = (
        "You are a strict but fair IELTS writing examiner. "
        "Grade the essay against the given rubric. "
        'Reply with a single JSON object: {"score": <number>, "feedback": "<text>"}. '
        "No markdown fence, no extra keys."
    )

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 30.0,
    ) -> None:
        """构造客户端。

        Args:
            base_url: 基址。
            api_key: 密钥；为空时构造即失败（配置错误要早失败）。
            model: 模型名。
            timeout: 单次超时（秒）。

        Raises:
            ProviderUnavailable: `api_key` 为空（`openai_compat` 必然需要密钥）。
        """
        if not api_key:
            raise ProviderUnavailable("missing_api_key")
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = max(1.0, float(timeout))

    @property
    def endpoint(self) -> str:
        """`/chat/completions` 的完整 URL。"""
        return f"{self.base_url}/chat/completions"

    def grade(self, *, prompt: str, max_tokens: int) -> ProviderGrade:
        """调用一次 `/chat/completions` 并解析出 `score` / `feedback`。

        Args:
            prompt: 用户提示词。
            max_tokens: 单次生成上限。

        Returns:
            `ProviderGrade`（`max_score` 由调用方覆盖，这里先填 0）。

        Raises:
            ProviderError: 网络失败 / 非 200 / 响应不是合法 JSON / 缺字段。
            ProviderUnavailable: 429（配额）或 401/403（鉴权）—— 这两类重试也没用。
        """
        body: dict[str, Any] = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": int(max_tokens),
            "messages": [
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        }
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                # ⚠️ 这一行是密钥**唯一**的去处：HTTP 头。
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            message = scrub(f"http_{exc.code}: {detail or exc.reason}")
            if exc.code in (401, 403):
                raise ProviderUnavailable(f"auth_failed:{message}") from None
            if exc.code == 429:
                raise ProviderUnavailable(f"quota_exceeded:{message}") from None
            raise ProviderError(f"http_error:{message}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ProviderError(f"network_error:{scrub(str(exc))}") from None

        return self._parse(raw)

    def _parse(self, raw: str) -> ProviderGrade:
        """从 API 响应里取出 `score` / `feedback` / `usage.total_tokens`。

        Args:
            raw: 响应体文本。

        Returns:
            解析结果（`max_score` 占位为 0，由调用方回填）。

        Raises:
            ProviderError: JSON 非法 / 缺 `choices` / 内容不是 JSON 对象 / 缺 score。
        """
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            raise ProviderError(f"bad_json:{scrub(raw)}") from None

        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise ProviderError(f"bad_payload:{scrub(raw)}") from None

        data = _loads_json_object(content)
        if data is None:
            raise ProviderError(f"bad_content:{scrub(str(content))}")

        try:
            score = float(data["score"])
        except (KeyError, TypeError, ValueError):
            raise ProviderError(f"bad_score:{scrub(str(content))}") from None

        feedback = data.get("feedback")
        tokens = 0
        usage = payload.get("usage")
        if isinstance(usage, dict):
            try:
                tokens = int(usage.get("total_tokens") or 0)
            except (TypeError, ValueError):
                tokens = 0

        return ProviderGrade(
            score=score,
            max_score=0.0,
            feedback=str(feedback or "").strip(),
            tokens=tokens,
            model=str(payload.get("model") or self.model),
        )


def _loads_json_object(text: str) -> dict[str, Any] | None:
    """宽容地解析「模型返回的 JSON」：允许 ```json 围栏与前后废话。

    Args:
        text: 模型输出的 content。

    Returns:
        dict（解析成功且顶层是对象），否则 `None`。
    """
    raw = (text or "").strip()
    if raw.startswith("```"):
        # 去掉 ```json / ``` 围栏
        raw = raw.split("\n", 1)[-1] if "\n" in raw else raw
        raw = raw.rsplit("```", 1)[0]
        raw = raw.strip()
    for candidate in (raw, _outermost_object(raw)):
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return None


def _outermost_object(text: str) -> str:
    """截出第一个 `{` 到最后一个 `}`（模型偶尔会加一句「Here is the JSON:」）。"""
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return ""
    return text[start : end + 1]


# ---------------------------------------------------------------------------
# 工厂（**测试的唯一注入点**）
# ---------------------------------------------------------------------------

#: 测试注入的 provider 工厂。`None` = 按 `settings.grading_provider` 构造。
_PROVIDER_FACTORY: Callable[[], GradingProvider] | None = None


def set_provider_factory(factory: Callable[[], GradingProvider] | None) -> None:
    """注入一个 provider 工厂（**仅供测试**）。

    Args:
        factory: 无参可调用对象，每次调用返回一个 provider；传 `None` 恢复默认。

    Notes:
        每次调用都重新取工厂结果，因此测试可以在一个用例里换掉 provider，
        且不影响其它用例（fixture 结束时记得 `reset_provider_factory()`）。
    """
    global _PROVIDER_FACTORY
    _PROVIDER_FACTORY = factory


def reset_provider_factory() -> None:
    """恢复默认的 provider 解析（按 `settings.grading_provider`）。"""
    set_provider_factory(None)


def resolve_provider() -> GradingProvider:
    """按配置（或测试注入）得到一个 provider 实例。

    Returns:
        provider 实例；不可用时返回 :class:`OffProvider`，或在配置非法时抛
        :class:`ProviderUnavailable`（由调用方转成降级）。

    Raises:
        ProviderUnavailable: `openai_compat` 缺 key，或 `grading_provider` 是未知值。
    """
    if _PROVIDER_FACTORY is not None:
        return _PROVIDER_FACTORY()

    name = str(settings.grading_provider or "").strip().lower()
    if name in ("", "off", "none", "disabled", "false"):
        return OffProvider()
    if name == "openai_compat":
        provider = OpenAICompatProvider(
            base_url=settings.grading_base_url,
            api_key=settings.grading_api_key,
            model=settings.grading_model,
            timeout=float(settings.grading_timeout_sec),
        )
        logger.info(
            "写作批改 provider=openai_compat model=%s base_url=%s key=%s",
            provider.model,
            provider.base_url,
            mask_secret(provider.api_key),
        )
        return provider
    raise ProviderUnavailable(f"unknown_provider:{name}")

"""写作批改（P4-4）：外部服务抽象 + 缓存 + 成本闸 + 编排。

模块分工见 `service.py` 的模块 docstring。对外**只暴露**这一层：

    from app.services.grading import run_grade_job, enqueue_grade

默认配置（`FAYELONG_GRADING_PROVIDER=off`）下**不产生任何费用**：交卷仍成功，
写作题拿到的是「参考范文 + 评分标准 + 自评清单」的降级包。
"""

from __future__ import annotations

from app.services.grading.provider import (
    GradingProvider,
    OffProvider,
    OpenAICompatProvider,
    ProviderError,
    ProviderGrade,
    ProviderUnavailable,
    mask_secret,
    reset_provider_factory,
    resolve_provider,
    set_provider_factory,
)
from app.services.grading.service import (
    GradingOutcome,
    enqueue_grade,
    finalize_session,
    grade_and_cache,
    run_grade_job,
)

__all__ = [
    "GradingOutcome",
    "GradingProvider",
    "OffProvider",
    "OpenAICompatProvider",
    "ProviderError",
    "ProviderGrade",
    "ProviderUnavailable",
    "enqueue_grade",
    "finalize_session",
    "grade_and_cache",
    "mask_secret",
    "reset_provider_factory",
    "resolve_provider",
    "run_grade_job",
    "set_provider_factory",
]

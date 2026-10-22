"""全局学习概览（M5 打磨）与统计页 overview 聚合（P2）。

给首页 / 生词本页一个「一眼看清学到哪了」的汇总，
数据全部来自本地 SQLite，不产生任何外部请求。
"""

from datetime import datetime

from pydantic import BaseModel


class MediaStatsOut(BaseModel):
    total: int = 0
    done: int = 0          # 已完成（可学习）
    processing: int = 0    # 处理中
    failed: int = 0


class VocabStatsOut(BaseModel):
    total: int = 0
    mastered: int = 0


class AttemptStatsOut(BaseModel):
    total: int = 0             # 累计提交次数
    attempted_sentences: int = 0  # 练过的句子数
    mastered_sentences: int = 0   # 曾全对的句子数


class StatsOut(BaseModel):
    """全局学习概览。"""

    media: MediaStatsOut
    sentences: int = 0
    notes: int = 0
    vocab: VocabStatsOut
    attempts: AttemptStatsOut


# ---------------------------------------------------------------------------
# P2 · 统计页 `/api/stats/overview` 响应模型（ARCH §6.1）。
# 口径：所有「按日」聚合都以**本地日** `YYYY-MM-DD` 为准，前端不做时区换算。
# ---------------------------------------------------------------------------


class DailyPoint(BaseModel):
    """单日听写量点。无听写日为显式 0（前端不判空）。"""

    date: str  # YYYY-MM-DD（本地日）
    attempts: int = 0
    accuracy: float = 0.0  # 0–1；无听写日 = 0
    new_vocab: int = 0


class KpiOut(BaseModel):
    """顶部 KPI 四卡。"""

    today_attempts: int = 0
    today_accuracy: float = 0.0
    today_new_vocab: int = 0
    streak_days: int = 0


class CourseProgressOut(BaseModel):
    """单个素材的听写完成度。"""

    media_id: int
    title: str
    total: int = 0        # 句子数
    attempted: int = 0    # 已练过的句子数（去重）
    pct: float = 0.0      # 0–100；total=0 时恒为 0


class RecentAttemptOut(BaseModel):
    """最近一次听写。"""

    sentence_text: str
    created_at: datetime
    accuracy: float


class OverviewOut(BaseModel):
    """统计页 overview 全量响应。"""

    days: int = 14
    daily: list[DailyPoint]
    kpi: KpiOut
    courses: list[CourseProgressOut]
    recent: list[RecentAttemptOut]
    # Donut 两态（已掌握/未掌握）数据源：团队在 ARCH §6.3 补充，故放在顶层。
    vocab: VocabStatsOut

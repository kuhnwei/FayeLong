"""全局学习概览（M5 打磨）。

给首页 / 生词本页一个「一眼看清学到哪了」的汇总，
数据全部来自本地 SQLite，不产生任何外部请求。
"""

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

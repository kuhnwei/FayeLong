"""听写相关的请求 / 响应模型（M3 / FR-S2 · FR-S3 · FR-A4）。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

TokenType = Literal["correct", "wrong", "missing", "extra"]


class DiffToken(BaseModel):
    """对齐结果中的一个位置。

    - `correct`：正常色，`expected == actual`
    - `wrong`  ：标红，显示用户写的 `actual`，`expected` 为正确形式
    - `missing`：红色下划线，显示 `expected`（用户漏掉的词）
    - `extra`  ：灰色删除线，只显示 `actual`（用户多写的词）
    """

    type: TokenType
    expected: str | None = None
    actual: str | None = None


class AttemptCreate(BaseModel):
    """提交一次听写。"""

    sentence_id: int
    input: str = Field(default="", max_length=4000)


class AttemptRecord(BaseModel):
    """一条历史听写记录（不含词级明细，明细由提交时返回）。"""

    id: int
    input: str
    accuracy: float
    is_correct: bool
    created_at: datetime


class AttemptListResponse(BaseModel):
    items: list[AttemptRecord]
    total: int


class AttemptResult(BaseModel):
    """一次听写的校验结果 + 该句累计统计。"""

    sentence_id: int
    attempt_id: int
    input: str
    accuracy: float
    is_correct: bool

    # 明细
    tokens: list[DiffToken] = Field(default_factory=list)
    total_words: int = 0
    correct: int = 0
    wrong: int = 0
    missing: int = 0
    extra: int = 0

    # 该句累计（用于卡片徽标，提交后即可就地更新，无需再拉详情）
    attempt_count: int = 0
    best_accuracy: float = 0.0
    mastered: bool = False

    created_at: datetime


class DictationSummary(BaseModel):
    """整个媒体的听写进度汇总（学习页头部）。"""

    sentences: int = 0          # 总句数
    attempted: int = 0          # 已听写过的句数
    mastered: int = 0           # 曾完全正确的句数
    total_attempts: int = 0     # 累计提交次数
    avg_best_accuracy: float = 0.0  # 各句最佳正确率的平均值

"""听写校验（FR-S2 / FR-S3，算法见设计文档 §9.3）。

输入标准答案（句子原文）与用户听写结果，输出**词级对齐**的四类标记：

| 类型      | 含义               | 前端呈现        |
|-----------|--------------------|-----------------|
| `correct` | 完全正确           | 正常色          |
| `wrong`   | 拼错 / 用错词      | 标红            |
| `missing` | 漏掉了某个词       | 红色下划线      |
| `extra`   | 多写了词           | 灰色删除线      |

正确率 = 正确词数 / 标准答案词数 × 100%。

本模块是**纯函数、无任何 I/O**，便于单测与在别处复用（如后续本地预校验）。
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

from app.core.config import settings

# 分词：按空白切开，标点视为「粘在词上」的展示信息（letter. / "hello"）
_TOKEN_RE = re.compile(r"\S+")
# 归一化：只保留字母、数字与内部撇号（don't / it's）
_KEEP_RE = re.compile(r"[^0-9a-z']+")

CORRECT = "correct"
WRONG = "wrong"
MISSING = "missing"
EXTRA = "extra"


@dataclass(frozen=True)
class Word:
    """一个词：`display` 用于展示（保留标点/大小写），`norm` 用于比对。"""

    display: str
    norm: str


@dataclass
class DiffToken:
    """对齐结果中的一个位置。"""

    type: str
    expected: str | None = None
    actual: str | None = None


# --------------------------- 归一化与分词 ---------------------------


def normalize_word(word: str) -> str:
    """把一个词归一化成比对用的形式（可能返回空串，表示纯标点）。"""
    text = word.replace("\u2019", "'").replace("\u2018", "'")
    if settings.dictation_ignore_case:
        text = text.lower()
    if settings.dictation_ignore_punctuation:
        text = _KEEP_RE.sub("", text).strip("'")
    return text


def tokenize(text: str) -> list[Word]:
    """切词；归一化后为空的纯标点词直接丢弃。"""
    words: list[Word] = []
    for raw in _TOKEN_RE.findall(text or ""):
        norm = normalize_word(raw)
        if norm:
            words.append(Word(display=raw, norm=norm))
    return words


# --------------------------- 对齐 ---------------------------


def _align(expected: list[Word], actual: list[Word]) -> list[DiffToken]:
    """词级对齐：等价/替换/删除/新增 → 四类标记。

    采用 `difflib.SequenceMatcher` 求最长匹配块，再对 `replace` 块做
    「成对记为 wrong、多出的记为 missing/extra」的二次分配，
    这样 `recieved a` vs `received` 这类错位也能合理归因。
    """
    expected_norms = [w.norm for w in expected]
    actual_norms = [w.norm for w in actual]
    matcher = difflib.SequenceMatcher(None, expected_norms, actual_norms, autojunk=False)

    tokens: list[DiffToken] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(i2 - i1):
                tokens.append(
                    DiffToken(
                        type=CORRECT,
                        expected=expected[i1 + offset].display,
                        actual=actual[j1 + offset].display,
                    )
                )
        elif tag == "replace":
            expected_len = i2 - i1
            actual_len = j2 - j1
            paired = min(expected_len, actual_len)
            for offset in range(paired):
                tokens.append(
                    DiffToken(
                        type=WRONG,
                        expected=expected[i1 + offset].display,
                        actual=actual[j1 + offset].display,
                    )
                )
            for offset in range(paired, expected_len):
                tokens.append(DiffToken(type=MISSING, expected=expected[i1 + offset].display))
            for offset in range(paired, actual_len):
                tokens.append(DiffToken(type=EXTRA, actual=actual[j1 + offset].display))
        elif tag == "delete":
            for index in range(i1, i2):
                tokens.append(DiffToken(type=MISSING, expected=expected[index].display))
        else:  # insert
            for index in range(j1, j2):
                tokens.append(DiffToken(type=EXTRA, actual=actual[index].display))

    return tokens


def evaluate(expected_text: str, actual_text: str) -> dict:
    """校验一次听写，返回标记明细与统计。

    返回结构（与前端 `AttemptResult` 对应）::

        {
          "tokens": [{"type": "wrong", "expected": "received", "actual": "recieved"}, ...],
          "total_words": 12, "correct": 11, "wrong": 1, "missing": 0, "extra": 0,
          "accuracy": 91.7, "is_correct": False
        }
    """
    expected = tokenize(expected_text)
    actual = tokenize(actual_text)
    tokens = _align(expected, actual)

    correct = sum(1 for t in tokens if t.type == CORRECT)
    wrong = sum(1 for t in tokens if t.type == WRONG)
    missing = sum(1 for t in tokens if t.type == MISSING)
    extra = sum(1 for t in tokens if t.type == EXTRA)

    total = len(expected)
    if total:
        accuracy = round(correct / total * 100, 1)
    else:
        # 标准答案为空：用户也没写才算对（正常不会出现）
        accuracy = 100.0 if not actual else 0.0

    # 「完全正确」= 正确率达到阈值，且没有多写（多写不参与正确率计算，需单独排除）
    is_correct = accuracy >= settings.dictation_pass_accuracy and extra == 0

    return {
        "tokens": [
            {"type": t.type, "expected": t.expected, "actual": t.actual} for t in tokens
        ],
        "total_words": total,
        "correct": correct,
        "wrong": wrong,
        "missing": missing,
        "extra": extra,
        "accuracy": accuracy,
        "is_correct": is_correct,
    }


def overview(expected_text: str) -> dict:
    """标准答案的概况（供前端展示「本句共 N 词」等）。"""
    words = tokenize(expected_text)
    return {"total_words": len(words)}

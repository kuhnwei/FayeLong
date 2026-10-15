"""原文「易听错」标记（v1.14）。

用户在原文上手动划出自己容易听错的片段，便于复习时重点听。

存储形态：`sentences.marks` 里的一行 JSON，元素是**闭区间** `[起始词序, 结束词序]`
（词序 0 基，按 `WORD_RE` 分词计数）。

为什么记「词序」而不是「原文片段」：
- 原文片段在句子里可能重复出现（`the ... the`），按下标定位才唯一；
- 分词规则与前端 `ClickableText` 完全一致（同一个正则），两边算出的下标必然对齐。

代价是原文被改写后下标会漂移 —— 所以 `PATCH text_en` / 拆分 / 合并都会**清空标记**，
宁可丢标记也不给出错位的高亮（错位高亮比没有更误导）。
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable

# 与前端 frontend/src/pages/StudyPage.tsx 的 WORD_SPLIT 保持一致
WORD_RE = re.compile(r"[A-Za-z][A-Za-z'’-]*")


def word_count(text: str) -> int:
    """原文的词数（与前端分词口径一致）。"""
    return len(WORD_RE.findall(text or ""))


def load(raw: str | None) -> list[list[int]]:
    """从库里的 JSON 文本还原标记；脏数据一律当「没有标记」，不抛异常。"""
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    ranges: list[list[int]] = []
    for item in data:
        if (
            isinstance(item, (list, tuple))
            and len(item) == 2
            and all(isinstance(v, int) and not isinstance(v, bool) for v in item)
        ):
            ranges.append([min(item[0], item[1]), max(item[0], item[1])])
    return ranges


def dump(ranges: Iterable[Iterable[int]], text: str) -> str:
    """把前端传来的区间归并（重叠/相邻合并）+ 夹到原文词数范围内 → JSON 文本。

    区间无效或全部越界时返回空串（等于清空标记）。
    """
    limit = word_count(text)
    if limit <= 0:
        return ""

    spans: list[tuple[int, int]] = []
    for item in ranges:
        pair = list(item)
        if len(pair) != 2 or not all(isinstance(v, int) and not isinstance(v, bool) for v in pair):
            continue
        lo, hi = min(pair[0], pair[1]), max(pair[0], pair[1])
        lo, hi = max(0, lo), min(limit - 1, hi)
        if lo <= hi:
            spans.append((lo, hi))

    if not spans:
        return ""

    spans.sort()
    merged: list[list[int]] = [[spans[0][0], spans[0][1]]]
    for lo, hi in spans[1:]:
        if lo <= merged[-1][1] + 1:  # 相邻或重叠 → 合并
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])
    return json.dumps(merged, separators=(",", ":"))

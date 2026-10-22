"""原文「易听错」标记纯函数单测（`services/marks.py`）。

咬住的历史判据（PROJECT-NOTES §4「原文易听错标记」）：
- `sentences.marks` = JSON 闭区间数组 `[[起始词序, 结束词序]]`（0 基）；
- `word_count` 分词正则与前端 `ClickableText` 一致（`[A-Za-z][A-Za-z'’-]*`）；
- `dump` 做**归并**（重叠或相邻闭区间合并）+ **夹取**（越界裁到合法范围）；
- **脏数据当无标记**：非法 JSON / 非数组 / 非二元组 / 非整数 / 负数 → 不抛异常。
"""

from __future__ import annotations

import json

import pytest

from app.services import marks


# ---------------------------------------------------------------------------
# word_count
# ---------------------------------------------------------------------------
class TestWordCount:
    def test_simple_sentence(self):
        assert marks.word_count("the cat and the dog") == 5

    def test_empty(self):
        assert marks.word_count("") == 0

    def test_none_is_safe(self):
        assert marks.word_count(None) == 0

    def test_apostrophe_and_hyphen_count_as_one_word(self):
        # it's / well-known 各自算 1 个词
        assert marks.word_count("it's a well-known fact") == 4

    def test_pure_punctuation_not_counted(self):
        assert marks.word_count("!!! ???") == 0

    def test_digits_not_counted(self):
        # 正则要求首字符为字母 → 纯数字不算词
        assert marks.word_count("123 456") == 0

    def test_duplicate_words_each_counted(self):
        assert marks.word_count("the cat and the cat") == 5


# ---------------------------------------------------------------------------
# load：脏数据当无标记
# ---------------------------------------------------------------------------
class TestLoad:
    def test_none_returns_empty(self):
        assert marks.load(None) == []

    def test_empty_string_returns_empty(self):
        assert marks.load("") == []

    def test_invalid_json_returns_empty(self):
        assert marks.load("not json at all") == []

    def test_json_object_returns_empty(self):
        assert marks.load('{"a": 1}') == []

    def test_json_of_scalars_returns_empty(self):
        assert marks.load("[1, 2, 3]") == []

    def test_non_integer_pair_returns_empty(self):
        assert marks.load('[["a", "b"]]') == []

    def test_boolean_elements_rejected(self):
        # bool 是 int 子类，实现显式排除 → 不得当成 0/1
        assert marks.load("[[true, false]]") == []

    def test_valid_pair_is_ordered(self):
        assert marks.load("[[3, 1]]") == [[1, 3]]

    def test_load_does_not_merge_or_clamp(self):
        # load 只做还原与排序，不归并、不夹取
        assert marks.load("[[1, 2], [2, 3]]") == [[1, 2], [2, 3]]

    def test_negative_preserved_by_load(self):
        assert marks.load("[[-5, -1]]") == [[-5, -1]]

    def test_mixed_valid_and_dirty_keeps_only_valid(self):
        assert marks.load('[[0, 1], ["x", "y"], [2, 2]]') == [[0, 1], [2, 2]]


# ---------------------------------------------------------------------------
# dump：归并 + 夹取
# ---------------------------------------------------------------------------
class TestDump:
    def test_adjacent_spans_merged(self):
        # [0,1] 与 [2,3] 相邻 → 合并为 [0,3]
        assert marks.dump([[0, 1], [2, 3]], "a b c d") == "[[0,3]]"

    def test_overlapping_spans_merged(self):
        assert marks.dump([[0, 2], [1, 3]], "a b c d") == "[[0,3]]"

    def test_same_span_deduped(self):
        assert marks.dump([[1, 1], [1, 1]], "a b c") == "[[1,1]]"

    def test_disjoint_spans_kept_separate(self):
        assert marks.dump([[0, 0], [2, 2]], "a b c") == "[[0,0],[2,2]]"

    def test_clamped_to_word_count(self):
        # 词数 3 → 合法下标 0..2；[0,10] 夹到 [0,2]
        assert marks.dump([[0, 10]], "a b c") == "[[0,2]]"

    def test_fully_out_of_range_dropped(self):
        assert marks.dump([[5, 9]], "a b c") == ""

    def test_negative_clamped_and_dropped_when_empty(self):
        # [-3,-1] → lo=max(0,-3)=0, hi=min(2,-1)=-1 → lo>hi → 丢弃
        assert marks.dump([[-3, -1]], "a b c") == ""

    def test_negative_start_clamped_into_range(self):
        # [-2, 1] → [0,1]
        assert marks.dump([[-2, 1]], "a b c") == "[[0,1]]"

    def test_reversed_pair_normalised(self):
        assert marks.dump([[3, 1]], "a b c d") == "[[1,3]]"

    def test_invalid_items_skipped(self):
        # 长度不对 / 非整数 → 跳过，只保留合法区间
        assert marks.dump([["a", "b"], [1, 2, 3], [0, 1]], "a b c") == "[[0,1]]"

    def test_all_invalid_returns_empty(self):
        assert marks.dump([["a", "b"], [1, 2, 3]], "a b c") == ""

    def test_empty_ranges_returns_empty(self):
        assert marks.dump([], "a b c") == ""

    def test_blank_text_returns_empty(self):
        assert marks.dump([[0, 1]], "") == ""

    def test_duplicate_words_distinguished_by_index(self):
        # 句内重复词 "the ... the"：靠下标唯一 → [0,0] 与 [4,4] 不合并
        text = "the cat and the cat"
        assert marks.word_count(text) == 5
        assert marks.dump([[0, 0], [4, 4]], text) == "[[0,0],[4,4]]"

    def test_output_is_compact_json(self):
        payload = marks.dump([[0, 1]], "a b c")
        assert payload == "[[0,1]]"
        assert json.loads(payload) == [[0, 1]]

    def test_string_element_of_len_two_skipped(self):
        # 字符串可迭代且长度为 2，但元素非整数 → 安全跳过（不抛异常）
        assert marks.dump([["a", "b"], [0, 1]], "a b c") == "[[0,1]]"

    def test_non_iterable_element_raises_known_gap(self):
        """已知边界：`dump` 未防御「元素本身不可迭代」（如混入裸 int）。

        与 PROJECT-NOTES「`word_count`/`load`/`dump` … 脏数据当无标记」的
        **表述冲突**——`load` 做到了不抛异常，`dump` 未做到（`list(item)` 抛
        TypeError）。按纪律「以实现为准」，此处**锁定实际行为**并在报告中标注
        该偏差；**不修改业务代码**。
        """
        with pytest.raises(TypeError):
            marks.dump([5], "a b c")

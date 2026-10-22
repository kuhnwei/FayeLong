"""听写校验纯函数单测（`services/dictation.py`）。

咬住的历史判据（PROJECT-NOTES §4「听写判据」）：
- 归一化 `’/‘ → '`，忽略大小写、忽略标点，只留 `[0-9a-z']`；
- 正确率 = 正确词数 / **标准答案**词数 → **多写词不进分母**；
- `is_correct = 正确率 ≥ 100 且 extra == 0`（多写一个词也必须判错）。
"""

from __future__ import annotations

from app.services import dictation


# ---------------------------------------------------------------------------
# normalize_word
# ---------------------------------------------------------------------------
class TestNormalizeWord:
    def test_curly_apostrophe_u2019_to_straight(self):
        assert dictation.normalize_word("don\u2019t") == "don't"

    def test_curly_apostrophe_u2018_to_straight_then_trimmed(self):
        # ‘ → ' 后再被 strip("'") 剥掉首撇号
        assert dictation.normalize_word("\u2018tis") == "tis"

    def test_lowercased(self):
        assert dictation.normalize_word("HELLO") == "hello"

    def test_trailing_punctuation_stripped(self):
        assert dictation.normalize_word("Hello,") == "hello"

    def test_surrounding_quotes_stripped(self):
        assert dictation.normalize_word("'hello'") == "hello"

    def test_internal_apostrophe_kept(self):
        assert dictation.normalize_word("don't") == "don't"

    def test_hyphen_is_removed_not_split(self):
        # 连字符不在保留集 [0-9a-z'] 内 → 被删除（不是拆成两词）
        assert dictation.normalize_word("well-known") == "wellknown"

    def test_digits_kept(self):
        assert dictation.normalize_word("2024") == "2024"

    def test_pure_punctuation_becomes_empty(self):
        assert dictation.normalize_word("...") == ""

    def test_whitespace_only_becomes_empty(self):
        assert dictation.normalize_word("   ") == ""


# ---------------------------------------------------------------------------
# tokenize / overview
# ---------------------------------------------------------------------------
class TestTokenize:
    def test_splits_on_whitespace_keeps_display(self):
        words = dictation.tokenize("Hello, world!")
        assert [w.display for w in words] == ["Hello,", "world!"]
        assert [w.norm for w in words] == ["hello", "world"]

    def test_drops_pure_punctuation_tokens(self):
        words = dictation.tokenize("Hello ... world !!!")
        assert [w.norm for w in words] == ["hello", "world"]

    def test_empty_string(self):
        assert dictation.tokenize("") == []

    def test_none_is_safe(self):
        assert dictation.tokenize(None) == []

    def test_overview_counts_words(self):
        assert dictation.overview("Hello world, again!") == {"total_words": 3}


# ---------------------------------------------------------------------------
# evaluate：核心判据
# ---------------------------------------------------------------------------
class TestEvaluate:
    def test_exact_match_is_correct(self):
        result = dictation.evaluate("Hello world", "hello world")
        assert result["total_words"] == 2
        assert result["correct"] == 2
        assert result["wrong"] == 0
        assert result["missing"] == 0
        assert result["extra"] == 0
        assert result["accuracy"] == 100.0
        assert result["is_correct"] is True

    def test_punctuation_and_case_ignored(self):
        result = dictation.evaluate("Hello, world!", "HELLO world")
        assert result["correct"] == 2
        assert result["accuracy"] == 100.0
        assert result["is_correct"] is True

    def test_curly_apostrophe_matches_straight(self):
        result = dictation.evaluate("Don\u2019t stop", "don't stop")
        assert result["correct"] == 2
        assert result["is_correct"] is True

    def test_extra_word_does_not_enter_denominator(self):
        # 标准答案 2 词，多写 1 词：正确率仍是 100，但 extra>0 → 判错
        result = dictation.evaluate("Hello world", "hello world extra")
        assert result["total_words"] == 2
        assert result["correct"] == 2
        assert result["extra"] == 1
        assert result["accuracy"] == 100.0
        assert result["is_correct"] is False

    def test_missing_word_lowers_accuracy(self):
        result = dictation.evaluate("Hello big world", "hello world")
        assert result["total_words"] == 3
        assert result["correct"] == 2
        assert result["missing"] == 1
        assert result["accuracy"] == 66.7
        assert result["is_correct"] is False

    def test_wrong_word_lowers_accuracy(self):
        result = dictation.evaluate("I received it", "I recieved it")
        assert result["total_words"] == 3
        assert result["correct"] == 2
        assert result["wrong"] == 1
        assert result["accuracy"] == 66.7
        assert result["is_correct"] is False

    def test_empty_expected_and_empty_actual_is_correct(self):
        result = dictation.evaluate("", "")
        assert result["total_words"] == 0
        assert result["accuracy"] == 100.0
        assert result["is_correct"] is True

    def test_empty_expected_but_user_wrote_something_is_wrong(self):
        result = dictation.evaluate("", "hello")
        assert result["total_words"] == 0
        assert result["extra"] == 1
        assert result["accuracy"] == 0.0
        assert result["is_correct"] is False

    def test_all_punctuation_expected_and_actual(self):
        result = dictation.evaluate("...", "!!!")
        assert result["total_words"] == 0
        assert result["accuracy"] == 100.0
        assert result["is_correct"] is True

    def test_leading_trailing_whitespace_ignored(self):
        result = dictation.evaluate("  hello   world  ", "hello world")
        assert result["correct"] == 2
        assert result["is_correct"] is True

    def test_hyphenated_written_as_one_token(self):
        # "well-known" 归一化成 "wellknown"；用户写 "wellknown" 也算对
        result = dictation.evaluate("well-known", "wellknown")
        assert result["accuracy"] == 100.0
        assert result["is_correct"] is True

    def test_pure_number_answer(self):
        result = dictation.evaluate("Chapter 2024", "chapter 2024")
        assert result["accuracy"] == 100.0
        assert result["is_correct"] is True

    def test_tokens_carry_display_forms(self):
        result = dictation.evaluate("I received it", "I recieved it")
        wrong = [t for t in result["tokens"] if t["type"] == dictation.WRONG]
        assert wrong == [
            {"type": "wrong", "expected": "received", "actual": "recieved"}
        ]

    def test_replace_block_with_surplus_actual_records_extra(self):
        # 「替换」块里用户多写：expected 2、actual 3 → 2 wrong + 1 extra
        result = dictation.evaluate("alpha beta", "gamma delta epsilon")
        assert result["wrong"] == 2
        assert result["extra"] == 1
        assert result["missing"] == 0
        assert result["total_words"] == 2

    def test_replace_block_with_surplus_expected_records_missing(self):
        # 「替换」块里用户少写：expected 3、actual 2 → 2 wrong + 1 missing
        result = dictation.evaluate("gamma delta epsilon", "alpha beta")
        assert result["wrong"] == 2
        assert result["missing"] == 1
        assert result["extra"] == 0
        assert result["total_words"] == 3

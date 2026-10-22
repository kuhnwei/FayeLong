"""本地词典单测（`services/dict.py`）。

**不依赖真实 `data/dict/ecdict.db`（811 MB）**：本文件自建一个微型 ECDICT
SQLite（列结构照 `dict.py` 实际读取的来），塞入针对性数据，并把词典路径
重定向到它 —— 可重复、快、零外部依赖。

咬住的历史判据（PROJECT-NOTES §4「词典三级优先」）：
- 查询顺序：① `word = ?` → ② `sw = ? AND word NOT LIKE '%-%'` → ③ `sw = ?`；
  排序 `collins DESC, frq DESC`；
- **音节拆分条目陷阱**：`hel-lo` / `chil-dren` 这类条目不能被 `sw` 误命中；
- 词形还原：`exchange` 含 `0:` → 用原型再查（`via=exchange`）；否则 lemminflect
  + 规则候选，**候选必须能命中词库才采用**。
"""

from __future__ import annotations

import sqlite3
import sys

import pytest

import app.services.dict as dsvc

# ---------------------------------------------------------------------------
# 自建微型 ECDICT（列名与 dict.py 的 SELECT 完全对齐）
# ---------------------------------------------------------------------------
_SCHEMA = """
CREATE TABLE stardict (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    word TEXT NOT NULL,
    sw TEXT,
    phonetic TEXT,
    definition TEXT,
    translation TEXT,
    pos TEXT,
    collins INTEGER DEFAULT 0,
    oxford INTEGER DEFAULT 0,
    tag TEXT,
    bnc INTEGER DEFAULT 0,
    frq INTEGER DEFAULT 0,
    exchange TEXT
);
"""

# word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange
_ROWS = [
    # —— 级 ①：word 精确命中，且质量低（collins/frq 小于拆分条目）——
    ("hello", "hello", "həˈləʊ", "used as a greeting", "你好\n喂", "int", 1, 0, "", 0, 10, ""),
    ("hel-lo", "hello", "", "", "（拆分条目）", "", 5, 0, "", 0, 99, ""),
    # —— 级 ②：word 大小写不同 → 级① 落空；级② 排除含连字符条目 ——
    ("Children", "children", "", "", "孩子们", "n", 2, 0, "", 0, 20, ""),
    ("chil-dren", "children", "", "", "（拆分）", "", 9, 0, "", 0, 90, ""),
    # —— 级 ③：只有含连字符的拆分条目 ——
    ("beau-tiful", "beautiful", "", "", "（拆分）", "", 9, 0, "", 0, 90, ""),
    # —— 排序：collins 优先 ——
    ("Colour", "colour", "", "", "颜色", "n", 3, 0, "", 0, 50, ""),
    ("COLOR", "colour", "", "", "颜色(大写)", "n", 2, 0, "", 0, 80, ""),
    # —— 排序：collins 相同则 frq 优先 ——
    ("Favour", "favour", "", "", "偏爱", "n", 2, 0, "", 0, 10, ""),
    ("FAVOUR", "favour", "", "", "偏爱(大写)", "n", 2, 0, "", 0, 90, ""),
    # —— 词形还原：exchange 的 0: 原型 ——
    ("went", "went", "", "", "去(过去式)", "v", 1, 0, "", 0, 1, "0:go"),
    ("go", "go", "", "", "去", "v", 5, 0, "", 0, 99, "i:going/p:went/d:gone"),
    # —— 词形还原：规则候选必须命中词库 ——
    ("run", "run", "", "", "跑", "v", 5, 0, "", 0, 90, "i:running/p:ran/d:run"),
    ("make", "make", "", "", "做", "v", 5, 0, "", 0, 80, "i:making"),
    # —— tag 映射 / oxford ——
    ("study", "study", "", "", "学习", "n", 4, 1, "gk cet6", 0, 70, ""),
]

_ROW_COUNT = len(_ROWS)


@pytest.fixture()
def ecdict(tmp_path, monkeypatch):
    """建迷你词库并把 `dict.py` 的 DICT_DIR / 连接缓存重定向到它。"""
    db_dir = tmp_path / "dict"
    db_dir.mkdir()
    db_file = db_dir / "ecdict.db"

    conn = sqlite3.connect(db_file)
    try:
        conn.execute(_SCHEMA)
        conn.executemany(
            "INSERT INTO stardict "
            "(word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            _ROWS,
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(dsvc, "DICT_DIR", db_dir)
    monkeypatch.setattr(dsvc, "_conn", None)
    monkeypatch.setattr(dsvc, "_conn_missing", False)
    try:
        yield db_file
    finally:
        # 关闭只读连接，避免 Windows 上 tmp_path 清理失败
        live = dsvc._conn
        if live is not None:
            live.close()
            dsvc._conn = None


@pytest.fixture()
def no_dict(tmp_path, monkeypatch):
    """指向一个不含 ecdict.db 的空目录 → 词库“未安装”。"""
    empty = tmp_path / "dict_missing"
    empty.mkdir()
    monkeypatch.setattr(dsvc, "DICT_DIR", empty)
    monkeypatch.setattr(dsvc, "_conn", None)
    monkeypatch.setattr(dsvc, "_conn_missing", False)
    return empty


@pytest.fixture()
def ecdict_no_table(tmp_path, monkeypatch):
    """存在 ecdict.db 文件但缺 `stardict` 表 → 触发 SQL 错误分支。"""
    db_dir = tmp_path / "dict_bad"
    db_dir.mkdir()
    db_file = db_dir / "ecdict.db"
    conn = sqlite3.connect(db_file)
    try:
        conn.execute("CREATE TABLE unrelated (x INTEGER)")
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(dsvc, "DICT_DIR", db_dir)
    monkeypatch.setattr(dsvc, "_conn", None)
    monkeypatch.setattr(dsvc, "_conn_missing", False)
    try:
        yield db_file
    finally:
        live = dsvc._conn
        if live is not None:
            live.close()
            dsvc._conn = None


# ---------------------------------------------------------------------------
# normalize / is_lookupable
# ---------------------------------------------------------------------------
class TestNormalize:
    def test_trims_and_lowercases(self):
        assert dsvc.normalize("  Hello  ") == "hello"

    def test_strips_quotes(self):
        assert dsvc.normalize('"word"') == "word"
        assert dsvc.normalize("“word”") == "word"
        assert dsvc.normalize("‘word’") == "word"

    def test_empty(self):
        assert dsvc.normalize("") == ""

    def test_none_safe(self):
        assert dsvc.normalize(None) == ""


class TestIsLookupable:
    @pytest.mark.parametrize(
        "word", ["hello", "a", "don't", "well-known", "HELLO", "Ab"]
    )
    def test_accepts_single_english_word(self, word):
        assert dsvc.is_lookupable(word) is True

    @pytest.mark.parametrize(
        "word", ["", "123", "hello world", "-x", "'x'", ".", "héllo"]
    )
    def test_rejects_non_words(self, word):
        assert dsvc.is_lookupable(word) is False


# ---------------------------------------------------------------------------
# _query：三级优先 + 音节拆分陷阱 + 排序
# ---------------------------------------------------------------------------
class TestQueryLevels:
    def test_level1_exact_word_beats_split_entry(self, ecdict):
        # 'hello' 精确命中（collins=1），不得被 collins=5 的 'hel-lo' 抢占
        entry = dsvc._query("hello")
        assert entry is not None
        assert entry.word == "hello"
        assert entry.collins == 1

    def test_level2_excludes_hyphenated_split_entry(self, ecdict):
        # 'children' 无精确 word；级② 排除 'chil-dren'（collins=9），取 'Children'
        entry = dsvc._query("children")
        assert entry is not None
        assert entry.word == "Children"
        assert entry.collins == 2

    def test_level3_falls_back_to_split_entry(self, ecdict):
        # 'beautiful' 只有含连字符条目 → 级③ 兜底
        entry = dsvc._query("beautiful")
        assert entry is not None
        assert entry.word == "beau-tiful"

    def test_ordering_prefers_higher_collins(self, ecdict):
        entry = dsvc._query("colour")
        assert entry is not None
        assert entry.word == "Colour"  # collins 3 > 2

    def test_ordering_prefers_higher_frq_on_collins_tie(self, ecdict):
        entry = dsvc._query("favour")
        assert entry is not None
        assert entry.word == "FAVOUR"  # collins 同为 2，frq 90 > 10

    def test_unknown_word_returns_none(self, ecdict):
        assert dsvc._query("zzzzzz") is None

    def test_to_entry_parses_tags_and_multiline(self, ecdict):
        study_entry = dsvc._query("study")
        assert study_entry is not None
        assert study_entry.tags == ["高考", "六级"]
        assert study_entry.oxford == 1

        hello_entry = dsvc._query("hello")
        assert hello_entry is not None
        assert hello_entry.phonetic == "həˈləʊ"
        assert hello_entry.translation == ["你好", "喂"]


# ---------------------------------------------------------------------------
# parse_exchange
# ---------------------------------------------------------------------------
class TestParseExchange:
    def test_full_exchange(self):
        mapping, forms = dsvc.parse_exchange("p:went/d:gone/i:going/3:goes/0:go")
        assert mapping == {
            "过去式": "went",
            "过去分词": "gone",
            "现在分词": "going",
            "第三人称单数": "goes",
            "原型": "go",
        }
        assert len(forms) == 5

    def test_duplicate_code_keeps_first_for_mapping(self):
        mapping, forms = dsvc.parse_exchange("1:went/1:gone")
        assert mapping["变换形式"] == "went"
        assert [f["value"] for f in forms] == ["went", "gone"]

    def test_none_returns_empty(self):
        assert dsvc.parse_exchange(None) == ({}, [])

    def test_empty_string_returns_empty(self):
        assert dsvc.parse_exchange("") == ({}, [])

    def test_malformed_pieces_skipped(self):
        # 'p:'（值空）、':x'（码空）、'garbage'（无冒号）→ 全部跳过
        assert dsvc.parse_exchange("p:/:x/garbage") == ({}, [])


# ---------------------------------------------------------------------------
# 规则候选与词形还原
# ---------------------------------------------------------------------------
class TestRuleCandidates:
    def test_running_yields_run(self):
        assert "run" in dsvc._rule_candidates("running")

    def test_ies_yields_y(self):
        assert "city" in dsvc._rule_candidates("cities")
        assert "study" in dsvc._rule_candidates("studies")

    def test_ed_yields_base(self):
        assert "play" in dsvc._rule_candidates("played")

    def test_ly_yields_base(self):
        assert "quick" in dsvc._rule_candidates("quickly")

    def test_no_match_returns_empty(self):
        assert dsvc._rule_candidates("xx") == []


class TestLemmaCandidates:
    def test_deduped_and_ordered(self):
        candidates = dsvc.lemma_candidates("studies")
        assert "study" in candidates
        assert len(candidates) == len(set(candidates))

    def test_lemminflect_candidates_empty_when_not_installed(self, monkeypatch):
        # 模拟「未安装 lemminflect」（轻量包场景）→ 防御分支返回 []
        monkeypatch.setitem(sys.modules, "lemminflect", None)
        assert dsvc._lemminflect_candidates("studies") == []

    def test_lemminflect_candidates_tolerates_getlemma_error(self, monkeypatch):
        # getLemma 抛异常时逐 upos 容错（continue），不冒泡
        import lemminflect

        def boom(*_args, **_kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(lemminflect, "getLemma", boom)
        assert dsvc._lemminflect_candidates("studies") == []


class TestLookup:
    def test_exact(self, ecdict):
        result = dsvc.lookup("hello")
        assert result.found is True
        assert result.via == "exact"
        assert result.entry is not None
        assert result.entry.word == "hello"

    def test_case_insensitive_query(self, ecdict):
        result = dsvc.lookup("HELLO")
        assert result.query == "hello"
        assert result.entry is not None
        assert result.entry.word == "hello"

    def test_exchange_prototype(self, ecdict):
        # 'went' 的 exchange 含 0:go → 用原型再查，标 via=exchange
        result = dsvc.lookup("went")
        assert result.found is True
        assert result.via == "exchange"
        assert result.lemma == "go"
        assert result.entry is not None
        assert result.entry.word == "go"

    def test_self_prototype_stays_exact(self, ecdict):
        # 'go' 自身没有「原型」键 → 仍走 exact，不做多余还原
        result = dsvc.lookup("go")
        assert result.via == "exact"
        assert result.entry is not None
        assert result.entry.word == "go"

    def test_lemma_candidate_must_hit_dictionary(self, ecdict, monkeypatch):
        # 'running' 未精确命中。**模拟轻量包（无 lemminflect）**，让候选只来自规则，
        # 首个候选是**未收录**的 'runn' —— 这样「拒绝未收录候选、回退到已收录的 'run'」
        # 这条路径才真正被走到（本机装了 lemminflect 时首候选恰好是 'run'，会掩盖该校验）。
        monkeypatch.setattr(dsvc, "_lemminflect_candidates", lambda _word: [])
        assert dsvc.lemma_candidates("running")[0] == "runn"  # 前提：首候选未收录

        result = dsvc.lookup("running")
        assert result.found is True
        assert result.lemma == "run"
        assert result.entry is not None
        assert result.entry.word == "run"
        assert result.via == "rule"

    def test_ing_candidate_with_restored_e(self, ecdict):
        result = dsvc.lookup("making")
        assert result.found is True
        assert result.lemma == "make"
        assert result.entry is not None
        assert result.entry.word == "make"

    def test_all_candidates_miss(self, ecdict):
        result = dsvc.lookup("zzxxing")
        assert result.found is False
        assert result.entry is None
        assert result.via == ""

    def test_empty_query_not_found(self, ecdict):
        result = dsvc.lookup("")
        assert result.found is False
        assert result.query == ""

    def test_non_word_query_not_found(self, ecdict):
        result = dsvc.lookup("123")
        assert result.found is False

    def test_unknown_word_not_found(self, ecdict):
        result = dsvc.lookup("don't")
        assert result.found is False


# ---------------------------------------------------------------------------
# 词库存在性 / 状态 / 缺失降级
# ---------------------------------------------------------------------------
class TestAvailability:
    def test_available_and_entry_count(self, ecdict):
        assert dsvc.available() is True
        assert dsvc.entry_count() == _ROW_COUNT

    def test_status_reports_installed(self, ecdict):
        info = dsvc.status()
        assert info["installed"] is True
        assert info["entries"] == _ROW_COUNT
        assert info["size_bytes"] > 0

    def test_connect_caches_single_connection(self, ecdict):
        first = dsvc._connect()
        second = dsvc._connect()
        assert first is second

    def test_missing_dict_available_false(self, no_dict):
        assert dsvc.available() is False

    def test_missing_dict_connect_raises(self, no_dict):
        with pytest.raises(dsvc.DictUnavailable):
            dsvc._connect()

    def test_missing_dict_entry_count_zero(self, no_dict):
        assert dsvc.entry_count() == 0

    def test_missing_dict_status(self, no_dict):
        info = dsvc.status()
        assert info["installed"] is False
        assert info["size_bytes"] == 0

    def test_entry_count_swallows_sql_error(self, ecdict_no_table):
        # 文件在、表不在 → sqlite3.Error 被吞，返回 0
        assert dsvc.entry_count() == 0

    def test_query_swallows_sql_error(self, ecdict_no_table):
        # 查询打到不存在的表 → 记日志并返回 None（不抛给上层）
        assert dsvc._query("hello") is None

"""本地词典服务（M4 / FR-S6）：ECDICT 词库 + 词形还原。

设计要点
--------
- **词库**：ECDICT（`data/dict/ecdict.db`，SQLite 版，约 28 万词条），含音标 /
  中文释义 / 英文释义 / 词性 / 柯林斯星级 / 牛津三千 / 考纲标签 / 词形变化。
  完全离线、免费，不调用任何在线接口。
- **优雅降级**：词库未安装时不抛异常，`available()` 返回 False，接口返回明确中文提示；
  由上层决定是否用在线翻译兜底。
- **词形还原两级**：① ECDICT `exchange` 字段的 `0:` 原型反查（最准，词库自带）；
  ② lemminflect 生成候选原型再回查 + 词库校验过的轻量规则兜底。
- **单连接 + 锁**：SQLite 只读查询，进程内共享一个连接，简单且足够快。
"""

from __future__ import annotations

import logging
import re
import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import DICT_DIR

logger = logging.getLogger(__name__)

DB_NAME = "ecdict.db"

# ECDICT exchange 字段的编码含义
_EXCHANGE_LABELS = {
    "p": "过去式",
    "d": "过去分词",
    "i": "现在分词",
    "3": "第三人称单数",
    "r": "比较级",
    "t": "最高级",
    "s": "复数",
    "0": "原型",
    "1": "变换形式",
}

# 考纲标签 → 中文
_TAG_LABELS = {
    "zk": "中考",
    "gk": "高考",
    "cet4": "四级",
    "cet6": "六级",
    "ky": "考研",
    "toefl": "托福",
    "ielts": "雅思",
    "gre": "GRE",
}

_WORD_RE = re.compile(r"^[a-zA-Z][a-zA-Z'\-]*$")


class DictUnavailable(RuntimeError):
    """词库未安装（上层据此给出安装指引）。"""


@dataclass
class Entry:
    """一个词条（已解析）。"""

    word: str                       # 词库中的主词形
    phonetic: str = ""
    translation: list[str] = field(default_factory=list)   # 中文释义（多行）
    definition: list[str] = field(default_factory=list)    # 英文释义（多行）
    pos: str = ""
    tags: list[str] = field(default_factory=list)          # 中文考纲标签
    collins: int = 0
    oxford: int = 0
    bnc: int = 0
    frq: int = 0
    exchange: dict[str, str] = field(default_factory=dict)  # label → value
    forms: list[dict] = field(default_factory=list)         # [{label, value}]


@dataclass
class Lookup:
    """一次查询的结果（含词形还原信息）。"""

    query: str                      # 用户查询的原词（已归一化）
    entry: Entry | None = None
    lemma: str | None = None        # 命中的原型（若查询词本身是变形）
    via: str = ""                   # exact / exchange / lemminflect / rule

    @property
    def found(self) -> bool:
        return self.entry is not None


# --------------------------- 词库连接 ---------------------------

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None
_conn_missing = False


def db_path() -> Path:
    return DICT_DIR / DB_NAME


def available() -> bool:
    """词库文件是否存在。"""
    return db_path().is_file()


def _connect() -> sqlite3.Connection:
    global _conn, _conn_missing
    if _conn is not None:
        return _conn
    path = db_path()
    if not path.is_file():
        _conn_missing = True
        raise DictUnavailable(
            "词典未安装：请执行 backend/scripts/fetch_dict.py 下载 ECDICT 词库"
        )
    uri = f"file:{path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    _conn = conn
    _conn_missing = False
    logger.info("ECDICT 词库已加载：%s", path)
    return conn


def entry_count() -> int:
    if not available():
        return 0
    try:
        with _lock:
            conn = _connect()
            return int(conn.execute("SELECT COUNT(*) FROM stardict").fetchone()[0])
    except (sqlite3.Error, DictUnavailable):
        return 0


def status() -> dict:
    """供 `/api/health` 与前端展示的自检信息。"""
    path = db_path()
    return {
        "installed": available(),
        "path": str(path),
        "size_bytes": path.stat().st_size if path.is_file() else 0,
        "entries": entry_count() if available() else 0,
    }


# --------------------------- 查询 ---------------------------


def normalize(word: str) -> str:
    """归一化查询词（去空白 / 转小写 / 剥掉首尾非字母）。"""
    text = (word or "").strip().strip("\"'“”‘’").lower()
    return text


def is_lookupable(word: str) -> bool:
    """单次查询只接受单个英文单词（含连字符与撇号）。"""
    return bool(_WORD_RE.match(word or ""))


def _query(word: str) -> Entry | None:
    """按词形直接查询词库（不还原）。

    ECDICT 除正常词条外还有**音节拆分条目**（如 `hel-lo` / `-running`），
    它们的 `sw`（去符号规范化词形）与正常词相同，若只按 `sw` 取值会优先
    命中这些拆分条目。因此按以下顺序尝试：

    1. `word = ?`：精确词形（走 `word` 唯一索引，几乎必然命中正常词条）；
    2. `sw = ?` 且排除含连字符的条目（覆盖大小写 / 标点差异）；
    3. `sw = ?`：最后兜底。

    结果按柯林斯星级与词频降序，保证取到质量更高的释义。
    """
    columns = (
        "word, phonetic, definition, translation, pos, collins, "
        "oxford, tag, bnc, frq, exchange"
    )
    attempts = (
        ("word = ?", "ORDER BY collins DESC, frq DESC"),
        (
            "sw = ? AND word NOT LIKE '%-%'",
            "ORDER BY collins DESC, frq DESC, length(word) ASC",
        ),
        ("sw = ?", "ORDER BY collins DESC, frq DESC, length(word) ASC"),
    )
    try:
        with _lock:
            conn = _connect()
            for where, order in attempts:
                row = conn.execute(
                    f"SELECT {columns} FROM stardict WHERE {where} {order} LIMIT 1",
                    (word,),
                ).fetchone()
                if row is not None:
                    return _to_entry(row)
    except sqlite3.Error as exc:
        logger.warning("词典查询失败 word=%s: %s", word, exc)
        return None
    return None


def _split_lines(text: str | None) -> list[str]:
    if not text:
        return []
    return [line.strip() for line in str(text).splitlines() if line.strip()]


def parse_exchange(raw: str | None) -> tuple[dict[str, str], list[dict]]:
    """解析 ECDICT 的 exchange 字段，如 `p:went/d:gone/i:going/3:goes/0:go`。"""
    mapping: dict[str, str] = {}
    forms: list[dict] = []
    if not raw:
        return mapping, forms
    for piece in str(raw).split("/"):
        code, _, value = piece.partition(":")
        code, value = code.strip(), value.strip()
        if not code or not value:
            continue
        label = _EXCHANGE_LABELS.get(code, code)
        # 同一编码可能有多值（如 1: 变换形式），保留首个用于还原，全部用于展示
        mapping.setdefault(label, value)
        forms.append({"label": label, "value": value})
    return mapping, forms


def _to_entry(row: sqlite3.Row) -> Entry:
    exchange, forms = parse_exchange(row["exchange"])
    tags = [
        _TAG_LABELS.get(tag, tag)
        for tag in str(row["tag"] or "").split()
        if tag
    ]
    return Entry(
        word=row["word"] or "",
        phonetic=(row["phonetic"] or "").strip(),
        translation=_split_lines(row["translation"]),
        definition=_split_lines(row["definition"]),
        pos=(row["pos"] or "").strip(),
        tags=tags,
        collins=int(row["collins"] or 0),
        oxford=int(row["oxford"] or 0),
        bnc=int(row["bnc"] or 0),
        frq=int(row["frq"] or 0),
        exchange=exchange,
        forms=forms,
    )


# --------------------------- 词形还原 ---------------------------

_rules = (
    (re.compile(r"(.+)ies$"), lambda m: f"{m.group(1)}y"),
    (re.compile(r"(.+[^s])s$"), lambda m: m.group(1)),
    (re.compile(r"(.+)ied$"), lambda m: f"{m.group(1)}y"),
    (re.compile(r"(.+)ed$"), lambda m: m.group(1)),
    (re.compile(r"(.+)ing$"), lambda m: m.group(1)),
    (re.compile(r"(.+)ly$"), lambda m: m.group(1)),
)


def _rule_candidates(word: str) -> list[str]:
    """轻量规则候选（仅在能被词库验证时才会被采用）。"""
    out: list[str] = []
    for pattern, transform in _rules:
        match = pattern.match(word)
        if not match:
            continue
        base = transform(match)
        candidates = [base]
        if base and base[-1:] not in "aeiou":
            candidates.append(base[:-1])     # 双写辅音：running → run
        if word.endswith("ing"):
            candidates.append(word[:-3] + "e")  # making → make
        out.extend(c for c in candidates if len(c) >= 2)
    return out


def _lemminflect_candidates(word: str) -> list[str]:
    """用 lemminflect 生成候选原型（覆盖词库外的变形）。"""
    try:
        from lemminflect import getLemma  # type: ignore
    except Exception:  # noqa: BLE001  未安装则跳过
        return []
    candidates: list[str] = []
    for upos in ("VERB", "NOUN", "ADJ", "ADV", "AUX"):
        try:
            for item in getLemma(word, upos=upos) or ():
                if item and item.lower() != word:
                    candidates.append(item.lower())
        except Exception:  # noqa: BLE001
            continue
    return candidates


def lemma_candidates(word: str) -> list[str]:
    """给出该词的候选原型（去重、按优先级排序）。"""
    seen: set[str] = set()
    ordered: list[str] = []
    for candidate in (*_lemminflect_candidates(word), *_rule_candidates(word)):
        if candidate and candidate not in seen:
            seen.add(candidate)
            ordered.append(candidate)
    return ordered


def lookup(word: str) -> Lookup:
    """查询一个单词（含词形还原）。

    未安装词库时抛 `DictUnavailable`，由调用方转为友好提示。
    """
    query = normalize(word)
    result = Lookup(query=query)
    if not query or not is_lookupable(query):
        return result

    entry = _query(query)
    if entry is not None:
        proto = entry.exchange.get("原型")          # 查询词本身是变形
        if proto and proto.lower() != query:
            base = _query(proto.lower())
            if base is not None:
                result.entry, result.lemma, result.via = base, proto.lower(), "exchange"
                return result
        result.entry, result.via = entry, "exact"
        return result

    # 未命中 → 词形还原后再查
    for index, candidate in enumerate(lemma_candidates(query)):
        base = _query(candidate)
        if base is not None:
            result.entry = base
            result.lemma = candidate
            result.via = "lemminflect" if index < len(_lemminflect_candidates(query)) else "rule"
            return result
    return result


__all__ = [
    "DictUnavailable",
    "Entry",
    "Lookup",
    "available",
    "db_path",
    "entry_count",
    "is_lookupable",
    "lemma_candidates",
    "lookup",
    "normalize",
    "parse_exchange",
    "status",
]

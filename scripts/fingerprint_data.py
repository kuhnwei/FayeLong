#!/usr/bin/env python
"""`data/` 内容指纹（**只读**）—— 取代过脆的「文件 md5」作为数据安全不变量。

为什么不用文件 md5：`data/app.db` 是一个**本来就会被正常使用**的应用库 —— 任何一次
真实登录都会写 `users.last_login_at`，于是文件 md5 必然变化。用文件 md5 当不变量会把
「正常使用」误判成「数据被污染」。因此改看**内容指纹**：逐表逐行规范化后取 sha256，
并**显式排除易变字段**（默认 `users.last_login_at`，且会把排除清单打印出来，绝不静默）。

同时输出 `data/media/library/` 的目录清单哈希 —— 这样「误上传 / 误删媒体文件」也能被抓到。

用法
----
    # 默认指纹真实库 + 默认媒体库目录
    python scripts/fingerprint_data.py

    # 指定库 / 目录（例如对副本做敏感性验证）
    python scripts/fingerprint_data.py --db /tmp/app-copy.db
    python scripts/fingerprint_data.py --exclude '' --exclude users.last_login_at

输出（制表符分隔，便于 diff / grep）
-----------------------------------
    # ...注释...
    media	4	<行哈希>
    ...
    LIBRARY	4	<清单哈希>
    TOTAL	<总哈希>

退出码：0 成功；2 环境错误（库不存在等）。
"""

from __future__ import annotations

import argparse
import hashlib
import sqlite3
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DEFAULT_DB = REPO_ROOT / "data" / "app.db"
DEFAULT_LIBRARY = REPO_ROOT / "data" / "media" / "library"

#: 默认排除的易变字段（`表.字段`）。默认排除登录时间戳 —— 它在正常使用时就会变。
DEFAULT_EXCLUDE = ("users.last_login_at",)


def norm_value(value: object) -> str:
    """把一个单元格值规范化为**稳定**的字符串（跨运行一致）。

    类型前缀保证 `1`(int) 与 `'1'`(str) 不会撞成同一个指纹。
    """
    if value is None:
        return "\x00NULL"
    if isinstance(value, bytes):
        return "\x00BIN:" + value.hex()
    if isinstance(value, bool):  # bool 是 int 子类，先判
        return "\x00BOOL:" + ("1" if value else "0")
    if isinstance(value, int):
        return "\x00INT:" + str(value)
    if isinstance(value, float):
        return "\x00FLOAT:" + repr(value)
    return "\x00TEXT:" + str(value)


def table_names(con: sqlite3.Connection) -> list[str]:
    """全部用户表名（排除 SQLite 内部表），按名排序。"""
    rows = con.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [row[0] for row in rows]


def row_order_clause(con: sqlite3.Connection, table: str) -> str:
    """行排序子句：优先按主键，无主键则用 rowid（保证顺序稳定）。"""
    info = con.execute(f'PRAGMA table_info("{table}")').fetchall()
    pk = sorted((r for r in info if r[5] > 0), key=lambda r: r[5])
    if pk:
        return ", ".join(f'"{r[1]}"' for r in pk)
    return "rowid"


def fingerprint_table(con: sqlite3.Connection, table: str, exclude: set[str]) -> tuple[int, str]:
    """某表的 (行数, 行哈希)。行哈希 = 逐行规范化哈希再整体哈希。"""
    order = row_order_clause(con, table)
    cur = con.execute(f'SELECT * FROM "{table}" ORDER BY {order}')
    columns = [d[0] for d in cur.description]
    # 排除键是 `表.字段`（如 users.last_login_at），必须带上表名比较。
    kept = sorted(c for c in columns if f"{table}.{c}" not in exclude)

    digest = hashlib.sha256()
    count = 0
    for row in cur:
        values = {c: row[i] for i, c in enumerate(columns)}
        canonical = "\x1f".join(f"{c}={norm_value(values[c])}" for c in kept)
        digest.update(hashlib.sha256(canonical.encode("utf-8")).digest())
        count += 1
    return count, digest.hexdigest()


def fingerprint_library(root: Path) -> tuple[int, str]:
    """媒体库目录清单的 (条目数, 清单哈希)：递归列出「类型 + 相对路径 (+ 文件大小)」。"""
    digest = hashlib.sha256()
    count = 0
    if not root.is_dir():
        return 0, digest.hexdigest()

    entries: list[str] = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_dir():
            entries.append(f"D\t{rel}")
        else:
            entries.append(f"F\t{rel}\t{path.stat().st_size}")
    for line in entries:
        digest.update(hashlib.sha256(line.encode("utf-8")).digest())
        count += 1
    return count, digest.hexdigest()


def build_report(db_path: Path, library: Path, exclude: set[str]) -> list[str]:
    """产出完整指纹报告（注释行 + 数据行）。"""
    lines: list[str] = []
    lines.append("# data 内容指纹（只读 · 取代文件 md5）")
    lines.append(f"# 库文件：{db_path}")
    lines.append(f"# 媒体库目录：{library}")
    if exclude:
        lines.append("# 排除的易变字段（已从指纹中剔除）：" + ", ".join(sorted(exclude)))
    else:
        lines.append("# 排除的易变字段：无")

    con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    try:
        con.row_factory = None
        total = hashlib.sha256()
        for table in table_names(con):
            count, table_hash = fingerprint_table(con, table, exclude)
            lines.append(f"{table}\t{count}\t{table_hash}")
            total.update(f"{table}\t{count}\t{table_hash}\n".encode("utf-8"))
    finally:
        con.close()

    lib_count, lib_hash = fingerprint_library(library)
    lines.append(f"LIBRARY\t{lib_count}\t{lib_hash}")
    total.update(f"LIBRARY\t{lib_count}\t{lib_hash}\n".encode("utf-8"))

    lines.append(f"TOTAL\t{total.hexdigest()}")
    return lines


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="data/ 内容指纹（只读）")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite 库路径（默认 data/app.db）")
    parser.add_argument(
        "--library", default=str(DEFAULT_LIBRARY), help="媒体库目录（默认 data/media/library）"
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=None,
        metavar="TABLE.COLUMN",
        help="排除的易变字段（可重复；默认 users.last_login_at）",
    )
    args = parser.parse_args(argv)

    db_path = Path(args.db).resolve()
    if not db_path.is_file():
        sys.stderr.write(f"[fingerprint] 库不存在：{db_path}\n")
        return 2

    exclude = set(DEFAULT_EXCLUDE if args.exclude is None else args.exclude)
    exclude.discard("")
    lines = build_report(db_path, Path(args.library).resolve(), exclude)
    sys.stdout.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FayeLong 设计稿 · 主色一键同步脚本

用法（在 design 目录下）：
    python recolor.py            # 恢复为标准柠檬黄 #FFD93B
    python recolor.py #F7CE3E    # 全部页面换成指定主色

会同步 6 个页面（媒体库 / 学习页 / 生词本 / 练习 / 登录）里的 --lemon-400。
改完刷新对应 HTML 即可看到效果。
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

PAGES = [
    "page-1-library.html",
    "page-2-study.html",
    "page-3-vocab.html",
    "page-4-practice.html",
    "page-5-login.html",
    "page-6-stats.html",
]

DEFAULT = "#FFD93B"


def main() -> None:
    new = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", new):
        print(f"非法色值：{new}（应为 #RRGGBB）")
        sys.exit(1)
    new = new.upper()
    for name in PAGES:
        f = HERE / name
        if not f.exists():
            print("跳过（不存在）", name)
            continue
        s = f.read_text(encoding="utf-8")
        before = re.search(r"--lemon-400:#[0-9A-Fa-f]{6}", s)
        s2 = re.sub(r"--lemon-400:#[0-9A-Fa-f]{6}", f"--lemon-400:{new}", s)
        f.write_text(s2, encoding="utf-8")
        old = before.group(0).split(":")[1] if before else "?"
        print(f"{name}: {old} -> {new}")
    print("完成。对比页 color-compare.html 请在生成后重建（或直接改 --sw 内联值）。")


if __name__ == "__main__":
    main()

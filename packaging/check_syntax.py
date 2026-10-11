"""对目录下所有 .py 做语法检查（只解析、不执行、不产生 __pycache__）。

用法::

    python packaging/check_syntax.py <目录>

之所以不用 `compileall`：它会在源码旁边生成 `__pycache__`，污染交付包 staging。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 2:
        print("用法：python check_syntax.py <目录>")
        return 2
    root = Path(sys.argv[1])
    if not root.is_dir():
        print(f"[×] 目录不存在：{root}")
        return 1

    files = sorted(root.rglob("*.py"))
    bad: list[str] = []
    for path in files:
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError) as exc:
            bad.append(f"  · {path.relative_to(root)}：{exc}")

    if bad:
        print(f"[×] 有 {len(bad)} 个文件语法错误：")
        for line in bad:
            print(line)
        return 1
    print(f"[√] 语法检查通过：{len(files)} 个 .py 文件")
    return 0


if __name__ == "__main__":
    sys.exit(main())

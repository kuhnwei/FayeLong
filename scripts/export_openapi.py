#!/usr/bin/env python
"""导出后端的 OpenAPI 契约基线。

用途
----
前端 React→Vue3 重写期间，后端必须保持契约稳定。本脚本把 `app.openapi()`
固化成可提交、可 diff 的 JSON 基线（`contracts/openapi-v1.json`），
供 `scripts/check-contract.mjs` 做结构化比对。

关键约定
--------
1. **不依赖运行中的服务**：直接 `from app.main import app` 后调用
   `app.openapi()`。历史坑位——旧 uvicorn 占着 8000 端口会让新实例静默
   失败，从而读到过期契约。进程内调用彻底规避该问题。
2. **确定性输出**：`sort_keys=True` + 固定 `indent` + `ensure_ascii=False`
   + 结尾换行，保证同一份代码在任何机器上产出逐字节相同的文件，
   diff 才有意义。
3. **环境敏感差异**：`app/main.py` 的 SPA 回退路由 `/` 仅在
   `frontend/dist/index.html` 不存在时才注册，且未加
   `include_in_schema=False`。因此 dist 缺失时 `openapi()` 会凭空多出
   1 个 `"/"` operation。基线与校验都应在 dist 存在下进行；该差异由
   `check-contract.mjs` 显式容忍（打印「已忽略」及原因），不静默吞掉。

用法
----
    # 默认写入 <repo>/contracts/openapi-v1.json
    python scripts/export_openapi.py

    # 导出到临时文件（供 check-contract 做 diff）
    python scripts/export_openapi.py /tmp/openapi-now.json

    # 从 backend 目录运行亦可
    cd backend && .venv/Scripts/python ../scripts/export_openapi.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# 路径解析：本脚本位于 <repo>/scripts/，需要把 <repo>/backend 加入 sys.path
# 才能 `import app.main`（app 包在 backend/ 下）。
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
BACKEND_DIR = REPO_ROOT / "backend"

if not (BACKEND_DIR / "app").is_dir():
    sys.stderr.write(
        f"[export_openapi] 未找到后端应用目录：{BACKEND_DIR / 'app'}\n"
        f"[export_openapi] 请确认脚本位于 <repo>/scripts/ 下。\n"
    )
    sys.exit(2)

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

#: 默认基线输出路径。
DEFAULT_OUT = REPO_ROOT / "contracts" / "openapi-v1.json"


def build_spec() -> dict:
    """在进程内构造 OpenAPI 规范（不启动服务）。

    Returns:
        规范化后的 OpenAPI 字典。
    """
    # 延迟导入：仅在路径就绪后导入，避免 import 期副作用。
    from app.main import app  # noqa: PLC0415

    # `app.openapi()` 内部有缓存，直接调用即可获得完整规范。
    return app.openapi()


def count_endpoints(spec: dict) -> tuple[int, int]:
    """统计 path 数与 operation 数。

    Args:
        spec: OpenAPI 规范字典。

    Returns:
        (path_count, operation_count)。operation 仅统计 HTTP 方法键
        （get/post/put/delete/patch/options/head/trace）。
    """
    http_methods = {"get", "post", "put", "delete", "patch", "options", "head", "trace"}
    paths = spec.get("paths", {}) or {}
    operations = 0
    for item in paths.values():
        operations += sum(1 for method in item if method.lower() in http_methods)
    return len(paths), operations


def dump_spec(spec: dict, out_path: Path) -> None:
    """把规范以确定性方式写入文件。

    Args:
        spec: OpenAPI 规范字典。
        out_path: 输出文件路径（父目录会自动创建）。
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(
        spec,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    )
    # 结尾统一补一个换行，避免不同工具链对「末尾换行」的处理差异。
    out_path.write_text(text + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    """脚本入口。

    Args:
        argv: 命令行参数（不含脚本名）。可选第一个参数为输出路径。

    Returns:
        进程退出码。
    """
    out_path = Path(argv[0]).resolve() if argv else DEFAULT_OUT
    spec = build_spec()
    dump_spec(spec, out_path)
    path_count, op_count = count_endpoints(spec)
    print(f"[export_openapi] 已写入：{out_path}")
    print(f"[export_openapi] paths = {path_count}, operations = {op_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

"""P0-4 基建冒烟测试。

目的不是覆盖业务逻辑（那是 P0-5 / P0-6 的事），而是**证明测试网本身可用**：

1. 数据目录重定向确实生效（`DB_PATH` 落在会话临时根下，绝不指向真实 `data/`）；
2. `client` fixture 能触发 lifespan（`ensure_dirs()` + `init_db()` + `requeue_unfinished()`），
   且这一切都作用在临时库上；
3. 一次真实 HTTP 调用（公开的 `/api/health`）能跑通，并回显已重定向的路径。
"""

from __future__ import annotations

from pathlib import Path

import app.core.config as config
from app.core.config import DB_PATH


def test_db_path_redirected_out_of_real_data():
    """护栏复核：DB_PATH 必须在临时根下，且不在真实 data/ 下。"""
    db_path = Path(DB_PATH).resolve()
    real_data = (config.ROOT_DIR / "data").resolve()

    assert "fayelong-pytest-" in str(db_path), f"未重定向：{db_path}"
    try:
        db_path.relative_to(real_data)
    except ValueError:
        pass
    else:
        raise AssertionError(f"DB_PATH 竟指向真实 data/：{db_path}")


def test_health_endpoint_uses_tmp_database(client, tmp_runtime_root):
    """/api/health 应返回 200，且回显的 db 路径位于临时根下。"""
    resp = client.get("/api/health")
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert body["status"] == "ok"

    reported_db = Path(body["paths"]["db"]).resolve()
    assert str(reported_db).startswith(str(tmp_runtime_root.resolve())), (
        f"health 回显的 db 路径不在临时根下：{reported_db}"
    )
    assert reported_db == Path(DB_PATH).resolve()

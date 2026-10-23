"""`init_db()` 的并发首启安全性（G3-④ 打包版首次启动的回归用例）。

背景（P3-6 实测的缺陷）
======================
P3-2 之后 **web 与 worker 是两个进程**，两边启动时都调 `init_db()`。
`create_all(checkfirst=True)` 是「先反射查存在性 → 再 CREATE TABLE」两步，
**不是原子的**：

* 打包版首次启动（`dist\\FayeLong` 全新解压）—— launcher 先写 pid、再起 worker、
  然后才 `uvicorn.run`，两个进程几乎同时 `init_db()`；
* 云端首次部署 —— `fayelong.service` 与 `fayelong-worker.service` 同时启动。

实测失败原文（`data/logs/worker.out`）::

    sqlite3.OperationalError: table notes already exists
    sqlite3.exc.OperationalError: (sqlite3.OperationalError) table notes already exists
      File ".../app/db.py", line 145, in init_db
        Base.metadata.create_all(bind=engine)

worker 进程直接崩掉，web 随后按 `FAYELONG_WEB_INPROC_WORKER=auto` 降级为进程内执行
—— 功能「看起来正常」，但双进程分离（G3-④）形同虚设，且用户零提示。

修法：`_create_all_tolerant()` —— 只把「已经存在」类错误当幂等重试，
**真正的 DDL 错误立即抛出**。本文件钉死这两条边界。
"""

from __future__ import annotations

import os
import pathlib
import shutil
import sqlite3
import subprocess
import sys
import time

import pytest
from sqlalchemy.exc import OperationalError

from app import db as db_module


def _already_exists_error() -> OperationalError:
    """构造一个与实测完全同形的 `table ... already exists` 异常。"""
    return OperationalError(
        "CREATE TABLE notes (id INTEGER NOT NULL)",
        {},
        sqlite3.OperationalError("table notes already exists"),
    )


class TestIsAlreadyExists:
    @pytest.mark.parametrize(
        "message",
        [
            "table notes already exists",
            "index ix_media_category_id already exists",
            "duplicate column name: marks",
            "TABLE NOTES ALREADY EXISTS",          # 大小写不敏感
        ],
    )
    def test_markers_are_treated_as_idempotent(self, message):
        error = OperationalError("stmt", {}, sqlite3.OperationalError(message))
        assert db_module._is_already_exists(error) is True

    @pytest.mark.parametrize(
        "message",
        ["database is locked", "no such table: media", "disk I/O error"],
    )
    def test_other_errors_are_not_swallowed(self, message):
        error = OperationalError("stmt", {}, sqlite3.OperationalError(message))
        assert db_module._is_already_exists(error) is False


class TestCreateAllTolerant:
    def test_retries_then_succeeds(self, monkeypatch):
        """先撞一次「表已存在」，重试后成功 —— 这正是两个进程的收敛过程。"""
        calls: list[int] = []

        def flaky(bind=None, **_kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise _already_exists_error()
            return None

        monkeypatch.setattr(db_module.Base.metadata, "create_all", flaky)
        monkeypatch.setattr(db_module, "_CREATE_ALL_RETRY_SEC", 0)

        db_module._create_all_tolerant()

        assert len(calls) == 2, "应当重试一次并成功"

    def test_gives_up_after_max_attempts(self, monkeypatch):
        """一直撞「已存在」也不会无限重试（防止病态环境下卡死启动）。"""
        calls: list[int] = []

        def always(bind=None, **_kwargs):
            calls.append(1)
            raise _already_exists_error()

        monkeypatch.setattr(db_module.Base.metadata, "create_all", always)
        monkeypatch.setattr(db_module, "_CREATE_ALL_RETRY_SEC", 0)

        with pytest.raises(OperationalError):
            db_module._create_all_tolerant()

        assert len(calls) == db_module._CREATE_ALL_ATTEMPTS

    def test_real_ddl_error_is_raised_immediately(self, monkeypatch):
        """非「已存在」类错误必须立刻抛，且**不重试**（不能掩盖真故障）。"""
        calls: list[int] = []

        def boom(bind=None, **_kwargs):
            calls.append(1)
            raise OperationalError(
                "CREATE TABLE media", {}, sqlite3.OperationalError("disk I/O error")
            )

        monkeypatch.setattr(db_module.Base.metadata, "create_all", boom)
        monkeypatch.setattr(db_module, "_CREATE_ALL_RETRY_SEC", 0)

        with pytest.raises(OperationalError, match="disk I/O error"):
            db_module._create_all_tolerant()

        assert len(calls) == 1, "真错误不许重试"


class TestEnsureColumnsConcurrent:
    def test_duplicate_column_race_is_tolerated(self, monkeypatch, tmp_path):
        """`PRAGMA` 与 `ALTER` 之间被另一进程抢先加列 → 吞掉，不算失败。"""
        statements: list[str] = []

        class FakeConn:
            def exec_driver_sql(self, sql):
                statements.append(sql)
                if sql.startswith("ALTER TABLE"):
                    raise OperationalError(
                        sql,
                        {},
                        sqlite3.OperationalError("duplicate column name: marks"),
                    )

                class _Result:
                    @staticmethod
                    def fetchall():
                        # 表存在但缺 marks 列（模拟「另一个进程刚好在这一刻加上」）
                        return [(0, "id", "INTEGER")]

                return _Result()

        class FakeBegin:
            def __enter__(self):
                return FakeConn()

            def __exit__(self, *_exc):
                return False

        monkeypatch.setattr(db_module.engine, "begin", lambda: FakeBegin())

        db_module._ensure_columns()      # 不抛异常

        assert any(sql.startswith("ALTER TABLE sentences") for sql in statements)

    def test_init_db_is_idempotent(self):
        """连调两次 `init_db()` 不该报错（启动 + 测试 fixture 都会调）。"""
        db_module.init_db()
        db_module.init_db()


# ---------------------------------------------------------------------------
# R1（QA 在双进程毫秒对齐实验里挖出的缺口）：
# 「瞬时 DDL 错误」也必须重试，否则 worker 进程会直接退出
# ---------------------------------------------------------------------------
# 症状与「两个进程抢着建表」完全一样（worker 死 → web 静默降级 web-inproc），
# 只是文案不同：`attempt to write a readonly database` /
# `database is locked`。QA 实测 D 盘 10 轮里 3 轮命中 readonly；同目录立刻重跑
# 0.045s 成功 → 是瞬时态，不是权限问题。
# ---------------------------------------------------------------------------


def _op_error(message: str, statement: str = "CREATE TABLE categories (id INTEGER)") -> OperationalError:
    """构造与 SQLite 原文同形的 `OperationalError`。"""
    return OperationalError(statement, {}, sqlite3.OperationalError(message))


class TestTransientDdlMarkers:
    @pytest.mark.parametrize(
        "message",
        [
            "attempt to write a readonly database",
            "database is locked",
            "DATABASE IS LOCKED",                      # 大小写不敏感
        ],
    )
    def test_transient_markers_are_retryable(self, message):
        error = _op_error(message)
        assert db_module._is_transient_ddl_error(error) is True
        assert db_module._is_retryable_ddl_error(error) is True
        # 它们**不是**「已存在」类，两个判据要分开（否则日志与语义都会撒谎）
        assert db_module._is_already_exists(error) is False

    @pytest.mark.parametrize(
        "message",
        [
            "disk I/O error",
            "no such table: media",
            "unable to open database file",
            "database disk image is malformed",
        ],
    )
    def test_hard_errors_are_not_retryable(self, message):
        """真故障必须立刻抛：把「盘坏了」重试成「启动慢 1.5s 后照旧失败」是掩盖。"""
        error = _op_error(message)
        assert db_module._is_transient_ddl_error(error) is False
        assert db_module._is_retryable_ddl_error(error) is False


class TestCreateAllRetriesTransientErrors:
    @pytest.mark.parametrize(
        "message",
        ["attempt to write a readonly database", "database is locked"],
    )
    def test_retries_then_succeeds(self, monkeypatch, message):
        """瞬时态：第一次抛、第二次成功 → 必须重试而不是崩。"""
        calls: list[int] = []

        def flaky(bind=None, **_kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise _op_error(message)
            return None

        monkeypatch.setattr(db_module.Base.metadata, "create_all", flaky)
        monkeypatch.setattr(db_module, "_CREATE_ALL_RETRY_SEC", 0)

        db_module._create_all_tolerant()

        assert len(calls) == 2

    @pytest.mark.parametrize(
        "message",
        ["disk I/O error", "no such table: media", "unable to open database file"],
    )
    def test_hard_error_raises_without_retry(self, monkeypatch, message):
        """真故障：**一次都不许重试**（断言调用次数，而不只是「最终抛了」）。"""
        calls: list[int] = []

        def boom(bind=None, **_kwargs):
            calls.append(1)
            raise _op_error(message)

        monkeypatch.setattr(db_module.Base.metadata, "create_all", boom)
        monkeypatch.setattr(db_module, "_CREATE_ALL_RETRY_SEC", 0)

        with pytest.raises(OperationalError):
            db_module._create_all_tolerant()

        assert len(calls) == 1, f"{message} 不该重试，实际尝试 {len(calls)} 次"


# ---------------------------------------------------------------------------
# G2：真进程并发（不是 mock）—— 两个真进程同时打同一个新库
# ---------------------------------------------------------------------------
# 判据：① 两个进程都成功（rc=0 且打印 INIT_OK）；② 表齐（18 张）。
# 这条用例的判别力来自「真并发」：mock 版只能验重试分支写没写对，验不了「并发真的
# 会撞」以及「撞了之后两边能否收敛到同一套结构」。
# ---------------------------------------------------------------------------

#: 子进程脚本：先补丁 `app.core.config` 的路径常量（必须在 import `app.db` 之前，
#: 因为 `db.py` 在 import 时就 `create_engine(DB_PATH)`），再到**文件屏障**上等齐，
#: 最后 `init_db()`。用文件屏障而不是固定 sleep：所有子进程真正同一毫秒开始 DDL。
_CHILD_SCRIPT = r"""
import os, sys, time, pathlib

root = pathlib.Path(sys.argv[1])
import app.core.config as config

data = root / "data"
config.DATA_DIR = data
config.MEDIA_DIR = data / "media"
config.INBOX_DIR = data / "media" / "audio"
config.LIBRARY_DIR = data / "media" / "library"
config.MODELS_DIR = data / "models"
config.DICT_DIR = data / "dict"
config.LOG_DIR = data / "logs"
config.DB_PATH = data / "app.db"
for _path in (config.MEDIA_DIR, config.INBOX_DIR, config.LIBRARY_DIR,
              config.MODELS_DIR, config.DICT_DIR, config.LOG_DIR):
    _path.mkdir(parents=True, exist_ok=True)

from app.db import init_db

(root / ("ready-" + str(os.getpid()))).write_text("1")
deadline = time.time() + 30
while not (root / "go").exists():
    if time.time() > deadline:
        print("BARRIER_TIMEOUT", flush=True)
        raise SystemExit(3)
    time.sleep(0.0002)

init_db()
print("INIT_OK", flush=True)
"""

#: 一轮里起几个进程。8 个并发把 DDL 挤到同一毫秒的**争抢最激烈**（实测未修版本
#: 单进程失败率 ≈37%，而 4 进程时只有 ≈14%）：所以**少量高并发**比「多轮低并发」
#: 既快又更容易命中。
_PROCS_PER_ROUND = 8
#: 跑几轮。1 轮 × 8 进程已实测 6/6 次出现失败（≈4.2s）；加轮数只增耗时。
_ROUNDS = 1
#: 19 = 9 张老表 + P3-2 的 jobs/workers + P4-3 的 7 张 IELTS 表 + v1.16.2 的 sentence_marks。
#: ⚠️ 加表时必须同步改这里：它的作用是「并发首启后表一张都不许缺」，
#:    写成字典序清单而不是数量会更严格，但这条用例的判据本身是「数量齐」。
_EXPECTED_TABLES = 19


def _app_root() -> pathlib.Path:
    """`app` 包所在目录（开发环境是 `backend/`；沙箱里就是沙箱根）。"""
    return pathlib.Path(db_module.__file__).resolve().parents[1]


def _spawn_child(root: pathlib.Path, env: dict[str, str]) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-c", _CHILD_SCRIPT, str(root)],
        env=env,
        cwd=str(_app_root()),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _run_concurrent_round(root: pathlib.Path) -> list[tuple[int, str, str]]:
    """起 `_PROCS_PER_ROUND` 个真进程，用文件屏障对齐，收齐结果。"""
    root.mkdir(parents=True, exist_ok=True)
    env = {**os.environ}
    env["PYTHONPATH"] = os.pathsep.join(
        [str(_app_root())] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])
    )

    children = [_spawn_child(root, env) for _ in range(_PROCS_PER_ROUND)]
    try:
        # 等所有子进程「已 import 完、正卡在屏障前」
        deadline = time.time() + 25
        while time.time() < deadline:
            ready = list(root.glob("ready-*"))
            if len(ready) >= _PROCS_PER_ROUND:
                break
            if all(child.poll() is not None for child in children):
                break
            time.sleep(0.01)
        (root / "go").write_text("1")          # ★ 放行：所有子进程同一毫秒开始 DDL

        results: list[tuple[int, str, str]] = []
        for child in children:
            try:
                out, err = child.communicate(timeout=30)
            except subprocess.TimeoutExpired:      # pragma: no cover - 极端卡死
                child.kill()
                out, err = child.communicate()
                err = (err or "") + "\nTIMEOUT"
            results.append((child.returncode or 0, out or "", err or ""))
        return results
    finally:
        for child in children:
            if child.poll() is None:               # pragma: no cover - 兜底
                child.kill()


def _warn_rmtree_failure(_func, path, exc_info) -> None:
    """`shutil.rmtree` 的 onerror：清理失败要**出声**，不许静默。

    Notes:
        上一版用的是 `ignore_errors=True`，而 Windows 上如果有连接没关（`sqlite3`
        的 `with` 只提交事务、**不关闭连接**），`app.db` 删不掉且毫无提示 —— 每跑
        一次就静默残留几百 KB。这里改成打印到 stderr，让问题在输出里可见。
    """
    print(f"[test-db-init] 清理临时目录失败（忽略，但请留意）：{path} -> {exc_info[1]}",
          file=sys.stderr)


class TestRealProcessConcurrency:
    def test_concurrent_init_db_converges(self, tmp_path):
        """`_PROCS_PER_ROUND` 个**真进程**同时 `init_db()`：全部必须成功、表必须齐。

        ⚠️ **本用例是「统计性」的，不是确定性门禁**：
            它靠真实竞态触发缺陷，单次运行**不保证**一定撞上（实测未修版本
            6/6 次都撞上了，失败进程率 ≈37%，但这是本机实测值，换机器/换负载会变）。
            **确定性守卫是 `TestCreateAllRetriesTransientErrors` 里的参数化单测**
            —— 「readonly/locked 必须重试、disk I/O 等硬错误必须立刻抛且不重试」。
            两条一起看：单测保证**重试逻辑**正确，本条保证**真实并发下确实会撞、
            且撞了能收敛**。别把这条当唯一的门禁。

        Raises:
            AssertionError: 有子进程 rc≠0 / 没打印 INIT_OK，或表数不足 18 张。
        """
        failures: list[str] = []
        try:
            for round_index in range(_ROUNDS):
                root = tmp_path / f"round{round_index}"
                for returncode, out, err in _run_concurrent_round(root):
                    if returncode != 0 or "INIT_OK" not in out:
                        failures.append(
                            f"round{round_index}: rc={returncode}\n"
                            f"  stdout={out.strip()[-300:]}\n"
                            f"  stderr={err.strip()[-600:]}"
                        )
                db_file = root / "data" / "app.db"
                assert db_file.is_file(), f"round{round_index} 没有建出库文件"

                # ⚠️ `sqlite3` 的 `with` 只提交事务、**不关闭连接**（不是
                # `contextlib.closing`）→ 必须显式 close，否则下面 rmtree 删不掉
                # app.db（Windows 上文件仍被持有），会静默残留。
                conn = sqlite3.connect(db_file)
                try:
                    names = {
                        row[0]
                        for row in conn.execute(
                            "SELECT name FROM sqlite_master WHERE type='table'"
                        )
                    }
                finally:
                    conn.close()
                assert len(names) == _EXPECTED_TABLES, \
                    f"round{round_index} 表数不对：{sorted(names)}"
                assert {"media", "sentences", "jobs", "workers"} <= names

            assert not failures, (
                "并发 init_db 有进程失败（未修版本就会这样：瞬时 DDL 错误没有被重试）:\n"
                + "\n".join(failures)
            )
        finally:
            # 收尾自清：一轮会产生十几个 ready-* 标记文件与库文件，没必要留给
            # pytest 的 tmp 垃圾回收（也免得批量删除时弹确认）。
            shutil.rmtree(tmp_path, onerror=_warn_rmtree_failure)


"""崩溃恢复的集成验收：**真子进程 + 真 kill**（G3-②）。

为什么必须是子进程
==================
`kill -9` 的本质是「进程内的所有线程同时消失、`workers` 行残留、心跳停止」。
在线程里模拟不了这件事（`threading` 无法被"杀掉"），所以这里起**真进程**，
用 `proc.kill()`（Windows 上是 `TerminateProcess`，语义等价于 `kill -9`）。

子进程怎么指向临时库
====================
`app/core/config.py` 的路径是**模块级常量、不读环境变量**，而 `app/db.py` 在
import 时就把 engine 绑到 `DB_PATH`。因此子进程的引导脚本必须**先给
`app.core.config` 打补丁、再 import 任何 `app.db` / `app.worker`**（与
`tests/conftest.py` 同一招）。`job_*` 阈值则走环境变量（`Settings` 读 env，
子进程是全新 import，天然生效）—— 这样**不必把 TTL 改到 1s 才能过**：
每个用例都会打印自己用的真实阈值，便于复核不是假绿。

本文件刻意**不**复用 conftest 的会话级临时库：崩溃恢复需要一个「能被我自由
kill、且可以反复重建」的隔离根目录，用 `tmp_path` 最干净。
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

import pytest

_BACKEND_DIR = Path(__file__).resolve().parents[1]

#: 子进程引导脚本模板。占位符用 `str.format` 填充（脚本里出现的花括号必须写成 `{{}}`）。
_CHILD_TEMPLATE = r'''
import sys, time
from pathlib import Path

sys.path.insert(0, r"{backend}")
import app.core.config as cfg

root = Path(r"{root}")
cfg.DATA_DIR = root / "data"
cfg.MEDIA_DIR = cfg.DATA_DIR / "media"
cfg.INBOX_DIR = cfg.MEDIA_DIR / "audio"
cfg.LIBRARY_DIR = cfg.MEDIA_DIR / "library"
cfg.MODELS_DIR = root / "models"
cfg.DICT_DIR = root / "dict"
cfg.LOG_DIR = cfg.DATA_DIR / "logs"
cfg.DB_PATH = cfg.DATA_DIR / "app.db"
for directory in (cfg.DATA_DIR, cfg.MEDIA_DIR, cfg.INBOX_DIR, cfg.LIBRARY_DIR,
                  cfg.MODELS_DIR, cfg.DICT_DIR, cfg.LOG_DIR):
    directory.mkdir(parents=True, exist_ok=True)

from app.db import SessionLocal, init_db
from app.models import Media
from app.services import jobs
import app.worker as w

init_db()
# 本文件只验证「崩溃恢复 + 双跑防护」，不验证链式推进：关掉 asr → translate 的接力
jobs.NEXT_STAGE[jobs.KIND_ASR] = None

MODE = {mode!r}
COUNTER = Path(r"{counter}")

def mark(text):
    with COUNTER.open("a", encoding="utf-8") as fh:
        fh.write(text + "\n")

def write_media(status, progress):
    db = SessionLocal()
    try:
        media = db.get(Media, 1)
        if media is not None:
            media.status = status
            media.progress = progress
            media.error = None
        db.commit()
    finally:
        db.close()

if MODE == "hold":
    def handler(ctx):
        mark("hold-start")
        # 模拟真实 stage 的「进度写 + 续租同一 commit」，fencing 失败即自杀
        db = SessionLocal()
        try:
            try:
                while True:
                    media = db.get(Media, 1)
                    if media is not None:
                        media.progress = 50
                    alive = jobs.touch(db, ctx.job_id, ctx.my_attempt, ctx.worker_id)
                    if not alive:
                        db.rollback()
                        raise w.JobAborted("已被回收")
                    db.commit()
                    time.sleep(0.05)
            except w.JobAborted:
                mark("hold-aborted")
                raise
            mark("hold-completed")
        finally:
            db.close()
elif MODE == "hold-sleep":
    def handler(ctx):
        mark("hold-sleep")
        # 长时间阻塞调用（模拟 whisper 的一次 transcribe）：期间**不续租**，
        # 于是租约自然过期 —— 这正是「任务其实还活着但心跳超时」的现场。
        time.sleep({sleep_sec})
        db = SessionLocal()
        try:
            media = db.get(Media, 1)
            if media is not None:
                media.progress = 50
            alive = jobs.touch(db, ctx.job_id, ctx.my_attempt, ctx.worker_id)
            if not alive:
                db.rollback()
                mark("hold-aborted")
                raise w.JobAborted("已被回收")
            db.commit()
            mark("hold-completed")
        finally:
            db.close()
else:
    def handler(ctx):
        mark("recover")
        write_media("done", 100)

w.Worker.HANDLERS = {{**w.HANDLERS, jobs.KIND_ASR: handler}}

db = SessionLocal()
try:
    if db.get(Media, 1) is None:
        db.add(Media(id=1, title="recovery", type="audio", original_name="a.mp3",
                     file_path="data/media/library/1/a.mp3"))
        db.commit()
    if {enqueue}:
        jobs.enqueue(jobs.KIND_ASR, 1)
finally:
    db.close()

w.main(argv={argv!r})
'''


# ---------------------------------------------------------------------------
# 子进程 / DB 探针
# ---------------------------------------------------------------------------


def _build_script(
    root: Path, mode: str, *, enqueue: bool, argv: list[str], sleep_sec: float = 0.0
) -> str:
    """渲染子进程引导脚本。"""
    return _CHILD_TEMPLATE.format(
        backend=str(_BACKEND_DIR).replace("\\", "/"),
        root=str(root).replace("\\", "/"),
        counter=str(root / "counter.txt").replace("\\", "/"),
        mode=mode,
        enqueue=enqueue,
        argv=argv,
        sleep_sec=sleep_sec,
    )


def _spawn(root: Path, mode: str, *, enqueue: bool, argv: list[str],
           env_extra: dict[str, str] | None = None,
           sleep_sec: float = 0.0) -> subprocess.Popen:
    """起一个真 worker 子进程（输出重定向到文件，避免管道阻塞）。"""
    env = {**os.environ}
    env.update(env_extra or {})
    log_path = root / f"child-{mode}-{time.monotonic_ns()}.log"
    handle = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, "-c",
         _build_script(root, mode, enqueue=enqueue, argv=argv, sleep_sec=sleep_sec)],
        cwd=str(_BACKEND_DIR),
        env=env,
        stdout=handle,
        stderr=subprocess.STDOUT,
    )
    process._fayelong_log = handle  # type: ignore[attr-defined]  便于 teardown 关闭
    process._fayelong_log_path = log_path  # type: ignore[attr-defined]
    return process


def _stop(process: subprocess.Popen | None) -> None:
    """尽力收掉子进程与其日志句柄。"""
    if process is None:
        return
    if process.poll() is None:
        try:
            process.kill()
            process.wait(timeout=10)
        except Exception:  # noqa: BLE001
            pass
    handle = getattr(process, "_fayelong_log", None)
    if handle is not None and not handle.closed:
        handle.close()


def _db_path(root: Path) -> Path:
    return root / "data" / "app.db"


def _query(root: Path, sql: str, params: tuple = ()) -> list[tuple]:
    """直接读临时库（不经 ORM，避免缓存干扰跨进程观察）。"""
    conn = sqlite3.connect(str(_db_path(root)), timeout=15)
    try:
        return [tuple(row) for row in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def _job_state(root: Path) -> tuple | None:
    rows = _query(
        root,
        "SELECT id, status, attempts, worker_id, error FROM jobs ORDER BY id DESC LIMIT 1",
    )
    return rows[0] if rows else None


def _media_state(root: Path) -> tuple | None:
    rows = _query(root, "SELECT status, progress FROM media WHERE id = 1")
    return rows[0] if rows else None


def _wait_until(predicate: Callable[[], bool], timeout: float, *, interval: float = 0.1) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if predicate():
                return True
        except sqlite3.Error:
            pass   # 子进程持有写锁时重试
        time.sleep(interval)
    return False


def _counter(root: Path) -> list[str]:
    path = root / "counter.txt"
    if not path.is_file():
        return []
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line]


#: 子进程用的阈值（**会被打印**，防止「把 TTL 调到 1s 才过」的假绿）。
_CHILD_ENV = {
    # ★ CPU 池必须钉成 1：默认 `job_cpu_threads=0` 会取 `os.cpu_count()`（本机 8），
    #   于是一个进程能同时跑 8 个 handler —— 「单进程不会自我并发」这个前提就不成立了，
    #   用例会看到同一进程把回收后的任务又抢一遍（实测过）。
    "FAYELONG_JOB_CPU_THREADS": "1",
    "FAYELONG_JOB_HEARTBEAT_INTERVAL_SEC": "1",
    "FAYELONG_JOB_WORKER_TTL_SEC": "3",
    "FAYELONG_JOB_LEASE_INTERVAL_SEC": "1",
    "FAYELONG_JOB_LEASE_TTL_SEC": "5",
    "FAYELONG_JOB_POLL_INTERVAL_MS": "100",
    "FAYELONG_JOB_IDLE_MAX_MS": "300",
    "FAYELONG_JOB_MAX_ATTEMPTS": "3",
}


@pytest.fixture(autouse=True)
def _report_thresholds() -> Any:
    """把本文件使用的阈值打出来（复核时先看这里）。"""
    print(
        "\n[worker-recovery] 阈值："
        + " ".join(f"{key.replace('FAYELONG_JOB_', '').lower()}={value}"
                   for key, value in(sorted(_CHILD_ENV.items())))
    )
    yield


# ---------------------------------------------------------------------------
# G3-②：kill -9 之后重启能恢复
# ---------------------------------------------------------------------------


def test_kill9_then_restart_recovers(tmp_path: Path) -> None:
    """A 被 kill -9 → B 启动后回收并重跑 → `attempts == 2`、media 轴被推进。"""
    processes: list[subprocess.Popen] = []
    try:
        process_a = _spawn(
            tmp_path, "hold", enqueue=True,
            argv=["--pools", "cpu", "--no-recovery"],
            env_extra=_CHILD_ENV,
        )
        processes.append(process_a)
        assert _wait_until(lambda: (_job_state(tmp_path) or ("", ""))[1] == "running", 20.0), (
            f"A 没能在 20s 内认领任务：{_job_state(tmp_path)!r}"
        )
        state_before = _job_state(tmp_path)
        assert state_before is not None
        assert state_before[2] == 1, "首次 claim 的 attempts 应为 1"

        # 真 kill -9（Windows 上 proc.kill() == TerminateProcess）
        process_a.kill()
        process_a.wait(timeout=20)
        assert process_a.returncode is not None

        process_b = _spawn(tmp_path, "recover", enqueue=False,
                           argv=["--pools", "cpu"], env_extra=_CHILD_ENV)
        processes.append(process_b)

        assert _wait_until(lambda: (_job_state(tmp_path) or ("", ""))[1] == "done", 30.0), (
            f"B 没能在 30s 内接管并完成任务：job={_job_state(tmp_path)!r} "
            f"counter={_counter(tmp_path)!r}"
        )

        job = _job_state(tmp_path)
        assert job is not None
        assert job[2] == 2, f"attempts 应为 2（A 一次 + B 一次），实际 {job[2]}"
        # worker_id 必须换成 B（B 的 id 就是 workers 表里那一行）
        worker_ids = [row[0] for row in _query(tmp_path, "SELECT id FROM workers")]
        assert job[3] in worker_ids, f"job.worker_id={job[3]!r} 不在 {worker_ids!r}"
        assert job[3] != state_before[3], "worker_id 应该换人（证明是 B 接管的）"

        # media 轴被 B 推进到 done（同一轮执行里写入）
        assert _media_state(tmp_path) == ("done", 100), _media_state(tmp_path)
        assert _counter(tmp_path).count("recover") == 1
    finally:
        for process in processes:
            _stop(process)


# ---------------------------------------------------------------------------
# 双跑防护：假超时（心跳被误判）也不许两个执行者同时写 media
# ---------------------------------------------------------------------------


def test_stale_running_job_is_not_double_run(tmp_path: Path) -> None:
    """A 其实还活着，但租约被判过期 → B 接管后，A 的写回必须被 fencing 拒绝。

    场景刻意做成「A 卡在一次长阻塞调用里、期间不续租」（真实对应 whisper 的一次
    `transcribe()`）：A 的租约自然过期 → B 依规接管 → A 醒来后写回时
    `WHERE attempts=?` 已不匹配 → `JobAborted`，**不写 media 轴**。

    A 的 `FAYELONG_JOB_LEASE_INTERVAL_SEC` 被调到 3600s：正常运行时 ticker 会替
    handler 续租（这正是「心跳被卡住」很难发生的原因），本用例要模拟的是
    **ticker 也被卡住**（GIL 饥饿 / swap / 长 GC）的极端情况。

    断言（全部可复核，不靠人眼）：
      * A 的 handler 被调用 1 次、B 1 次；
      * A 以 `JobAborted` 结束（counter 里有 `hold-aborted`、**没有** `hold-completed`）；
      * `media` 轴最终是 B 写的 `done/100`（A 的 `progress=50` 被回滚）。
    """
    processes: list[subprocess.Popen] = []
    try:
        env_a = {**_CHILD_ENV, "FAYELONG_JOB_LEASE_INTERVAL_SEC": "3600"}
        process_a = _spawn(
            tmp_path, "hold-sleep", enqueue=True,
            argv=["--pools", "cpu", "--no-recovery"], env_extra=env_a,
            sleep_sec=9.0,
        )
        processes.append(process_a)
        assert _wait_until(lambda: (_job_state(tmp_path) or ("", ""))[1] == "running", 20.0), (
            f"A 没能在 20s 内认领任务：{_job_state(tmp_path)!r}"
        )
        assert _wait_until(lambda: "hold-sleep" in _counter(tmp_path), 10.0)

        process_b = _spawn(tmp_path, "recover", enqueue=False,
                           argv=["--pools", "cpu"], env_extra=_CHILD_ENV)
        processes.append(process_b)

        assert _wait_until(lambda: (_job_state(tmp_path) or ("", ""))[1] == "done", 30.0), (
            f"B 没能在 30s 内接管：job={_job_state(tmp_path)!r} counter={_counter(tmp_path)!r}"
        )
        # A 在 sleep 结束后写回，此时 fencing 必须让它自杀
        assert _wait_until(lambda: "hold-aborted" in _counter(tmp_path), 25.0), (
            f"A 没有因 fencing 自杀：{_counter(tmp_path)!r}"
        )

        events = _counter(tmp_path)
        assert events.count("hold-sleep") == 1, events
        assert events.count("recover") == 1, events
        assert "hold-completed" not in events, f"A 竟然正常跑完了：{events!r}"

        job = _job_state(tmp_path)
        assert job is not None and job[2] == 2, job
        # media 轴只有 B 的写（A 的 progress=50 被回滚掉）
        assert _media_state(tmp_path) == ("done", 100), _media_state(tmp_path)
    finally:
        for process in processes:
            _stop(process)


# ---------------------------------------------------------------------------
# 正常退出：workers 行必须消失（否则 auto 模式下 web 永远不会接管）
# ---------------------------------------------------------------------------


def test_worker_unregisters_on_graceful_exit(tmp_path: Path) -> None:
    """`--parent-pid` 守护触发正常退出后，`workers` 表里不能留下自己的行。

    为什么不用 `proc.terminate()`：Windows 上它是 `TerminateProcess`，子进程
    没有机会跑 `finally`（`workers` 行会残留 —— 这属于「被 kill」而不是「优雅退出」，
    已由上一个用例覆盖）。这里用 `--parent-pid` 的孤儿自检触发**优雅退出**，
    POSIX 上的 `terminate()` 路径另有一条 `skipif` 用例。
    """
    pid_file = tmp_path / "data" / "logs" / "fayelong.pid"
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text("424242", encoding="ascii")

    process = _spawn(
        tmp_path, "idle", enqueue=False,
        argv=["--pools", "cpu", "--no-recovery", "--parent-pid", "424242"],
        env_extra=_CHILD_ENV,
    )
    try:
        assert _wait_until(
            lambda: len(_query(tmp_path, "SELECT id FROM workers")) == 1, 20.0
        ), "worker 没有注册心跳行"

        # 父进程"消失"：pid 文件内容不再等于 --parent-pid
        pid_file.write_text("1", encoding="ascii")

        assert _wait_until(lambda: process.poll() is not None, 25.0), \
            "孤儿自检没有让 worker 退出"
        assert process.returncode == 0, f"优雅退出应返回 0，实际 {process.returncode}"

        assert _query(tmp_path, "SELECT id FROM workers") == [], \
            "正常退出必须删掉自己的 workers 行"
    finally:
        _stop(process)


@pytest.mark.skipif(os.name == "nt", reason="Windows 上 terminate() 是 TerminateProcess，没有优雅退出的机会")
def test_worker_unregisters_on_sigterm(tmp_path: Path) -> None:
    """POSIX：SIGTERM 必须走优雅退出（systemd stop 就是这个信号）。"""
    process = _spawn(
        tmp_path, "idle", enqueue=False,
        argv=["--pools", "cpu", "--no-recovery"], env_extra=_CHILD_ENV,
    )
    try:
        assert _wait_until(lambda: len(_query(tmp_path, "SELECT id FROM workers")) == 1, 20.0)
        process.terminate()
        assert _wait_until(lambda: process.poll() is not None, 25.0)
        assert _query(tmp_path, "SELECT id FROM workers") == []
    finally:
        _stop(process)


# ---------------------------------------------------------------------------
# 孤儿自检
# ---------------------------------------------------------------------------


def test_orphan_worker_exits_when_parent_gone(tmp_path: Path) -> None:
    """`--parent-pid 999999` 且 pid 文件不存在 → 15s 内自行退出。"""
    process = _spawn(
        tmp_path, "idle", enqueue=False,
        argv=["--pools", "cpu", "--no-recovery", "--parent-pid", "999999"],
        env_extra=_CHILD_ENV,
    )
    try:
        assert _wait_until(lambda: process.poll() is not None, 15.0), \
            "父进程不在时 worker 没有自行退出（会变成抢任务的孤儿）"
        assert process.returncode == 0
    finally:
        _stop(process)

#!/usr/bin/env python
"""G3 闸门的人工复核脚本：G3-②（kill -9 后能恢复）与 G3-③（ASR 不阻塞翻译）。

用法
====
::

    python scripts/verify_worker_g3.py            # 默认：替身 handler，约 15s
    python scripts/verify_worker_g3.py --real     # 额外跑一次真 ffmpeg 转码（需 ffmpeg）

输出固定为 `[PASS]/[FAIL]/[SKIP] <断言名> —— <实测数值>`，退出码 0/1。

⚠️ 为什么**必须打印实际阈值**
============================
「把 `job_lease_ttl_sec` 调到 1s 才过」也能让脚本变绿，但那种绿是假的：
线上是 120s / 30s / 3 次。所以脚本开头就把本次用到的每个阈值打出来，
复核的人一眼能看出「是不是偷偷调了参数」。默认跑**生产默认值**；
只有崩溃恢复这一步为了不让脚本等 120s，才用一组明确列出的小阈值。

⚠️ 安全边界
==========
全程在 `tempfile.mkdtemp()` 出来的隔离根目录里跑（自己建 `data/`、`app.db`），
**一个字节都不会写进项目的 `data/`**。`--real` 也是同一个隔离根。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Callable

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
BACKEND_DIR = PROJECT_ROOT / "backend"

#: 隔离根（模块级：patch config 之前就要算好路径）。
ISOLATED_ROOT = Path(tempfile.mkdtemp(prefix="fayelong-g3-"))

_RESULTS: list[tuple[bool | None, str, str]] = []


# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------


def report(passed: bool | None, name: str, detail: str = "") -> None:
    """记录并打印一条断言结果。`None` 表示 SKIP。"""
    _RESULTS.append((passed, name, detail))
    tag = "[SKIP]" if passed is None else ("[PASS]" if passed else "[FAIL]")
    suffix = f" —— {detail}" if detail else ""
    print(f"{tag} {name}{suffix}", flush=True)


def section(title: str) -> None:
    print(f"\n===== {title} =====", flush=True)


# ---------------------------------------------------------------------------
# 隔离环境（必须在 import app.* 之前完成）
# ---------------------------------------------------------------------------


def prepare_isolated_root() -> None:
    """把 `app.core.config` 的运行时路径全部重指向 :data:`ISOLATED_ROOT`。

    Raises:
        SystemExit: 隔离根落在了真实 `data/` 之下（绝不允许，直接中止）。
    """
    real_data = (PROJECT_ROOT / "data").resolve()
    if ISOLATED_ROOT.resolve() == real_data or real_data in ISOLATED_ROOT.resolve().parents:
        raise SystemExit(f"隔离根危险地落在真实 data/ 下：{ISOLATED_ROOT}")

    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))

    import app.core.config as config  # noqa: PLC0415  必须最先

    data_dir = ISOLATED_ROOT / "data"
    config.DATA_DIR = data_dir
    config.MEDIA_DIR = data_dir / "media"
    config.INBOX_DIR = data_dir / "media" / "audio"
    config.LIBRARY_DIR = data_dir / "media" / "library"
    config.MODELS_DIR = ISOLATED_ROOT / "models"
    config.DICT_DIR = ISOLATED_ROOT / "dict"
    config.LOG_DIR = data_dir / "logs"
    config.DB_PATH = data_dir / "app.db"
    for directory in (
        config.DATA_DIR,
        config.MEDIA_DIR,
        config.INBOX_DIR,
        config.LIBRARY_DIR,
        config.MODELS_DIR,
        config.DICT_DIR,
        config.LOG_DIR,
    ):
        directory.mkdir(parents=True, exist_ok=True)


def print_thresholds() -> None:
    """打印本次使用的全部阈值（含「为跑得快而调小」的那几个）。"""
    from app.core.config import settings  # noqa: PLC0415

    print("隔离根：", ISOLATED_ROOT)
    print("生产默认阈值（进程内与 --real 部分使用）：")
    print(f"  job_cpu_threads          = {settings.job_cpu_threads}（0 = 自动取核数）")
    print(f"  job_io_threads           = {settings.job_io_threads}")
    print(f"  job_heartbeat_interval_s = {settings.job_heartbeat_interval_sec}")
    print(f"  job_worker_ttl_s         = {settings.job_worker_ttl_sec}")
    print(f"  job_lease_interval_s     = {settings.job_lease_interval_sec}")
    print(f"  job_lease_ttl_s          = {settings.job_lease_ttl_sec}")
    print(f"  job_max_attempts         = {settings.job_max_attempts}")
    print("崩溃恢复子进程用的**调小后**阈值（否则要等满 120s）：")
    for key, value in sorted(CRASH_ENV.items()):
        print(f"  {key:<44} = {value}")


# ---------------------------------------------------------------------------
# 通用助手
# ---------------------------------------------------------------------------


def db_query(sql: str, params: tuple = ()) -> list[tuple]:
    """直读隔离库（不经 ORM）。"""
    from app.core.config import DB_PATH  # noqa: PLC0415

    conn = sqlite3.connect(str(DB_PATH), timeout=15)
    try:
        return [tuple(row) for row in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def wait_until(predicate: Callable[[], bool], timeout: float, interval: float = 0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if predicate():
                return True
        except sqlite3.Error:
            pass
        time.sleep(interval)
    return False


# ---------------------------------------------------------------------------
# G3-③ 池隔离
# ---------------------------------------------------------------------------

_RECORDS: list[tuple[str, int, float, float]] = []
_LOCK = threading.Lock()


def _fake_handler(seconds: float, *, mark: str, fail: bool = False) -> Callable[[Any], None]:
    def handler(ctx: Any) -> None:
        start = time.monotonic()
        try:
            with _LOCK:
                _RECORDS.append((f"{mark}", ctx.ref_id, start, -1.0))
            if fail:
                raise RuntimeError("替身失败")
            time.sleep(seconds)
        finally:
            with _LOCK:
                for index in range(len(_RECORDS) - 1, -1, -1):
                    kind, ref_id, record_start, end = _RECORDS[index]
                    if kind == mark and ref_id == ctx.ref_id and end < 0:
                        _RECORDS[index] = (kind, ref_id, record_start, time.monotonic())
                        break

    return handler


def _interval(mark: str, ref_id: int) -> tuple[float, float]:
    with _LOCK:
        for kind, record_ref, start, end in _RECORDS:
            if kind == mark and record_ref == ref_id and end >= 0:
                return start, end
    raise AssertionError(f"没有 {mark}/{ref_id} 的执行记录：{_RECORDS!r}")


def _max_concurrent(marks: set[str]) -> int:
    events: list[tuple[float, int]] = []
    with _LOCK:
        for mark, _ref, start, end in _RECORDS:
            if mark in marks and end >= 0:
                events.append((start, +1))
                events.append((end, -1))
    events.sort(key=lambda item: (item[0], item[1]))
    current = peak = 0
    for _ts, delta in events:
        current += delta
        peak = max(peak, current)
    return peak


def check_pool_isolation() -> bool:
    """G3-③：cpu=1 / io=2，长 ASR 期间 3 个翻译必须全部跑完。"""
    from app.db import Base, SessionLocal, engine  # noqa: PLC0415
    from app.models import Job  # noqa: PLC0415
    from app.services import jobs as jobs_service  # noqa: PLC0415
    from app.worker import Worker  # noqa: PLC0415

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        db.query(Job).delete()
        db.commit()
    finally:
        db.close()
    with _LOCK:
        _RECORDS.clear()

    original_next = dict(jobs_service.NEXT_STAGE)
    originals = {kind: Worker.HANDLERS.get(kind) for kind in (jobs_service.KIND_ASR, jobs_service.KIND_TRANSLATE)}
    worker = Worker(cpu_threads=1, io_threads=2, mode="external", recover=False)
    try:
        # 关掉链式推进：本断言只关心「池是否隔离」
        for kind in list(jobs_service.NEXT_STAGE):
            jobs_service.NEXT_STAGE[kind] = None
        Worker.HANDLERS[jobs_service.KIND_ASR] = _fake_handler(0.8, mark="ASR")
        Worker.HANDLERS[jobs_service.KIND_TRANSLATE] = _fake_handler(0.05, mark="TRANSLATE")

        jobs_service.enqueue(jobs_service.KIND_ASR, 1)
        for ref_id in (101, 102, 103):
            jobs_service.enqueue(jobs_service.KIND_TRANSLATE, ref_id)
        worker.start()
        idle = worker.wait_idle(timeout=15.0)
    finally:
        worker.stop()
        for kind, handler in originals.items():
            if handler is None:
                Worker.HANDLERS.pop(kind, None)
            else:
                Worker.HANDLERS[kind] = handler
        for kind, next_kind in original_next.items():
            jobs_service.NEXT_STAGE[kind] = next_kind

    if not idle:
        report(False, "G3-③ worker 在 15s 内空闲", "超时")
        return False

    asr_start, asr_end = _interval("ASR", 1)
    translate_ends = [_interval("TRANSLATE", ref)[1] for ref in (101, 102, 103)]
    overlapped = [
        ref for ref in (101, 102, 103)
        if _interval("TRANSLATE", ref)[0] < asr_end and _interval("TRANSLATE", ref)[1] > asr_start
    ]
    cpu_peak = _max_concurrent({"ASR"})
    io_peak = _max_concurrent({"TRANSLATE"})

    ok = True
    ok &= _assert(
        max(translate_ends) < asr_end,
        "G3-③ 3 个翻译全部早于 ASR 结束",
        f"max(translate_end) - asr_end = {max(translate_ends) - asr_end:.3f}s（负值=更早）",
    )
    ok &= _assert(
        bool(overlapped),
        "G3-③ 至少 1 个翻译与 ASR 时间区间重叠（物理并行）",
        f"overlapped={overlapped} asr=[{asr_start:.3f},{asr_end:.3f}]",
    )
    ok &= _assert(cpu_peak <= 1, "G3-③ CPU 池最大并发 ≤ 1", f"cpu_peak={cpu_peak}")
    ok &= _assert(io_peak <= 2, "G3-③ IO 池最大并发 ≤ 2", f"io_peak={io_peak}")

    rows = db_query("SELECT kind, status, attempts FROM jobs ORDER BY id")
    done = [row for row in rows if row[1] == "done"]
    ok &= _assert(len(done) == 4, "G3-③ 4 个任务全部 done", f"done={len(done)}/{len(rows)}")
    return bool(ok)


def _assert(passed: bool, name: str, detail: str = "") -> bool:
    report(passed, name, detail)
    return passed


# ---------------------------------------------------------------------------
# G3-② 崩溃恢复（真子进程 + 真 kill）
# ---------------------------------------------------------------------------

CRASH_ENV = {
    "FAYELONG_JOB_HEARTBEAT_INTERVAL_SEC": "1",
    "FAYELONG_JOB_WORKER_TTL_SEC": "3",
    "FAYELONG_JOB_LEASE_INTERVAL_SEC": "1",
    "FAYELONG_JOB_LEASE_TTL_SEC": "5",
    "FAYELONG_JOB_POLL_INTERVAL_MS": "100",
    "FAYELONG_JOB_MAX_ATTEMPTS": "3",
}

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
jobs.NEXT_STAGE[jobs.KIND_ASR] = None

MODE = {mode!r}

def mark(text):
    with Path(r"{counter}").open("a", encoding="utf-8") as fh:
        fh.write(text + "\n")

def write_media():
    db = SessionLocal()
    try:
        media = db.get(Media, 1)
        if media is not None:
            media.status = "done"
            media.progress = 100
        db.commit()
    finally:
        db.close()

if MODE == "hold":
    def handler(ctx):
        mark("hold-start")
        time.sleep(120)
else:
    def handler(ctx):
        mark("recover")
        write_media()

w.Worker.HANDLERS = {{**w.HANDLERS, jobs.KIND_ASR: handler}}

db = SessionLocal()
try:
    if db.get(Media, 1) is None:
        db.add(Media(id=1, title="g3", type="audio", original_name="a.mp3",
                     file_path="data/media/library/1/a.mp3"))
        db.commit()
    if {enqueue}:
        jobs.enqueue(jobs.KIND_ASR, 1)
finally:
    db.close()

w.main(argv={argv!r})
'''


def _spawn_child(mode: str, *, enqueue: bool, argv: list[str]) -> subprocess.Popen:
    script = _CHILD_TEMPLATE.format(
        backend=str(BACKEND_DIR).replace("\\", "/"),
        root=str(ISOLATED_ROOT).replace("\\", "/"),
        counter=str(ISOLATED_ROOT / "counter.txt").replace("\\", "/"),
        mode=mode,
        enqueue=enqueue,
        argv=argv,
    )
    env = {**os.environ, **CRASH_ENV}
    log_path = ISOLATED_ROOT / f"child-{mode}-{time.monotonic_ns()}.log"
    handle = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, "-c", script],
        cwd=str(BACKEND_DIR),
        env=env,
        stdout=handle,
        stderr=subprocess.STDOUT,
    )
    process._g3_log = handle  # type: ignore[attr-defined]
    process._g3_log_path = log_path  # type: ignore[attr-defined]
    return process


def _stop_child(process: subprocess.Popen | None) -> None:
    if process is None:
        return
    if process.poll() is None:
        try:
            process.kill()
            process.wait(timeout=10)
        except Exception:  # noqa: BLE001
            pass
    handle = getattr(process, "_g3_log", None)
    if handle is not None and not handle.closed:
        handle.close()


def check_crash_recovery() -> bool:
    """G3-②：kill -9 一个正在跑任务的 worker → 新 worker 接管并完成。"""
    from app.db import Base, SessionLocal, engine  # noqa: PLC0415
    from app.models import Job, Worker as WorkerRow  # noqa: PLC0415

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        db.query(Job).delete()
        db.query(WorkerRow).delete()
        db.commit()
    finally:
        db.close()

    ok = True
    processes: list[subprocess.Popen] = []
    try:
        child_a = _spawn_child("hold", enqueue=True, argv=["--pools", "cpu", "--no-recovery"])
        processes.append(child_a)
        started = wait_until(lambda: (db_query("SELECT status FROM jobs") or [("",)])[0][0] == "running", 25.0, 0.1)
        ok &= _assert(started, "G3-② A 认领任务并进入 running", f"job={db_query('SELECT id,status,attempts FROM jobs')}")
        if not started:
            return False

        child_a.kill()
        child_a.wait(timeout=20)
        killed_at = time.monotonic()
        report(True, "G3-② A 已被 kill -9（TerminateProcess）", f"returncode={child_a.returncode}")

        child_b = _spawn_child("recover", enqueue=False, argv=["--pools", "cpu"])
        processes.append(child_b)

        done = wait_until(lambda: (db_query("SELECT status FROM jobs") or [("",)])[0][0] == "done", 40.0, 0.1)
        elapsed = time.monotonic() - killed_at
        ok &= _assert(done, "G3-② B 接管并完成（status=done）",
                      f"耗时 {elapsed:.1f}s（lease_ttl={CRASH_ENV['FAYELONG_JOB_LEASE_TTL_SEC']}s "
                      f"worker_ttl={CRASH_ENV['FAYELONG_JOB_WORKER_TTL_SEC']}s）")

        rows = db_query("SELECT attempts, worker_id, status FROM jobs")
        attempts = rows[0][0] if rows else -1
        ok &= _assert(attempts == 2, "G3-② attempts == 2（A 一次 + B 一次）", f"attempts={attempts}")

        media = db_query("SELECT status, progress FROM media WHERE id=1")
        ok &= _assert(media == [("done", 100)], "G3-② media 轴被 B 推进到 done/100", f"media={media}")

        counter_path = ISOLATED_ROOT / "counter.txt"
        counter = counter_path.read_text(encoding="utf-8").split() if counter_path.is_file() else []
        ok &= _assert(counter.count("recover") == 1, "G3-② 恢复执行只发生 1 次（没有双跑）",
                      f"counter={counter}")
        return bool(ok)
    finally:
        for process in processes:
            _stop_child(process)


# ---------------------------------------------------------------------------
# 附带检查：schema 与 fencing
# ---------------------------------------------------------------------------


def check_schema() -> bool:
    """`uq_jobs_active` 必须是部分唯一索引，且 `ref_id` 非空。"""
    row = db_query("SELECT sql FROM sqlite_master WHERE type='index' AND name='uq_jobs_active'")
    ddl = " ".join((row[0][0] or "").split()) if row else ""
    ok = _assert(bool(row), "schema uq_jobs_active 存在", ddl or "缺失")
    ok &= _assert("WHERE status IN (" in ddl, "schema uq_jobs_active 是**部分**唯一索引", ddl)
    info = {r[1]: r for r in db_query("PRAGMA table_info(jobs)")}
    ok &= _assert(info.get("ref_id", (None,) * 4)[3] == 1, "schema jobs.ref_id 为 NOT NULL",
                  f"notnull={info.get('ref_id', (None,) * 4)[3]}")
    counts = {r[0]: r[1] for r in db_query("SELECT status, COUNT(*) FROM jobs GROUP BY status")}
    print(f"     当前 jobs 分布：{json.dumps(counts, ensure_ascii=False)}")
    return bool(ok)


# ---------------------------------------------------------------------------
# --real：真 ffmpeg 转码（可选）
# ---------------------------------------------------------------------------


def check_real_transcode() -> bool | None:
    """用隔离根里的合成音频跑一次**真** `stage_transcode`（需要 ffmpeg）。"""
    from app.core.tools import ffmpeg_path  # noqa: PLC0415

    exe = ffmpeg_path()
    if not exe:
        report(None, "G3-③（真链路）ffmpeg 转码", "未找到 ffmpeg，跳过")
        return None

    from app.db import SessionLocal  # noqa: PLC0415
    from app.models import Media  # noqa: PLC0415
    from app.services import jobs as jobs_service  # noqa: PLC0415
    from app.worker import Worker  # noqa: PLC0415

    src = ISOLATED_ROOT / "sine.wav"
    subprocess.run(
        [exe, "-y", "-loglevel", "error", "-f", "lavfi", "-i",
         "sine=frequency=440:duration=3", str(src)],
        check=False, capture_output=True,
    )
    if not src.is_file():
        report(None, "G3-③（真链路）ffmpeg 转码", "合成音频失败，跳过")
        return None

    db = SessionLocal()
    try:
        db.query(Media).delete()
        media = Media(title="real-transcode", type="audio", original_name="sine.wav",
                      file_path=str(src), duration_ms=3000)
        db.add(media)
        db.commit()
        media_id = media.id
    finally:
        db.close()

    original_next = dict(jobs_service.NEXT_STAGE)
    jobs_service.NEXT_STAGE[jobs_service.KIND_TRANSCODE] = None   # 只跑转码
    worker = Worker(cpu_threads=1, io_threads=1, mode="external", recover=False, pools=("cpu",))
    try:
        jobs_service.enqueue(jobs_service.KIND_TRANSCODE, media_id)
        worker.start()
        idle = worker.wait_idle(timeout=120.0)
    finally:
        worker.stop()
        for kind, next_kind in original_next.items():
            jobs_service.NEXT_STAGE[kind] = next_kind

    db = SessionLocal()
    try:
        media = db.get(Media, media_id)
        audio_path = Path(media.audio_path) if media and media.audio_path else None
        has_audio = bool(audio_path and audio_path.is_file() and audio_path.stat().st_size > 0)
        status = media.status if media else "?"
    finally:
        db.close()

    ok = _assert(idle, "G3-③（真链路）worker 在 120s 内空闲", "超时" if not idle else "")
    ok &= _assert(has_audio, "G3-③（真链路）标准 wav 已生成",
                  f"{audio_path} status={status}")
    return bool(ok)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FayeLong G3-②/③ 验收脚本")
    parser.add_argument("--real", action="store_true", help="额外跑一次真 ffmpeg 转码（需要 ffmpeg）")
    args = parser.parse_args(argv)

    print("FayeLong G3 闸门验收（G3-② kill -9 恢复 / G3-③ ASR 不阻塞翻译）")
    prepare_isolated_root()
    print_thresholds()

    try:
        section("G3-③ 池隔离（替身 handler，不依赖 whisper/ffmpeg/网络）")
        check_pool_isolation()

        section("G3-② 崩溃恢复（真子进程 + 真 kill）")
        check_crash_recovery()

        section("schema 与 fencing 不变量")
        check_schema()

        if args.real:
            section("真链路（--real）")
            check_real_transcode()
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        report(False, "脚本执行未抛异常", "见上方 traceback")

    section("汇总")
    failed = [item for item in _RESULTS if item[0] is False]
    skipped = [item for item in _RESULTS if item[0] is None]
    print(f"PASS={len([r for r in _RESULTS if r[0] is True])} "
          f"FAIL={len(failed)} SKIP={len(skipped)}")
    shutil.rmtree(ISOLATED_ROOT, ignore_errors=True)
    if failed:
        for _ok, name, detail in failed:
            print(f"  [FAIL] {name} —— {detail}")
        return 1
    print("G3 闸门：通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

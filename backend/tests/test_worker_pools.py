"""P3-3 池隔离的集成验收：**ASR 不阻塞翻译**（G3-③）。

为什么这些用例能在 1 秒内跑完且**不依赖 whisper / ffmpeg / 网络**
==============================================================
用 `Worker.HANDLERS[kind] = fake` 注入替身 handler —— 注入点是**模块级的普通
dict**（刻意如此设计，见 `app/worker.py` 的 `HANDLERS` 注释）。因此这里测的是
「池与调度」，而不是模型本身。

时间证据怎么取
==============
`jobs.started_at` / `finished_at` 是 SQLite 的 `CURRENT_TIMESTAMP`（**秒级**），
0.8s 的 ASR 与 0.05s 的翻译会落在同一秒里，用它们做 `<` 断言会假红。所以替身
handler 自己在 `time.monotonic()` 上记录 `(kind, ref_id, start, end)`，用它算
**区间重叠**与**每池最大并发**；DB 时间戳只用来做「已落库」的辅助断言。

⚠️ 判别力前提：G3-③ 的断言**只在 CPU 池 = 1 槽时**才有判别力
============================================================
实测矩阵（`KIND_TRANSLATE` 从 IO 池改回 CPU 池这一变异）：

=========================  ======================  =======================
cpu_threads                真分池                  变异(translate→cpu)
=========================  ======================  =======================
1                          翻译早于 ASR 结束 ✅     翻译排在 ASR 之后 ❌（抓到）
2 / 4 / 8                  翻译早于 ASR 结束 ✅     翻译早于 ASR 结束 ✅（抓不到）
=========================  ======================  =======================

原因（机制）：CPU 池 ≥ 2 槽时，变异后翻译仍能抢到剩余槽 —— 单个 ASR **只占 1 槽**，
3 个 0.05s 的翻译完全挤得进剩下的槽里，于是 `translate_end < asr_end` 与「区间重叠」
**依旧成立**，变异抓不到。只有 CPU 池恰好 1 槽时，「串行 = 必然排在 ASR 之后」才让
这两条断言具备判别力。

因此：
1. **不许为了「对齐生产默认」把这里的 `cpu=1` 改成 `0` / `auto`**。
   `job_cpu_threads=0` 表示「自动取 `os.cpu_count()`」，本机 8 核就变成 8 槽，
   上面那条保证会**静默失效**（测试全绿但什么都不再证明）。
2. `os.cpu_count()` **不识别 cgroup 配额**（容器 / 云主机会拿到宿主核数，
   2 vCPU 的实例可能报 32）。所以生产**必须显式**配 `FAYELONG_JOB_CPU_THREADS`，
   不能依赖 `auto`（deploy/linux/fayelong-worker.service 已显式设 1）。

另：`cpu_peak <= 1` / `io_peak <= 2` 这类断言是**容量上限未被突破**的检查，
**不是判别证据** —— 池容量本来就是 1/2，峰值不可能超过它，恒真。真正的判别证据
只有「`translate_end < asr_end`」与「至少一个区间重叠」；`== 2` 的严格断言只放在
`test_io_pool_concurrency`（4×0.25s，能稳定跑到 2）。
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.db import Base, SessionLocal, engine
from app.models import Job, Media
from app.models import Worker as WorkerRow
from app.services import jobs as jobs_service
from app.services.jobs import (
    JOB_DONE,
    KIND_ASR,
    KIND_CLIP,
    KIND_GRADE_WRITING,
    KIND_TRANSCODE,
    KIND_TRANSLATE,
    POOL_CPU,
    POOL_IO,
)
from app.worker import Worker
#: `_PoolRunner` 是私有类，但 A3 的断言对象**就是**它的 `idle()` ——
#: 通过公开的 `Worker.wait_idle()` 测不到「单个池怎么判空闲」。
from app.worker import _PoolRunner

#: 替身 handler 的执行记录：(kind, ref_id, start, end) —— `time.monotonic()` 秒。
_RECORDS: list[tuple[str, int, float, float]] = []
_RECORD_LOCK = threading.Lock()


@pytest.fixture(scope="module", autouse=True)
def _schema() -> None:
    """确保临时库里有表（不依赖别的测试文件的执行顺序）。"""
    Base.metadata.create_all(bind=engine)


@pytest.fixture(autouse=True)
def _clean_tables() -> Any:
    """每个用例前清空 `jobs` / `workers` 与本模块的记录表。"""
    db = SessionLocal()
    try:
        db.query(Job).delete()
        db.query(WorkerRow).delete()
        db.commit()
    finally:
        db.close()
    with _RECORD_LOCK:
        _RECORDS.clear()
    yield


@pytest.fixture(autouse=True)
def _no_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    """关掉链式推进：本模块只测「池路由与并发」，链式推进由 test_jobs 覆盖。

    不关的话，一个 `media_asr` 任务成功后会顺手入队 `media_translate`，
    计数与时间断言都会被这条「没人期待的后续任务」污染。
    """
    for kind in list(jobs_service.NEXT_STAGE):
        monkeypatch.setitem(jobs_service.NEXT_STAGE, kind, None)


# ---------------------------------------------------------------------------
# 替身 handler
# ---------------------------------------------------------------------------


def _fake_handler(seconds: float, *, fail: bool = False) -> Callable[[Any], None]:
    """造一个「睡 N 秒并记录区间」的替身 handler。"""

    def handler(ctx: Any) -> None:
        start = time.monotonic()
        try:
            if fail:
                raise RuntimeError("替身失败")
            time.sleep(seconds)
        finally:
            with _RECORD_LOCK:
                _RECORDS.append((ctx.kind, ctx.ref_id, start, time.monotonic()))

    return handler


def _kind_records(*kinds: str) -> list[tuple[str, int, float, float]]:
    with _RECORD_LOCK:
        return [record for record in _RECORDS if not kinds or record[0] in kinds]


def _interval_of(kind: str, ref_id: int) -> tuple[float, float]:
    for record_kind, record_ref, start, end in _kind_records(kind):
        if record_ref == ref_id:
            return start, end
    raise AssertionError(f"没有找到 {kind}/{ref_id} 的执行记录：{_RECORDS!r}")


def _max_concurrent(pool: str) -> int:
    """按执行区间计算某个池的**最大同时在飞数**（扫描线算法）。"""
    events: list[tuple[float, int]] = []
    for kind, _ref, start, end in _kind_records():
        if jobs_service.pool_of(kind) != pool:
            continue
        events.append((start, +1))
        events.append((end, -1))
    events.sort(key=lambda item: (item[0], item[1]))   # 同一时刻先 -1 再 +1
    current = peak = 0
    for _timestamp, delta in events:
        current += delta
        peak = max(peak, current)
    return peak


def _job(kind: str, ref_id: int) -> Job:
    db = SessionLocal()
    try:
        row = (
            db.query(Job)
            .filter(Job.kind == kind, Job.ref_id == ref_id)
            .order_by(Job.id.desc())
            .first()
        )
        assert row is not None, f"没有 {kind}/{ref_id} 的任务行"
        db.expunge(row)
        return row
    finally:
        db.close()


def _try_job(kind: str, ref_id: int) -> Job | None:
    """按 `kind + ref_id` 取最新一条任务行；不存在返回 `None`（`_job` 的容错版）。"""
    db = SessionLocal()
    try:
        row = (
            db.query(Job)
            .filter(Job.kind == kind, Job.ref_id == ref_id)
            .order_by(Job.id.desc())
            .first()
        )
        if row is not None:
            db.expunge(row)
        return row
    finally:
        db.close()


def _run_worker(monkeypatch: pytest.MonkeyPatch,
                seconds_handlers: dict[str, float],
                enqueues: list[tuple[str, int]],
                *, cpu: int, io: int,
                mutate_handlers: dict[str, Callable] | None = None) -> None:
    """起一个 worker 跑完一批任务后停掉（每个用例的公共骨架）。

    Notes:
        替身一律用 `monkeypatch.setitem` 注入：`Worker.HANDLERS` 就是模块级的
        `HANDLERS` dict，直接赋值再 `pop` 会**删掉真实 handler**（`_handle_asr` 等），
        让后面的用例静默变成「没有 handler」。
    """
    handlers: dict[str, Callable] = {
        kind: _fake_handler(sec) for kind, sec in seconds_handlers.items()
    }
    if mutate_handlers:
        handlers.update(mutate_handlers)
    for kind, handler in handlers.items():
        monkeypatch.setitem(Worker.HANDLERS, kind, handler)

    worker = Worker(cpu_threads=cpu, io_threads=io, mode="external", recover=False)
    try:
        for kind, ref_id in enqueues:
            jobs_service.enqueue(kind, ref_id)
        worker.start()
        assert worker.wait_idle(timeout=15.0), "worker 未在 15s 内空闲"
    finally:
        worker.stop()


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------


class TestRouting:
    def test_kind_routes_to_expected_pool(self) -> None:
        expected = {
            KIND_TRANSCODE: POOL_CPU,
            KIND_ASR: POOL_CPU,
            KIND_CLIP: POOL_CPU,
            KIND_TRANSLATE: POOL_IO,
            KIND_GRADE_WRITING: POOL_IO,
        }
        assert {kind: jobs_service.KIND_POOL[kind] for kind in jobs_service.KIND_POOL} == expected

    def test_unknown_kind_falls_back_to_cpu(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """未知 kind 必须落 CPU 池（`DEFAULT_POOL`）—— 慢，但不会压垮 IO 池。"""
        assert jobs_service.pool_of("nope") == POOL_CPU
        assert jobs_service.pool_of(KIND_GRADE_WRITING) == POOL_IO

        monkeypatch.setitem(Worker.HANDLERS, "nope", _fake_handler(0.02))
        worker = Worker(cpu_threads=1, io_threads=1, mode="external", recover=False)
        try:
            jobs_service.enqueue("nope", ref_id=900)
            worker.start()
            io_runner = next(r for r in worker._runners if r.pool == POOL_IO)
            assert io_runner.kinds is not None and "nope" not in io_runner.kinds, \
                "IO 池的认领白名单里不该出现未登记 kind"
            assert worker.wait_idle(timeout=10.0)
        finally:
            worker.stop()

        assert _job("nope", 900).status == JOB_DONE
        assert len(_kind_records("nope")) == 1, "未知 kind 的任务必须真的被执行一次"


# ---------------------------------------------------------------------------
# G3-③：ASR 不阻塞翻译
# ---------------------------------------------------------------------------


class TestPoolIsolation:
    def test_translate_not_blocked_by_slow_asr(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """cpu=1 / io=2：长 ASR（0.8s）期间，3 个翻译必须全部跑完。"""
        _run_worker(
            monkeypatch,
            {KIND_ASR: 0.8, KIND_TRANSLATE: 0.05},
            [(KIND_ASR, 1), (KIND_TRANSLATE, 101), (KIND_TRANSLATE, 102), (KIND_TRANSLATE, 103)],
            # ★ cpu 必须是 1，**不许为了「对齐生产默认」改成 0/auto**：
            #   CPU 池 ≥2 槽时，单个 ASR 只占 1 槽，3 个 0.05s 的翻译仍能挤进剩余槽 →
            #   即使把 translate 误配回 CPU 池，`translate_end < asr_end` 与「区间重叠」
            #   也照样成立，本用例的判别力**静默归零**（详见模块 docstring「判别力前提」
            #   的 cpu∈{1,2,4,8} 矩阵）。
            cpu=1,
            io=2,
        )

        asr_start, asr_end = _interval_of(KIND_ASR, 1)

        # ① 3 个翻译全部在 ASR 结束**之前**完成（不靠人眼，用单调时钟区间）
        for ref in (101, 102, 103):
            _start, end = _interval_of(KIND_TRANSLATE, ref)
            assert end < asr_end, f"翻译 {ref} 被 ASR 拖到了它之后"
        # ② 至少一个翻译与 ASR 的区间重叠 → 证明物理并行（不是「恰好排在前面」）
        overlapped = [
            ref
            for ref in (101, 102, 103)
            if _interval_of(KIND_TRANSLATE, ref)[0] < asr_end
            and _interval_of(KIND_TRANSLATE, ref)[1] > asr_start
        ]
        assert overlapped, "没有任何翻译与 ASR 并行 —— 池隔离没生效"
        # ③ 池容量未被突破。
        #    ⚠️ 这两条是**恒真的容量检查，不是判别证据**（池容量就是 1/2，峰值不可能
        #    超过它）。真正的判别证据是上面的 ①「翻译全部早于 ASR 结束」与 ②「区间
        #    重叠」—— 变异（translate→cpu）只会让 ①② 变红，③ 仍绿。
        assert _max_concurrent(POOL_CPU) <= 1, f"CPU 池并发 {_max_concurrent(POOL_CPU)} > 1"
        assert _max_concurrent(POOL_IO) <= 2, f"IO 池并发 {_max_concurrent(POOL_IO)} > 2"

        # ④ 两条轴都正常落库（不是「跑完但没写回」）
        assert _job(KIND_ASR, 1).status == JOB_DONE
        for ref in (101, 102, 103):
            assert _job(KIND_TRANSLATE, ref).status == JOB_DONE
            assert _job(KIND_TRANSLATE, ref).attempts == 1

    def test_cpu_pool_saturates_at_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """3 个慢 CPU 任务 + cpu_threads=1 → 最大并发恰好 1（串行）。"""
        _run_worker(
            monkeypatch,
            {KIND_ASR: 0.2},
            [(KIND_ASR, 201), (KIND_ASR, 202), (KIND_ASR, 203)],
            cpu=1,
            io=1,
        )
        assert _max_concurrent(POOL_CPU) == 1
        assert len(_kind_records(KIND_ASR)) == 3

    def test_io_pool_concurrency(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """4 个慢 IO 任务 + io_threads=2 → 最大并发恰好 2。"""
        _run_worker(
            monkeypatch,
            {KIND_TRANSLATE: 0.25},
            [(KIND_TRANSLATE, 301), (KIND_TRANSLATE, 302),
             (KIND_TRANSLATE, 303), (KIND_TRANSLATE, 304)],
            cpu=1,
            io=2,
        )
        assert _max_concurrent(POOL_IO) == 2
        assert len(_kind_records(KIND_TRANSLATE)) == 4

    def test_failed_handler_retries_then_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """handler 抛异常 → 重试到上限后 failed，且 media 轴与 jobs 轴**一起**收敛。

        ⚠️ 这个用例原来**没有**对应的 `media` 行（`ref_id=401` 在 media 表里不存在），
        `mark_terminal_failure()` 里 `db.get(Media, 401) is None` 会把 media 轴整段
        跳过 —— 于是「同一 Session 一次 commit 双写」这条 DD-001 §4.2 第 5 行的
        不变量从来没有被真正执行过。补一行真 Media 才有覆盖。
        """
        db = SessionLocal()
        try:
            db.add(
                Media(
                    id=401,
                    title="terminal-failure",
                    type="audio",
                    original_name="t.mp3",
                    file_path="data/media/library/401/t.mp3",
                    audio_path="data/media/library/401/audio.wav",
                    status="asr",
                    progress=55,
                )
            )
            db.commit()
        finally:
            db.close()

        monkeypatch.setitem(Worker.HANDLERS, KIND_ASR, _fake_handler(0.0, fail=True))
        worker = Worker(cpu_threads=1, io_threads=1, mode="external", recover=False)
        try:
            jobs_service.enqueue(KIND_ASR, ref_id=401)
            worker.start()
            assert worker.wait_idle(timeout=15.0)
        finally:
            worker.stop()

        row = _job(KIND_ASR, 401)
        assert row.status == "failed"
        assert row.attempts == int(settings.job_max_attempts)
        assert row.error and "替身失败" in row.error
        assert len(_kind_records(KIND_ASR)) == int(settings.job_max_attempts)

        # ---- media 轴：必须同时被置 failed，且 error 与进度被清 ----
        try:
            db = SessionLocal()
            try:
                media = db.get(Media, 401)
                assert media is not None
                assert media.status == "failed", f"media.status={media.status!r}（双写没发生）"
                assert media.progress == 0
                assert media.error and "替身失败" in media.error
            finally:
                db.close()
        finally:
            # 清掉本用例造的行，避免污染其它模块（它们假定 media 表是干净的）
            cleanup = SessionLocal()
            try:
                cleanup.query(Media).filter(Media.id == 401).delete(synchronize_session=False)
                cleanup.commit()
            finally:
                cleanup.close()


# ---------------------------------------------------------------------------
# 心跳 / 注册 / 租约
# ---------------------------------------------------------------------------


class TestHeartbeatAndLease:
    def test_worker_registers_and_unregisters(self) -> None:
        worker = Worker(cpu_threads=1, io_threads=1, mode="external", recover=False)
        worker.start()
        try:
            db = SessionLocal()
            try:
                online = jobs_service.online_workers(db)
            finally:
                db.close()
            assert [row.id for row in online] == [worker.instance_id]
            assert online[0].mode == "external"
            assert online[0].pools == "cpu=1,io=1"
        finally:
            worker.stop()

        db = SessionLocal()
        try:
            assert jobs_service.online_workers(db) == []
        finally:
            db.close()

    def test_lease_renewed_during_long_job(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """长任务执行期间租约必须前进（否则会被别的 worker 判死回收）。

        把 `job_lease_interval_sec` 调到 1s 让续租在 1.8s 的任务里真实发生一次。
        """
        monkeypatch.setattr(settings, "job_lease_interval_sec", 1)
        monkeypatch.setitem(Worker.HANDLERS, KIND_ASR, _fake_handler(1.8))
        worker = Worker(cpu_threads=1, io_threads=1, mode="external", recover=False)
        try:
            jobs_service.enqueue(KIND_ASR, ref_id=501)
            worker.start()

            # 等它真的开始跑，抓一份 claim 时写下的 heartbeat_at
            deadline = time.monotonic() + 5.0
            claimed_at = None
            while time.monotonic() < deadline:
                row = _job(KIND_ASR, 501)
                if row.status == "running":
                    claimed_at = row.heartbeat_at
                    break
                time.sleep(0.05)
            assert claimed_at is not None, "任务没有被认领"

            assert worker.wait_idle(timeout=15.0), "慢任务未在 15s 内结束"
        finally:
            worker.stop()

        renewed = _job(KIND_ASR, 501).heartbeat_at
        assert renewed is not None and claimed_at is not None
        assert renewed > claimed_at, f"租约没有前进：claim={claimed_at} now={renewed}"


# ---------------------------------------------------------------------------
# web 进程内降级 worker（DD-001 §1 决策 1 的「安全网」）
# ---------------------------------------------------------------------------


class TestInprocWorker:
    """`FAYELONG_WEB_INPROC_WORKER` 三态。

    这条安全网是决策 1 能成立的前提：worker 没起来时，用户看到的必须是「慢」
    而不是「永远排队中、且没有任何报错」。
    """

    @pytest.fixture(autouse=True)
    def _reset_inproc(self) -> Any:
        from app import main as app_main

        app_main.stop_inproc_worker()
        yield
        app_main.stop_inproc_worker()

    def test_off_never_starts_inproc_worker(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app import main as app_main

        monkeypatch.setattr(settings, "web_inproc_worker", "off")
        app_main.maybe_start_inproc_worker()
        assert app_main._inproc_worker is None

    def test_on_starts_inproc_worker(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app import main as app_main

        monkeypatch.setattr(settings, "web_inproc_worker", "on")
        app_main.maybe_start_inproc_worker()
        try:
            assert app_main._inproc_worker is not None
            db = SessionLocal()
            try:
                online = jobs_service.online_workers(db)
            finally:
                db.close()
            assert [row.mode for row in online] == ["web-inproc"]
            # 小池：不与真正的 worker 抢核
            assert app_main._inproc_worker.cpu_threads == app_main._INPROC_CPU_THREADS
            assert app_main._inproc_worker.io_threads == app_main._INPROC_IO_THREADS
        finally:
            app_main.stop_inproc_worker()
        db = SessionLocal()
        try:
            assert jobs_service.online_workers(db) == []
        finally:
            db.close()

    def test_auto_defers_and_yields_to_online_worker(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`auto` 模式下「已有在线 worker」→ 5s 后检查时让位，不起进程内 worker。"""
        from app import main as app_main

        monkeypatch.setattr(settings, "web_inproc_worker", "auto")
        monkeypatch.setattr(app_main, "_INPROC_AUTO_DELAY_SEC", 0.05)

        # 造一个在线的"独立 worker"
        db = SessionLocal()
        try:
            jobs_service.register_worker(db, "w-external", 9999, mode="external", pools="cpu=1")
        finally:
            db.close()

        app_main.maybe_start_inproc_worker()
        time.sleep(0.4)
        assert app_main._inproc_worker is None, "已有在线 worker 时不该抢任务"

    def test_auto_takes_over_when_no_worker(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`auto` 模式下无在线 worker → 接管（这是「卡死无提示」的唯一兜底）。"""
        from app import main as app_main

        monkeypatch.setattr(settings, "web_inproc_worker", "auto")
        monkeypatch.setattr(app_main, "_INPROC_AUTO_DELAY_SEC", 0.05)

        app_main.maybe_start_inproc_worker()
        assert app_main._inproc_worker is None, "auto 必须**延迟**判断，不能立刻起"
        assert app_main._inproc_timer is not None

        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and app_main._inproc_worker is None:
            time.sleep(0.02)
        try:
            assert app_main._inproc_worker is not None, "无在线 worker 时必须在 5s 内接管"
        finally:
            app_main.stop_inproc_worker()


# ---------------------------------------------------------------------------
# 写回路径的 fencing（fence 必须是 **claim 时快照**，不是重新读库的当前归属）
# ---------------------------------------------------------------------------


def _claim_as(worker_id: str) -> Job:
    """以指定 worker_id 认领一个 `media_asr` 任务。"""
    db = SessionLocal()
    try:
        job = jobs_service.claim(db, [KIND_ASR], worker_id)
    finally:
        db.close()
    assert job is not None, "前置条件：应当认领到任务"
    return job


def _take_over(job_id: int, worker_id: str, attempts: int) -> None:
    """模拟「A 被回收 + B 接管」后的行状态（B 正持有该任务）。"""
    db = SessionLocal()
    try:
        db.execute(
            text(
                "UPDATE jobs SET status='running', worker_id=:worker, attempts=:attempts,"
                " heartbeat_at=CURRENT_TIMESTAMP, error=NULL WHERE id=:job_id"
            ),
            {"worker": worker_id, "attempts": attempts, "job_id": job_id},
        )
        db.commit()
    finally:
        db.close()


class TestWritebackFencing:
    """迟到写回必须被拒（DD-001 §4.3 第 2 条：写回一律带 claim 时的 worker_id/attempts）。

    这组用例的现场是：A 认领 → 被 `recover_stale` 回收 → B 接管（attempts+1、
    worker_id=B）→ **A 才姗姗来迟地写回**。正确行为是 rowcount=0 后彻底放弃
    （不改行、不入队下一 stage、不动 media）；错误行为是拿「当前归属」当 fence，
    于是 A 能把 B 正在跑的任务改成 done / 打回 pending。
    """

    def test_late_success_is_fenced(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A 迟到的 `handle_success` 不得把 B 正在跑的任务写成 done。"""
        # 本用例需要**开启**链式推进，才能断言「下一 stage 未被入队」
        monkeypatch.setitem(jobs_service.NEXT_STAGE, KIND_ASR, KIND_TRANSLATE)

        jobs_service.enqueue(KIND_ASR, ref_id=601)
        job_a = _claim_as("worker-A")              # 快照：attempts=1, owner=A
        _take_over(job_a.id, "worker-B", 2)        # B 已接管

        worker_a = Worker(cpu_threads=1, io_threads=1, mode="external", recover=False)
        worker_a.handle_success(job_a)             # A 迟到写回

        row = _job(KIND_ASR, 601)
        assert row.status == "running", f"B 的任务被 A 写成 {row.status!r}"
        assert row.attempts == 2, "attempts 被回退/改写"
        assert row.worker_id == "worker-B", "worker_id 被 A 抢改"
        assert row.finished_at is None, "finished_at 被 A 写了"
        # 下一 stage 绝不能被 A 入队（否则整条下游链会被跑两遍）
        assert _try_job(KIND_TRANSLATE, 601) is None, "A 的迟到写回入队了下一 stage"

    def test_late_success_control_does_chain(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """对照：**合法**的 `handle_success` 必须入队下一 stage（证明上一条不是恒真）。"""
        monkeypatch.setitem(jobs_service.NEXT_STAGE, KIND_ASR, KIND_TRANSLATE)

        jobs_service.enqueue(KIND_ASR, ref_id=602)
        job = _claim_as("worker-A")

        worker = Worker(cpu_threads=1, io_threads=1, mode="external", recover=False)
        worker.handle_success(job)

        row = _job(KIND_ASR, 602)
        assert row.status == "done"
        assert row.finished_at is not None
        nxt = _try_job(KIND_TRANSLATE, 602)
        assert nxt is not None, "合法写回必须入队下一 stage"
        assert nxt.status == "pending"

    def test_late_failure_is_fenced(self) -> None:
        """A 迟到的 `handle_failure` 不得把 B 的 running 打回 pending。"""
        jobs_service.enqueue(KIND_ASR, ref_id=603)
        job_a = _claim_as("worker-A")
        _take_over(job_a.id, "worker-B", 2)

        worker_a = Worker(cpu_threads=1, io_threads=1, mode="external", recover=False)
        worker_a.handle_failure(job_a, RuntimeError("A 的迟到失败"))

        row = _job(KIND_ASR, 603)
        assert row.status == "running", f"B 的任务被 A 打回 {row.status!r}"
        assert row.worker_id == "worker-B", "worker_id 被清/改"
        assert row.attempts == 2
        assert row.error is None, f"B 的任务被写了 A 的失败原因：{row.error!r}"

    def test_late_terminal_failure_does_not_touch_media(self) -> None:
        """A 迟到的**终态**失败：job 被 fence 拒后，media 轴也必须原封不动。

        这是最恶劣的一条：若 `mark_terminal_failure()` 先无条件写 media、再看
        `force_failed()` 的结果，用户会看到「失败了」，而 B 还在跑、B 的结果随后
        又被 fence 丢掉 —— 两轴互相矛盾且无从排错。
        """
        db = SessionLocal()
        try:
            db.add(
                Media(
                    id=604,
                    title="late-terminal",
                    type="audio",
                    original_name="t.mp3",
                    file_path="data/media/library/604/t.mp3",
                    status="asr",
                    progress=55,
                )
            )
            db.commit()
        finally:
            db.close()

        try:
            jobs_service.enqueue(KIND_ASR, ref_id=604)
            # 让 A 的快照 attempts 顶到上限（模拟「最后一次尝试」）
            limit = int(settings.job_max_attempts)
            job_a: Job | None = None
            for _ in range(limit):
                job_a = _claim_as("worker-A")
                if job_a.attempts < limit:
                    db = SessionLocal()
                    try:
                        db.execute(
                            text("UPDATE jobs SET status='pending', worker_id=NULL,"
                                 " heartbeat_at=NULL WHERE id=:i"),
                            {"i": job_a.id},
                        )
                        db.commit()
                    finally:
                        db.close()
            assert job_a is not None and job_a.attempts == limit, job_a

            # B 在此之后接管（attempts 再 +1）
            _take_over(job_a.id, "worker-B", limit + 1)

            worker_a = Worker(cpu_threads=1, io_threads=1, mode="external", recover=False)
            worker_a.handle_failure(job_a, RuntimeError("A 的迟到终态失败"))

            row = _job(KIND_ASR, 604)
            assert row.status == "running", f"B 的任务被 A 判成 {row.status!r}"
            assert row.worker_id == "worker-B"
            assert row.attempts == limit + 1
            assert row.error is None, f"job 被写了 A 的失败原因：{row.error!r}"

            db = SessionLocal()
            try:
                media = db.get(Media, 604)
                assert media is not None
                assert media.status == "asr", f"media 被 A 污染成 {media.status!r}"
                assert media.progress == 55, "media 进度被 A 清零"
                assert media.error is None, f"media 被写了 A 的失败原因：{media.error!r}"
            finally:
                db.close()
        finally:
            cleanup = SessionLocal()
            try:
                cleanup.query(Media).filter(Media.id == 604).delete(synchronize_session=False)
                cleanup.commit()
            finally:
                cleanup.close()


# ---------------------------------------------------------------------------
# P4 挂账 A1：非 media 分支的终态失败写回必须带 fence
# ---------------------------------------------------------------------------


class TestNonMediaTerminalFence:
    """`_write_terminal_failure()` 的**非 media** 分支（将来的 `grade_writing`）。

    现场与 :class:`TestWritebackFencing` 完全一样：A 认领 → 被回收 → B 接管 →
    A 才姗姗来迟地写终态失败。唯一区别是 kind 换成非 media 的 `grade_writing`，
    于是写回只走 `jobs` 轴。

    为什么以前没被抓到：P3-2 阶段**无人入队** `grade_writing`，这条分支不可达
    （`recover_stale` 会把 `attempts>=max` 的 running 直接判 failed）。
    P4-4 一启用写作批改，它就是 P3-2 那个 P1 缺陷的翻版。
    """

    @staticmethod
    def _claim_grade_writing(ref_id: int) -> Job:
        """以 `worker-A` 认领一条 `grade_writing` 任务（返回 **claim 时**的快照）。"""
        db = SessionLocal()
        try:
            job = jobs_service.claim(db, [KIND_GRADE_WRITING], "worker-A")
        finally:
            db.close()
        assert job is not None, "前置条件：应当认领到 grade_writing 任务"
        assert job.ref_id == ref_id
        return job

    def test_stale_executor_terminal_write_is_fenced(self) -> None:
        """A 迟到的终态失败不得把 B 正在跑的任务判成 failed。"""
        jobs_service.enqueue(KIND_GRADE_WRITING, ref_id=701)
        job_a = self._claim_grade_writing(701)      # 快照：attempts=1, owner=A
        _take_over(job_a.id, "worker-B", 2)         # B 已接管

        worker_a = Worker(cpu_threads=1, io_threads=1, mode="external", recover=False)
        worker_a._write_terminal_failure(           # noqa: SLF001 - 验收私有分支
            KIND_GRADE_WRITING,
            701,
            job_a.id,
            job_a.worker_id,
            job_a.attempts,
            "A 的迟到终态失败",
        )

        row = _job(KIND_GRADE_WRITING, 701)
        # 四样都必须原封不动：状态 / owner / attempts / error
        assert row.status == "running", f"B 的任务被 A 判成 {row.status!r}"
        assert row.worker_id == "worker-B", "worker_id 被 A 抢改"
        assert row.attempts == 2, "attempts 被回退/改写"
        assert row.error is None, f"B 的任务被写了 A 的失败原因：{row.error!r}"
        assert row.finished_at is None, "finished_at 被 A 写了"

    def test_current_executor_terminal_write_succeeds(self) -> None:
        """对照：**合法**执行者的终态写回必须真的落 failed（证明上一条不是恒真）。"""
        jobs_service.enqueue(KIND_GRADE_WRITING, ref_id=702)
        job = self._claim_grade_writing(702)

        worker = Worker(cpu_threads=1, io_threads=1, mode="external", recover=False)
        worker._write_terminal_failure(             # noqa: SLF001 - 验收私有分支
            KIND_GRADE_WRITING,
            702,
            job.id,
            job.worker_id,
            job.attempts,
            "真的失败了",
        )

        row = _job(KIND_GRADE_WRITING, 702)
        assert row.status == "failed"
        assert row.worker_id == "worker-A"
        assert row.attempts == 1
        assert row.error and "真的失败了" in row.error
        assert row.finished_at is not None

    def test_missing_fence_never_writes(self) -> None:
        """fence 缺失时**一行都不许写**（宁可留 running 给租约回收，也不盲写）。"""
        jobs_service.enqueue(KIND_GRADE_WRITING, ref_id=703)
        job = self._claim_grade_writing(703)

        worker = Worker(cpu_threads=1, io_threads=1, mode="external", recover=False)
        worker._write_terminal_failure(             # noqa: SLF001 - 验收私有分支
            KIND_GRADE_WRITING, 703, job.id, None, job.attempts, "无 fence 的写回"
        )

        row = _job(KIND_GRADE_WRITING, 703)
        assert row.status == "running"
        assert row.error is None


# ---------------------------------------------------------------------------
# P4 挂账 A3：`idle()` 必须按「本池认领得了的 kind」判断
# ---------------------------------------------------------------------------


class TestIdleKindFilter:
    """`--once` 空转缺陷的回归（最多白等 5s，无正确性问题但验收会误判为「卡住」）。

    判别力来自 `cpu_runner.idle() is True`：修之前 `idle()` 看的是**全局** pending，
    队列里只要还剩一条 IO 任务，CPU 池就永远不空闲。
    """

    def test_cpu_runner_idle_when_only_io_jobs_pending(self) -> None:
        worker = Worker(cpu_threads=1, io_threads=1, mode="external", recover=False)
        cpu_runner = _PoolRunner(worker, POOL_CPU, 1)
        io_runner = _PoolRunner(worker, POOL_IO, 1)
        try:
            jobs_service.enqueue(KIND_TRANSLATE, ref_id=801)   # 只投 IO 类的活
            assert cpu_runner.idle() is True, "队列里只有 IO 任务时 CPU 池理应空闲"
            assert io_runner.idle() is False, "IO 池自己还有活，不许判空闲"

            jobs_service.enqueue(KIND_ASR, ref_id=802)         # 现在有 CPU 类的活
            assert cpu_runner.idle() is False, "有本池可认领的 pending → 不空闲"
        finally:
            cpu_runner.executor.shutdown(wait=False)
            io_runner.executor.shutdown(wait=False)

    def test_once_exits_promptly_when_only_io_jobs_pending(self) -> None:
        """只启 CPU 池的 `--once` worker：队列里只剩 IO 任务时应立即退出。

        `wait_idle()` 的成功判据是「所有 runner 都 idle」；修之前它会一直等到
        超时才返回 `False`，`--once` 于是白等到 `drain_timeout`。
        """
        worker = Worker(
            cpu_threads=1, io_threads=1, mode="external", recover=False, pools=(POOL_CPU,)
        )
        try:
            jobs_service.enqueue(KIND_TRANSLATE, ref_id=803)
            worker.start()
            started = time.monotonic()
            assert worker.wait_idle(timeout=3.0) is True, "只启 CPU 池的 worker 判不空闲"
            elapsed = time.monotonic() - started
            assert elapsed < 1.5, f"CPU-only worker 空等了 {elapsed:.2f}s（A3 未修复）"
        finally:
            worker.stop()



# ---------------------------------------------------------------------------
# Python 版本兼容：Thread 内部方法不得被实例属性覆盖
# ---------------------------------------------------------------------------


class TestThreadInternalNameShadowing:
    """`_PoolRunner` 继承 `threading.Thread`，**不得**用 Thread 的内部**方法名**做实例属性。

    背景（2026-10-22 云端切换实测，典型「本地全绿、生产必崩」）：
        `_PoolRunner` 曾把停止信号命名为 `self._stop = Event()`。CPython ≤3.12 的
        `Thread._wait_for_tstate_lock()` 在 join 收尾时会 `self._stop()`，
        被 Event 覆盖后抛 `TypeError: 'Event' object is not callable`。
        Python 3.13 移除了那条内部调用 —— 本地 3.13 的 377 条测试全绿，
        云端 Python 3.12 的 worker 一 stop 就崩（systemd 里表现为直接退出）。

    为什么是结构性断言：
        在 3.13 上跑不出行为差异，所以断言对象是「实例 `__dict__` 不许出现内部方法名」。
        ⚠️ 集合里**只放方法名**：像 `_is_stopped` / `_tstate_lock` / `_initialized`
        这类是 `Thread.__init__` 自己写进实例的**属性**，出现在 `__dict__` 里是正常的，
        把它们算进「违规」会误伤。

    为什么必须 `start()` 之后再扫：
        `_runners` 在 `start()` 之前是空列表。第一版用例直接遍历它，
        **在空集合上恒真**（等于没断言），这类「无牙守卫」比没有守卫更危险。
    """

    #: 只列 `Thread` 的**方法名**（CPython 3.9–3.13 并集），覆盖即可能被内部调用到。
    #: ⚠️ 不含 `_invoke_excepthook`：`Thread.__init__` 会把 `_make_invoke_excepthook()`
    #:    的结果写进实例，属正常属性（实测踩过，误报一次）。
    _RESERVED_METHODS = frozenset({
        "_stop",
        "_bootstrap",
        "_bootstrap_inner",
        "_wait_for_tstate_lock",
        "_delete",
        "_reset_internal_locks",
    })

    def _assert_no_shadow(self, thread: threading.Thread) -> None:
        clash = self._RESERVED_METHODS & set(thread.__dict__)
        assert not clash, (
            f"{type(thread).__name__} 用实例属性覆盖了 threading.Thread 的内部方法名 "
            f"{sorted(clash)}：Python ≤3.12 的 join() 会调用 Thread._stop()，"
            f"覆盖后抛 TypeError: 'Event' object is not callable。请改名为 _stop_event 之类。"
        )

    def test_pool_runner_does_not_shadow_thread_methods(self) -> None:
        """直接构造 `_PoolRunner`（不依赖 start），断言其 `__dict__` 干净。"""
        worker = Worker(cpu_threads=1, io_threads=1, mode="external", recover=False)
        runner = _PoolRunner(worker, POOL_CPU, 1)
        try:
            self._assert_no_shadow(runner)
            # 反向自检：守卫真的在读一个非空 dict（防「空对象上恒真」）
            assert runner.__dict__, "_PoolRunner.__dict__ 为空，守卫失效"
            assert "_stop_event" in runner.__dict__, "停止信号应命名为 _stop_event"
        finally:
            runner.executor.shutdown(wait=False)

    def test_started_worker_threads_do_not_shadow_thread_methods(self) -> None:
        """`start()` 之后扫**真实运行的**线程：runners + 维护线程都不许覆盖内部方法名。"""
        worker = Worker(cpu_threads=1, io_threads=1, mode="external", recover=False)
        try:
            worker.start()
            threads: list[threading.Thread] = list(worker._runners)
            if worker._maintenance is not None:
                threads.append(worker._maintenance)
            assert len(threads) >= 2, f"start() 后应至少有 runner + 维护线程，实际 {len(threads)}"
            for thread in threads:
                self._assert_no_shadow(thread)
        finally:
            worker.stop()

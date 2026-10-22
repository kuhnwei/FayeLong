"""P3-5 可观测性用例：`job_id` 日志贯穿 + `/api/health` 的 `disk` 块。

为什么这些断言值得存在（不是「覆盖率凑数」）
============================================
1. **无 job_id 时日志格式逐字不变**：P3-5 之前的所有日志分析 / 用户截图对照都基于
   这个格式。加可观测性最容易踩的坑就是「顺手给所有日志加个空标记」，从而让既有的
   grep / 正则在无人察觉时失效。本文件用「同一个 `LogRecord` 分别经原生 Formatter 与
   本项目的 JobAwareFormatter 渲染，逐字比较」来钉死这件事。
2. **contextvars 必须复位**：`ThreadPoolExecutor` 复用线程，`ContextVar.set()` 的
   影响是线程级的 —— 漏掉 reset，下一条任务（可能是**另一个媒体的** job）的日志会
   带上上一条的 job_id，排错时把人带到完全错误的方向。这里用 `max_workers=1` 的
   单线程池连跑两个任务，直接证明「第二个任务不会继承第一个的 job_id」。
3. **`disk` 块**：拨测脚本会直接读 `free_percent` 做阈值告警，因此字段名/类型/取值
   范围都是对外约定，不能让它在重构中悄悄变成 `None` 或字符串。
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.core.logging import (
    _FORMAT,
    _FORMAT_WITH_JOB,
    JobAwareFormatter,
    JobIdFilter,
    current_job_id,
    job_log_context,
)


def _record(message: str = "hello", name: str = "app.services.jobs") -> logging.LogRecord:
    """构造一条固定时间戳的 `LogRecord`（让两次渲染的 `asctime` 完全一致）。"""
    record = logging.LogRecord(
        name=name,
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=None,
        exc_info=None,
    )
    record.created = 1_700_000_000.0
    record.msecs = 0
    return record


class TestJobIdLogFormat:
    def test_without_job_id_matches_legacy_format_byte_for_byte(self):
        """无 job_id → 与 P3-2 及以前的格式**逐字**相同。"""
        record = _record("已入队 media_transcode ref=1")
        assert JobIdFilter().filter(record) is True
        assert record.job_id is None

        legacy = logging.Formatter(_FORMAT).format(record)
        current = JobAwareFormatter(_FORMAT, _FORMAT_WITH_JOB).format(record)

        assert current == legacy
        assert "[job:" not in current
        # 顺便钉死格式形状本身（别让人「顺手美化」成 ISO 时间戳之类）
        assert current.endswith(" INFO app.services.jobs: 已入队 media_transcode ref=1")

    def test_with_job_id_only_inserts_marker(self):
        """有 job_id → 只在 `name:` 之后插入 `[job:N]`，其余逐字不变。"""
        record = _record("开始执行")
        with job_log_context(42):
            JobIdFilter().filter(record)
        assert record.job_id == "42"

        legacy = logging.Formatter(_FORMAT).format(_record("开始执行"))
        current = JobAwareFormatter(_FORMAT, _FORMAT_WITH_JOB).format(record)

        assert "[job:42] " in current
        assert current.replace("[job:42] ", "") == legacy

    def test_current_job_id_defaults_to_none(self):
        assert current_job_id() is None


class TestJobLogContextReset:
    def test_context_is_cleared_after_block(self):
        with job_log_context(7):
            assert current_job_id() == "7"
        assert current_job_id() is None

    def test_nested_context_restores_outer_value(self):
        with job_log_context(1):
            with job_log_context(2):
                assert current_job_id() == "2"
            assert current_job_id() == "1"
        assert current_job_id() is None

    def test_reset_survives_executor_thread_reuse(self):
        """同一线程跑两条任务：第二条绝不能继承第一条的 job_id。

        这正是 `ThreadPoolExecutor` 复用线程 + `ContextVar` 的经典坑：只在任务开头
        `set()` 而不 `reset()`，第二条任务会读到第一条的值（且这种 bug 在生产里
        表现为「日志张冠李戴」，不会报错）。
        """
        observed: list[str | None] = []

        def task(job_id: int) -> None:
            with job_log_context(job_id):
                observed.append(current_job_id())
            observed.append(current_job_id())   # 退出上下文后，同一线程里必须已复位

        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(task, 11).result()
            pool.submit(task, 22).result()

        assert observed == ["11", None, "22", None]


class TestWorkerJobIdThreading:
    """job_id 必须真的贯穿到 **worker 执行期**（不只是格式好看）。"""

    def test_handler_runs_inside_job_log_context(self, monkeypatch, client):
        # `client` 只用来触发 lifespan → `init_db()`（否则单独跑本文件时临时库没有表）
        from app import worker as worker_mod
        from app.services import jobs as jobs_service

        # 关掉链式推进：本用例只关心「执行期上下文」，不要被后续 stage 干扰
        monkeypatch.setitem(jobs_service.NEXT_STAGE, jobs_service.KIND_ASR, None)

        observed: dict[str, str | None] = {}

        def handler(ctx):
            if ctx.ref_id == 7_001:
                observed["during"] = current_job_id()
                observed["job_id"] = str(ctx.job_id)

        monkeypatch.setitem(worker_mod.Worker.HANDLERS, jobs_service.KIND_ASR, handler)

        job_id = jobs_service.enqueue(jobs_service.KIND_ASR, 7_001)
        assert job_id is not None

        worker = worker_mod.Worker(
            cpu_threads=1, io_threads=1, mode="external", recover=False
        )
        try:
            worker.start()
            assert worker.wait_idle(timeout=15.0), "worker 未在 15s 内空闲"
        finally:
            worker.stop()

        assert observed.get("during") == observed.get("job_id") == str(job_id), \
            "handler 执行期间 current_job_id() 必须等于本任务的 job id"
        # 主线程（pytest 自己）不受影响
        assert current_job_id() is None


class _CaptureHandler(logging.Handler):
    """捕获本进程日志，并把 `job_id` 按与生产一致的 Filter 规则注入。"""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []
        self.addFilter(JobIdFilter())

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D102
        self.records.append(record)


class TestJobIdResetAfterFailure:
    """G1：**异常路径**也必须复位（只测正常路径是不够的）。

    为什么这条非补不可：`_execute` 里 `job_log_context` 的 `finally` 会执行，
    但这是「代码看起来会执行」；真正需要证明的是**线程被复用后**下一条任务不继承
    上一条的 job_id。而上一条任务恰恰是**抛异常结束**的那条 —— 这是最容易漏掉
    reset 的路径（异常会跳过 `else` 分支，且 `handle_failure` 里还有一堆日志）。
    一旦漏了，A（失败）的 job_id 会粘在 B 的日志上，排错时会把人带到完全错误的
    媒体上。
    """

    def test_context_is_reset_for_next_task_after_handler_raises(self, monkeypatch, client):
        from app import worker as worker_mod
        from app.core.config import settings
        from app.services import jobs as jobs_service

        # `client` 只用来触发 lifespan → `init_db()`
        monkeypatch.setitem(jobs_service.NEXT_STAGE, jobs_service.KIND_ASR, None)
        monkeypatch.setattr(settings, "job_max_attempts", 1)   # A 一次失败即终态

        seen: dict[str, str | None] = {}

        def handler(ctx):
            if ctx.ref_id == 7_003:
                raise RuntimeError("替身失败：模拟 handler 崩溃（走终态失败路径）")
            if ctx.ref_id == 7_004:
                seen["during"] = current_job_id()

        monkeypatch.setitem(worker_mod.Worker.HANDLERS, jobs_service.KIND_ASR, handler)

        capture = _CaptureHandler()
        capture.setLevel(logging.INFO)
        root = logging.getLogger()
        previous_level = root.level
        root.addHandler(capture)
        root.setLevel(logging.INFO)
        try:
            job_a = jobs_service.enqueue(jobs_service.KIND_ASR, 7_003)
            job_b = jobs_service.enqueue(jobs_service.KIND_ASR, 7_004)
            assert job_a is not None and job_b is not None

            # cpu=1 → 同一个执行器线程必然被两条任务复用（这是本用例的判别力前提）
            worker = worker_mod.Worker(
                cpu_threads=1, io_threads=1, mode="external", recover=False
            )
            try:
                worker.start()
                assert worker.wait_idle(timeout=20.0), "worker 未在 20s 内空闲"
                # ★ 判别力的真正来源：向**同一个执行线程**提交一个探针，直接读它的
                #   contextvar。理由（QA 的定向变异实测）：只断言「B 的日志里不再出现
                #   [job:A]」是**恒真**的 —— 执行线程上除了上下文内部之外根本没有日志
                #   （claim 日志在 runner 线程、handle_failure 日志在上下文内），所以
                #   「只 set 不 reset」的变异体照样能过。而线程被复用后残留的 job_id
                #   只有从**该线程自身**才观察得到。
                cpu_runner = next(
                    runner for runner in worker._runners
                    if runner.pool == jobs_service.POOL_CPU
                )
                thread_leftover = cpu_runner.executor.submit(current_job_id).result(timeout=10)
            finally:
                worker.stop()
        finally:
            root.removeHandler(capture)
            root.setLevel(previous_level)

        # ① A 确实走了失败路径（否则这条用例在测一个不存在的场景）
        assert any(
            record.job_id == str(job_a) and "执行失败" in record.getMessage()
            for record in capture.records
        ), "任务 A 应当以异常结束并留下带 [job:A] 的失败日志"

        # ② B 执行期间看到的是自己的 id
        assert seen.get("during") == str(job_b)

        # ③ 把记录按生产格式渲染，检查 B 的「开始执行」之后不再出现 A 的标记
        formatter = JobAwareFormatter(_FORMAT, _FORMAT_WITH_JOB)
        rendered = [formatter.format(record) for record in capture.records]
        start_of_b = [
            index
            for index, record in enumerate(capture.records)
            if record.job_id == str(job_b) and "开始执行" in record.getMessage()
        ]
        assert start_of_b, "没找到 B 的「开始执行」日志"
        first_b = start_of_b[0]
        assert f"[job:{job_b}] " in rendered[first_b], "B 的日志必须带 [job:B] 标记"
        leaked = [
            line
            for line in rendered[first_b:]
            if f"[job:{job_a}] " in line
        ]
        assert not leaked, "B 开始执行之后仍出现 A 的 [job:A] 标记 → contextvars 没复位：\n" \
            + "\n".join(leaked)

        # ④ 主线程始终 None
        assert current_job_id() is None

        # ⑤ **执行线程**的上下文也必须已复位（这条才是「只 set 不 reset」变异体的杀手）
        assert thread_leftover is None, (
            "执行线程的 job_id 上下文未被复位（当前值="
            f"{thread_leftover!r}）→ 线程被复用时下一条任务会串号"
        )


class TestEnqueueLog:
    def test_success_and_dedup_paths_are_both_logged(self, client):
        # `client` 只用来触发 lifespan → `init_db()`（见上一个用例的说明）
        from app.services import jobs as jobs_service

        handler = _CaptureHandler()
        handler.setLevel(logging.INFO)
        root = logging.getLogger()
        previous_level = root.level
        root.addHandler(handler)
        root.setLevel(logging.INFO)
        try:
            job_id = jobs_service.enqueue(jobs_service.KIND_CLIP, 7_002)
            assert job_id is not None
            tagged = [
                record for record in handler.records if record.job_id == str(job_id)
            ]
            assert any("入队" in record.getMessage() for record in tagged), \
                "入队成功必须有一条带 job_id 的日志"

            # 去重（`uq_jobs_active` 幂等）是正常路径，但必须留痕且**不带** job_id
            assert jobs_service.enqueue(jobs_service.KIND_CLIP, 7_002) is None
            dedup = [
                record
                for record in handler.records
                if record.job_id is None and "去重" in record.getMessage()
            ]
            assert dedup, "去重路径必须有一条明确日志（否则「点了重试没反应」无从判断）"
        finally:
            root.removeHandler(handler)
            root.setLevel(previous_level)


class TestHealthDiskBlock:
    def test_health_reports_disk_usage(self, client):
        payload = client.get("/api/health").json()

        disk = payload["disk"]
        assert set(disk) == {"total", "used", "free", "free_percent"}
        assert isinstance(disk["total"], int) and disk["total"] > 0
        assert isinstance(disk["used"], int) and disk["used"] >= 0
        assert isinstance(disk["free"], int) and disk["free"] >= 0
        assert isinstance(disk["free_percent"], float)
        assert 0.0 <= disk["free_percent"] <= 100.0
        # 保留 1 位小数（拨测按这个口径做阈值比较）
        assert round(disk["free_percent"], 1) == disk["free_percent"]
        assert disk["used"] + disk["free"] <= disk["total"]

    def test_health_asr_model_flag_is_boolean(self, client):
        """`checks.asr_model` 必须反映模型文件是否存在（布尔），不是「依赖装了没」。"""
        checks = client.get("/api/health").json()["checks"]
        assert isinstance(checks["asr_model"], bool)
        assert isinstance(checks["asr"], bool)

    def test_health_still_has_worker_and_jobs_blocks(self, client):
        payload = client.get("/api/health").json()
        assert set(payload["jobs"]) == {"pending", "running", "done", "failed"}
        assert set(payload["worker"]) == {"online", "count", "mode", "last_heartbeat_at"}

    def test_disk_block_failure_does_not_break_health(self, client, monkeypatch):
        """磁盘统计炸了也不能让自检接口 500（沿用 worker/jobs 块的兜底约定）。"""
        from app.api import health as health_api

        def boom(_path=None):
            raise OSError("disk_usage 失败")

        monkeypatch.setattr(health_api.shutil, "disk_usage", boom)
        payload = client.get("/api/health")
        assert payload.status_code == 200
        assert payload.json()["disk"] == {
            "total": 0, "used": 0, "free": 0, "free_percent": 0.0,
        }

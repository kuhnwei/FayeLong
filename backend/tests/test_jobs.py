"""P3-2 调度内核的单元验收（`services/jobs.py`）。

覆盖 DD-001 §7.1 的清单：入队幂等、原子 claim、fencing（`attempts` 作代次）、
`done` 与下一 stage 同事务、失败重试/终态、以及 5 种崩溃恢复口径。

所有用例只碰**临时库**（conftest 已把 `DB_PATH` 重指向 `tempfile.mkdtemp`），
每个用例前清空 `jobs` / `workers`，因此彼此独立、可重复。
"""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.db import Base, SessionLocal, engine
from app.models import Job, Worker
from app.services import jobs as jobs_service
from app.services.jobs import (
    JOB_DONE,
    JOB_FAILED,
    JOB_PENDING,
    JOB_RUNNING,
    KIND_ASR,
    KIND_CLIP,
    KIND_TRANSCODE,
    KIND_TRANSLATE,
)

@pytest.fixture(scope="module", autouse=True)
def _schema() -> None:
    """确保临时库里有表（不依赖别的测试文件是否先跑过 `app_client`）。"""
    Base.metadata.create_all(bind=engine)


@pytest.fixture(autouse=True)
def _clean_job_tables() -> Any:
    """每个用例前清空调度两张表（临时库，绝不触碰真实 data/）。"""
    db = SessionLocal()
    try:
        db.query(Job).delete()
        db.query(Worker).delete()
        db.commit()
    finally:
        db.close()
    yield


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------


def _scalar(sql: str, params: dict | None = None) -> Any:
    """执行一条 SQL 并返回首行首列（**会 commit**，因此也可用于 UPDATE/DDL）。

    Notes:
        SQLite 的 DDL 也是事务性的 —— 造数据/摘索引必须提交，否则 `close()`
        会把改动回滚掉，用例就变成了「什么都没发生也全绿」。
    """
    db = SessionLocal()
    try:
        result = db.execute(text(sql), params or {})
        value = result.scalar() if result.returns_rows else result.rowcount
        db.commit()
        return value
    finally:
        db.close()


def _rows(sql: str, params: dict | None = None) -> list[tuple]:
    """执行一条返回多行的 SQL。"""
    db = SessionLocal()
    try:
        return [tuple(row) for row in db.execute(text(sql), params or {}).all()]
    finally:
        db.close()


def _job_row(kind: str, ref_id: int) -> tuple | None:
    rows = _rows(
        "SELECT id, status, attempts, worker_id, heartbeat_at, started_at, finished_at, progress"
        " FROM jobs WHERE kind = :kind AND ref_id = :ref_id ORDER BY id DESC LIMIT 1",
        {"kind": kind, "ref_id": ref_id},
    )
    return rows[0] if rows else None


def _claim_one(worker_id: str = "w-test", kinds: tuple[str, ...] = (KIND_TRANSCODE,)) -> Job | None:
    db = SessionLocal()
    try:
        return jobs_service.claim(db, list(kinds), worker_id)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 入队
# ---------------------------------------------------------------------------


class TestEnqueue:
    def test_enqueue_creates_pending(self) -> None:
        job_id = jobs_service.enqueue(KIND_TRANSCODE, ref_id=7)
        assert job_id is not None
        row = _job_row(KIND_TRANSCODE, 7)
        assert row is not None
        _id, status, attempts, worker_id, heartbeat_at, started_at, finished_at, progress = row
        assert status == JOB_PENDING
        assert attempts == 0
        assert worker_id is None
        assert heartbeat_at is None
        assert started_at is None
        assert finished_at is None
        assert progress == 0

    def test_enqueue_is_idempotent_on_active(self) -> None:
        first = jobs_service.enqueue(KIND_TRANSCODE, ref_id=7)
        second = jobs_service.enqueue(KIND_TRANSCODE, ref_id=7)
        assert first is not None
        assert second is None, "重复入队必须因 uq_jobs_active 变 no-op"
        assert _scalar("SELECT COUNT(*) FROM jobs WHERE kind=:k AND ref_id=7", {"k": KIND_TRANSCODE}) == 1

    def test_enqueue_allowed_after_terminal(self) -> None:
        """`uq_jobs_active` 只管活跃态：failed 之后必须能再入队（DD-001 §9 R1）。"""
        job_id = jobs_service.enqueue(KIND_TRANSCODE, ref_id=11)
        assert job_id is not None
        _scalar(
            "UPDATE jobs SET status='failed', finished_at=CURRENT_TIMESTAMP WHERE id=:id",
            {"id": job_id},
        )

        again = jobs_service.enqueue(KIND_TRANSCODE, ref_id=11)
        assert again is not None and again != job_id
        assert _scalar("SELECT COUNT(*) FROM jobs WHERE kind=:k AND ref_id=11", {"k": KIND_TRANSCODE}) == 2

    def test_enqueue_rejects_null_ref_id(self) -> None:
        with pytest.raises(ValueError):
            jobs_service.enqueue(KIND_TRANSCODE, None)  # type: ignore[arg-type]

    def test_enqueue_rejects_empty_kind(self) -> None:
        with pytest.raises(ValueError):
            jobs_service.enqueue("", 5)

    def test_partial_unique_index_is_partial(self) -> None:
        """`uq_jobs_active` 的 DDL 必须含 WHERE（写成普通唯一索引是致命且静默的 bug）。"""
        ddl = _scalar("SELECT sql FROM sqlite_master WHERE type='index' AND name='uq_jobs_active'")
        assert ddl is not None, "uq_jobs_active 未创建"
        normalized = " ".join(str(ddl).split())
        assert "WHERE status IN (" in normalized, normalized
        for status_value in ("'pending'", "'running'"):
            assert status_value in normalized, normalized


# ---------------------------------------------------------------------------
# 认领（执行权唯一来源）
# ---------------------------------------------------------------------------


class TestClaim:
    def test_claim_is_atomic(self) -> None:
        """两个会话抢同一个 job：只有一个 rowcount==1，另一个拿 None。"""
        jobs_service.enqueue(KIND_TRANSCODE, ref_id=21)

        db_a = SessionLocal()
        db_b = SessionLocal()
        try:
            got_a = jobs_service.claim(db_a, [KIND_TRANSCODE], "worker-a")
            got_b = jobs_service.claim(db_b, [KIND_TRANSCODE], "worker-b")
        finally:
            db_a.close()
            db_b.close()

        assert (got_a is None) != (got_b is None), "同一任务不能被两个执行者同时抢到"
        winner = got_a or got_b
        row = _job_row(KIND_TRANSCODE, 21)
        assert row is not None
        assert row[2] == 1, "只应 +1 一次"
        assert row[3] == winner.worker_id

    def test_claim_bumps_attempts_and_sets_lease(self) -> None:
        jobs_service.enqueue(KIND_TRANSCODE, ref_id=22)

        first = _claim_one("w-1")
        assert first is not None
        assert first.attempts == 1
        assert first.worker_id == "w-1"
        assert first.heartbeat_at is not None
        assert first.started_at is not None
        first_started = first.started_at

        # 放回 pending 再抢一次：started_at 必须保持首次 claim 的时间
        _scalar("UPDATE jobs SET status='pending', worker_id=NULL, heartbeat_at=NULL WHERE id=:i",
                {"i": first.id})
        second = _claim_one("w-2")
        assert second is not None
        assert second.attempts == 2
        assert second.worker_id == "w-2"
        assert second.started_at == first_started, "started_at 只能写一次（COALESCE）"

    def test_claim_returns_none_when_queue_empty(self) -> None:
        assert _claim_one("w-1", kinds=(KIND_ASR,)) is None

    def test_claim_honours_priority(self) -> None:
        low = jobs_service.enqueue(KIND_TRANSCODE, ref_id=31, priority=0)
        high = jobs_service.enqueue(KIND_TRANSCODE, ref_id=32, priority=10)
        claimed = _claim_one("w-prio")
        assert claimed is not None
        assert claimed.id == high, f"高优先应先被认领（low={low} high={high}）"


# ---------------------------------------------------------------------------
# fencing：touch / check_alive
# ---------------------------------------------------------------------------


class TestFencing:
    def test_touch_with_stale_attempt_is_rejected(self) -> None:
        jobs_service.enqueue(KIND_TRANSCODE, ref_id=41)
        job = _claim_one("w-1")
        assert job is not None

        db = SessionLocal()
        try:
            assert jobs_service.touch(db, job.id, job.attempts, "w-1") is True
            assert jobs_service.touch(db, job.id, job.attempts - 1, "w-1") is False, \
                "旧代次的写回必须 rowcount=0"
            assert jobs_service.touch(db, job.id, job.attempts, "w-other") is False, \
                "别的 worker 不能给别人的任务续租"
            db.commit()
        finally:
            db.close()

    def test_check_alive_false_after_reap(self) -> None:
        jobs_service.enqueue(KIND_TRANSCODE, ref_id=42)
        job = _claim_one("w-1")
        assert job is not None

        # 模拟被回收：回到 pending、清 worker_id
        _scalar("UPDATE jobs SET status='pending', worker_id=NULL, heartbeat_at=NULL WHERE id=:i",
                {"i": job.id})

        db = SessionLocal()
        try:
            assert jobs_service.check_alive(db, job.id, "w-1", job.attempts) is False
        finally:
            db.close()

    def test_check_alive_true_while_running(self) -> None:
        jobs_service.enqueue(KIND_TRANSCODE, ref_id=43)
        job = _claim_one("w-1")
        assert job is not None
        db = SessionLocal()
        try:
            assert jobs_service.check_alive(db, job.id, "w-1", job.attempts) is True
        finally:
            db.close()

    def test_finish_ok_writes_done(self) -> None:
        jobs_service.enqueue(KIND_TRANSCODE, ref_id=44)
        job = _claim_one("w-1")
        assert job is not None

        db = SessionLocal()
        try:
            assert jobs_service.finish_ok(db, job, next_kind=None) is True
            db.commit()
        finally:
            db.close()

        row = _job_row(KIND_TRANSCODE, 44)
        assert row is not None and row[1] == JOB_DONE

    def test_second_finish_ok_is_rejected(self) -> None:
        """已完成的任务再写一次必须被 fencing 拒绝（防「老执行者复活」）。"""
        jobs_service.enqueue(KIND_TRANSCODE, ref_id=45)
        job = _claim_one("w-1")
        assert job is not None

        db = SessionLocal()
        try:
            assert jobs_service.finish_ok(db, job, next_kind=None) is True
            db.commit()
            assert jobs_service.finish_ok(db, job, next_kind=None) is False
            db.commit()
        finally:
            db.close()


# ---------------------------------------------------------------------------
# 完成 / 失败写回
# ---------------------------------------------------------------------------


class TestWriteBack:
    def test_finish_ok_chains_next_stage_in_same_tx(self) -> None:
        """`done` 与「入队下一 stage」必须同一次 commit（否则中途崩溃任务消失）。"""
        jobs_service.enqueue(KIND_TRANSCODE, ref_id=51)
        job = _claim_one("w-1")
        assert job is not None

        db = SessionLocal()
        try:
            assert jobs_service.finish_ok(db, job, next_kind=KIND_ASR) is True
            db.commit()
        finally:
            db.close()

        row = _job_row(KIND_TRANSCODE, 51)
        assert row is not None and row[1] == JOB_DONE and row[6] is not None
        nxt = _job_row(KIND_ASR, 51)
        assert nxt is not None, "下一 stage 未入队"
        assert nxt[1] == JOB_PENDING and nxt[2] == 0

    def test_finish_ok_rollback_discards_both_rows(self) -> None:
        """反向验证「同一事务」：未 commit 时两条变更都不可见。"""
        jobs_service.enqueue(KIND_TRANSCODE, ref_id=52)
        job = _claim_one("w-1")
        assert job is not None

        db = SessionLocal()
        try:
            assert jobs_service.finish_ok(db, job, next_kind=KIND_ASR) is True
            db.rollback()   # 模拟「还没提交就崩了」
        finally:
            db.close()

        row = _job_row(KIND_TRANSCODE, 52)
        assert row is not None and row[1] == JOB_RUNNING, "未提交的 done 不该可见"
        assert _job_row(KIND_ASR, 52) is None, "未提交的下一 stage 不该可见"

    def test_finish_ok_terminal_stage_sets_finished_at(self) -> None:
        jobs_service.enqueue(KIND_CLIP, ref_id=53)
        job = _claim_one("w-1", kinds=(KIND_CLIP,))
        assert job is not None

        db = SessionLocal()
        try:
            assert jobs_service.finish_ok(db, job, next_kind=jobs_service.NEXT_STAGE[KIND_CLIP]) is True
            db.commit()
        finally:
            db.close()

        row = _job_row(KIND_CLIP, 53)
        assert row is not None
        assert row[1] == JOB_DONE
        assert row[6] is not None, "finished_at 必须写"
        assert _scalar("SELECT COUNT(*) FROM jobs WHERE ref_id=53") == 1, "链尾不应再产生新 job"

    def test_finish_failed_retries_under_limit(self) -> None:
        jobs_service.enqueue(KIND_TRANSCODE, ref_id=54)
        job = _claim_one("w-1")
        assert job is not None

        db = SessionLocal()
        try:
            outcome = jobs_service.finish_failed(db, job, "临时失败", max_attempts=3)
            db.commit()
        finally:
            db.close()

        assert outcome == JOB_PENDING
        row = _job_row(KIND_TRANSCODE, 54)
        assert row is not None
        assert row[1] == JOB_PENDING
        assert row[3] is None, "重试必须清 worker_id"
        assert row[4] is None, "重试必须清 heartbeat_at"
        error = _scalar("SELECT error FROM jobs WHERE id=:i", {"i": job.id})
        assert error and "临时失败" in error

    def test_finish_failed_terminal_over_limit(self) -> None:
        jobs_service.enqueue(KIND_TRANSCODE, ref_id=55)
        job = _claim_one("w-1")
        assert job is not None
        # 把 attempts 直接顶到上限（模拟已经试过 3 次）
        _scalar("UPDATE jobs SET attempts=3 WHERE id=:i", {"i": job.id})

        db = SessionLocal()
        try:
            fresh = db.get(Job, job.id)
            outcome = jobs_service.finish_failed(db, fresh, "彻底失败", max_attempts=3)
            db.commit()
        finally:
            db.close()

        assert outcome == JOB_FAILED
        row = _job_row(KIND_TRANSCODE, 55)
        assert row is not None
        assert row[1] == JOB_FAILED
        assert row[6] is not None, "终态必须写 finished_at"

    def test_finish_failed_truncates_error(self) -> None:
        jobs_service.enqueue(KIND_TRANSCODE, ref_id=56)
        job = _claim_one("w-1")
        assert job is not None
        db = SessionLocal()
        try:
            jobs_service.finish_failed(db, job, "x" * 1000, max_attempts=3)
            db.commit()
        finally:
            db.close()
        assert len(_scalar("SELECT error FROM jobs WHERE id=:i", {"i": job.id})) == 500


# ---------------------------------------------------------------------------
# 崩溃恢复
# ---------------------------------------------------------------------------


def _make_running(
    kind: str,
    ref_id: int,
    *,
    worker_id: str | None,
    heartbeat_offset_sec: int | None,
    attempts: int = 1,
) -> None:
    """直接造一条 `running` 任务（绕过 claim，便于精确控制状态）。"""
    jobs_service.enqueue(kind, ref_id)
    if heartbeat_offset_sec is None:
        params = {
            "kind": kind, "ref_id": ref_id, "worker": worker_id, "attempts": attempts,
        }
        _scalar(
            "UPDATE jobs SET status='running', worker_id=:worker, attempts=:attempts,"
            " started_at=CURRENT_TIMESTAMP, heartbeat_at=CURRENT_TIMESTAMP"
            " WHERE kind=:kind AND ref_id=:ref_id",
            params,
        )
        return
    _scalar(
        "UPDATE jobs SET status='running', worker_id=:worker, attempts=:attempts,"
        " started_at=datetime('now','-400 seconds'),"
        " heartbeat_at=datetime('now',:offset)"
        " WHERE kind=:kind AND ref_id=:ref_id",
        {
            "kind": kind, "ref_id": ref_id, "worker": worker_id,
            "attempts": attempts, "offset": f"-{int(heartbeat_offset_sec)} seconds",
        },
    )


def _register_online_worker(worker_id: str = "w-live") -> None:
    db = SessionLocal()
    try:
        jobs_service.register_worker(db, worker_id, 4242, mode="external", pools="cpu=1,io=1")
    finally:
        db.close()


class TestRecoverStale:
    def test_recover_stale_by_lease_timeout(self) -> None:
        """租约过期（心跳 200s 前）→ 回 pending。"""
        _make_running(KIND_TRANSCODE, 61, worker_id="w-live", heartbeat_offset_sec=200)
        _register_online_worker("w-live")   # worker 在线，但租约已过期

        db = SessionLocal()
        try:
            assert jobs_service.recover_stale(db) == 1
        finally:
            db.close()

        row = _job_row(KIND_TRANSCODE, 61)
        assert row is not None
        assert row[1] == JOB_PENDING
        assert row[3] is None and row[4] is None

    def test_recover_stale_by_dead_worker(self) -> None:
        """`worker_id` 不在在线集合 → **即使心跳很新**也回收（DD-001 §4.3 第 6 条 OR）。"""
        _make_running(KIND_TRANSCODE, 62, worker_id="ghost", heartbeat_offset_sec=0)

        db = SessionLocal()
        try:
            assert jobs_service.recover_stale(db) == 1
        finally:
            db.close()

        assert _job_row(KIND_TRANSCODE, 62)[1] == JOB_PENDING

    def test_recover_skips_live_job_with_fresh_lease(self) -> None:
        """不误伤护栏：在线 worker + 心跳 5s 前 → 绝不回收。"""
        _register_online_worker("w-live")
        _make_running(KIND_TRANSCODE, 63, worker_id="w-live", heartbeat_offset_sec=5)

        db = SessionLocal()
        try:
            assert jobs_service.recover_stale(db) == 0
        finally:
            db.close()

        row = _job_row(KIND_TRANSCODE, 63)
        assert row[1] == JOB_RUNNING
        assert row[3] == "w-live"

    def test_recover_marks_failed_when_attempts_exhausted(self) -> None:
        """次数已用尽的僵死任务直接 failed（防崩溃循环）。"""
        _make_running(KIND_TRANSCODE, 64, worker_id="ghost", heartbeat_offset_sec=400, attempts=3)

        db = SessionLocal()
        try:
            assert jobs_service.recover_stale(db) == 1
        finally:
            db.close()

        row = _job_row(KIND_TRANSCODE, 64)
        assert row[1] == JOB_FAILED
        assert row[6] is not None

    def test_active_duplicate_state_is_impossible(self) -> None:
        """同一 `(kind, ref_id)` 不可能有 2 条活跃行 —— 部分唯一索引的硬保证。

        设计稿 §7.1 的 `test_recover_does_not_double_enqueue` 想「强行造」这个脏
        状态，再验证回收路径撞索引时不抛异常。**实测造不出来**：把索引摘掉灌入脏
        数据后，索引一建回来 SQLite 立刻用 `IntegrityError` 拒绝（`CREATE UNIQUE
        INDEX` 会校验存量数据）。也就是说 `uq_jobs_active` 是一条**结构性**保证，
        而不是靠代码自觉。

        因此这里改为等价的、可重复的两条断言：
          ① 脏状态在索引存在时**无法存在**（回收路径根本遇不到它）；
          ② 正常数据上回收是幂等的（第二次不再回收）。
        `recover_stale()` 里仍保留了「同键已有活跃行 → 改判 failed」的防御分支，
        它只是一层不会触发的保险。
        """
        jobs_service.enqueue(KIND_TRANSCODE, ref_id=65)   # 活跃行 A（pending）
        _scalar("DROP INDEX uq_jobs_active")
        _scalar(
            "INSERT INTO jobs (kind, ref_id, status, progress, priority, payload, attempts,"
            " worker_id, started_at, heartbeat_at)"
            " VALUES (:k, 65, 'running', 30, 0, '{}', 1, 'ghost',"
            " datetime('now','-400 seconds'), datetime('now','-400 seconds'))",
            {"k": KIND_TRANSCODE},
        )
        assert _scalar(
            "SELECT COUNT(*) FROM jobs WHERE kind=:k AND ref_id=65 AND status IN ('pending','running')",
            {"k": KIND_TRANSCODE},
        ) == 2, "前置条件：索引摘掉后确实能造出 2 条活跃行"

        with pytest.raises(Exception):
            # 索引一建回来就拒绝存量脏数据 → 这条约束是真的（不是注释里的君子协定）
            _scalar(
                "CREATE UNIQUE INDEX uq_jobs_active ON jobs(kind, ref_id)"
                " WHERE status IN ('pending','running')"
            )

        # 清掉脏行、把索引建回去，验证回收在正常数据上幂等且不抛异常。
        _scalar("DELETE FROM jobs WHERE status='running' AND worker_id='ghost'")
        _scalar(
            "CREATE UNIQUE INDEX uq_jobs_active ON jobs(kind, ref_id)"
            " WHERE status IN ('pending','running')"
        )
        _make_running(KIND_TRANSCODE, 65, worker_id="ghost2", heartbeat_offset_sec=400)
        db = SessionLocal()
        try:
            assert jobs_service.recover_stale(db) == 1
            assert jobs_service.recover_stale(db) == 0
        finally:
            db.close()
        assert _scalar(
            "SELECT COUNT(*) FROM jobs WHERE kind=:k AND ref_id=65 AND status IN ('pending','running')",
            {"k": KIND_TRANSCODE},
        ) == 1, "活跃行仍只有 1 条"

    def test_recover_is_idempotent(self) -> None:
        _make_running(KIND_TRANSCODE, 66, worker_id="ghost", heartbeat_offset_sec=400)
        db = SessionLocal()
        try:
            assert jobs_service.recover_stale(db) == 1
            assert jobs_service.recover_stale(db) == 0
        finally:
            db.close()


# ---------------------------------------------------------------------------
# 续租 / 删除媒体的清理 / 统计
# ---------------------------------------------------------------------------


class TestMaintenance:
    def test_renew_lease_touches_all_running_jobs_of_worker(self) -> None:
        jobs_service.enqueue(KIND_TRANSCODE, ref_id=71)
        jobs_service.enqueue(KIND_TRANSCODE, ref_id=72)
        job_a = _claim_one("w-1")
        job_b = _claim_one("w-1")
        assert job_a is not None and job_b is not None
        _scalar("UPDATE jobs SET heartbeat_at=datetime('now','-100 seconds') WHERE worker_id='w-1'")

        db = SessionLocal()
        try:
            assert jobs_service.renew_lease(db, "w-1") == 2
            assert jobs_service.renew_lease(db, "w-other") == 0
        finally:
            db.close()

        stale = _scalar(
            "SELECT COUNT(*) FROM jobs WHERE worker_id='w-1'"
            " AND heartbeat_at <= datetime('now','-50 seconds')"
        )
        assert stale == 0, "两个 running job 的租约都应被续上"

    def test_purge_for_media_only_touches_media_kinds(self) -> None:
        jobs_service.enqueue(KIND_TRANSCODE, ref_id=81)
        jobs_service.enqueue(KIND_ASR, ref_id=81)
        jobs_service.enqueue(jobs_service.KIND_GRADE_WRITING, ref_id=81)

        db = SessionLocal()
        try:
            assert jobs_service.purge_for_media(db, 81) == 2
            db.commit()
        finally:
            db.close()

        left = _rows("SELECT kind FROM jobs WHERE ref_id=81")
        assert [row[0] for row in left] == [jobs_service.KIND_GRADE_WRITING]

    def test_counts_by_status_has_all_four_keys(self) -> None:
        jobs_service.enqueue(KIND_TRANSCODE, ref_id=91)
        db = SessionLocal()
        try:
            counts = jobs_service.counts_by_status(db)
        finally:
            db.close()
        assert set(counts) == {JOB_PENDING, JOB_RUNNING, JOB_DONE, JOB_FAILED}
        assert counts[JOB_PENDING] == 1

    def test_worker_register_heartbeat_unregister(self) -> None:
        db = SessionLocal()
        try:
            jobs_service.register_worker(db, "w-reg", 1234, mode="web-inproc", pools="cpu=1")
            assert [w.id for w in jobs_service.online_workers(db)] == ["w-reg"]
            assert jobs_service.heartbeat_worker(db, "w-reg") is True
            snapshot = jobs_service.worker_snapshot(db)
            assert snapshot["online"] is True
            assert snapshot["count"] == 1
            assert snapshot["mode"] == "web-inproc"
            assert isinstance(snapshot["last_heartbeat_at"], str)

            jobs_service.unregister_worker(db, "w-reg")
            assert jobs_service.online_workers(db) == []
        finally:
            db.close()

    def test_offline_worker_is_not_online(self) -> None:
        """心跳早于 TTL 的 worker 不算在线（`auto` 模式的接管判据）。"""
        db = SessionLocal()
        try:
            jobs_service.register_worker(db, "w-old", 1, mode="external")
            assert len(jobs_service.online_workers(db)) == 1
            db.execute(
                text("UPDATE workers SET heartbeat_at=datetime('now',:offset) WHERE id='w-old'"),
                {"offset": f"-{int(settings.job_worker_ttl_sec) + 5} seconds"},
            )
            db.commit()
            assert jobs_service.online_workers(db) == []
        finally:
            db.close()

    def test_cleanup_dead_workers(self) -> None:
        db = SessionLocal()
        try:
            jobs_service.register_worker(db, "w-dead", 1, mode="external")
            db.execute(
                text("UPDATE workers SET heartbeat_at=datetime('now','-3600 seconds') WHERE id='w-dead'")
            )
            db.commit()
            assert jobs_service.cleanup_dead_workers(db) == 1
            assert _scalar("SELECT COUNT(*) FROM workers") == 0
        finally:
            db.close()


# ---------------------------------------------------------------------------
# 表约束（schema 层面拦住的错误）
# ---------------------------------------------------------------------------


class TestSchemaGuards:
    def test_ref_id_is_not_null(self) -> None:
        """`ref_id NOT NULL`：可空会让部分唯一索引被 NULL 语义绕过（DD-001 §3.1）。"""
        with sqlite3.connect(str(engine.url.database)) as conn:
            info = {row[1]: row for row in conn.execute("PRAGMA table_info(jobs)")}
        assert info["ref_id"][3] == 1, info["ref_id"]   # notnull 列

    def test_status_check_constraint(self) -> None:
        with pytest.raises(Exception):
            _scalar(
                "INSERT INTO jobs (kind, ref_id, status) VALUES ('media_asr', 1, 'cancelled')"
            )

    def test_progress_check_constraint(self) -> None:
        with pytest.raises(Exception):
            _scalar(
                "INSERT INTO jobs (kind, ref_id, status, progress)"
                " VALUES ('media_asr', 2, 'pending', 101)"
            )


class TestHasActiveWork:
    """`has_active_work()` 的 kind 过滤（P4 挂账 A3 的单元层）。

    基线语义（不带参数 = 全局）必须保持不变，否则 `wait_idle()` 的既有用例会
    静默改变含义；新加的两个可选过滤参数只为让 `_PoolRunner.idle()` 能问出
    「**我这个池**还有没有活」。
    """

    def test_empty_queue_is_false(self) -> None:
        db = SessionLocal()
        try:
            assert jobs_service.has_active_work(db) is False
        finally:
            db.close()

    def test_global_default_sees_any_kind(self) -> None:
        jobs_service.enqueue(KIND_TRANSLATE, ref_id=901)
        db = SessionLocal()
        try:
            assert jobs_service.has_active_work(db) is True
        finally:
            db.close()

    def test_kinds_filter_is_exclusive(self) -> None:
        jobs_service.enqueue(KIND_TRANSLATE, ref_id=902)
        db = SessionLocal()
        try:
            assert jobs_service.has_active_work(db, kinds=[KIND_TRANSLATE]) is True
            assert jobs_service.has_active_work(db, kinds=[KIND_ASR]) is False
            assert jobs_service.has_active_work(db, kinds=[]) is True, "空列表 = 不过滤"
        finally:
            db.close()

    def test_exclude_kinds_filter(self) -> None:
        """「除这些之外都算」—— CPU 池的口径（它要覆盖所有未登记 kind）。"""
        jobs_service.enqueue(KIND_TRANSLATE, ref_id=903)
        db = SessionLocal()
        try:
            assert jobs_service.has_active_work(db, exclude_kinds=[KIND_TRANSLATE]) is False
            assert jobs_service.has_active_work(db, exclude_kinds=[KIND_ASR]) is True
        finally:
            db.close()

    def test_running_and_finished_jobs_do_not_count(self) -> None:
        """只数 `pending`：running 由「在飞计数」管，done/failed 是历史。"""
        jobs_service.enqueue(KIND_ASR, ref_id=904)
        db = SessionLocal()
        try:
            job = jobs_service.claim(db, [KIND_ASR], "worker-x")
        finally:
            db.close()
        assert job is not None

        db = SessionLocal()
        try:
            # running：已经不在 pending 里
            assert jobs_service.has_active_work(db) is False
            # 重试上限给 1 → 直接判终态 failed（若回到 pending，下一条断言就会假红）
            outcome = jobs_service.finish_failed(db, job, "boom", max_attempts=1)
            db.commit()
        finally:
            db.close()
        assert outcome == JOB_FAILED

        db = SessionLocal()
        try:
            # failed：也不算「还有活」
            assert jobs_service.has_active_work(db) is False
        finally:
            db.close()

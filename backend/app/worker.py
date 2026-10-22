"""独立 worker 进程：`python -m app.worker`。

职责
====
把 `jobs` 表里 `pending` 的任务认领出来执行，两个池物理隔离：
  * **CPU 池**（`job_cpu_threads`，0 = 核数）：`media_transcode` / `media_asr` / `media_clip`
  * **IO 池**（`job_io_threads`，默认 4）：`media_translate` / `grade_writing`（P4）

为什么必须拆池：长 ASR 会占满 CPU 槽位，若翻译也在同一个池里排队，
G3-③「ASR 不阻塞翻译」物理上不可能通过（DD-001 §5.2）。

线程模型
========
::

    main thread
      ├─ _maintenance 线程：worker 心跳(10s) / 租约续期(20s) / 恢复扫描(5s)
      ├─ _PoolRunner(cpu)：主循环 claim → 丢给 cpu executor（size = cpu_threads）
      └─ _PoolRunner(io) ：主循环 claim → 丢给 io executor （size = io_threads）

`_PoolRunner` 自己也是线程，但**只负责认领与派发**（`ThreadPoolExecutor.submit`），
真正的 handler 跑在 executor 的线程里。用信号量把「在飞任务数」压在池容量内。

⚠️ 绝不调用 `input()`
=====================
打包版用 `pythonw.exe` 启动，没有控制台：任何 `input()` / `msvcrt.getch()` 都会抛
`RuntimeError: input(): lost sys.stdin`，进程直接死掉且**没有任何提示**。
因此这里没有任何交互式确认，`--once` 也只是「跑完手上这批就退出」。
"""

from __future__ import annotations

import argparse
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Sequence

from app.core.config import LOG_DIR, ensure_dirs, settings
from app.core.logging import WORKER_LOG_FILENAME, job_log_context, setup_logging
from app.core.tasks import new_executor
from app.db import SessionLocal, init_db
from app.models import Job
from app.services import jobs as jobs_service
from app.services import media as media_service
from app.services import grading as grading_service
from app.services.jobs import JobAborted, JobCtx

logger = logging.getLogger(__name__)

#: handler 签名：只收一个 `JobCtx`。
Handler = Callable[[JobCtx], None]


# ---------------------------------------------------------------------------
# kind → handler 映射（**模块级 dict，测试与子进程都靠它注入替身**）
# ---------------------------------------------------------------------------


def _handle_transcode(ctx: JobCtx) -> None:
    media_service.stage_transcode(ctx.ref_id, ctx)


def _handle_asr(ctx: JobCtx) -> None:
    media_service.stage_asr(ctx.ref_id, ctx)


def _handle_translate(ctx: JobCtx) -> None:
    media_service.stage_translate(ctx.ref_id, ctx)


def _handle_clip(ctx: JobCtx) -> None:
    media_service.stage_clip(ctx.ref_id, ctx)


def _handle_grade_writing(ctx: JobCtx) -> None:
    """P4-4：写作批改（IO 池）。`ctx.ref_id` = `responses.id`。

    Notes:
        真正的判分在 :func:`app.services.grading.service.run_grade_job` 里：它负责
        缓存 / 成本闸 / 降级 / 落库与 fencing。这里只做一个转发，好处是
        `worker.py` 不必 import 题型与 provider（那些模块的依赖面比调度层大得多）。
    """
    grading_service.run_grade_job(ctx)


#: `KIND_*` → 执行函数。
#: ⚠️ **必须是模块级、可原地 patch 的普通 dict**：`tests/test_worker_pools.py` 靠
#: `Worker.HANDLERS[kind] = fake` 注入「慢 ASR / 快翻译」，从而不依赖 whisper
#: 模型、ffmpeg 与网络（G3-③ 才可能 1 秒内跑完且可重复）。
#: `grade_writing` 自 P4-4 起**已登记**（此前刻意不登记 → 未登记的 kind 会被判失败）。
HANDLERS: dict[str, Handler] = {
    jobs_service.KIND_TRANSCODE: _handle_transcode,
    jobs_service.KIND_ASR: _handle_asr,
    jobs_service.KIND_TRANSLATE: _handle_translate,
    jobs_service.KIND_CLIP: _handle_clip,
    jobs_service.KIND_GRADE_WRITING: _handle_grade_writing,
}

#: 维护线程的 tick（秒）。用它把三个不同周期的动作（心跳/续租/恢复）挂在一条
#: 线程上，避免开三条几乎不干活的线程。0.2s 的空转开销可忽略，但让「续租间隔
#: 设成 1s」这种测试配置能真实生效。
_MAINTENANCE_TICK_SEC = 0.2

#: 恢复扫描间隔（秒），DD-001 §4.1。
RECOVERY_INTERVAL_SEC = 5.0

#: `--parent-pid` 的检查间隔（秒）。设计稿写 15s，这里改 5s：
#: ① 孤儿 worker 越早退出越好（它会和新 worker 抢任务、白占内存）；
#: ② 验收用例要求「15s 内自行退出」，检查间隔就等于下限，5s 留足余量；
#: ③ 一次 stat 调用的成本可忽略。
PARENT_CHECK_INTERVAL_SEC = 5.0

#: `data/logs/fayelong.pid` —— launcher 写入自己的 pid，worker 用它做孤儿自检。
PARENT_PID_FILENAME = "fayelong.pid"


class MissingHandlerError(RuntimeError):
    """某个 kind 没有注册 handler（配置/代码错误，**不重试**，直接判失败）。"""


# ---------------------------------------------------------------------------
# 池执行器
# ---------------------------------------------------------------------------


class _PoolRunner(threading.Thread):
    """一个池的「认领 + 派发」循环。

    Attributes:
        pool: 池名（`cpu` / `io`）。
        size: 池容量（同时在飞的 handler 数上限）。
    """

    def __init__(self, worker: "Worker", pool: str, size: int) -> None:
        super().__init__(name=f"fayelong-{pool}-runner", daemon=True)
        self.pool = pool
        self.owner = worker
        self.size = max(1, int(size))
        self.executor: ThreadPoolExecutor = new_executor(pool, self.size)
        self._slots = threading.Semaphore(self.size)
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._active = 0
        self._poll = max(0.05, settings.job_poll_interval_ms / 1000.0)
        self._idle_max = max(self._poll, settings.job_idle_max_ms / 1000.0)

        # 认领口径：
        #   CPU 池 = 「排除 IO 池的 kind」→ 自动覆盖**未登记 kind**（DEFAULT_POOL=cpu）
        #   IO  池 = 显式白名单（只认自己那几个）
        if pool == jobs_service.POOL_CPU:
            self.kinds: tuple[str, ...] | None = None
            self.exclude_kinds: tuple[str, ...] = tuple(
                kind
                for kind in jobs_service.ALL_KINDS
                if jobs_service.pool_of(kind) != jobs_service.POOL_CPU
            )
        else:
            self.kinds = tuple(jobs_service.kinds_of_pool(pool))
            self.exclude_kinds = ()

    # -------------------------------------------------------------- 状态查询
    def active_count(self) -> int:
        """当前在飞的 handler 数。"""
        with self._lock:
            return self._active

    def idle(self) -> bool:
        """本池是否已无事可做（没有在飞任务，也没有**本池认领得了的** pending）。

        Returns:
            `True` = 本池空闲。

        Notes:
            **P4 挂账 A3**：判据必须带上本池的 kind 过滤（`self.kinds` /
            `self.exclude_kinds`），否则 `--once` 在「队列里只剩别的池的 job」时
            会空转到 `drain_timeout`（最多 5s）。过滤口径与 `_claim_one()` 完全
            一致 —— 两条路径若各写一份，就会出现「idle 说没事、claim 却抢到活」
            的诡异状态。
        """
        if self.active_count() > 0:
            return False
        db = SessionLocal()
        try:
            return not jobs_service.has_active_work(
                db, kinds=self.kinds, exclude_kinds=self.exclude_kinds
            )
        finally:
            db.close()

    # ------------------------------------------------------------------ 循环
    def run(self) -> None:  # noqa: D401  （threading.Thread 的约定入口）
        """主循环：抢槽位 → 认领 → 派发；空转时指数退避到 `job_idle_max_ms`。"""
        idle_delay = self._poll
        while not self._stop.is_set():
            if not self._slots.acquire(timeout=self._poll):
                continue
            # ★ 先占住「我可能要执行」的名额，**再**认领。
            #   `claim()` 已提交事务（行变 running）到 `executor.submit()` 之间有一个
            #   窗口，若此刻 `idle()` 观察，就会看到「active==0 且无 pending」→ 误判
            #   空闲（实测会让 `wait_idle()` 随机假绿，进而让用例在任务仍 running 时
            #   就去断言结果）。把名额提前占住，这个窗口就不存在了。
            with self._lock:
                self._active += 1
            try:
                job = self._claim_one()
            except Exception:  # noqa: BLE001  认领失败不能让池线程死掉
                logger.exception("%s 池认领任务出错", self.pool)
                with self._lock:
                    self._active -= 1
                self._slots.release()
                self._stop.wait(self._idle_max)
                continue

            if job is None:
                with self._lock:
                    self._active -= 1
                self._slots.release()
                self._stop.wait(idle_delay)
                idle_delay = min(self._idle_max, idle_delay * 2)
                continue

            idle_delay = self._poll
            try:
                self.executor.submit(self._execute, job)
            except RuntimeError:  # 执行器已关闭（进程退出中）
                with self._lock:
                    self._active -= 1
                self._slots.release()
                logger.error(
                    "%s 池的执行器已关闭，任务 [job %s#%s] 将以 running 状态残留，"
                    "由租约回收后重跑", self.pool, job.kind, job.id,
                )
                break

    def _claim_one(self) -> Job | None:
        """认领一个本池的 pending 任务。"""
        db = SessionLocal()
        try:
            return jobs_service.claim(
                db,
                self.kinds,
                self.owner.instance_id,
                exclude_kinds=self.exclude_kinds,
            )
        finally:
            db.close()

    def _execute(self, job: Job) -> None:
        """执行一个已认领的任务，并按结果写回两条轴。

        Notes:
            **P3-5**：整段执行包在 :func:`job_log_context` 里 —— 执行期间本线程打的
            每条日志都带 `[job:<id>]`，退出时 `reset()`（contextvars 在
            `ThreadPoolExecutor` 复用的线程上不会自动复位，漏掉 reset 会把上一条
            任务的 job_id 串到下一条）。设置与复位都发生在**本工作线程内**，所以
            不需要在 `submit` 时 `copy_context().run(...)`（submit 也不传播上下文）。
        """
        ctx = JobCtx.from_job(job)
        handler = self.owner.HANDLERS.get(job.kind)
        started = time.monotonic()
        try:
            with job_log_context(ctx.job_id):
                logger.info("%s 开始执行（pool=%s worker=%s）",
                            ctx.label(), self.pool, self.owner.instance_id[:8])
                try:
                    if handler is None:
                        raise MissingHandlerError(f"没有为 kind={job.kind!r} 注册 handler")
                    handler(ctx)
                except JobAborted:
                    # 控制流哨兵：我已不是合法执行者 → 不写 media 轴，静默返回
                    logger.warning("%s 已失去执行权，放弃写回", ctx.label())
                except Exception as exc:  # noqa: BLE001  handler 的任何异常都转成任务状态
                    logger.exception("%s 执行失败", ctx.label())
                    self.owner.handle_failure(job, exc)
                else:
                    logger.info("%s 执行完成（%.2fs）", ctx.label(), time.monotonic() - started)
                    self.owner.handle_success(job)
        finally:
            with self._lock:
                self._active -= 1
            self._slots.release()

    # -------------------------------------------------------------- 生命周期
    def stop(self) -> None:
        """停止认领 → 等在飞任务收尾，然后关闭执行器。

        Notes:
            必须先 `join` 认领线程、**再** `shutdown` 执行器：反过来的话，正在
            `_claim_one()` 里的那一轮会在执行器关闭后才 `submit`，任务被认领了却
            没人跑（要等租约过期才被回收）。join 的等待上限取得很短（一轮轮询），
            因为 `run()` 的每个阻塞点都带超时、收到 stop 后最迟一个 poll 就退出。
        """
        self._stop.set()
        if self.is_alive() and threading.current_thread() is not self:
            self.join(timeout=max(5.0, self._poll * 4))
        self.executor.shutdown(wait=True, cancel_futures=False)


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------


class Worker:
    """一个 worker 进程的执行体（独立进程与 web 进程内降级共用）。

    Attributes:
        HANDLERS: 类属性，指向模块级 :data:`HANDLERS`（可被测试/子进程整体替换）。
        instance_id: `workers.id`（`uuid4().hex`）。
        mode: `external` / `web-inproc`。
    """

    #: 类属性（不是实例属性）：`tests/test_worker_pools.py` 用 `Worker.HANDLERS[k]=f`
    #: 注入替身，子进程用 `Worker.HANDLERS = {...}` 整体替换 —— 两种写法都作用在同一
    #: 个 dict 上，因此实例里统一通过 `self.HANDLERS` 查找。
    HANDLERS: dict[str, Handler] = HANDLERS

    def __init__(
        self,
        cpu_threads: int | None = None,
        io_threads: int | None = None,
        mode: str = "external",
        recover: bool = True,
        pools: Sequence[str] = jobs_service.ALL_POOLS,
    ) -> None:
        """构造（**不启动**）。

        Args:
            cpu_threads: CPU 池容量；`None` 取 `settings.job_cpu_threads`
                （0 → `max(1, os.cpu_count() or 1)`）。
            io_threads: IO 池容量；`None` 取 `settings.job_io_threads`。
            mode: `external`（独立进程）/ `web-inproc`（web 进程内降级）。
            recover: 启动时是否先跑一次恢复扫描。
            pools: 要启用的池（`("cpu","io")`）。
        """
        self.instance_id = jobs_service.new_worker_id()
        self.pid = os.getpid()
        self.mode = mode
        self.cpu_threads = self._resolve_cpu_threads(cpu_threads)
        self.io_threads = max(1, int(io_threads if io_threads is not None else settings.job_io_threads))
        self.recover = recover
        self.enabled_pools = tuple(pool for pool in pools if pool in jobs_service.ALL_POOLS)

        self._heartbeat_sec = max(1.0, float(settings.job_heartbeat_interval_sec))
        self._lease_sec = max(1.0, float(settings.job_lease_interval_sec))
        self._recover_sec = RECOVERY_INTERVAL_SEC

        self._runners: list[_PoolRunner] = []
        self._maintenance: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._started = False
        self._recovered = 0

    # ------------------------------------------------------------------ 助手
    @staticmethod
    def _resolve_cpu_threads(value: int | None) -> int:
        """CPU 池容量：显式值优先，`0`/`None` 表示自动取核数。"""
        raw = settings.job_cpu_threads if value is None else value
        if int(raw) > 0:
            return int(raw)
        return max(1, os.cpu_count() or 1)

    def pools_label(self) -> str:
        """`workers.pools` 列的内容（纯诊断用，不参与容量决策）。"""
        parts = []
        if jobs_service.POOL_CPU in self.enabled_pools:
            parts.append(f"{jobs_service.POOL_CPU}={self.cpu_threads}")
        if jobs_service.POOL_IO in self.enabled_pools:
            parts.append(f"{jobs_service.POOL_IO}={self.io_threads}")
        return ",".join(parts)

    def _active_total(self) -> int:
        """所有池里在飞的 handler 总数。"""
        return sum(runner.active_count() for runner in self._runners)

    # -------------------------------------------------------------- 生命周期
    def start(self) -> None:
        """注册心跳行 → 恢复扫描 → 起维护线程 → 起各池 runner。"""
        if self._started:
            return
        db = SessionLocal()
        try:
            cleared = jobs_service.cleanup_dead_workers(db)
            if cleared:
                logger.info("清理了 %d 条 10 分钟前的死 worker 行", cleared)
            jobs_service.register_worker(
                db,
                self.instance_id,
                self.pid,
                mode=self.mode,
                pools=self.pools_label(),
            )
        finally:
            db.close()

        if self.recover:
            self.recover_once()

        self._maintenance = threading.Thread(
            target=self._maintenance_loop, name="fayelong-maintenance", daemon=True
        )
        self._maintenance.start()

        for pool in self.enabled_pools:
            size = self.cpu_threads if pool == jobs_service.POOL_CPU else self.io_threads
            runner = _PoolRunner(self, pool, size)
            runner.start()
            self._runners.append(runner)

        self._started = True
        logger.info(
            "worker 已启动：id=%s pid=%s mode=%s pools=%s（cpu=%d io=%d）",
            self.instance_id[:8], self.pid, self.mode,
            ",".join(self.enabled_pools), self.cpu_threads, self.io_threads,
        )

    def stop(self) -> None:
        """停止认领 → 等在飞任务收尾 → 注销心跳行（幂等）。"""
        if not self._started:
            return
        self._stop_event.set()
        for runner in self._runners:
            runner.stop()
        self._runners.clear()
        if self._maintenance is not None:
            self._maintenance.join(timeout=5.0)
            self._maintenance = None
        db = SessionLocal()
        try:
            jobs_service.unregister_worker(db, self.instance_id)
        finally:
            db.close()
        self._started = False
        logger.info("worker 已停止：id=%s", self.instance_id[:8])

    def wait_idle(self, timeout: float = 5.0) -> bool:
        """等待「没有在飞任务且没有 pending 任务」。

        Args:
            timeout: 最长等待秒数。

        Returns:
            `True` = 已空闲；`False` = 超时（测试里应视为失败）。
        """
        deadline = time.monotonic() + max(0.0, timeout)
        while time.monotonic() < deadline:
            if all(runner.idle() for runner in self._runners):
                return True
            time.sleep(0.02)
        return False

    # ------------------------------------------------------------ 维护与恢复
    def recover_once(self) -> int:
        """跑一次僵死任务回收，返回回收条数。"""
        db = SessionLocal()
        try:
            count = jobs_service.recover_stale(db)
        except Exception:  # noqa: BLE001  恢复失败不能拖死 worker
            logger.exception("恢复扫描失败")
            return 0
        finally:
            db.close()
        if count:
            self._recovered += count
            logger.warning("恢复扫描回收了 %d 个僵死任务", count)
        return count

    def _maintenance_loop(self) -> None:
        """一条线程承担三件事：worker 心跳 / job 租约续期 / 僵死回收。"""
        started = time.monotonic()
        next_heartbeat = started + self._heartbeat_sec
        next_lease = started + self._lease_sec
        next_recover = started + self._recover_sec

        while not self._stop_event.wait(_MAINTENANCE_TICK_SEC):
            now = time.monotonic()
            if now >= next_heartbeat:
                next_heartbeat = now + self._heartbeat_sec
                self._heartbeat_once()
            if now >= next_lease:
                next_lease = now + self._lease_sec
                self._renew_lease_once()
            if now >= next_recover:
                next_recover = now + self._recover_sec
                self.recover_once()

    def _heartbeat_once(self) -> None:
        """一次 `workers.heartbeat_at` 更新（1 次写，不是每 job 一次）。"""
        db = SessionLocal()
        try:
            if not jobs_service.heartbeat_worker(db, self.instance_id):
                logger.warning("心跳行丢失，重新注册 worker=%s", self.instance_id[:8])
                jobs_service.register_worker(
                    db, self.instance_id, self.pid, mode=self.mode, pools=self.pools_label()
                )
        except Exception:  # noqa: BLE001
            logger.exception("worker 心跳失败")
        finally:
            db.close()

    def _renew_lease_once(self) -> None:
        """一条 UPDATE 续本进程**全部** running job 的租约（成本恒定）。"""
        db = SessionLocal()
        try:
            renewed = jobs_service.renew_lease(db, self.instance_id)
            if renewed:
                logger.debug("续期 %d 个任务的租约", renewed)
        except Exception:  # noqa: BLE001
            logger.exception("续期任务租约失败")
        finally:
            db.close()

    # -------------------------------------------------------------- 结果写回
    @staticmethod
    def _fence(job: Job) -> Any:
        """把 claim 时的 `Job` 收成**不可变快照**，作为写回时唯一的 fence 来源。

        Args:
            job: `claim()` 返回的 `Job`（其 `attempts` / `worker_id` 就是 claim 那一刻
                的值，即 fence 的正确定义）。

        Returns:
            带 `id / kind / ref_id / attempts / worker_id` 的轻量对象。

        Notes:
            ⚠️ **绝不能用 `db.get(Job, id)` 读回来的「当前归属」当 fence**：老执行者
            被 `recover_stale` 回收、新执行者接管后，当前行的 `worker_id/attempts` 已经
            是**新主人**的；拿它当 fence 等于 fencing 归零 —— 迟到的写回会把别人正在跑
            的任务改成 `done`（还顺带入队下一 stage）或打回 `pending`（把别人的结果
            丢掉、错误信息串成自己的）。

            ⚠️ 也**绝不能**「把 `fresh.attempts` 赋值成旧值再传」：`fresh` 在 Session
            的 identity map 里，赋值会让它变 dirty，`commit()` 时把 `attempts` 计数器
            写坏（比原问题更隐蔽）。这里是纯值对象，没有任何 flush 的可能。
        """
        return SimpleNamespace(
            id=int(job.id),
            kind=job.kind,
            ref_id=int(job.ref_id),
            attempts=int(job.attempts),
            worker_id=job.worker_id,
        )

    @staticmethod
    def _exists(db: Any, job_id: int) -> bool:
        """任务行是否还存在（媒体被删会 `purge_for_media` 掉整行）。

        Args:
            db: 调用方的会话（不另开连接：SQLite 上多一条连接就多一次抢锁机会）。
            job_id: 任务 id。

        Notes:
            只查 `id` 列，**不加载 ORM 实体**：避免把「当前归属」带进写回路径，
            也避免在 identity map 里留下一个即将过期的对象。
        """
        return db.query(Job.id).filter(Job.id == job_id).first() is not None

    def handle_success(self, job: Job) -> None:
        """正常完成：`done` + **同事务**入队下一 stage。"""
        next_kind = jobs_service.NEXT_STAGE.get(job.kind)
        fence = self._fence(job)
        db = SessionLocal()
        try:
            if not self._exists(db, job.id):
                logger.info("[job %s#%s] 任务行已不存在（媒体被删），跳过写回",
                            job.kind, job.id)
                return
            if not jobs_service.finish_ok(db, fence, next_kind=next_kind):
                # fencing 失败 = 我已不是合法执行者 → 一行都不改、下一 stage 也不入队
                db.rollback()
                logger.warning(
                    "[job %s#%s] 完成写回被 fencing 拒绝（claim 时 worker=%s attempt=%s），"
                    "放弃写回且不入队下一 stage",
                    job.kind, job.id, fence.worker_id, fence.attempts,
                )
                return
            db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
            logger.exception("[job %s#%s] 完成写回失败", job.kind, job.id)
        finally:
            db.close()

    def handle_failure(self, job: Job, exc: BaseException) -> None:
        """失败：按 `attempts` 决定重试还是终态；终态时 media 与 job 一次提交双写。"""
        message = str(exc) or exc.__class__.__name__
        limit = int(settings.job_max_attempts)
        #: claim 时快照 —— 终态判定与写回 fence 都必须用它，不能用重新读库的当前值。
        fence = self._fence(job)
        #: 终态快照。刻意**不在**下面那个会话里做双写：`_mark_failed` 需要
        #: 「media + jobs 同一 Session 一次 commit」，那是它自己的事务边界。
        terminal: tuple[str, int, int, str | None, int] | None = None

        db = SessionLocal()
        try:
            if not self._exists(db, job.id):
                logger.info("[job %s#%s] 任务行已不存在（媒体被删），跳过失败写回",
                            job.kind, job.id)
            elif fence.attempts >= limit or isinstance(exc, MissingHandlerError):
                # 没有 handler 属于配置错误：重试 3 次也不会有 handler → 直接终态
                terminal = (fence.kind, fence.ref_id, fence.id, fence.worker_id, fence.attempts)
            else:
                outcome = jobs_service.finish_failed(db, fence, message, limit)
                if outcome:
                    db.commit()
                    logger.warning(
                        "[job %s#%s] 失败（attempt %s/%s）→ %s：%s",
                        job.kind, job.id, fence.attempts, limit,
                        outcome, message[:200],
                    )
                else:
                    db.rollback()
                    logger.warning(
                        "[job %s#%s] 失败写回被 fencing 拒绝（claim 时 worker=%s attempt=%s），"
                        "放弃写回（不改行、不动 media）",
                        job.kind, job.id, fence.worker_id, fence.attempts,
                    )
        except Exception:  # noqa: BLE001
            db.rollback()
            logger.exception("[job %s#%s] 失败写回出错", job.kind, job.id)
            terminal = None
        finally:
            db.close()

        if terminal is not None:
            self._write_terminal_failure(*terminal, message=message)

    def _write_terminal_failure(
        self,
        kind: str,
        ref_id: int,
        job_id: int,
        worker_id: str | None,
        attempts: int,
        message: str,
    ) -> None:
        """终态失败：`media` 与 `jobs` 在**同一 Session 一次 commit** 里双写。

        Args:
            kind: 任务 kind。
            ref_id: 多态引用（media 类 = `media.id`）。
            job_id: 任务 id。
            worker_id: **claim 时**快照的执行者 id（fencing token 的一半）。
            attempts: **claim 时**快照的尝试次数（fencing token 的另一半）。
            message: 失败原因。

        Notes:
            **fence 必须来自 claim 时的快照**（`handle_failure` 里的 `self._fence(job)`），
            不能重新读库拿「当前归属」—— 见下方非 media 分支的说明。
        """
        if kind in jobs_service.MEDIA_KINDS:
            media_service.mark_terminal_failure(
                media_id=ref_id,
                message=message,
                job_id=job_id,
                worker_id=worker_id,
                attempts=attempts,
            )
            return

        # 非 media 的任务（如将来的 grade_writing）：只写 jobs 轴。
        #
        # 🔴 P4 必修（P3-2 收尾挂账第 1 条）：这里曾经走
        #     `db.get(Job, job_id)` + `force_failed(db, job)` —— 即拿**当前归属**
        #     当 fence。老执行者被 `recover_stale` 回收、新执行者接管后，迟到的终态
        #     写回会把**别人的**任务判成 failed（还带上自己的错误信息）。P3-2 已经
        #     在 `handle_success` / `finish_failed` 上修过同一类缺陷，本分支当时
        #     不可达（无人入队 grade_writing）所以漏了；P4-4 一启用写作批改就是
        #     P1 级事故。修法：把 claim 时的 `worker_id` / `attempts` 显式传下去，
        #     `force_failed()` 本来就支持「裸 job id + 显式 fence」。
        if not worker_id or attempts is None:
            logger.error(
                "[job %s#%s] 终态失败写回缺少 fence（worker_id=%r attempts=%r），"
                "放弃写回：宁可让任务行停在 running 交给租约回收，也不做无 fence 的盲写",
                kind, job_id, worker_id, attempts,
            )
            return

        db = SessionLocal()
        try:
            fenced_ok = jobs_service.force_failed(
                db,
                job_id,
                message,
                worker_id=worker_id,
                attempts=int(attempts),
            )
            if not fenced_ok:
                db.rollback()
                logger.warning(
                    "[job %s#%s] 终态失败写回被 fencing 拒绝"
                    "（claim 时 worker=%s attempt=%s），放弃写回（本执行者已被回收）",
                    kind, job_id, worker_id, attempts,
                )
                return
            db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
            logger.exception("[job %s#%s] 终态失败写回出错", kind, job_id)
        finally:
            db.close()

    # ------------------------------------------------------------------ 回收
    def __enter__(self) -> "Worker":
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.stop()


# ---------------------------------------------------------------------------
# 孤儿自检（`--parent-pid`）
# ---------------------------------------------------------------------------


def _watch_parent(parent_pid: int, stop_event: threading.Event) -> None:
    """守护线程：launcher 没了就优雅退出（Windows 上 `taskkill /T` 可能漏杀）。

    Args:
        parent_pid: 期望的父进程 pid（launcher 写在 `data/logs/fayelong.pid`）。
        stop_event: 置位即退出。

    Notes:
        * 判据是 `data/logs/fayelong.pid` 的**内容**是否等于 `parent_pid`：
          文件不存在或内容不符 → 父进程已退出（或已被新实例接管）。
        * 第一次检查**延后一个间隔**：launcher 可能刚写完 pid 文件就 fork 我们，
          抢在写入前检查会把健康的 worker 误杀。
        * 严禁 `input()`（`pythonw` 下会 RuntimeError）。
    """
    pid_file = Path(LOG_DIR) / PARENT_PID_FILENAME
    if stop_event.wait(PARENT_CHECK_INTERVAL_SEC):
        return
    while not stop_event.is_set():
        try:
            current = pid_file.read_text(encoding="ascii").strip()
        except OSError:
            current = ""
        if current != str(parent_pid):
            logger.warning(
                "父进程已不在（期望 pid=%s，pid 文件内容=%r），worker 自行退出",
                parent_pid, current,
            )
            stop_event.set()
            return
        if stop_event.wait(PARENT_CHECK_INTERVAL_SEC):
            return


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """构造命令行参数解析器。"""
    parser = argparse.ArgumentParser(
        prog="python -m app.worker",
        description="FayeLong 任务执行进程（jobs 表的唯一执行者）",
    )
    parser.add_argument(
        "--pools",
        default=",".join(jobs_service.ALL_POOLS),
        help="要启用的池，逗号分隔（默认 cpu,io）",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="跑完当前可认领的任务就退出（不等待新任务，供排错/验收用）",
    )
    parser.add_argument(
        "--parent-pid",
        type=int,
        default=0,
        help="父进程 pid：该进程消失时本进程自行退出（打包版防孤儿）",
    )
    parser.add_argument(
        "--no-recovery",
        action="store_true",
        help="启动时不跑僵死任务回收（仅在明确知道有别的 worker 时使用）",
    )
    parser.add_argument(
        "--drain-timeout",
        type=float,
        default=5.0,
        help="--once 模式下等待在飞任务收尾的秒数（默认 5s）",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """进程入口。

    Args:
        argv: 命令行参数（默认取 `sys.argv[1:]`；测试可显式传入）。

    Returns:
        进程退出码（0 = 正常）。
    """
    args = build_parser().parse_args(argv)

    ensure_dirs()
    setup_logging(filename=WORKER_LOG_FILENAME)
    init_db()

    pools = tuple(
        pool.strip() for pool in str(args.pools).split(",") if pool.strip()
    ) or jobs_service.ALL_POOLS

    worker = Worker(
        mode="external",
        recover=not args.no_recovery,
        pools=pools,
    )

    stop_event = threading.Event()
    parent_thread: threading.Thread | None = None
    if args.parent_pid:
        parent_thread = threading.Thread(
            target=_watch_parent,
            args=(int(args.parent_pid), stop_event),
            name="fayelong-parent-watch",
            daemon=True,
        )
        parent_thread.start()

    worker.start()
    try:
        if args.once:
            worker.wait_idle(timeout=float(args.drain_timeout))
            logger.info("--once 完成，退出")
            return 0
        while not stop_event.wait(0.5):
            pass
        logger.info("收到退出信号，开始收尾")
        return 0
    except KeyboardInterrupt:
        logger.info("收到 Ctrl+C，开始收尾")
        return 0
    finally:
        worker.stop()


if __name__ == "__main__":  # pragma: no cover - 由 `python -m app.worker` 触发
    raise SystemExit(main())

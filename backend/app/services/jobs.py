"""任务调度内核：`jobs` / `workers` 表的**唯一**读写入口。

设计契约（`docs/DD-001-P3-2-jobs与分池-系统设计.md`，改代码前先读）
====================================================================
* **jobs 驱动、media 跟随**：`jobs` 是调度真相源，`media.status` 只是给用户看的投影；
  两者在**同一事务**里一起收敛。
* **执行权只有一个来源**：`claim()` 的一条原子 `UPDATE ... WHERE status='pending'`
  + `rowcount == 1` 判定。不要用「先 SELECT 再判断再改」的两段式。
* **`attempts` 兼作 fencing token**：claim 成功后调用方把新 `attempts` 记在内存
  （`JobCtx.my_attempt`），之后**所有**写回都带 `WHERE worker_id=? AND attempts=?`；
  `rowcount == 0` 意味着「我不再是这个 job 的合法执行者」→ 立即停手（`JobAborted`）。
  这一步是「心跳超时误判 + 回收」窗口里**唯一**能挡住双跑的东西，别省。
* **回收也带乐观条件**：`WHERE worker_id=:快照值 AND heartbeat_at <= :快照值`，
  等价于 CAS —— 若原执行者刚续过租，`rowcount == 0`，不会误伤。
* **时间一律走下 SQL**（`CURRENT_TIMESTAMP` / `datetime('now','-N seconds')`），
  **不在 Python 侧算时间差**：Python 本地时区与 SQLite 的 UTC 混用会让回收永不触发。
* **入队唯一入口**是本模块的 `enqueue()` / `finish_ok(next_kind=...)`。
  任何其它模块都**不许**自己写 `INSERT INTO jobs`（否则 `uq_jobs_active` 的幂等语义
  和 payload 约定会各写一份）。
"""

from __future__ import annotations

import json
import logging
import platform
import socket
import uuid
from contextlib import contextmanager
from typing import Any, Iterator, Sequence

from sqlalchemy import func, or_, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import job_log_context
from app.db import SessionLocal
from app.models import Job, Worker

logger = logging.getLogger(__name__)

__all__ = [
    # 状态
    "JOB_PENDING",
    "JOB_RUNNING",
    "JOB_DONE",
    "JOB_FAILED",
    "ACTIVE_STATUSES",
    # kind / 池
    "KIND_TRANSCODE",
    "KIND_ASR",
    "KIND_TRANSLATE",
    "KIND_CLIP",
    "KIND_GRADE_WRITING",
    "ALL_KINDS",
    "MEDIA_KINDS",
    "POOL_CPU",
    "POOL_IO",
    "ALL_POOLS",
    "KIND_POOL",
    "DEFAULT_POOL",
    "NEXT_STAGE",
    "pool_of",
    "kinds_of_pool",
    # 异常
    "JobAborted",
    # 入队 / 认领 / 写回
    "enqueue",
    "claim",
    "touch",
    "check_alive",
    "finish_ok",
    "finish_failed",
    "force_failed",
    "renew_lease",
    "recover_stale",
    "purge_for_media",
    "counts_by_status",
    "has_active_work",
    # workers 表
    "new_worker_id",
    "register_worker",
    "heartbeat_worker",
    "unregister_worker",
    "online_workers",
    "cleanup_dead_workers",
    "worker_snapshot",
    # 上下文
    "JobCtx",
]

# ---------------------------------------------------------------------------
# 常量（跨文件约定，见 DD-001 §5.1 / §8 —— 必须完全一致）
# ---------------------------------------------------------------------------

JOB_PENDING = "pending"
JOB_RUNNING = "running"
JOB_DONE = "done"
JOB_FAILED = "failed"

#: 活跃态（占据 `uq_jobs_active` 的部分唯一索引）
ACTIVE_STATUSES: tuple[str, ...] = (JOB_PENDING, JOB_RUNNING)

KIND_TRANSCODE = "media_transcode"
KIND_ASR = "media_asr"
KIND_TRANSLATE = "media_translate"
KIND_CLIP = "media_clip"
#: P4-4 预留：本阶段**只登记映射，不实现 handler**
KIND_GRADE_WRITING = "grade_writing"

ALL_KINDS: tuple[str, ...] = (
    KIND_TRANSCODE,
    KIND_ASR,
    KIND_TRANSLATE,
    KIND_CLIP,
    KIND_GRADE_WRITING,
)

#: 与 `media` 表相关的 kind（删媒体时按这个前缀清理任务行）
MEDIA_KINDS: tuple[str, ...] = (KIND_TRANSCODE, KIND_ASR, KIND_TRANSLATE, KIND_CLIP)

POOL_CPU = "cpu"
POOL_IO = "io"
ALL_POOLS: tuple[str, ...] = (POOL_CPU, POOL_IO)

#: kind → 池。CPU：ffmpeg / whisper / 切片；IO：在线翻译、未来的写作批改。
KIND_POOL: dict[str, str] = {
    KIND_TRANSCODE: POOL_CPU,
    KIND_ASR: POOL_CPU,
    KIND_CLIP: POOL_CPU,
    KIND_TRANSLATE: POOL_IO,
    KIND_GRADE_WRITING: POOL_IO,
}

#: 未知 kind 保守落 CPU：慢，但不会把 CPU 活扔进 IO 池压垮机器。
DEFAULT_POOL = POOL_CPU

#: 链式推进：本 stage 完成后自动入队下一 stage（`None` = 链尾）。
NEXT_STAGE: dict[str, str | None] = {
    KIND_TRANSCODE: KIND_ASR,
    KIND_ASR: KIND_TRANSLATE,
    KIND_TRANSLATE: KIND_CLIP,
    KIND_CLIP: None,
    KIND_GRADE_WRITING: None,
}

#: `jobs.error` 截断长度（与 `media.error` 一致）
MAX_ERROR_LENGTH = 500

#: `claim()` 在「候选被别人抢走」时的重试次数（个人自用规模下 1~2 次足够）
_CLAIM_RETRIES = 8

#: 死 worker 行的清理阈值（秒）：启动时清「10 分钟前」的死行（DD-001 §3.3）
_DEAD_WORKER_RETENTION_SEC = 600


def pool_of(kind: str) -> str:
    """`kind` 对应的池名；未知 kind 落 :data:`DEFAULT_POOL`。"""
    return KIND_POOL.get(kind, DEFAULT_POOL)


def kinds_of_pool(pool: str) -> list[str]:
    """某个池负责的全部 kind（供 `_PoolRunner` 的 claim 过滤）。

    Notes:
        未知 kind 会落到 CPU 池（:data:`DEFAULT_POOL`），但这里只能枚举**已登记**的
        kind —— 因此 CPU 池的 claim 还要额外接受「不在 `KIND_POOL` 里的 kind」
        （见 `Worker._PoolRunner` 的 `allow_unknown` 开关）。
    """
    return [kind for kind in ALL_KINDS if pool_of(kind) == pool]


class JobAborted(RuntimeError):
    """停止执行：租约已失效 / 任务已被回收 / 任务行已被删除。

    这是一个**控制流哨兵**，不是错误：捕获方应当**不写 media 轴**直接返回。
    """


# ---------------------------------------------------------------------------
# 内部助手
# ---------------------------------------------------------------------------


def _truncate(message: str | None) -> str:
    """把错误信息截断到 :data:`MAX_ERROR_LENGTH`（与 `media.error` 同口径）。"""
    return (message or "处理失败")[:MAX_ERROR_LENGTH]


def _insert_job(
    db: Session,
    kind: str,
    ref_id: int,
    payload: dict[str, Any] | None = None,
    priority: int = 0,
) -> int | None:
    """插入一条 `pending` job（**不 commit**，供事务内复用）。

    Args:
        db: 会话（调用方负责 commit / rollback）。
        kind: `KIND_*` 常量，禁止裸字符串。
        ref_id: 多态引用（本阶段 = `media.id`），**必须非空**。
        payload: 阶段参数（JSON 可序列化），本阶段恒为 `{}`。
        priority: 越大越优先。

    Returns:
        新建行的 id；若已存在同 `(kind, ref_id)` 的**活跃**任务则返回 `None`
        （`uq_jobs_active` 让它天然 no-op）。

    Raises:
        ValueError: `kind` 为空 / `ref_id` 为空 / 被忽略但不是唯一索引冲突
            （例如 NOT NULL / CHECK 违约 —— `INSERT OR IGNORE` 会把这些一起吞掉，
            所以 `rowcount == 0` 时**必须**二次查询确认原因）。
    """
    if not kind:
        raise ValueError("入队失败：kind 不能为空")
    if not isinstance(ref_id, int) or isinstance(ref_id, bool):
        raise ValueError(f"入队失败：ref_id 必须是整数（收到 {ref_id!r}）")

    params = {
        "kind": kind,
        "ref_id": ref_id,
        "priority": int(priority),
        "payload": json.dumps(payload or {}, ensure_ascii=False),
    }
    result = db.execute(
        text(
            "INSERT OR IGNORE INTO jobs"
            " (kind, ref_id, status, progress, priority, payload, attempts)"
            " VALUES (:kind, :ref_id, 'pending', 0, :priority, :payload, 0)"
        ),
        params,
    )
    if result.rowcount == 1:
        return int(result.lastrowid or 0)

    # rowcount == 0：要么是唯一索引冲突（正常 no-op），要么是非法行被吞掉（Bug）。
    existing = db.execute(
        text(
            "SELECT id FROM jobs WHERE kind = :kind AND ref_id = :ref_id"
            " AND status IN ('pending','running') LIMIT 1"
        ),
        {"kind": kind, "ref_id": ref_id},
    ).first()
    if existing is None:
        raise ValueError(
            f"入队失败：kind={kind!r} ref_id={ref_id!r} 被 SQLite 忽略，"
            "且不存在同键的活跃任务（疑似 NOT NULL / CHECK 违约）"
        )
    logger.debug("入队跳过（已有活跃任务）：%s#%s → job %s", kind, ref_id, existing[0])
    return None


def _cas_clause(job: Job) -> tuple[str, dict[str, Any]]:
    """构造 `WHERE` 的「我仍是合法执行者」子句（fencing + 乐观条件）。

    Args:
        job: 内存里那份 job（`worker_id` / `attempts` / `heartbeat_at` 是**claim 时**
            或**读取时**的快照）。

    Returns:
        `(sql 片段, 参数)`。片段以 ` AND ` 开头，可直接拼到 `WHERE ...` 后面。

    Notes:
        `heartbeat_at` 可能是 NULL，而 SQL 里 `x <= NULL` 恒为 NULL（不是 False，
        但同样不成立），因此 NULL 必须走 `IS NULL` 分支。
    """
    params: dict[str, Any] = {"job_id": int(job.id), "attempts": int(job.attempts)}
    parts = ["id = :job_id", "attempts = :attempts"]

    if job.worker_id is None:
        parts.append("worker_id IS NULL")
    else:
        parts.append("worker_id = :worker_id")
        params["worker_id"] = job.worker_id

    if job.heartbeat_at is None:
        parts.append("heartbeat_at IS NULL")
    else:
        parts.append("heartbeat_at <= :heartbeat_at")
        # 归一成 SQLite `CURRENT_TIMESTAMP` 的格式（'YYYY-MM-DD HH:MM:SS'）：
        # ① 直接绑 datetime 会走 Python 3.12 已弃用的默认 adapter（DeprecationWarning）；
        # ② 默认 adapter 会带上微秒（'...12:00:00.123456'），与库里的
        #    '...12:00:00' 做字符串比较时会把「同一秒」判成更大 → CAS 误放行。
        params["heartbeat_at"] = job.heartbeat_at.strftime("%Y-%m-%d %H:%M:%S")

    return " AND " + " AND ".join(parts), params


def _seconds_ago(seconds: int) -> Any:
    """生成 SQLite 的「now - N 秒」表达式（时间比较一律下 SQL）。"""
    return func.datetime("now", f"-{int(seconds)} seconds")


# ---------------------------------------------------------------------------
# 入队
# ---------------------------------------------------------------------------


def enqueue(
    kind: str,
    ref_id: int,
    payload: dict[str, Any] | None = None,
    priority: int = 0,
) -> int | None:
    """把任务加入队列（**唯一**入队入口，重复入队天然 no-op）。

    Args:
        kind: `KIND_*` 常量。
        ref_id: 多态引用（本阶段 = `media.id`）。
        payload: 阶段参数，本阶段恒为 `None`（落库为 `{}`）。
        priority: 越大越优先。

    Returns:
        job id；若已存在同 `(kind, ref_id)` 的活跃任务则 `None`。

    Raises:
        ValueError: 参数非法（见 :func:`_insert_job`）。
    """
    db = SessionLocal()
    try:
        job_id = _insert_job(db, kind, ref_id, payload, priority)
        db.commit()
        if job_id is not None:
            # P3-5：入队日志带 job_id，worker 侧执行日志也带同一个（`[job:<id>]`），
            # 于是「谁入队的 / 谁执行的 / 重试了几次」能在两进程的日志里串起来。
            with job_log_context(job_id):
                logger.info("入队 %s ref=%s", kind, ref_id)
        else:
            # 去重是**正常路径**（`uq_jobs_active` 幂等），但必须留痕：
            # 否则「点了重试却没反应」时无从判断是去重还是根本没进队列。
            logger.info("入队被去重（同类活跃任务已存在）：%s ref=%s", kind, ref_id)
        return job_id
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 认领 / 续租 / 存活自检
# ---------------------------------------------------------------------------


def claim(
    db: Session,
    kinds: Sequence[str] | None,
    worker_id: str,
    exclude_kinds: Sequence[str] = (),
) -> Job | None:
    """认领一个 `pending` job（**执行权的唯一来源**）。

    Args:
        db: 会话。
        kinds: 本池负责的 kind 列表；`None` 或空 = 不按 kind 白名单过滤
            （此时必须给 `exclude_kinds`，否则拒绝执行 —— 见 Notes）。
        worker_id: 执行者 id（`workers.id`）。
        exclude_kinds: 明确排除的 kind。CPU 池用「排除 IO 池的 kind」表达
            「CPU + 所有未登记 kind」，这样未知 kind 会保守落到 CPU 池
            （`DEFAULT_POOL = POOL_CPU`），无需枚举未知 kind。

    Returns:
        认领成功的 `Job`（`attempts` 已是**新值**，调用方须记下来当 fencing token）；
        无可认领任务或全部被抢走时返回 `None`。

    Notes:
        两步（SELECT 候选 → 原子 UPDATE）而不是一条 `UPDATE ... WHERE id=(SELECT ...)`：
        需要知道抢到的是哪一行，且 `rowcount == 1` 是唯一的抢到判据。
        Python 的 sqlite3 在**只读语句上不开启事务**，所以 SELECT 不会持读锁，
        也就不会出现「两个进程同时持有读锁再升级写锁」的 SQLITE_BUSY 死锁。
    """
    include = [kind for kind in dict.fromkeys(kinds or ()) if kind]
    exclude = [kind for kind in dict.fromkeys(exclude_kinds or ()) if kind]
    if not include and not exclude:
        # 既没有白名单也没有黑名单 = 「任何 kind 都可以」，这类调用一律拒绝：
        # 它会让 IO 池抢走 CPU 活（或反之），是难以排查的性能事故源头。
        return None

    clauses = ["status = 'pending'"]
    params: dict[str, Any] = {}
    if include:
        placeholders = ", ".join(f":k{index}" for index in range(len(include)))
        clauses.append(f"kind IN ({placeholders})")
        params.update({f"k{index}": kind for index, kind in enumerate(include)})
    if exclude:
        placeholders = ", ".join(f":x{index}" for index in range(len(exclude)))
        clauses.append(f"kind NOT IN ({placeholders})")
        params.update({f"x{index}": kind for index, kind in enumerate(exclude)})

    select_sql = text(
        "SELECT id FROM jobs WHERE " + " AND ".join(clauses)
        + " ORDER BY priority DESC, id ASC LIMIT 1"
    )
    update_sql = text(
        "UPDATE jobs SET status = 'running', worker_id = :worker_id,"
        " attempts = attempts + 1,"
        " started_at = COALESCE(started_at, CURRENT_TIMESTAMP),"
        " heartbeat_at = CURRENT_TIMESTAMP, error = NULL"
        " WHERE id = :job_id AND status = 'pending'"
    )

    for _attempt in range(_CLAIM_RETRIES):
        row = db.execute(select_sql, params).first()
        if row is None:
            return None
        job_id = int(row[0])
        result = db.execute(update_sql, {"worker_id": worker_id, "job_id": job_id})
        db.commit()  # 必须立刻提交：持锁时间越短，跨进程争抢越少
        if result.rowcount != 1:
            continue  # 被别人抢走了，重新挑候选
        job = db.get(Job, job_id)
        if job is None:
            return None  # 媒体被删 → 任务行已被 purge
        logger.info(
            "[job %s/%s#%s] %s 认领（attempt %d）",
            job.kind, job.ref_id, job.id, worker_id, job.attempts,
        )
        return job
    return None


def touch(db: Session, job: Job | int, my_attempt: int, worker_id: str | None = None) -> bool:
    """续租 + 存活自检（一条 UPDATE，**不 commit**）。

    Args:
        db: 会话。
        job: `Job` 实例（取其 `id` / `worker_id`）或裸 job id。
        my_attempt: claim 时记下的 `attempts`（fencing token）。
        worker_id: `job` 是裸 id 时必须显式给。

    Returns:
        `True` = 我仍是合法执行者且租约已续；`False` = 已被回收/删行/换人。

    Notes:
        刻意**不 commit**：进度回调里它要与 `media.progress` 的写**同一次提交**
        （DD-001 §6 T03 ②「进度写与续租同一次 commit，零额外写」）。
    """
    job_id = int(job.id) if isinstance(job, Job) else int(job)
    owner = worker_id if worker_id is not None else getattr(job, "worker_id", None)
    if not owner:
        raise ValueError("touch() 需要 worker_id（裸 job id 调用时必须显式传）")
    result = db.execute(
        text(
            "UPDATE jobs SET heartbeat_at = CURRENT_TIMESTAMP"
            " WHERE id = :job_id AND worker_id = :worker_id"
            " AND attempts = :attempts AND status = 'running'"
        ),
        {"job_id": job_id, "worker_id": owner, "attempts": int(my_attempt)},
    )
    return result.rowcount == 1


def check_alive(db: Session, job_id: int, worker_id: str, my_attempt: int) -> bool:
    """只读存活自检（阶段边界用，廉价）。

    Args:
        db: 会话。
        job_id: 任务 id。
        worker_id: 我的 worker id。
        my_attempt: claim 时记下的 `attempts`。

    Returns:
        `True` = 仍是 `running` 且归属我这一代；否则 `False`。
    """
    row = db.execute(
        text("SELECT status, worker_id, attempts FROM jobs WHERE id = :job_id"),
        {"job_id": int(job_id)},
    ).first()
    if row is None:
        return False
    return (
        row[0] == JOB_RUNNING
        and row[1] == worker_id
        and int(row[2]) == int(my_attempt)
    )


def renew_lease(db: Session, worker_id: str) -> int:
    """续本进程**全部** running job 的租约（一条 UPDATE，成本恒定）。

    Args:
        db: 会话。
        worker_id: 我的 worker id。

    Returns:
        被续租的行数。

    Notes:
        由 worker 的 ticker 线程每 `job_lease_interval_sec` 调一次。
        这里会 commit —— 它是独立的小事务，不与任何业务写混在一起。
    """
    result = db.execute(
        text(
            "UPDATE jobs SET heartbeat_at = CURRENT_TIMESTAMP"
            " WHERE worker_id = :worker_id AND status = 'running'"
        ),
        {"worker_id": worker_id},
    )
    db.commit()
    return int(result.rowcount or 0)


# ---------------------------------------------------------------------------
# 写回：完成 / 失败
# ---------------------------------------------------------------------------


def finish_ok(
    db: Session,
    job: Job,
    next_kind: str | None = None,
    ref_id: int | None = None,
    payload: dict[str, Any] | None = None,
    priority: int = 0,
) -> bool:
    """把 job 置为 `done`，并在**同一事务**里入队下一 stage（**不 commit**）。

    Args:
        db: 会话（调用方 commit）。
        job: 内存里那份 job（带 `worker_id` / `attempts`）。
        next_kind: 下一 stage 的 kind；`None` = 链尾（`NEXT_STAGE[kind] is None`）。
        ref_id: 下一 stage 的引用 id（默认沿用本 job 的）。
        payload: 下一 stage 的参数。
        priority: 下一 stage 的优先级。

    Returns:
        `True` = 写回成功；`False` = fencing 失败（我已不是合法执行者）。

    Notes:
        **绝不能**「先 commit done、再单独入队下一 stage」：两次提交之间崩溃
        = 任务凭空消失（DD-001 §4.2 第 3 行）。因此这里两件事共用一次 commit。
    """
    result = db.execute(
        text(
            "UPDATE jobs SET status = 'done', progress = 100, finished_at = CURRENT_TIMESTAMP"
            " WHERE id = :job_id AND attempts = :attempts AND worker_id = :worker_id"
            " AND status = 'running'"
        ),
        {
            "job_id": int(job.id),
            "attempts": int(job.attempts),
            "worker_id": job.worker_id,
        },
    )
    if result.rowcount != 1:
        logger.warning(
            "[job %s/%s#%s] 完成写回被 fencing 拒绝（worker=%s attempt=%s）",
            job.kind, job.ref_id, job.id, job.worker_id, job.attempts,
        )
        return False

    if next_kind is not None:
        target_ref = int(ref_id if ref_id is not None else job.ref_id)
        _insert_job(db, next_kind, target_ref, payload, priority)
    return True


def finish_failed(
    db: Session,
    job: Job,
    message: str,
    max_attempts: int | None = None,
) -> str:
    """按 `attempts` 决定「重试」还是「终态失败」（**不 commit**）。

    Args:
        db: 会话（调用方 commit —— 终态时还要与 `media` 一起提交）。
        job: 内存里那份 job。
        message: 失败原因（自动截断到 500 字）。
        max_attempts: 尝试上限（默认取 `settings.job_max_attempts`）。

    Returns:
        * :data:`JOB_PENDING` —— 已回到 pending，等待重试；
        * :data:`JOB_FAILED` —— 已达上限，终态失败；
        * `""` —— 写回被 fencing 拒绝（我已不是合法执行者，什么都没改）。
    """
    limit = int(max_attempts if max_attempts is not None else settings.job_max_attempts)
    error = _truncate(message)
    attempts = int(job.attempts)

    if attempts >= limit:
        result = db.execute(
            text(
                "UPDATE jobs SET status = 'failed', progress = 0, error = :error,"
                " finished_at = CURRENT_TIMESTAMP"
                " WHERE id = :job_id AND attempts = :attempts AND worker_id = :worker_id"
                " AND status = 'running'"
            ),
            {
                "job_id": int(job.id),
                "attempts": attempts,
                "worker_id": job.worker_id,
                "error": error,
            },
        )
        outcome = JOB_FAILED
    else:
        result = db.execute(
            text(
                "UPDATE jobs SET status = 'pending', progress = 0, error = :error,"
                " worker_id = NULL, heartbeat_at = NULL"
                " WHERE id = :job_id AND attempts = :attempts AND worker_id = :worker_id"
                " AND status = 'running'"
            ),
            {
                "job_id": int(job.id),
                "attempts": attempts,
                "worker_id": job.worker_id,
                "error": error,
            },
        )
        outcome = JOB_PENDING

    if result.rowcount != 1:
        return ""
    return outcome


def force_failed(
    db: Session,
    job: Job | int,
    message: str,
    worker_id: str | None = None,
    attempts: int | None = None,
) -> bool:
    """无条件把 job 置 `failed`（**不 commit**，已带 fencing）。

    用途：终态失败时 `media` 与 `jobs` 要在**同一 Session 一次 commit** 里双写
    （DD-001 §4.2 第 5 行「两轴一起失败，不允许只失败一边」）。调用方
    （`media.mark_terminal_failure`）已经判定了「这是终态」，因此这里不再判 `attempts`。

    Args:
        db: 会话（调用方 commit）。
        job: `Job` 实例，或裸 job id。
        message: 失败原因（截断 500 字）。
        worker_id: `job` 是裸 id 时必须显式给（fencing）。
        attempts: 同上。

    Returns:
        `True` = 写回成功；`False` = fencing 失败（我已不是合法执行者）。
    """
    if isinstance(job, Job):
        job_id, owner, fence = int(job.id), job.worker_id, int(job.attempts)
    else:
        job_id, owner, fence = int(job), worker_id, attempts
    if not owner or fence is None:
        raise ValueError("force_failed() 需要 worker_id 与 attempts（裸 job id 调用时必须显式传）")

    result = db.execute(
        text(
            "UPDATE jobs SET status = 'failed', progress = 0, error = :error,"
            " finished_at = CURRENT_TIMESTAMP"
            " WHERE id = :job_id AND attempts = :attempts AND worker_id = :worker_id"
            " AND status = 'running'"
        ),
        {
            "job_id": job_id,
            "attempts": int(fence),
            "worker_id": owner,
            "error": _truncate(message),
        },
    )
    return result.rowcount == 1


# ---------------------------------------------------------------------------
# 崩溃恢复
# ---------------------------------------------------------------------------


def recover_stale(db: Session, now: Any = None) -> int:
    """回收僵死任务（worker 消失 **或** 租约过期），返回回收条数。

    回收口径（DD-001 §4.3 第 6 条，两条是 **OR** 关系）：
      ① `heartbeat_at` 早于 `now - job_lease_ttl_sec`；
      ② `worker_id` 不在「在线 worker 集合」里（`workers.heartbeat_at > now - worker_ttl`）
         —— 有了 ②，`kill -9` 后重启的 worker **30s 内**就能接管，不必等满 120s。

    Args:
        db: 会话。
        now: 保留参数（时间比较一律下 SQL，不用 Python 时间；仅为可读性留位）。

    Returns:
        被回收（改回 pending 或直接 failed）的行数。

    Notes:
        * 每条回收都带 CAS（`worker_id` + `heartbeat_at <= 快照值`），防止
          「刚续完租约，回收线程基于旧快照把我重置」。
        * 若该 job 的 `attempts` 已到上限 → 直接 `failed`（防崩溃循环）。
        * 若回收成 pending 会撞 `uq_jobs_active`（同键已有另一个活跃任务，
          理论上不该出现），则改判 `failed` 并写明原因 —— 宁可留下可读的失败记录，
          也不要让一条 IntegrityError 把整个恢复扫描打断。
    """
    lease_ttl = int(settings.job_lease_ttl_sec)
    worker_ttl = int(settings.job_worker_ttl_sec)
    max_attempts = int(settings.job_max_attempts)

    online_ids = [
        row[0]
        for row in db.query(Worker.id)
        .filter(Worker.heartbeat_at > _seconds_ago(worker_ttl))
        .all()
    ]

    stale_filter = or_(
        Job.heartbeat_at.is_(None),
        Job.heartbeat_at <= _seconds_ago(lease_ttl),
    )
    dead_owner_filter = or_(Job.worker_id.is_(None), Job.worker_id.notin_(online_ids))
    candidates = (
        db.query(Job)
        .filter(Job.status == JOB_RUNNING)
        .filter(or_(stale_filter, dead_owner_filter))
        .all()
    )
    if not candidates:
        return 0

    recovered = 0
    for job in candidates:
        # CAS 用**这里读到的** worker_id / attempts / heartbeat_at 作为乐观条件。
        # ⚠️ 这就是同一个 ORM 对象，没有做深拷贝 —— 之所以等价于「快照」，是因为
        #    SQLAlchemy 的 identity map 不会因为下面那些裸 SQL UPDATE 而自动刷新它
        #    （`expire_on_commit` 只在 commit 时生效，这里对 candidates 读完没有再
        #    commit 过）。若将来把这段改成「UPDATE 后 commit 再复用该对象」，语义就
        #    变了：那时必须显式先取出三元组再 commit。
        snapshot = job
        where_sql, params = _cas_clause(snapshot)
        duplicate_active = (
            db.query(Job.id)
            .filter(
                Job.kind == job.kind,
                Job.ref_id == job.ref_id,
                Job.status.in_(ACTIVE_STATUSES),
                Job.id != job.id,
            )
            .first()
            is not None
        )

        if int(job.attempts) >= max_attempts:
            # 崩溃循环防护：次数已用尽，直接终态失败
            result = db.execute(
                text(
                    "UPDATE jobs SET status = 'failed', progress = 0,"
                    " error = COALESCE(error, '任务执行者失联且重试次数已用尽'),"
                    " finished_at = CURRENT_TIMESTAMP"
                    f" WHERE status = 'running'{where_sql}"
                ),
                params,
            )
            if result.rowcount == 1:
                recovered += 1
                logger.error(
                    "[job %s/%s#%s] 执行者失联且 attempts=%d 已用尽 → failed",
                    job.kind, job.ref_id, job.id, job.attempts,
                )
            continue

        # ── 防御分支（**结构性不可达**，保留但不属于任何「双入队」兜底）─────────
        # `uq_jobs_active` 是部分唯一索引，同一 (kind, ref_id) 在数据库层面**不可能**
        # 同时存在两条活跃行；因此「回收成 pending 会撞唯一索引」这个场景根本构造不
        # 出来（实测：摘掉索引灌入脏数据后，`CREATE UNIQUE INDEX` 会当场用
        # IntegrityError 拒绝存量数据）。
        # 保留它的理由有两条：
        #   ① 万一将来有人把 `uq_jobs_active` 从迁移里弄丢（例如漏了 sqlite_where，
        #      见 tests/test_migrations.py 的两道网），这里能防止 `recover_stale()`
        #      被一条 IntegrityError 整个打断；
        #   ② 把「无法回 pending」的僵死行改判 failed，比让它永远停在 running 可排查。
        # ⚠️ 它**不是**「防止双入队」的兜底 —— 真正的护栏只有两条：
        #    ① 部分唯一索引 `uq_jobs_active`（DB 层拒绝第二条活跃行）；
        #    ② `claim()` 的原子 `UPDATE ... WHERE status='pending'` + `rowcount==1`
        #       （执行权只能被一个进程拿到）。本分支与它们无关。
        if duplicate_active:  # pragma: no cover - 结构性不可达（见上方说明）
            result = db.execute(
                text(
                    "UPDATE jobs SET status = 'failed', progress = 0,"
                    " error = '同一素材已有新的活跃任务，本任务被回收',"
                    " finished_at = CURRENT_TIMESTAMP"
                    f" WHERE status = 'running'{where_sql}"
                ),
                params,
            )
            if result.rowcount == 1:
                recovered += 1
                logger.warning(
                    "[job %s/%s#%s] 回收时发现同键活跃任务，改判 failed",
                    job.kind, job.ref_id, job.id,
                )
            continue

        result = db.execute(
            text(
                "UPDATE jobs SET status = 'pending', progress = 0, error = NULL,"
                " worker_id = NULL, heartbeat_at = NULL"
                f" WHERE status = 'running'{where_sql}"
            ),
            params,
        )
        if result.rowcount == 1:
            recovered += 1
            logger.warning(
                "[job %s/%s#%s] 僵死任务已回收（worker=%s attempt=%d）",
                job.kind, job.ref_id, job.id, job.worker_id, job.attempts,
            )

    db.commit()
    return recovered


def purge_for_media(db: Session, media_id: int) -> int:
    """删除某个媒体的全部任务行（**不 commit**，与 `db.delete(media)` 同一事务）。

    Args:
        db: 会话。
        media_id: 媒体 id。

    Returns:
        删除的行数。

    Notes:
        `ref_id` 是**多态引用、刻意不加外键**（DD-001 §3.2）→ 媒体删除后的任务清理
        必须在应用层做。执行中的 job 行被删后，其线程下一次写回 `rowcount == 0`
        → 自动自杀（因此不需要 `cancelled` 状态）。
    """
    result = db.execute(
        text("DELETE FROM jobs WHERE kind LIKE 'media_%' AND ref_id = :ref_id"),
        {"ref_id": int(media_id)},
    )
    return int(result.rowcount or 0)


def counts_by_status(db: Session) -> dict[str, int]:
    """按状态统计 job 数量（给 `/api/health` 用），4 个键恒存在。"""
    counts = {JOB_PENDING: 0, JOB_RUNNING: 0, JOB_DONE: 0, JOB_FAILED: 0}
    rows = db.execute(text("SELECT status, COUNT(*) FROM jobs GROUP BY status")).all()
    for status, total in rows:
        counts[str(status)] = int(total)
    return counts


def has_active_work(
    db: Session,
    kinds: Sequence[str] | None = None,
    exclude_kinds: Sequence[str] = (),
) -> bool:
    """队列里是否还有**本调用方认领得了**的 `pending` 任务（`wait_idle` 用）。

    Args:
        db: 会话。
        kinds: kind 白名单；`None` / 空 = 不按白名单过滤（与 :func:`claim` 同义）。
        exclude_kinds: 明确排除的 kind。CPU 池用「排除 IO 池的 kind」表达
            「CPU + 所有未登记 kind」，与它的 `claim()` 口径**必须完全一致** ——
            否则 `idle()` 与 `claim()` 会对「谁该处理这个 job」给出两个答案。

    Returns:
        `True` = 至少还有一条本方可认领的 `pending` 任务。

    Notes:
        **P4 挂账 A3 的修法**：原实现只看全局 `pending`，于是 `--once` 在
        「队列里只有本池接不了的 job」时会空转到 `drain_timeout`（最多 5s，
        无正确性问题但白等）。去掉白等不需要新语义，只需要把 `claim()` 的
        过滤条件在「查询」上也表达一遍。

        两个参数都为空 = 全局判断（保持旧行为，向后兼容）。
        只给 `exclude_kinds` = 「除这些之外都算」（CPU 池用法）。
    """
    include = [kind for kind in dict.fromkeys(kinds or ()) if kind]
    exclude = [kind for kind in dict.fromkeys(exclude_kinds or ()) if kind]

    clauses = ["status = 'pending'"]
    params: dict[str, Any] = {}
    if include:
        placeholders = ", ".join(f":k{index}" for index in range(len(include)))
        clauses.append(f"kind IN ({placeholders})")
        params.update({f"k{index}": kind for index, kind in enumerate(include)})
    if exclude:
        placeholders = ", ".join(f":x{index}" for index in range(len(exclude)))
        clauses.append(f"kind NOT IN ({placeholders})")
        params.update({f"x{index}": kind for index, kind in enumerate(exclude)})

    row = db.execute(
        text("SELECT 1 FROM jobs WHERE " + " AND ".join(clauses) + " LIMIT 1"),
        params,
    ).first()
    return row is not None


# ---------------------------------------------------------------------------
# workers 表（进程心跳）
# ---------------------------------------------------------------------------


def new_worker_id() -> str:
    """生成 worker id：`uuid4().hex`。

    Notes:
        **不要用 `hostname:pid`**：pid 会复用，重启后旧行可能「看起来还活着」。
    """
    return uuid.uuid4().hex


def register_worker(
    db: Session,
    worker_id: str,
    pid: int,
    mode: str = "external",
    pools: str = "",
) -> None:
    """注册（或幂等更新）一个 worker 行。"""
    db.execute(
        text(
            "INSERT INTO workers (id, pid, host, mode, pools, started_at, heartbeat_at)"
            " VALUES (:id, :pid, :host, :mode, :pools, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            " ON CONFLICT(id) DO UPDATE SET pid = :pid, host = :host,"
            " mode = :mode, pools = :pools, heartbeat_at = CURRENT_TIMESTAMP"
        ),
        {
            "id": worker_id,
            "pid": int(pid),
            "host": hostname(),
            "mode": mode,
            "pools": pools[:64],
        },
    )
    db.commit()


def heartbeat_worker(db: Session, worker_id: str) -> bool:
    """更新本进程心跳（1 次写，不是每 job 一次）。返回是否命中行。"""
    result = db.execute(
        text("UPDATE workers SET heartbeat_at = CURRENT_TIMESTAMP WHERE id = :id"),
        {"id": worker_id},
    )
    db.commit()
    return result.rowcount == 1


def unregister_worker(db: Session, worker_id: str) -> None:
    """正常退出时删掉自己那一行。"""
    db.execute(text("DELETE FROM workers WHERE id = :id"), {"id": worker_id})
    db.commit()


def online_workers(db: Session) -> list[Worker]:
    """在线 worker 列表（`heartbeat_at > now - worker_ttl`）。"""
    return (
        db.query(Worker)
        .filter(Worker.heartbeat_at > _seconds_ago(int(settings.job_worker_ttl_sec)))
        .order_by(Worker.heartbeat_at.desc())
        .all()
    )


def cleanup_dead_workers(db: Session, retention_sec: int = _DEAD_WORKER_RETENTION_SEC) -> int:
    """清理 `retention_sec` 之前就没了心跳的死行（启动时跑一次）。

    Notes:
        `datetime('now', :offset)` 必须写在 **SQL 里**（而不是 Python 算好时间再
        当参数传）：`settings` 里全是「相对秒数」，SQLite 的 `now` 是 UTC，Python
        算出来的本地时间与它混用会让这条清理（以及回收扫描）永远不生效。
    """
    result = db.execute(
        text("DELETE FROM workers WHERE heartbeat_at < datetime('now', :offset)"),
        {"offset": f"-{int(retention_sec)} seconds"},
    )
    db.commit()
    return int(result.rowcount or 0)


def worker_snapshot(db: Session) -> dict[str, Any]:
    """`/api/health` 的 `worker` 块（**只含 JSON 可序列化值**）。"""
    online = online_workers(db)
    latest = db.query(func.max(Worker.heartbeat_at)).scalar()
    return {
        "online": bool(online),
        "count": len(online),
        "mode": (online[0].mode if online else "none"),
        "last_heartbeat_at": latest.isoformat() if latest is not None else None,
    }


def hostname() -> str:
    """当前主机名（`workers.host` 用，截断到列宽）。"""
    try:
        return socket.gethostname()[:64]
    except OSError:  # pragma: no cover - 极端环境下 gethostname 可能失败
        return platform.node()[:64]


# ---------------------------------------------------------------------------
# JobCtx：交给业务 handler 的执行上下文
# ---------------------------------------------------------------------------


class JobCtx:
    """一个已认领 job 的执行上下文（handler 的唯一入参）。

    为什么需要它：业务 stage 既要知道「我是谁（fencing token）」，又要能
    `touch` / `check_alive` / 写回，但不该直接摸 `jobs` 表的 SQL。

    Attributes:
        job_id: 任务 id。
        kind: `KIND_*`。
        ref_id: 多态引用（本阶段 `media.id`）。
        worker_id: 我的 worker id。
        my_attempt: claim 时记下的 `attempts`（fencing token），**执行期间不变**。
        payload: 已解析的 dict（`json.loads(job.payload or "{}")`，永不假设非空）。
    """

    def __init__(
        self,
        job_id: int,
        kind: str,
        ref_id: int,
        worker_id: str,
        my_attempt: int,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self.job_id = int(job_id)
        self.kind = kind
        self.ref_id = int(ref_id)
        self.worker_id = worker_id
        self.my_attempt = int(my_attempt)
        self.payload: dict[str, Any] = payload or {}

    @classmethod
    def from_job(cls, job: Job) -> "JobCtx":
        """由已认领的 `Job` 构造上下文（`my_attempt` 取 claim 后的新 `attempts`）。"""
        try:
            payload = json.loads(job.payload or "{}")
        except json.JSONDecodeError:
            logger.warning("[job %s/%s#%s] payload 不是合法 JSON，按空处理",
                           job.kind, job.ref_id, job.id)
            payload = {}
        return cls(
            job_id=job.id,
            kind=job.kind,
            ref_id=job.ref_id,
            worker_id=job.worker_id or "",
            my_attempt=job.attempts,
            payload=payload if isinstance(payload, dict) else {},
        )

    def __repr__(self) -> str:  # pragma: no cover - 仅排错可读性
        return (
            f"JobCtx(kind={self.kind!r}, ref_id={self.ref_id}, job_id={self.job_id},"
            f" attempt={self.my_attempt}, worker={self.worker_id[:8]})"
        )

    def label(self) -> str:
        """日志前缀：`[job <kind>/<ref_id>#<id>]`（DD-001 §8 约定格式）。"""
        return f"[job {self.kind}/{self.ref_id}#{self.job_id}]"

    @contextmanager
    def session(self) -> Iterator[Session]:
        """开一个业务会话：异常自动 rollback，结束必定 close。

        Notes:
            这里**不替你 commit** —— stage 自己掌握提交点（进度写要节流），
            而 `with` 退出时若仍有未提交内容，由 `close()` 丢弃（= 回滚）。
            `JobAborted` 因此天然实现「不写 media 轴」：抛出去的那一刻，
            当前未提交的进度写全部作废。
        """
        db = SessionLocal()
        try:
            yield db
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def touch(self) -> bool:
        """续租一次（独立小事务）。返回是否仍持有执行权。"""
        with self.session() as db:
            alive = touch(db, self.job_id, self.my_attempt, self.worker_id)
            db.commit()
        if not alive:
            logger.warning("%s 租约续期失败，疑似已被回收", self.label())
        return alive

    def check_alive(self) -> None:
        """存活自检；已失去执行权时抛 :class:`JobAborted`。"""
        with self.session() as db:
            alive = check_alive(db, self.job_id, self.worker_id, self.my_attempt)
        if not alive:
            raise JobAborted(f"{self.label()} 已失去执行权（租约失效或已被回收）")

    def ensure_alive(self, db: Session) -> None:
        """用调用方**已有**的会话做存活自检（省一次连接，供逐句循环里用）。"""
        if not check_alive(db, self.job_id, self.worker_id, self.my_attempt):
            raise JobAborted(f"{self.label()} 已失去执行权（租约失效或已被回收）")

    def finish_ok(self, next_kind: str | None = None, payload: dict[str, Any] | None = None) -> bool:
        """把本 job 置 `done` 并在同一事务入队下一 stage。"""
        with self.session() as db:
            job = db.get(Job, self.job_id)
            if job is None:
                return False
            ok = finish_ok(db, job, next_kind=next_kind, payload=payload)
            db.commit()
        return ok

    def finish_failed(self, message: str, max_attempts: int | None = None) -> str:
        """按尝试次数决定重试/终态失败。"""
        with self.session() as db:
            job = db.get(Job, self.job_id)
            if job is None:
                return ""
            outcome = finish_failed(db, job, message, max_attempts)
            db.commit()
        return outcome

# DD-001 P3-2 / P3-3 系统设计：`jobs` 表 + 独立 worker + CPU/IO 分池

- **状态**：待评审（设计稿，尚未施工）
- **上游需求**：`docs/REFACTOR-PLAN-001-执行计划.md` §6（P3-2 / P3-3）、§2 G3 闸门 ②③
- **上游动机**：`docs/ADR-001-技术栈选型与重构决策.md` §5.4 D2/D3/D6
- **前置成果**：P3-1（Alembic 基线 `0001`，**禁止修改**；启动路径不跑 alembic）
- **本文性质**：施工文件。工程师照 §6 的任务顺序做即可，不需要再自行做架构判断。

---

## 1. 结论摘要

1. **`jobs` 表是调度真相源，`media.status` 降级为用户可见投影**：jobs 驱动、media 跟随，两者在同一事务里一起收敛。
2. **不把整条 `transcode→asr→translate→clip` 链塞进一个池槽**，而是拆成 **4 个 stage job**（各自声明 pool），用「done 时同事务插入下一 stage」串起来 —— 这是 G3-③「ASR 不阻塞翻译」唯一的可验证解（详 §5.2）。
3. **心跳绑 worker 进程 + 绑 job**双层，回收用「**租约 + `attempts` 作 fencing token**」，从机制上杜绝双跑，而不是靠约定（详 §4.3）。
4. **web 进程默认不执行长任务，但保留 `web_inproc_worker=auto` 安全网**：worker 不在线时 web 5s 内接管，上线后自动让位；两个执行者并存也不会双跑（DB 原子 claim）。一个环境变量可整体退回旧行为。
5. **新增 `workers` 表**（进程心跳）—— 它同时解决决策 1（worker 是否在线）、决策 3（崩溃检测不必逐 job 高频写）、决策 7（health 可判断）三件事。

### 7 个决策的结论表

| # | 决策 | 结论 | 选 A 不选 B 的代价 |
|---|---|---|---|
| 1 | web 是否彻底不执行 | **三态 `FAYELONG_WEB_INPROC_WORKER`**：云端/打包 `off`，**开发与打包交付包用 `auto`（安全网）**；判定依据 = `workers` 表心跳（10s/次，TTL 30s）；防双份 = DB 原子 claim + fencing（不是 flag 约定） | 选「web 彻底不执行(B)」：worker 没起时上传永远 pending 且无报错，用户看到卡死；而**本阶段不许改前端、不许改契约（不能加 503）**，无法补偿。代价：`auto` 模式下 web 会持 1+2 个空闲线程与 ~10MB 开销 |
| 2 | jobs 最终 schema | 计划给的 12 字段 **+ `worker_id` + `heartbeat_at`**；**不加** `updated_at`（会撒谎的字段比没有更糟）、**不加** `pool`（由 kind 推导，单一真相源）、**不加外键**（`ref_id` 是多态引用）；4 个索引，含 1 个**部分唯一索引**做入队幂等 | 加 FK → 删媒体时要么 CASCADE 删掉历史任务（审计丢失）要么 SET NULL（丢关联），且锁死 `ref_id` 到单表，P4 的 `grade_writing` 无法复用 |
| 3 | 崩溃恢复 | worker 级心跳 10s/TTL 30s；job 级租约 20s/TTL 120s；**`attempts` 兼作 fencing token**；claim/写回/回收三条语句全部带 `WHERE attempts=? AND worker_id=?` | 只用心跳超时（B）→ 「任务其实还活着但心跳被卡住」时必然双跑；加了 fencing 后，老执行者的写回 rowcount=0 直接自杀 |
| 4 | 两条轴的衔接 | **jobs 驱动、media 跟随**；失败时同一 Session 一次 commit 双写；`requeue_unfinished()` **保留且签名不变**（它修的是「有 media 无 job 的老库遗留」，与 jobs 恢复不重叠）；重复入队靠 `uq_jobs_active` 变 no-op | 删 `requeue_unfinished()`（B）→ 直接打破 `test_media_flow.py::TestRequeueUnfinished` 2 例，184 基线失守；且老库升级瞬间崩溃的遗留任务无人修 |
| 5 | CPU/IO 分池 | **拆 stage**：`media_transcode / media_asr / media_clip`→CPU，`media_translate / grade_writing`→IO；CPU 默认 `os.cpu_count()`，IO 默认 4；**每个 translate job 内部串行 + 保留 150ms 限流**（并发是"跨媒体"的，不是"跨句子"的） | 保留单条链（B）→ 长 ASR 占住 CPU 槽，同槽排队；G3-③ 物理上不可能通过。代价：4 个 stage × 3 次 handoff，事务边界变多，需要每 stage 幂等（已逐一核对，见 §5.3） |
| 6 | 三套启动方式 | 开发 = `dev.bat` 起 3 窗 + `start-backend.bat` **不动**（靠 `auto` 兜底）；打包 = launcher 起 worker 子进程（`fayelong.pid` 树杀 + worker 自杀兜底）；云端 = **两个 unit**（不选 wrapper） | 云端选 wrapper（B）→ 自己实现进程管理/信号传播/僵尸回收，systemd 的 `Restart` 只保得住 wrapper，等于白写重监控栈，违反「不引入重监控栈」 |
| 7 | 可观测性 | `/api/health` 的 dict 加 `worker`（online/count/mode/last_heartbeat_at）+ `jobs`（按 status 计数）两块。**因为该端点无 `response_model`，加字段不改变 OpenAPI schema → 契约 34/42 不变**（施工时必须现场跑 `check-contract.mjs` 证实）；job_id 贯穿日志**推迟到 P3-5** | 本阶段做全局 `job_id` 日志 Filter（B）→ 要动 `core/logging.py` 的 formatter + contextvars + 所有入口，收益低、回归面大；用 `logger.info("[job %s/%s] ...")` 手工带即可 |

---

## 2. 进程模型

### 2.1 三种形态

```
① 开发（FAYELONG_WEB_INPROC_WORKER=auto，默认）
   ┌──────────────┐        ┌───────────────────────────┐
   │ uvicorn:8000 │        │ worker 子进程（可缺）      │
   │  API + 静态   │        │  CPU池(核数) + IO池(4)     │
   │  in-proc 池   │◄──────►│                           │
   │  CPU1 + IO2   │  DB    │  仅当 workers 表无在线记录 │
   │  （让位逻辑） │        │  时才由 web 接管           │
   └──────────────┘        └───────────────────────────┘
            └────────── SQLite data/app.db（jobs / workers / media）──────────┘

② 打包交付（launcher 起两个进程，web_inproc=auto 作安全网）
   launcher.py(pid 写入 data/logs/fayelong.pid)
     ├─ 同进程 uvicorn.run("app.main:app")        ← 现状不变
     └─ Popen([python, "-m", "app.worker"])       ← 新增，静默时 CREATE_NO_WINDOW

③ 云端（systemd，两个 unit，web_inproc=off）
   fayelong.service         → uvicorn（MemoryMax=400M，不加载 whisper）
   fayelong-worker.service  → python -m app.worker（MemoryMax=1400M）
```

> **额外收益（务必写进部署说明）**：拆分后 web 进程不再执行 job，而 `services/asr.py` 本来就是延迟导入 → **whisper 模型只在 worker 里加载**。2 GB 实例上 web 常驻从「≈1.1 GB」降到「≈150 MB」，总占用反而比现状更低。

### 2.2 时序图（上传 → 入队 → 分池执行 → 双轴回写）

见 `docs/sequence-diagram.mermaid`（同内容，供工具渲染）。核心要点：

- **入队只是一条 `INSERT OR IGNORE`**，不触发任何执行；
- **执行权靠一条原子 `UPDATE ... WHERE status='pending'`** 取得；
- **每个 stage 结束时，在同一个事务里**做三件事：`jobs→done` + `media` 轴推进 + `INSERT 下一 stage`；
- **翻译阶段在 IO 池里跑**，与任何 CPU 池里的 ASR 物理隔离。

### 2.3 状态机（`jobs.status` 与 `media.status` 的耦合关系）

```
jobs:   pending ──claim──► running ──ok & 无下一 stage──► done
                              │
                              ├──ok & 有下一 stage──► done（同事务 insert 下一 stage 的 pending）
                              ├──异常 & attempts<3──► pending（重试）
                              ├──异常 & attempts>=3► failed（同事务 media→failed）
                              └──租约过期/worker消失─► pending（崩溃恢复，attempts 已 +1）

media:  pending → transcoding → (ready) → asr → translating → clipping → done
                 └──────────────── 任一阶段失败 → failed ────────────────┘
```

---

## 3. 数据模型

### 3.1 `jobs` 表最终 DDL

```sql
CREATE TABLE jobs (
    id           INTEGER      NOT NULL PRIMARY KEY,          -- rowid 别名，自增
    kind         VARCHAR(32)  NOT NULL,                      -- 见 §5.1 kind 常量
    ref_id       INTEGER      NOT NULL,                      -- 多态引用：media.id / responses.id
    status       VARCHAR(16)  NOT NULL DEFAULT 'pending',
    progress     INTEGER      NOT NULL DEFAULT 0,            -- ★ 阶段内进度 0-100（不是全局）
    error        TEXT         NULL,                          -- 最近一次失败原因，截断 500 字
    priority     INTEGER      NOT NULL DEFAULT 0,            -- 越大越优先
    payload      TEXT         NOT NULL DEFAULT '{}',         -- JSON，阶段参数（本阶段全为 {}）
    attempts     INTEGER      NOT NULL DEFAULT 0,            -- 兼作 fencing token（见 §4.3）
    worker_id    VARCHAR(64)  NULL,                          -- 归属执行者；pending 时为 NULL
    heartbeat_at DATETIME     NULL,                          -- 租约：claim 时置 now，执行中每 20s 续
    created_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at   DATETIME     NULL,                          -- 首次 claim 时间
    finished_at  DATETIME     NULL,                          -- done / failed 时间
    CHECK (status IN ('pending','running','done','failed')),
    CHECK (progress BETWEEN 0 AND 100)
);

CREATE INDEX        ix_jobs_claim           ON jobs(status, priority, id);
CREATE UNIQUE INDEX uq_jobs_active          ON jobs(kind, ref_id) WHERE status IN ('pending','running');
CREATE INDEX        ix_jobs_kind_ref        ON jobs(kind, ref_id);
CREATE INDEX        ix_jobs_status_heartbeat ON jobs(status, heartbeat_at);
```

| 索引 | 服务的查询 | 说明 |
|---|---|---|
| `ix_jobs_claim` | `SELECT id FROM jobs WHERE status='pending' AND kind IN (...) ORDER BY priority DESC, id ASC LIMIT 1` | status 等值过滤走索引；`priority DESC, id ASC` 混合方向 SQLite 可能需要一次小排序。**个人自用规模 ≤ 数千行，不为此牺牲语义**，别改成 `id DESC`（会变成后进先出） |
| `uq_jobs_active` | 入队幂等：`INSERT OR IGNORE` | **部分唯一索引**。同一 `(kind, ref_id)` 同时只能有 1 个活跃任务 → 重复 `enqueue` 天然 no-op，崩溃恢复与 `requeue_unfinished()` 重叠也不会双入队。⚠️ 要求 `ref_id NOT NULL`（NULL 在唯一索引里互不相等，会绕过约束）→ 已定为 `NOT NULL` |
| `ix_jobs_kind_ref` | `WHERE kind LIKE 'media_%' AND ref_id=?`（删媒体时清任务、查某媒体任务历史） | 部分索引只覆盖活跃行，查历史需要全量索引 |
| `ix_jobs_status_heartbeat` | 恢复扫描 `WHERE status='running' AND heartbeat_at < ?` | 每 5s 一次，必须走索引 |

### 3.2 决策记录：为什么**不加** `updated_at` / `pool` / 外键

| 候选字段 | 结论 | 理由 |
|---|---|---|
| `updated_at` | ❌ 不加 | `heartbeat_at` 已能回答「这个 job 最后一次有动静是什么时候」。而 `updated_at` 要求**每一条 UPDATE 都记得写它**（text SQL / `INSERT OR IGNORE` 都不会触发 ORM 的 `onupdate`），漏一处就变成一个会撒谎的字段 —— 排错时它比没有更糟 |
| `pool` | ❌ 不加 | `kind → pool` 是编译期常量映射（§5.1）。入库等于存了第二份真相，一旦两处不一致，排错成本远大于「日志里打一下 pool 名」的收益 |
| 外键 → `media.id` | ❌ 不加 | `ref_id` 是多态引用（本阶段 `media.id`，P4 起 `responses.id`）。加 FK 只能指一张表；且删媒体时 FK 语义两难：CASCADE 会连历史任务记录一起删（审计丢失），SET NULL 会让 `uq_jobs_active` 的部分唯一索引失去区分度。改为**应用层清理**（§3.4） |
| `max_attempts` | ❌ 不加 | 全局常量 `3`。若将来某 kind 需要不同上限，再加列，别提前抽象 |
| `not_before`（延迟重试） | ❌ 不加 | 失败重试直接回 `pending`，靠 `attempts>=3` 终止。中毒任务最多空转 3 次（秒级）即 `failed`，不需要退避调度器 |

### 3.3 `workers` 表（新增，进程心跳）

```sql
CREATE TABLE workers (
    id           VARCHAR(64) NOT NULL PRIMARY KEY,   -- uuid4().hex，每进程一个
    pid          INTEGER     NOT NULL,
    host         VARCHAR(64) NOT NULL DEFAULT '',
    mode         VARCHAR(16) NOT NULL DEFAULT 'external',  -- external | web-inproc
    pools        VARCHAR(64) NOT NULL DEFAULT '',    -- 'cpu=8,io=4'，纯诊断用
    started_at   DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    heartbeat_at DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX ix_workers_heartbeat ON workers(heartbeat_at);
```

- 每 10s 由心跳线程 `UPDATE workers SET heartbeat_at=CURRENT_TIMESTAMP WHERE id=?`（**1 次写**，不是每 job 一次）。
- **在线判定**：`heartbeat_at > now-30s`。`online_workers()` 就是这条查询。
- 启动时清理 10 分钟前的死行（`DELETE FROM workers WHERE heartbeat_at < now-600s`）。
- 正常退出时 `DELETE FROM workers WHERE id=?`。

### 3.4 与 `media` 的关系

| 场景 | 行为 |
|---|---|
| 删除媒体（`DELETE /api/media/{id}`） | `api/media.py::delete_media` 在 `db.delete(media)` 之后、同一事务内调用 `jobs_service.purge_for_media(db, media_id)`：`DELETE FROM jobs WHERE kind LIKE 'media_%' AND ref_id=?`。**执行中的 job 行被删后，其线程下一次写回 rowcount=0 → 自动自杀**（§4.3 第 4 条），无需 `cancelled` 状态 |
| 删分类 | 与 jobs 无关（jobs 不引用 category） |
| 历史任务堆积 | 个人自用规模可忽略。若需清理，另加 `DELETE FROM jobs WHERE status IN ('done','failed') AND finished_at < now-30d`（本阶段**不做**，写进 §9 风险） |

---

## 4. 崩溃恢复协议

### 4.1 阈值

| 参数 | 默认 | 依据 |
|---|---|---|
| worker 心跳间隔 | **10 s** | 一次 UPDATE，可忽略 |
| worker 心跳 TTL（判死） | **30 s** | 3× 间隔；容忍一次 GC/调度抖动 |
| job 租约续期间隔 | **20 s** | 由 worker 的 ticker 线程**一条 UPDATE 续本进程所有 running job**（`UPDATE jobs SET heartbeat_at=CURRENT_TIMESTAMP WHERE worker_id=? AND status='running'`），成本恒定 |
| job 租约 TTL（判僵死） | **120 s** | 6× 间隔。ASR 单次 `transcribe()` 在 2 vCPU 上可能几分钟，但进度回调频繁触发，且 ticker 是独立线程 → 120s 有充分余量 |
| `attempts` 上限 | **3** | claim 即 +1，故一个 job 最多被尝试 3 次（含崩溃导致的空转），可防「每次把 worker 搞 OOM」的无限重启循环 |
| 恢复扫描间隔 | **5 s** | worker 主循环里做，不做成独立进程 |

### 4.2 状态转移表（崩溃 / 失败 / 恢复）

| 起点 | 触发 | 终点 | `attempts` | `media` 轴 | 条件 / 备注 |
|---|---|---|---|---|---|
| `pending` | 执行者 claim | `running` | +1 | 不动（stage 自己 `_set_stage`） | `UPDATE ... WHERE id=? AND status='pending'`，rowcount=1 才算抢到 |
| `running` | stage 正常完成、无下一 stage | `done` | 不变 | `status/ progress` 由 stage 写 | 同事务 |
| `running` | stage 正常完成、有下一 stage | `done` | 不变 | 同上 | **同一事务**内 `INSERT OR IGNORE` 下一 stage 的 `pending`。绝不能"先 commit done、再单独入队"（两次提交之间崩溃 = 任务凭空消失） |
| `running` | 抛异常，`attempts < 3` | `pending` | 不变（已 +1） | `failed→pending`？**不**：保持 stage 的 `_mark_failed` 语义 | 记 `error`，清 `worker_id`/`heartbeat_at`。重试从**本 stage 开头**重跑（每 stage 幂等，§5.3） |
| `running` | 抛异常，`attempts >= 3` | `failed` | 不变 | **同事务**置 `status=failed, progress=0, error=截断500` | 两轴一起失败，不允许只失败一边 |
| `running` | 租约过期（`heartbeat_at < now-120s`）**或** `worker_id` 不在在线集合 | `pending` | 不变（已 +1） | `status=pending, progress=0, error=NULL` | 崩溃恢复。若 `attempts >= 3` → 直接 `failed`（防崩溃循环） |
| `pending` | 用户 `POST /retry` | （新增一条 `pending`） | 新行 `attempts=0` | `status=pending, progress=0` | 老行若已 `failed` 不在活跃集合里，新行可插入；老行若仍 `running`，`INSERT OR IGNORE` 变 no-op（**行为变更**：以前 retry 会并发出第二个处理线程，现改为忽略。这是改进，写进 §8） |
| 任意 | 媒体被删除 | 行被删除 | — | — | 执行线程下一次写回 rowcount=0 → 自杀 |

### 4.3 双跑防护（本节是本设计的核心，务必逐条实现）

> 问题本质：**「任务其实还活着，但心跳超时了」**。任何只靠超时的回收都会在这个窗口里制造两个执行者。解法不是把超时调大（那只是降低概率），而是让**老执行者的每一次写回都带一个代次校验**。

1. **原子 claim（执行权唯一来源）**
   ```sql
   UPDATE jobs
      SET status='running', worker_id=:me, attempts=attempts+1,
          started_at=COALESCE(started_at, CURRENT_TIMESTAMP),
          heartbeat_at=CURRENT_TIMESTAMP, error=NULL
    WHERE id = :job_id AND status = 'pending'
   ```
   `cursor.rowcount == 1` 才算抢到；`== 0` 说明被别人抢走，静默放弃。SQLite 的单写锁 + 单条语句原子性保证跨进程互斥。

2. **`attempts` 作 fencing token**：claim 成功后把 `my_attempt = job.attempts`（新值）记在**内存里**。执行期间**所有**对这条 job 的写回都必须带
   ```sql
   WHERE id=:job_id AND worker_id=:me AND attempts=:my_attempt
   ```
   rowcount=0 → **立刻停止执行并 return**（不抛异常，不写 media）。这一步是「老执行者复活后写坏数据」的唯一拦截点。

3. **回收也带乐观条件**（防「刚续完租约，回收线程基于旧快照把我重置」）：
   ```sql
   UPDATE jobs
      SET status='pending', worker_id=NULL, heartbeat_at=NULL
    WHERE id=:job_id AND status='running'
      AND worker_id=:stale_worker AND heartbeat_at <= :stale_before
   ```
   带 `worker_id` + `heartbeat_at <= 快照值`，等价于 CAS。若在此期间原执行者续了租，`heartbeat_at` 变大 → rowcount=0 → 不回收。

4. **阶段边界的存活自检**（廉价、兜底）：每个 stage 开始时、以及每次 `progress` 回调里，顺手校验一次
   ```sql
   SELECT status, worker_id, attempts FROM jobs WHERE id=:job_id
   ```
   若 `status != 'running'` 或 `worker_id != me` 或 `attempts != my_attempt` → 抛内部哨兵异常 `JobAborted`，stage 捕获后**不写 media 轴**直接返回。代价：每次进度回调多一次索引查询（且只在进度变化 ≥2% 时发生），可忽略。

5. **不做的两件事**（避免过度设计）：
   - **不做分布式锁**（fencing 已足够，且只有 1~2 个执行者进程）。
   - **不把 `job_id` 贯穿到 ffmpeg 子进程**：`transcode_to_wav` 是同步阻塞调用，无法中途自检。转码结束后统一做第 4 条校验即可；转码本身幂等（覆盖写同一个 wav），重复执行只浪费 CPU，不破坏数据。

6. **`kill -9` 到底发生了什么**（写清楚，避免误判测试结果）：
   - 进程被 `TerminateProcess`（Windows）/ `SIGKILL`（Linux）杀掉 → 线程全部死亡，`workers` 行**残留**且心跳停止。
   - 重启后新 worker 启动时：① 清理死 `workers` 行（>10min）② 立刻跑一次恢复扫描。**但此时死 worker 的心跳可能只过去 5s（< TTL 30s）**，不会立刻回收 —— 要等 TTL 到期。所以验收脚本必须**等到** `job_lease_timeout` 之后，或者恢复条件里加上「`worker_id` 已不在在线集合」这条（本文采用后者，**两条 OR 关系**，所以重启后 30s 内即可恢复，不必等 120s）。

---

## 5. 池化设计

### 5.1 `kind` → 池 映射

| `kind` 常量 | 值 | 池 | 说明 |
|---|---|---|---|
| `KIND_TRANSCODE` | `media_transcode` | **CPU** | ffprobe + ffmpeg 转码。入口 `stage_transcode` |
| `KIND_ASR` | `media_asr` | **CPU** | faster-whisper 识别。入口 `stage_asr` |
| `KIND_CLIP` | `media_clip` | **CPU** | ffmpeg 逐句切片。入口 `stage_clip` |
| `KIND_TRANSLATE` | `media_translate` | **IO** | 在线翻译（网络 IO + 150ms 限流）。入口 `stage_translate` |
| `KIND_GRADE_WRITING` | `grade_writing` | **IO** | P4-4 预留，本阶段**只登记映射，不实现 handler** |

```python
# app/services/jobs.py
POOL_CPU = "cpu"
POOL_IO = "io"

KIND_POOL: dict[str, str] = {
    KIND_TRANSCODE: POOL_CPU,
    KIND_ASR: POOL_CPU,
    KIND_CLIP: POOL_CPU,
    KIND_TRANSLATE: POOL_IO,
    KIND_GRADE_WRITING: POOL_IO,
}
DEFAULT_POOL = POOL_CPU          # 未知 kind 保守落 CPU：慢，但不会把 CPU 活扔进 IO 池压垮机器

# 链式推进：完成本 stage 后自动入队下一 stage
NEXT_STAGE: dict[str, str | None] = {
    KIND_TRANSCODE: KIND_ASR,
    KIND_ASR: KIND_TRANSLATE,
    KIND_TRANSLATE: KIND_CLIP,
    KIND_CLIP: None,
    KIND_GRADE_WRITING: None,
}
```

### 5.2 难点：一条 `process_media` 链里既有 CPU 又有 IO —— 拆 stage

**问题**：现状 `process_media(media_id)` 是一个函数跑完 transcode→asr→translate→clip。若把它当**一个 job**，那么「翻译」这段网络 IO 会占住一个 CPU 池槽位。2 vCPU 云端 CPU 池 = 2，两个媒体同时进入 translate 阶段就把 CPU 池占满 → **第三个媒体的转码无法开始**，G3-③ 物理上不可能通过。

**解**：把链拆成 4 个 job，**每个 job 自带 pool 归属**；链的衔接 = 上一 stage `done` 时在**同一事务**里插入下一 stage 的 `pending` 行。

```python
# app/services/media.py（重构后骨架，只示意结构，签名以 §6 T03 为准）

def stage_transcode(media_id: int, job: JobCtx) -> None:
    """CPU 池。幂等：标准 wav 已存在且 media.audio_path 指向它 → 直接跳过。"""
    with job.session() as db:
        media = db.get(Media, media_id)
        if media is None:
            return                                  # 媒体已删除 → 静默结束（job 会被 purge）
        media.error = None
        _ensure_audio(db, media)                    # 内部已含 ffprobe + transcode_to_wav + _set_stage(transcoding)
        db.commit()
    # 不在这里入队下一 stage：交给 job 完成路径统一处理（保证同事务）

def stage_asr(media_id: int, job: JobCtx) -> None:
    """CPU 池。幂等：句子表整体重建。"""
    with job.session() as db:
        media = db.get(Media, media_id)
        if media is None:
            return
        audio = Path(media.audio_path or audio_wav_path(media_id))
        if not audio.is_file():
            raise MediaError("标准音频丢失，请执行「重新处理」")
        _set_stage(db, media, STATUS_ASR, _scale(1, PROGRESS_ASR))
        sentences, _info = asr_service.transcribe(
            audio, duration_ms=media.duration_ms,
            on_progress=_Progress(db, media, PROGRESS_ASR, job=job),   # 进度回调同时续租 + 自检
        )
        if not sentences:
            raise MediaError("未识别到任何语音内容，请确认音频中有英文人声")
        _persist_sentences(db, media.id, sentences)
        media.progress = _scale(100, PROGRESS_ASR)
        db.commit()

def stage_translate(media_id: int, job: JobCtx) -> None:
    """IO 池。幂等：只 UPDATE text_zh，不重建句子。"""
    with job.session() as db:
        media = db.get(Media, media_id)
        if media is None:
            return
        rows = _sentences_of(db, media_id)                  # ORDER BY idx
        if not rows:                                        # all-zero 除零防护
            raise MediaError("没有可翻译的句子")
        _set_stage(db, media, STATUS_TRANSLATING, PROGRESS_TRANSLATE[0])
        total, failed = len(rows), 0
        for index, row in enumerate(rows):
            job.check_alive()                               # ★ fencing 自检（每句一次，很便宜）
            result = translate_service.translate(row.text_en)
            if result["text"]:
                row.text_zh = result["text"]
            else:
                failed += 1
            if index < total - 1:
                translate_service.sleep_between()            # 保留 150ms 限流
            media.progress = _scale(int((index + 1) / total * 100), PROGRESS_TRANSLATE)
            if index % 5 == 0 or index == total - 1:
                db.commit()
        db.commit()
        if failed:
            logger.warning("媒体 %s 有 %d/%d 句翻译失败（保留空译文待人工补）", media_id, failed, total)

def stage_clip(media_id: int, job: JobCtx) -> None:
    """CPU 池。幂等：先 clear_clips 再逐句重切。完成后 media → done。"""
    ...
    media.status = STATUS_DONE
    media.progress = 100
    media.error = None
```

**注意「不把翻译按句扇出到 IO 池」**（这是一处刻意的取舍）：
- 免费引擎（有道 / MyMemory）**按 IP 限流**，按句并发会大面积 429 → `failed` 计数暴涨，比串行还差；
- `translate_service` 有 `translations` 表做缓存 + `sleep_between()` 限流，串行是刻意设计；
- **IO 池的价值是「不同媒体/不同 kind 之间并行」**（媒体 A 在翻译时，媒体 B 的翻译、将来的写作批改可以同时跑），不是「同一媒体的 N 句并行」。
- 若将来要把单媒体翻译提速，正确做法是「每 N 句一个 `media_translate` 子任务，`ref_id` 仍是 media_id 但 `payload` 带句子区间」——**那时才需要放宽 `uq_jobs_active`**（改为 `(kind, ref_id, payload_key)`）。本阶段不做，写进 §9 演进备注。

### 5.3 拆 stage 的可行性前提：每 stage 必须幂等（已逐一核对）

| stage | 重复执行会发生什么 | 是否安全 |
|---|---|---|
| `transcode` | `_ensure_audio` 已有「wav 存在且 `media.audio_path` 指向它 → 直接 return」的短路；否则 `ffmpeg -y` 覆盖写同一路径 | ✅ 幂等 |
| `asr` | `_persist_sentences` 先 `DELETE` 再重建。⚠️ 句子 id 变化 → `attempts`/`notes` 的 `ON DELETE CASCADE` **会删掉用户听写记录** | ✅ 数据一致，⚠️ 有副作用；**这是现状既有行为**（`retranscribe` 一样），见 §9 R6 |
| `translate` | 只 `UPDATE text_zh`；已翻译过的句子会被重新翻译（走 `translations` 缓存，实际不重复请求） | ✅ 幂等 |
| `clip` | `clip_service.clear_clips(media.id)` 先清空再逐句 `cut_clip_auto`（覆盖写） | ✅ 幂等 |

### 5.4 配置项清单（沿用 `FAYELONG_*`）

| 配置项（env 名去掉 `FAYELONG_` 前缀） | 默认 | 含义 |
|---|---|---|
| `job_cpu_threads` | `0` | CPU 池线程数。**`0` = 自动**，取 `max(1, os.cpu_count() or 1)`。云端必须显式设 `1`（见 §6 T04） |
| `job_io_threads` | `4` | IO 池线程数。翻译/未来批改。免费引擎限流下 4 已是上限，不要调大 |
| `job_poll_interval_ms` | `500` | 池循环轮询间隔（有活时） |
| `job_idle_max_ms` | `2000` | 空闲退避上限 |
| `job_heartbeat_interval_sec` | `10` | worker 级心跳间隔 |
| `job_worker_ttl_sec` | `30` | worker 判死阈值 |
| `job_lease_interval_sec` | `20` | job 租约续期（ticker 一条 UPDATE 覆盖全部） |
| `job_lease_ttl_sec` | `120` | job 判僵死阈值 |
| `job_max_attempts` | `3` | 尝试上限 |
| `web_inproc_worker` | `"auto"` | `auto` / `off` / `on`，见 §1 决策 1 |
| `worker_threads` | `2` | ⚠️ **旧变量，保留字段但任何代码都不再读取**（云端 unit 现在设的是 1，不能让它悄悄失效 → 显式新增 `job_cpu_threads`，见 §6 T04 的兼容顺序） |

---

## 6. 文件级任务清单（有序，照做）

> 每个任务 = 一次可提交、可独立验收的改动。**依赖顺序不可调换**：T01 建表 → T02 调度内核 → T03 业务衔接 → T04 启动链路 → T05 测试与闸门 → T06（后置）打包链。
> 硬约束：T01~T05 是 P3-2/P3-3 的交付范围；**T06 属 P3-6，可后置**，但 T04 里 launcher 的改动必须先做（否则打包版没有 worker）。

---

### T01 数据层与迁移（P0）

**依赖**：无
**优先级**：P0
**验收**：`cd backend && .venv/Scripts/python -m pytest tests/test_migrations.py -q` 全绿；`alembic upgrade head` 对 `data/app.db` 副本是「只新增 2 张表，9 张老表零改动」。

| 文件 | 改什么 |
|---|---|
| `backend/app/models/entities.py` | 新增 `Job`、`Worker` 两个模型。`Job.__table_args__` = `(CheckConstraint(...) ×2, Index('ix_jobs_claim',...), Index('uq_jobs_active', 'kind','ref_id', unique=True, sqlite_where=text("status IN ('pending','running')")), ...)`。⚠️ **必须用 `sqlite_where=`** 才是部分唯一索引；写成普通 `unique=True` 会让「同一个媒体只能有一次任务」变成永久约束，整个设计报废 |
| `backend/app/models/__init__.py` | `Job`、`Worker` 加入 import 与 `__all__` |
| `backend/migrations/versions/0002_jobs_and_workers.py` | 新迁移。`revision='0002'`、`down_revision='0001'`。⚠️ **必须 `inspect(conn).has_table('jobs')` 先判存在再 `create_table`**（原因：打包版就地升级走 `init_db()` → `create_all` 已经把表建出来了，此时 `alembic upgrade head` 绝不能报 "table already exists"）。`downgrade()` 反向 `drop_table`（顺序：先 `workers` 后 `jobs`）|
| `backend/app/db.py` | `create_engine(..., connect_args={"check_same_thread": False, "timeout": 15})` —— 两进程并发写 SQLite 时避免瞬时 `database is locked`。⚠️ **不要开 WAL**（`fingerprint_data.py`、`data/backups` 脚本按现有 journal 模式工作，改模式会让备份/指纹口径变化，属本阶段范围外） |
| `backend/tests/test_migrations.py` | **必须同步修改（不改就红）**，共 4 处，见下方「精确改法」 |

**`test_migrations.py` 的精确改法**（这是「184 passed 不能破」的关键，改完必须让 QA 逐条核对没放宽断言）：

1. 拆成两组常量：
   ```python
   _LEGACY_TABLES = frozenset({...原来的 9 张...})          # 一字不改
   _NEW_TABLES    = frozenset({"jobs", "workers"})
   _EXPECTED_TABLES = _LEGACY_TABLES | _NEW_TABLES
   ```
2. `_BASELINE_REVISION = "0001"` → 改名 `_HEAD_REVISION = "0002"`（3 处断言跟改）。语义从「基线」变「当前 head」，**不要**保留 `0001` 的断言（那会阻止任何新迁移）。
3. `test_fresh_schema_matches_models_exactly`：`63` → `63 + jobs 列数 (14) + workers 列数 (7) = 84`；`8` → `8 + 5 = 13`；`9` → `11`。**数字必须现场从 `Base.metadata` 数出来再填，不许照抄本文**（`_actual_columns` 数出的真实值优先）。注释里那串 `4+15+10+...` 分解式必须补全。
4. `test_real_database_copy_upgrade_keeps_everything` 与 `test_legacy_database_upgrade_is_noop_and_keeps_data`：语义要**精确化**为
   ```python
   # 老 9 张表必须逐列零改动（这条断言一个字都不许放宽）
   assert {t: info[t] for t in _LEGACY_TABLES} == {t: before_info[t] for t in _LEGACY_TABLES}
   # 新表必须出现
   assert _NEW_TABLES <= _table_names(copy_db)
   ```
   原因：`_table_info()` 遍历 `_EXPECTED_TABLES`，而真实库升级前没有 `jobs` 表 → `PRAGMA table_info(jobs)` 返回 `[]`，与升级后的列集合不等 → 若整表比对会**假红**；但删掉这条断言又会丢掉「老库结构不许动」的保护。拆成上面两句才是既不放宽也不假红。

---

### T02 调度内核：`services/jobs.py` + `worker.py` + `core/tasks.py` 双池（P0）

**依赖**：T01
**优先级**：P0
**验收**：`pytest tests/test_jobs.py tests/test_worker_pools.py -q` 全绿（含下面 §7.1 全部用例）；`python -m app.worker --help` 正常；`python -m app.worker` 能在空库上启动并空闲轮询（日志每 30s 有 worker 心跳，`workers` 表有 1 行）。

| 文件 | 改什么 |
|---|---|
| `backend/app/services/jobs.py`（新，约 320 行） | **单一入口模块**。<br>① 常量：`JOB_PENDING/RUNNING/DONE/FAILED`、`KIND_*`、`POOL_CPU/POOL_IO`、`KIND_POOL`、`NEXT_STAGE`（§5.1）。<br>② `enqueue(kind, ref_id, payload=None, priority=0) -> int|None`：`INSERT OR IGNORE`，返回 job id 或 `None`（已存在活跃任务）。⚠️ `INSERT OR IGNORE` 会连 NOT NULL 违约一起吞掉 → 插入后校验 `rowcount`，为 0 时**再查一次**确认是「唯一索引冲突」而不是「非法行」，非法则抛 `ValueError`。<br>③ `claim(session, kinds, worker_id) -> Job|None`：§4.3 第 1 条的原子 UPDATE + 回读。<br>④ `touch(session, job, my_attempt)` / `check_alive(session, job_id, worker_id, my_attempt) -> bool`：§4.3 第 2、4 条。<br>⑤ `finish_ok(session, job, next_kind=None, ref_id=None, payload=None)`：§4.2 第 3 行，**同事务** done + 入队下一 stage。<br>⑥ `finish_failed(session, job, message, max_attempts)`：§4.2 第 4、5 行，判重试还是终态。<br>⑦ `recover_stale(session, now) -> int`：§4.2 第 6 行，返回回收条数。<br>⑧ `renew_lease(session, worker_id)`：§4.1 的一条 UPDATE 续全部。<br>⑨ `purge_for_media(session, media_id)`：§3.4。<br>⑩ `counts_by_status(session) -> dict`：给 health 用。<br>⑪ `register_worker/ heartbeat_worker / unregister_worker / online_workers`：`workers` 表 CRUD。 |
| `backend/app/worker.py`（新，约 260 行） | `class Worker`：`__init__(cpu_threads, io_threads, mode)`；`start()`（注册 worker 行 → `recover_stale()` → 起心跳线程 → 起租约 ticker 线程 → 起 2 个 `_PoolRunner`）；`stop()`（置位 → join → unregister）。<br>`class _PoolRunner(threading.Thread)`：信号量限流 + `claim(kinds_of_pool)` + `executor.submit(_execute)`；`_execute` 内捕获所有异常交给 `finish_failed`；捕获 `JobAborted` 静默返回。<br>`HANDLERS: dict[str, Callable[[JobCtx], None]]` —— **必须是模块级可 patch 的 dict**（测试要靠它注入假 handler，见 §7.2）。<br>`main()`：`argparse`（`--pools cpu,io`、`--once`、`--parent-pid`、`--no-recovery`）；`ensure_dirs() → setup_logging(filename="worker.log") → init_db() → Worker(...).start()`；`if args.parent_pid: 起一个守护线程每 15s 检查 data/logs/fayelong.pid 是否存在且内容 == parent_pid，不符则优雅退出`（Windows 孤儿防护，见 §6 T04）。⚠️ **绝不调用 `input()`**（`pythonw` 下会 `RuntimeError`），`--once` 仅供参考用，不做交互确认。 |
| `backend/app/core/tasks.py` | 改为「池与执行器注册」：保留 `submit()`/`shutdown()` 名字（`main.py` 还在调 `shutdown_tasks`），但语义改为「进程内默认池的 submit（已废弃，仅向后兼容）」。新增 `POOL_CPU/POOL_IO` 常量引用 + `new_executor(name, size)`。⚠️ 不要在这里塞业务逻辑 |
| `backend/app/core/config.py` | `Settings` 加 §5.4 的 10 个字段；`worker_threads` 保留并加注释 `# deprecated: P3-2 起不再读取` |
| `backend/app/core/logging.py` | `setup_logging(level=INFO, filename="app.log")`；worker 传 `"worker.log"`。⚠️ **必须分开**：两个进程同时 `RotatingFileHandler` 轮转同一个 `app.log` 在 Windows 上会 `PermissionError`，且轮转会互相覆盖 |

---

### T03 业务衔接：`media.py` 拆 stage + 双轴状态 + lifespan（P0）

**依赖**：T02
**优先级**：P0
**验收**：`pytest -q` 全绿（尤其 `test_media_flow.py::TestRequeueUnfinished` 2 例**零改动通过**）；`test_smoke.py` 通过（lifespan 不炸）；`python -c "from app.main import app"` 正常。

| 文件 | 改什么 |
|---|---|
| `backend/app/services/media.py` | ① 拆出 `stage_transcode / stage_asr / stage_translate / stage_clip`（§5.2 骨架），复用现有 `_ensure_audio`/`_persist_sentences`/`_set_stage`/`_Progress`。<br>② `_Progress.__init__` 加 `job=None` 参数，回调里顺手 `jobs_service.touch()` + `check_alive()`（进度写与续租同一次 commit，**零额外写**）。<br>③ `_mark_failed(media_id, message, job=None)`：加 job 参数，**同一 Session** 里既写 media 又写 job（§4.2 第 5 行）。<br>④ `enqueue(media_id)` → `jobs_service.enqueue(KIND_TRANSCODE, media_id)`；`enqueue_retranscribe(media_id)` → `jobs_service.enqueue(KIND_ASR, media_id)`。<br>⑤ `process_media()` / `retranscribe_media()`：**保留函数名不要删**（`__all__` 里有），改为「同步跑完整链」的兼容包装（内部依次调 4 个 stage，不经过池）—— 只在手工排错/测试用，生产路径不再调用。<br>⑥ `requeue_unfinished()` **一字不改**（签名、返回条数、`enqueue` 调用方式全部保持）—— 它现在的作用变成「把老库遗留的 media 状态修回 pending 并**入队**」，执行由 worker 负责。 |
| `backend/app/main.py` | `lifespan` 变成：`ensure_dirs() → setup_logging() → init_db() → requeue_unfinished() → maybe_start_inproc_worker()`；`yield` 后 `stop_inproc_worker(); shutdown_tasks()`。<br>`maybe_start_inproc_worker()` 逻辑：`mode = settings.web_inproc_worker.lower()`；`off` → 什么都不做；`on` → 无条件起；`auto` → **延迟 5s**（`threading.Timer`）后再判一次 `jobs_service.online_workers()`，为空才起，且 `mode="web-inproc"`、`cpu_threads=1, io_threads=2`（小池，避免与真正的 worker 抢核）。⚠️ 起之前先打一条 `logger.warning("未检测到独立 worker 进程，web 进程降级为进程内执行（FAYELONG_WEB_INPROC_WORKER=auto）")`。 |
| `backend/app/api/media.py` | ① `delete_media`：`db.delete(media)` 后调 `jobs_service.purge_for_media(db, media_id)`，同一事务提交。<br>② 三处 `media_service.enqueue(...)` **调用点不改**（签名不变）。<br>③ ⚠️ **不新增任何端点、不改任何响应模型/状态码**（契约 34/42 必须不变） |
| `backend/app/api/health.py` | 返回 dict 增加两块（§1 决策 7）：`"worker": {"online": bool, "count": int, "mode": str, "last_heartbeat_at": str|None}`、`"jobs": {"pending": n, "running": n, "done": n, "failed": n}`。⚠️ `last_heartbeat_at` 必须由 ORM 的 `datetime` 显式转成 `.isoformat()` 字符串（该端点有 `-> dict` 返回注解，FastAPI 会按 `Dict[str, Any]` 序列化，别把裸 `datetime` 混进 dict 里）。**整体包在 `try/except` 里**（沿用现有 `media_total` 的写法），自检接口不能因统计失败而 500。⚠️ 加完立刻跑 `node scripts/check-contract.mjs` 证实契约不变；若变了**停下来报告**，不要自己改基线 |
| `backend/tests/conftest.py` | 在 import `app.main` 之前加一行 `config.settings.web_inproc_worker = "off"`（并注释原因：**测试里绝不能让 lifespan 起后台执行线程**，否则用例之间会互相抢任务、变成随机失败）。⚠️ 这一行必须在 `import app.main` 之前 |

---

### T04 启动链路：开发 / 打包 / 云端（P1）

**依赖**：T03
**优先级**：P1
**验收**：① `scripts/start-worker.bat` 能起 worker 并在 `data/logs/worker.log` 看到心跳；② `packaging\launcher.py --check` 通过（不起 worker）；③ `launcher.py` 正常启动后 `data/logs/worker.pid` 存在、`taskkill /PID <launcher> /T /F` 后 worker 进程消失；④ `systemd-analyze verify deploy/linux/fayelong-worker.service`（在云端或本地 WSL）通过。

| 文件 | 改什么 |
|---|---|
| `packaging/launcher.py` | ① 新增 `start_worker(port_unused)`：`subprocess.Popen([sys.executable, "-m", "app.worker"], cwd=ROOT, env={**os.environ, "FAYELONG_WEB_INPROC_WORKER": "auto"}, creationflags=(subprocess.CREATE_NO_WINDOW if silent else 0), stdout=open(LOG_DIR/"worker.out", "a"))`；把 `proc.pid` 写 `data/logs/worker.pid`。<br>② `run_server()` 的 `finally` 里 `worker_proc.terminate()` → `wait(5)` → `kill()`，并 unlink `worker.pid`。<br>③ `--check` 分支**不得**起 worker（`build.ps1` 9/9 会调它）。<br>④ 环境变量 `FAYELONG_WEB_INPROC_WORKER`：**打包版保持 `auto`**（安全网优先，交付给小白用户时「卡死无提示」是不可接受的）。<br>⑤ 注意 `sys.executable` 在 `pythonw.exe` 下就是 `pythonw.exe` → 子进程天然无窗口，不需要额外处理；但**仍然**要传 `CREATE_NO_WINDOW`（`python.exe --silent` 的情况） |
| `scripts/start-worker.bat`（新） | `backend\.venv\Scripts\python.exe -m app.worker`，`cd /d "%~dp0.."`，`chcp 65001`。**不要加 `--reload`**（worker 没有热重载，改代码要手动重启） |
| `scripts/dev.bat` | 改成起 3 个窗口：Backend / Worker / Frontend。⚠️ `start-backend.bat` **一个字不改**（它只起 web，靠 `auto` 在 5s 后接管 → 只跑后端也能用，行为与今天一致） |
| `deploy/linux/fayelong-worker.service`（新） | `Type=simple`、`WorkingDirectory=/opt/fayelong/backend`、`ExecStart=/opt/fayelong/venv/bin/python -m app.worker`、`Restart=on-failure`、`RestartSec=5`、`MemoryHigh=1000M`、`MemoryMax=1400M`、`Environment=FAYELONG_JOB_CPU_THREADS=1`、`Environment=FAYELONG_JOB_IO_THREADS=4`、`Environment=FAYELONG_WEB_INPROC_WORKER=off`、日志 `append:/var/log/fayelong/worker.log`。**不设 `After=fayelong.service`**（worker 不该等 web） |
| `deploy/linux/fayelong.service` | ① 加 `Environment=FAYELONG_JOB_CPU_THREADS=1`（**必须显式加**：`job_cpu_threads=0` 在 2 vCPU 上会取 2，跟 ASR 抢核）；② 加 `Environment=FAYELONG_WEB_INPROC_WORKER=off`；③ `MemoryHigh=300M` / `MemoryMax=400M`（web 不再加载 whisper，可以大幅收紧；拆进程后总占用反而更低）；④ 保留 `FAYELONG_WORKER_THREADS=1` 但**加注释说明它已不生效**（这样任何中途回滚到旧代码的部署仍然拿到 1） |
| `deploy/linux/update.sh` | 重启顺序改为：`systemctl stop fayelong fayelong-worker` → 解包 → `chown` → `systemctl start fayelong` → `systemctl start fayelong-worker`。⚠️ **先启 worker 或先启 web 都安全**（`off` 模式下 web 不干活，`auto` 模式下 web 会兜底），但**必须先 `stop` 完两个再动文件**，否则 worker 会在解包过程中 import 到半截代码 |
| `deploy/README.md` | 新增「§X 双进程部署」：两个 unit 的安装/启停/日志位置/内存上限依据；并明确写 **回滚动作**：`systemctl disable --now fayelong-worker` + 把 web unit 的 `FAYELONG_WEB_INPROC_WORKER` 改回 `auto/on` → `daemon-reload` + `restart fayelong`，即退回「单进程全干」的旧行为 |

---

### T05 测试与闸门（P0）

**依赖**：T03、T04
**优先级**：P0
**验收**：`cd backend && .venv/Scripts/python -m pytest -q` → **`184 + 新增` 全绿**；`node scripts/check-contract.mjs` → `✅ 契约与基线一致（paths = 34, operations = 42）`；`scripts/verify_worker_g3.py` 输出 PASS。

| 文件 | 改什么 |
|---|---|
| `backend/tests/test_jobs.py`（新，约 12 例） | 状态机与租约，见 §7.1 清单 |
| `backend/tests/test_worker_pools.py`（新，约 6 例） | 池路由与「ASR 不阻塞翻译」，见 §7.2 |
| `backend/tests/test_worker_recovery.py`（新，约 4 例） | 崩溃恢复（真子进程，见 §7.3） |
| `scripts/verify_worker_g3.py`（新，约 180 行） | G3-②/③ 的**可重复**验收脚本（起隔离根，`kill` 真进程，断言恢复），见 §7.4 |
| `backend/tests/test_media_flow.py` | **不改**（除非 T03 改坏了 `requeue_unfinished`）。若红 → 说明 T03 违反了「签名不变」约束，回去改代码，不许改测试 |
| 全量门禁 | 依次跑：`pytest -q`、`node scripts/check-contract.mjs`、`python scripts/export_openapi.py` + 契约比对、`packaging\build.ps1 -NoZip`（T06） |

---

### T06（后置，属 P3-6）打包链回归（P2）

**依赖**：T04、T05
**优先级**：P2
**验收**：G3-④ `packaging\build.ps1 -NoZip` 通过；解压产物里 `runtime\python\python.exe scripts\launcher.py --check` 通过；双击 `静默启动 FayeLong.vbs` 后任务管理器里有 **2 个** FayeLong 相关进程，且 `data/logs/worker.log` 有心跳。

| 文件 | 改什么 |
|---|---|
| `packaging/build.ps1` | ① 9/9 自检步骤只需确认 `launcher.py --check` 仍通过（`backend/app` 是整目录 `Copy-Tree`，`worker.py` 自动进包，**不需要新增拷贝步骤**）；② 若 `--check` 因新增 import 失败，检查是否漏了 `app/worker.py`<br>⚠️ **本阶段可以不做**：T01–T05 只保证代码与开发链路可用 |
| `packaging/files/停止 FayeLong.bat` | 现状 `taskkill /PID %PID% /T /F` 的 `/T` 已能连带杀掉 worker 子进程，**理论上零改动**。仍需实测确认（Windows 的 `taskkill /T` 按 `ParentProcessId` 递归），若发现漏杀则补 `data\logs\worker.pid` 的二次 kill |
| `packaging/files/使用说明.txt` | 补一句排错提示：「素材一直显示『排队中』」→ 看 `data\logs\worker.log` |

---

## 7. 测试策略（全部可重复，不含「肉眼看」）

### 7.1 单测 `tests/test_jobs.py`

| 用例 | 断言 |
|---|---|
| `test_enqueue_creates_pending` | 插入后 `status='pending'`, `attempts=0`, `worker_id is None` |
| `test_enqueue_is_idempotent_on_active` | 同 `(kind, ref_id)` 连调两次 → 只有 1 行，第二次返回 `None` |
| `test_enqueue_allowed_after_terminal` | 第一次 `status='failed'` 后再次 enqueue → 新建一行（`uq_jobs_active` 只管活跃态） |
| `test_enqueue_rejects_null_ref_id` | `ref_id=None` → `ValueError` |
| `test_claim_is_atomic` | 两个 `Session` 各自 claim 同一 job → 只有一个 `rowcount==1`，另一个 `None` |
| `test_claim_bumps_attempts_and_sets_lease` | `attempts==1`、`worker_id==me`、`heartbeat_at is not None`、`started_at` 首次写入后不再被覆盖（第二次 claim 时 `started_at` 不变） |
| `test_touch_with_stale_attempt_is_rejected` | `my_attempt` 比库里小 1 → `rowcount==0`（fencing 生效） |
| `test_check_alive_false_after_reap` | 回收后再 `check_alive(my_attempt)` → `False` |
| `test_finish_ok_chains_next_stage_in_same_tx` | `finish_ok(job, next_kind=KIND_ASR)` → 本 job `done` **且** 出现 `(KIND_ASR, ref_id)` 的 `pending`，且两行同一次 commit（用 `db.rollback()` 反向验证：未 commit 时两行都不可见） |
| `test_finish_ok_terminal_stage_sets_finished_at` | `KIND_CLIP` → `done` 且 `finished_at` 非空且无新 job |
| `test_finish_failed_retries_under_limit` | `attempts=1`, `max=3` → `status='pending'`, `error` 非空, `worker_id` 清空 |
| `test_finish_failed_terminal_over_limit` | `attempts=3` → `status='failed'`, `finished_at` 非空 |
| `test_recover_stale_by_lease_timeout` | 造 `running` + `heartbeat_at=now-200s` → 回收 → `pending` |
| `test_recover_stale_by_dead_worker` | 造 `running` + `worker_id='ghost'` + 心跳是刚才（未超 TTL）→ `workers` 表里没有 `ghost` → **仍然回收**（§4.3 第 6 条的 OR 条件） |
| `test_recover_skips_live_job_with_fresh_lease` | 造 `running` + 在线 worker + 心跳 5s 前 → **不回收**（这条是「不误伤」的护栏） |
| `test_recover_marks_failed_when_attempts_exhausted` | `attempts=3` 的僵死 job → 直接 `failed`，不回 `pending`（防崩溃循环） |
| `test_recover_does_not_double_enqueue` | `running` 僵死 + 同 `(kind,ref_id)` 已有一个 `pending`（不该出现，但强行造）→ 回收成 `pending` 时撞 `uq_jobs_active` → 不抛异常，行数仍为 1 |

### 7.2 集成 `tests/test_worker_pools.py`（G3-③ 的**主要**验证手段）

**关键**：用 `Worker.HANDLERS` 注入假 handler，**不需要 whisper 模型、不需要 ffmpeg、不需要网络**，1 秒内跑完。

```python
def test_translate_not_blocked_by_slow_asr(tmp_root):
    # cpu=1, io=2
    w = Worker(cpu_threads=1, io_threads=2, mode="external", recover=False)
    w.HANDLERS[KIND_ASR] = lambda ctx: time.sleep(0.8)      # 模拟长 ASR
    w.HANDLERS[KIND_TRANSLATE] = lambda ctx: time.sleep(0.05)
    jobs_service.enqueue(KIND_ASR, ref_id=1)
    for ref in (101, 102, 103):
        jobs_service.enqueue(KIND_TRANSLATE, ref_id=ref)
    w.start(); w.wait_idle(timeout=5); w.stop()

    rows = {j.ref_id: j for j in all_jobs()}
    # ① 3 个翻译全部在 ASR 之前/期间完成（时间戳重叠，不靠人眼）
    assert max(rows[r].finished_at for r in (101,102,103)) < rows[1].finished_at
    # ② ASR 与至少一个翻译的执行区间重叠 → 证明物理并行
    assert rows[101].started_at < rows[1].finished_at
    # ③ 池容量未被突破：CPU 池同时 running 的最大值 == 1
    assert max_concurrent(all_jobs(), pool=POOL_CPU) <= 1
    assert max_concurrent(all_jobs(), pool=POOL_IO) <= 2
```

其余用例：
| 用例 | 断言 |
|---|---|
| `test_kind_routes_to_expected_pool` | `{k: KIND_POOL[k] for k in KIND_POOL}` 与期望表逐项相等；未知 kind → `DEFAULT_POOL` |
| `test_unknown_kind_falls_back_to_cpu` | 入队一个 `kind='nope'` → 被 CPU 池取走（不是 IO） |
| `test_cpu_pool_saturates_at_one` | 3 个慢 CPU 任务 + `cpu_threads=1` → `max_concurrent == 1` |
| `test_io_pool_concurrency` | 4 个慢 IO 任务 + `io_threads=2` → `max_concurrent == 2` |
| `test_worker_registers_and_unregisters` | `start()` 后 `online_workers()` 含自己；`stop()` 后为空 |
| `test_lease_renewed_during_long_job` | 慢 job（1.5s）跑完，期间 `heartbeat_at` 至少前进一次（用替身时钟或 TTL 设很小） |

### 7.3 集成 `tests/test_worker_recovery.py`（真子进程 + 真 kill）

**难点**：`core/config.py` 的路径是**模块级常量，不读环境变量**，所以子进程不能靠 env 指向临时库。做法：`-c` 内联引导脚本，**先打补丁再 import `app.worker`**（与 `conftest.py` 同一招）：

```python
_CHILD = r'''
import sys, time
from pathlib import Path
sys.path.insert(0, r"{backend}")
import app.core.config as cfg
root = Path(r"{root}")
cfg.DATA_DIR = root / "data"; cfg.MEDIA_DIR = cfg.DATA_DIR / "media"
cfg.INBOX_DIR = cfg.MEDIA_DIR / "audio"; cfg.LIBRARY_DIR = cfg.MEDIA_DIR / "library"
cfg.MODELS_DIR = root / "models"; cfg.DICT_DIR = root / "dict"
cfg.LOG_DIR = cfg.DATA_DIR / "logs"; cfg.DB_PATH = cfg.DATA_DIR / "app.db"
for p in (cfg.DATA_DIR, cfg.MEDIA_DIR, cfg.LOG_DIR): p.mkdir(parents=True, exist_ok=True)
from app.db import init_db; init_db()
from app.services import jobs
import app.worker as w
if "{hold}" == "1":
    w.Worker.HANDLERS = {{**w.HANDLERS, w.KIND_ASR: lambda ctx: time.sleep(120)}}
    jobs.enqueue(w.KIND_ASR, 1)
w.main(argv={argv!r})
'''
```

| 用例 | 步骤 | 断言 |
|---|---|---|
| `test_kill9_then_restart_recovers` | 子进程 A（`hold=1`）→ 等 `jobs.status=='running'`（轮询 DB，不 sleep 拍脑袋）→ `proc.kill()`（Windows = `TerminateProcess` ≈ `kill -9`）→ 子进程 B（正常 worker，`HANDLERS[asr]` 改成 `lambda ctx: None`）→ 轮询直到 `status=='done'`（超时 15s） | `attempts == 2`、`worker_id == B 的 id`、`media.status == 'done'` |
| `test_stale_running_job_is_not_double_run` | 子进程 A 跑慢 job；**不等它死**，直接手工把 `heartbeat_at` 改到 `now-300s`（模拟误判），再起子进程 B | 断言 A 的 handler 被调用次数 + B 的调用次数 == 1（A 的 `touch`/`check_alive` 失败后自杀），`media` 轴只被写一次 |
| `test_worker_unregisters_on_sigterm` | `proc.terminate()` | `workers` 表该行消失 |
| `test_orphan_worker_exits_when_parent_pid_file_gone` | 起 worker 带 `--parent-pid 999999`，`data/logs/fayelong.pid` 不存在 | 15s 内进程自行退出（`returncode is not None`） |

### 7.4 闸门脚本 `scripts/verify_worker_g3.py`

一次跑完 G3-②③ 的「人可复核」版本（真 ffmpeg/真模型可选）：

```
python scripts/verify_worker_g3.py            # 默认：test handler（快，10s）
python scripts/verify_worker_g3.py --real     # 真链路：需要 data/models + ffmpeg + 一个短素材（~2min）
```

输出格式固定为 `[PASS]/[FAIL] <断言名>`，退出码 0/1。**必须打印实际阈值**（`lease_ttl=120s`、`worker_ttl=30s`、`attempts=2`），便于复核时确认不是「因为阈值被调到 1s 才过」。

### 7.5 必须一起跑的老网（防退步）

```bash
cd backend && .venv/Scripts/python -m pytest -q                    # 期望 184 + 新增，0 failed
cd .. && node scripts/check-contract.mjs                            # 期望 34 / 42
cd .. && backend/.venv/Scripts/python.exe scripts/export_openapi.py && node scripts/check-contract.mjs
```

---

## 8. 共享知识（跨文件约定，必须完全一致）

| 项 | 约定 |
|---|---|
| **`jobs.status` 取值** | `pending` / `running` / `done` / `failed`（**不加 `cancelled`**：取消 = 删行） |
| **`jobs.kind` 取值** | `media_transcode` / `media_asr` / `media_translate` / `media_clip` / `grade_writing`（P4 预留）。**必须用 `services/jobs.py` 的 `KIND_*` 常量，禁止裸字符串** |
| **`jobs.progress` 语义** | **阶段内** 0-100。**全局**进度在 `media.progress`，用现成的 `_scale(pct, PROGRESS_*)` 映射。**两处不要混** |
| **`jobs.payload`** | JSON 文本，本阶段恒为 `{}`。读取一律 `json.loads(job.payload or "{}")`，**永不假设非空** |
| **`ref_id`** | **非空**（部分唯一索引依赖它）。本阶段 = `media.id`；`grade_writing` = `responses.id` |
| **时间** | 全部 `CURRENT_TIMESTAMP`（SQLite 的 UTC 字符串），**不在 Python 侧算时间差**；比较一律用 SQL（`heartbeat_at < datetime('now', '-120 seconds')`），避免 Python 本地时区/UTC 混用导致回收永不触发 |
| **`workers.id`** | `uuid4().hex`（64 字符列宽足够）。**不要用 `hostname:pid`**（pid 会复用，重启后旧行可能"看起来还活着"） |
| **池名** | 只有两个字符串：`"cpu"` / `"io"`（`POOL_CPU` / `POOL_IO`），**小写**，与日志/健康检查输出一致 |
| **入队 API** | 唯一入口 `jobs_service.enqueue(kind, ref_id, payload=None, priority=0)`。**禁止任何模块自己写 `INSERT INTO jobs`** |
| **`INSERT OR IGNORE`** | 它同时吞掉 NOT NULL / CHECK 违约。凡使用它的地方**必须**在 rowcount==0 时二次查询确认原因（见 T02 ②） |
| **日志** | worker 写 `data/logs/worker.log`，web 写 `data/logs/app.log`，**两个进程绝不共用一个文件**。关键节点日志手工带 `[job <kind>/<ref_id>#<id>]` 前缀（P3-5 才做全局贯穿） |
| **`FAYELONG_WEB_INPROC_WORKER`** | 三值小写：`auto` / `off` / `on`。**测试环境必须是 `off`**（`conftest.py` 强制） |
| **旧变量 `worker_threads`** | 保留字段、不再读取。任何地方都不许再引用它做容量决策 |
| **不许动** | `frontend/`、`frontend-vue/`、`scripts/verify_*.mjs`、`contracts/`、`data/`、`migrations/versions/0001_baseline.py`、`media.status` 的取值与语义、`PROCESSING_STATUSES`/`STATUS_LABEL` 依赖的全部状态串 |

---

## 9. 风险登记册（按 可能性 × 影响 降序）

| # | 风险 | 可能性 | 影响 | 缓解 | 出问题怎么回滚 |
|---|---|---|---|---|---|
| **R1** | **部分唯一索引写错**（写成普通 `unique=True`）→ 一个媒体一生只能跑一次任务，第二次上传/重试静默无效 | 中 | **致命** | T01 验收里显式断言：`PRAGMA index_list(jobs)` 能看到 `uq_jobs_active` 且 `sqlite_master.sql` 里含 `WHERE status IN`；`test_enqueue_allowed_after_terminal` 用例守住 | 0002 迁移 `downgrade` + 重做 |
| **R2** | **`test_migrations.py` 被"顺手放宽"**（把老 9 表的比对整段删掉而不是按 §6 T01 拆成两句）→ 掩盖真实结构退化 | 中高 | 高（假绿） | T01 的改法逐条对照；QA 必须看 diff，确认 `_LEGACY_TABLES` 的逐列断言**仍在** | 恢复测试文件后用真库副本重跑 |
| **R3** | **双跑**：心跳超时误判 + 回收 → 同一媒体两线程同时写 `media` | 中 | 高（数据错乱，用户看到句子重复/丢失） | §4.3 五条全实现；`test_stale_running_job_is_not_double_run` 专测 | 立即 `FAYELONG_WEB_INPROC_WORKER=off` 收敛到单执行者；再修 fencing |
| **R4** | **两个进程写 SQLite 出现 `database is locked`**（job claim + media 进度写并发） | 中 | 中（瞬时 500 / 任务重试） | T01 的 `connect_args={"timeout": 15}`；写事务保持短（每次 `db.commit()` 之间不 sleep）；进度写节流沿用现有「≥2% 才写」 | 把 `job_poll_interval_ms` 调大（500→2000）降低争抢；`job_io_threads` 降到 2 |
| **R5** | **`asr` 阶段重试重建句表** → `attempts`/`notes` 的 CASCADE 删掉用户听写记录 | 中（只在崩溃/失败重试时） | 高（用户数据丢失） | ⚠️ **这是现状既有行为**（`retranscribe` 一样），本次拆分**缩小**了影响面（剪辑/翻译阶段崩溃不再触发重建）。缓解：`stage_asr` 检测到「该媒体已有 attempts 且本次是重试（`attempts>=2`）」时**仍按现状执行但打 ERROR 日志**，不静默 | 用 `data/backups/` 还原；`scripts/fingerprint_data.py` 前后对比定位 |
| **R6** | 契约被无意改动（health 加字段真的改了 schema / 有人顺手加了端点） | 低中 | 高（G0 门禁整体失效） | T03 硬性要求加完字段立刻跑 `check-contract.mjs`；T05 把它列为门禁 | 401/500 之外的响应结构一律不进 openapi（因为无 `response_model`）→ 若发现真的变了，说明有人加了 `response_model`，改回去 |
| **R7** | **云端 2 vCPU 内存**：worker(1400M) + web(400M) 在 2GB 机器上边沿运行 | 中 | 高（OOM kill → 任务中断，虽然能恢复） | 拆分后 web 不加载模型，总占用应低于现状 1300M；`MemoryMax` 分别设死；上线后用 `systemd-cgtop` 实测一次再定稿 | 把 worker `MemoryMax` 提到 1500M / web 降到 300M；或回滚到单进程形态（`web_inproc=on` + 停 worker unit） |
| **R8** | `launcher.py` 起了 worker 但 `--silent` 下 worker 崩了没人知道 → 用户看到进度不动 | 中 | 中 | worker 崩溃时 `data/logs/worker.log` 有栈；launcher 在主循环里 poll `worker_proc.poll()`，发现退出就 `warn()` 一次（不重启，避免崩溃循环） | `auto` 模式下 web 5s 内接管 → 任务仍会完成（这正是选 `auto` 作为交付包默认的原因） |
| **R9** | 孤儿 worker（launcher 被任务管理器杀掉，`taskkill /T` 没走）持续抢任务 | 低 | 中（占内存、与重启的 worker 并存） | `--parent-pid` + `fayelong.pid` 守护线程（T02）；`/api/health` 的 `worker.count > 1` 可发现 | `taskkill /IM pythonw.exe` 或重启机器；`workers` 表 10min 后自动清死行 |
| **R10** | 历史 `jobs` 行无限增长 | 低 | 低 | 表规模在个人自用下可忽略；`ix_jobs_claim` 保证扫描成本恒定 | 定期 `DELETE FROM jobs WHERE status IN ('done','failed') AND finished_at < datetime('now','-30 day')`（手工，不做自动任务） |
| **R11** | `attempts` 上限 3 导致「长时间下载中偶尔失败」直接 `failed` | 低 | 低 | `media.error` 可读 + 前端已有「重试」按钮 | 调 `FAYELONG_JOB_MAX_ATTEMPTS` |

---

## 10. 待明确事项（需要拍板，3 条）

1. **允许修改 `backend/tests/test_migrations.py` 吗？** 新增 `jobs`/`workers` 后，该文件的 3 处硬编码（`63 列 / 8 索引 / 9 表`）与 `_BASELINE_REVISION="0001"` **必然变红**。§6 T01 给了「只拆常量、不删断言」的最小改法。**这触碰了「184 passed 不能破」的红线，需要你确认"改测试但要加强而非放宽"是可接受的**（我的判断：不可避免，因为 schema 是合法增长的；但必须留下可复核的 diff）。

2. **云端内存上限用哪组数？** 我给的初始值 `web=400M / worker=1400M`。这需要在 2 vCPU 机器上用 `systemd-cgtop` 实测一次（尤其 whisper small int8 在独立进程里的真实 RSS）。要么你先拍一个保守值，要么允许 T04 之后加一次「实测并回填数字」的子步骤。

3. **`asr` 阶段重试会重建句表 → 删掉该媒体的听写记录（R5）**。我建议**本阶段不修**（与现状一致，且拆分已缩小影响面）。如果你希望顺手修，我会在 `stage_asr` 里加「重试时按 `text_en` 精确匹配把 `attempts` 迁到新句 id」——但这会把 T03 从「搬运」变成「改业务逻辑」，需要额外 0.5 天和 2 个新测试用例。请明确选哪个。

---

## 附：施工顺序速查（给工程师的一页纸）

```
T01  建表 + 迁移 0002 + db.py timeout + 改 test_migrations   → pytest tests/test_migrations.py
T02  services/jobs.py + worker.py + tasks 双池 + config + logging → pytest tests/test_jobs.py tests/test_worker_pools.py
T03  media.py 拆 stage + main.py lifespan + api/media.py + health → pytest -q（必须 184 全绿，test_media_flow 零改动）
T04  launcher + bat + systemd 两 unit + deploy README      → launcher --check / systemd-analyze verify
T05  test_worker_recovery.py + scripts/verify_worker_g3.py  → pytest -q + check-contract + verify_worker_g3
T06  打包链回归（P3-6，可后置）                            → build.ps1 -NoZip
```

**每一步做完立刻跑一次 `pytest -q`**，不要攒到最后 —— 本仓库历史上最大的失败模式就是「先都写完再一起调」。

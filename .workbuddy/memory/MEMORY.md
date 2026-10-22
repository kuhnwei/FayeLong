# FayeLong 英语学习网站 — 项目记忆索引 v4（2026-10-16）

> ⚠️ `MEMORY.md` 受 3,000 字符/会话写入上限约束，只放**高频锚点**。
> **完整项目档案见同目录 `PROJECT-NOTES.md`（算法判据 / 环境坑 / 云端流程 / ADR 决策全在里面，开工前先读它）**；逐日操作见 `YYYY-MM-DD.md`。

## 定位
个人自用、**零付费依赖**的英语精听/听写站。FastAPI(单端口 8000，同时托管前端) + React/Vite SPA。ASR=本地 faster-whisper small；翻译=有道 aidemo→MyMemory 免费在线；词典=ECDICT 全量。**唯一数据根 = `data/`，拷贝即迁移。**

## 现状
- 版本 **v1.16.1**（`cb89281`），分支 `main`，本机可直连 GitHub。
- 后端 `backend/app`：11 个 api 模块 / **42 个 REST 端点** / 9 张表。前端 `frontend/src`：**22 个 ts(x) / 7,564 行**。
- 云端 http://114.132.173.241/（腾讯云轻量 2vCPU·2GB，**2026-11-14 到期未自动续费**）；`ssh -i ~/.ssh/fayelong_deploy root@114.132.173.241` 可用（`ubuntu@` 不行）。

## 正在执行
**REFACTOR-PLAN-001**（`docs/REFACTOR-PLAN-001-执行计划.md`，施工文件，按闸门 G0→G5 推进）：
前端 React→Vue3 全量重写（新建 `frontend-vue/`，**不覆盖 `frontend/`**）+ 后端架构债（Alembic / jobs+worker / CPU-IO 分池 / 测试网 / health 扩展）+ 题型插件化 + IELTS 新表族。**后端不换语言**。
- 2026-10-20 进度：**前端链 P0–P2 + 后端 P3 全部完成，G3 四项判据达成**（均经 QA 独立复核）。`frontend-vue/src` **7,895 行**，5 条路由全可用；后端 **278 passed / 1 skipped**、契约 34/42 不变。**下一步：P4 题型插件化 + IELTS 数据模型**。
  - ⭐ **P3-4 分层原则**：`api/media.py` 682→420，新增 `services/media_ops.py` 承载**请求侧**领域动作；**不要**并进 `services/media.py`（那是 worker 热路径，4 stage + fencing，跑在 CPU/IO 池，两者失败语义不同）。
  - ⭐ **job_id 日志**：`ThreadPoolExecutor.submit` **不传播 contextvars** → 必须**在执行线程内部** `with job_log_context(...)`，不能在提交侧 `copy_context()`；`Filter` 要挂在 **handler** 上（logger 的 filter 不管子 logger 的 propagate）。
  - 🔴 **打包三坑**：① embeddable Python 的 `_pth` 隔离模式**忽略 `PYTHONPATH`** → `python -m app.worker` 在包里起不来，须用 `packaging/worker_entry.py`（`runpy`）；② 两进程首启 `create_all` 非原子 → `_create_all_tolerant` 重试 `already exists` + `readonly/locked` 两组；③ **改过的文件不能直接 `cmp`**（build.ps1 对 txt 做占位符+CRLF、对 bat 做 CRLF）。
  - P2-E/P2-F 实测：`verify_vocab_practice` **29/29**（⚠️ 脚本里 `record(` 出现 32 次，**真实断言 29 条**，别按 32 记账）、`verify_mobile` **36/36**、`verify_m4` 由 9/12 → **12/12**（证明 P2-D 那 3 项失败归因成立）。
  - **前端链验收的成熟套路（照抄即可）**：隔离后端 `scripts/run_isolated_backend.py --port 8010` + `FAYELONG_API_TARGET=http://127.0.0.1:8010 npm run dev`(5174) + `node scripts/verify_x.mjs --url http://localhost:5174`（**脚本零改动**，靠 `data-*` 属性驱动）+ 收尾比对内容指纹。**旧套件能直接打 Vue 版，是因为迁移时刻意保持 className/data-* 逐字一致。**
  - ⭐ **P3-2 三条不可回退的设计**：`process_media` 拆 4 个 stage job（否则 CPU 池被翻译 IO 占死，G3-③ 不可能通过）；崩溃恢复判据 `租约超时 OR worker 不在线`；web 三态 `WEB_INPROC_WORKER=off|auto|on`。
  - ⭐ **fencing 必须用 claim 时快照**（`_fence()` 返回 `SimpleNamespace`），**media 轴也要同一张 fence**；不能用 `db.get(Job)` 的当前归属、不能给 `fresh.attempts` 赋值（ORM dirty 会 flush 坏计数器）。
  - ⚠️ G3-③ 断言**只在 CPU 池=1 有判别力**；`os.cpu_count()` **不识 cgroup**，云端必须显式配 `JOB_CPU_THREADS=1`。
- ⭐ **数据安全不变量**：一律用**内容指纹** `python scripts/fingerprint_data.py`，基线 `TOTAL 278bcd28…6b13104c90ff4d32dad697f3b4f`；**文件 md5 不可靠**（真实登录会写 `users.last_login_at`）。
- ⭐ 新基建：`scripts/run_isolated_backend.py`（隔离后端，默认 8010，**破坏性验证必须跑它**）+ `session.mjs` 铸牌免登录（零写库）。
- 计划偏差累计 7+ 处（记录在 `PROJECT-NOTES.md` §14 与计划 §3 偏差块），最关键三条：**没有 /login 路由**（登录是 App 层门禁）；**必须搬样式**（tailwind 的 theme.extend 是空的，样式 99% 靠 className）；**5174 必须配 Vite 代理**（后端 cors 只认 5173）。
- ⚠️ 配额：工程师 worker 曾 429（到 21:32 UTC+8 重置）；期间主理人直接实现 P2-C。

## 地盘与命令
- 解释器 `backend/.venv/Scripts/python.exe`（3.13.14）；Node 22.22.2。**pip 用阿里云源**；**npm 必须 `--ignore-scripts`**。
- 端到端验证 `node scripts/verify_*.mjs`（**必须 Node 22**，无头 Chrome + CDP）。**改完前端源码必须 `vite build` 再验。**

## 三条铁律（历史高频事故）
1. **`data/app.db` 是唯一真实数据** —— 测试/脚本绝不直接触碰，要测就用副本。
2. 听写判定**只在服务端**；隐藏内容**不进 DOM**（防 F12）。
3. 学习页布局**严禁 `calc(100vh - Npx)`**；触摸目标统一 32px；外壳用 `h-dvh` 三段式。

## 别改回去的点
登录守卫=**中间件默认拒绝**（`/api/auth/*`+`/api/health` 豁免，前端静态资源不拦）；词典**三级优先**查询（`word=` → `sw= AND word NOT LIKE '%-%'` → `sw=`）；marks 记**词序**不记文字、**改写原文即清空**；生词练习 `isSpelling = mode !== 'en2zh'`；「下一题」按钮**不能加 autoFocus**；朗读不缓存空 `getVoices()`。

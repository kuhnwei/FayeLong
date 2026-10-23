# FayeLong 精听 — 项目记忆索引 v4（2026-10-16）

> ⚠️ `MEMORY.md` 受 3,000 字符/会话写入上限约束，只放**高频锚点**。
> **完整项目档案见同目录 `PROJECT-NOTES.md`（算法判据 / 环境坑 / 云端流程 / ADR 决策全在里面，开工前先读它）**；逐日操作见 `YYYY-MM-DD.md`。

## 定位
个人自用、**零付费依赖**的英语精听/听写站。FastAPI(单端口 8000，同时托管前端) + React/Vite SPA。ASR=本地 faster-whisper small；翻译=有道 aidemo→MyMemory 免费在线；词典=ECDICT 全量。**唯一数据根 = `data/`，拷贝即迁移。**

## 现状
- 版本 **v1.16.2**（多用户 + admin 管理），分支 `main`，本机可直连 GitHub。
- 后端 `backend/app`：12 个 api 模块 / **48 个 REST 端点**（+`/api/admin/*` 7 个 + marks 独立端点）/ 19 张表（+sentence_marks）。前端 `frontend-vue/`（Vue3）。
- **多用户**：媒体库全站共享（admin 上传）；普通用户仅 admin 创建；删除=软删除；admin 账号迁移后自动建（`services/bootstrap.py`，随机密码打印控制台）；user_id 外键**刻意 NO ACTION**（SQLite ALTER 无法表达 ondelete + 软删除策略）。
- 云端 **https://fayelong.com.cn/**（2026-10-23 起 HTTPS；腾讯云轻量 2vCPU·2GB，已续费；**Python 3.12** — 与本地 3.13 不同）；裸 IP http://114.132.173.241/ 会 301 到域名。`ssh -i ~/.ssh/fayelong_deploy root@114.132.173.241` 可用（`ubuntu@` 不行）。
  - ⭐ **HTTPS 口径**：服务器是 **Caddy 2.11.4，没有 nginx / certbot，以后也不要装**。站点地址写域名即自动签发+自动续期（走 LE ARI 建议窗口，无 cron/timer）。云防火墙须放通 **TCP 443 + UDP 443**（UDP 是 HTTP/3，Caddy 默认发 `Alt-Svc: h3`）。详见 `deploy/README.md` §十二。

## 正在执行
**REFACTOR-PLAN-001**（`docs/REFACTOR-PLAN-001-执行计划.md`，施工文件，按闸门 G0→G5 推进）：
前端 React→Vue3 全量重写（新建 `frontend-vue/`，**不覆盖 `frontend/`**）+ 后端架构债（Alembic / jobs+worker / CPU-IO 分池 / 测试网 / health 扩展）+ 题型插件化 + IELTS 新表族。**后端不换语言**。
- 2026-10-22 进度：**重构全部完成并已上线**。前端链 P0–P2 + P3 + P4 + P5 全绿（均经 QA 独立复核）。本地 **378 passed / 1 skipped**、契约 **41/49**；云端 http://114.132.173.241/ 已跑 **Vue 版**，`fayelong` + `fayelong-worker` 双服务 active、`worker.mode=external`、写作批改 `off`（零付费降级）。
  - 🔴 **云端是 Python 3.12、本地是 3.13** —— 凡涉及 CPython 内部行为的改动（线程 / contextvars / asyncio），**本地全绿 ≠ 云端能跑**。踩过的实例：`_PoolRunner` 把停止信号命名 `self._stop`，与 `Thread._stop()` 冲突，3.12 的 join 收尾会调用它 → `TypeError: 'Event' object is not callable`，worker 一 stop 就崩；3.13 已移除该调用。已改名 `_stop_event` + 加结构性守卫。
  - ⭐ **云端部署口径**：库无 `alembic_version`、只有 8 表、venv 无 alembic → **不走迁移**，靠 `init_db()` 的 `create_all` + `_ensure_columns` 自愈（实测 18 表齐、旧表行数零漂移）。worker unit **必须先装再跑 update.sh**。
  - ⭐ **回滚**：**旧 React 源码已于 2026-10-22 从仓库删除**（保留在 tag `frontend-react-final`）。回滚 = 从 tag 重建产物并置于 `STATIC_CANDIDATES` 首位；云端可直接用 `/opt/fayelong/.backup/dist-20261022-145723`（现成旧构建）。
  - ⭐ **P5 双跑**：7 脚本 × React(5173)/Vue(5174) = 193=193 零分歧；⚠️ 旧 React 的 vite 代理**写死 8000**，隔离后端必须占 8000，否则打真实库。
  - 🔴 **判产物来源不能用 `id="app"`** —— 两套 `index.html` **都是 `id="root"`**。正确判据：逐文件 md5 全等 + `__VUE__` 命中/`react.production` 为 0 + 旧 bundle 404。
  - 🔴 **版本库**：`frontend-vue/`、`tests/`、`migrations/`、`contracts/` 此前全 untracked（两周无基线），已补 6 个提交。**阶段结束必须 commit。**
  - ⭐ **P4 题型插件**：`services/question_types/` + `GET /api/question-types`（实时读注册表）；前端 `src/question-types/` 三级降级；`<component :is>` 在 `SentenceStage.vue`（不是 StudyPage，上移威胁 `verify_mobile`）。
  - 🔴 **answer 铁律三重力证**：schema 无该字段 + 白名单挑字段 + `SECRET-*` 串断言；`report` **必须按 `submitted_at` 设闸**（领域层 409），`ResponseOut` 已删 `detail` —— 判分明细只经 report。
  - ⭐ **IELTS 迁移口径**：`0003` 只 `CREATE`；18 表/131 列/20 索引/11 外键；老库副本升级后**老 9 表逐表哈希不变**（TOTAL 必变，别拿 TOTAL 当证据）；**「只回退本批」用 `downgrade 0002`，不是 `downgrade base`**。
  - ⭐ **写作批改默认降级**：`FAYELONG_GRADING_PROVIDER=off` ⇒ 零付费离线可用，`degraded` 是成功态；缓存不存降级结果；`ungraded ≠ degraded`。
- ⭐ **多用户改造（2026-10-23 完成，v1.16.2）**：详见 `2026-10-23.md`。关键坑：① `user_id` 必须声明在**表末尾**（ALTER 加列尾 vs create_all 模型顺序，否则迁移零差异断言红）；② 唯一约束用**显式 `Index(unique=True)`** 不用 UniqueConstraint；③ token 加 `ver`（token_version）实现软删/改密/停用即时失效；④ `test_auth` 清 users 前先清带 user_id 外键的子表；⑤ conftest `db_session` 依赖 `app_client` 触发 init_db。**后端 413 passed**。
- ⭐ **数据安全不变量**：一律用**内容指纹** `python scripts/fingerprint_data.py`，基线 `TOTAL 278bcd28…6b13104c90ff4d32dad697f3b4f`；**文件 md5 不可靠**（真实登录会写 `users.last_login_at`）。
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

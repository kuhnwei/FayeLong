# FayeLong 英语学习网站 — 完整项目档案

> 原名 `MEMORY.md` v3（2026-10-15）。因 `MEMORY.md` 有 3,000 字符/会话写入上限、注入时被截断，
> 现将**完整档案**移入本文件，`MEMORY.md` 只保留高频锚点索引。开工前先读本文件。

## 1. 定位与架构
个人自用、可联网、**零付费依赖**的英语精听/听写站。交付目标：**无开发环境的 Windows 笔记本（8GB）**，小白式安装（拷文件夹 → 双击启动 → 用浏览器）。
- 前端 React+TS+Vite+Tailwind（SPA）；后端 FastAPI(Uvicorn) **同时托管前端静态文件**，单端口 8000。
- ASR **必须本地** faster-whisper `small`（int8，带时间戳）——没有免密钥的免费在线 ASR。
- 翻译：免费在线 **有道 aidemo → MyMemory 回退**，结果写 `translations` 表缓存。
- 词典：**ECDICT 全量**（`data/dict/ecdict.db`，340 万条 / 811.9 MB）+ 词形还原。
- 转码/切片：ffmpeg/ffprobe **便携版随包分发**（`tools/ffmpeg/`）；视频**只取音轨**（`-vn`），原始文件保留。

## 2. 数据目录（唯一运行时数据根 = 项目根 `data/`，拷贝它即完成迁移）
- `data/app.db`（SQLite 9 表：media / sentences〔含 `marks`〕 / attempts / notes / vocab / settings / translations / users）
- `data/media/audio/`＝**收件箱**（用户投放素材）；`data/media/library/<id>/`＝`original.<ext>` + `audio.wav`(16k 单声道) + `clips/`
- `data/models/`、`data/dict/`、`data/logs/`、`data/backups/`
- `.gitignore` 覆盖 app.db / library / models|dict|logs；`data/media/audio/*` 忽略但留 `.gitkeep`
- ⚠️ **`data/app.db` 是唯一真实数据**，任何测试/脚本一律不得直接读写它（要测就用副本）。

## 3. 里程碑
**M0–M6 全部完成**（2026-10-11）：M1 导入播放 → M2 识别翻译 → M3 单句听写 → M4 词典/生词本/笔记 → M5 打磨 → M6 打包交付。
交付链：`packaging/build.ps1` 一条命令出包（内置 Python 3.13.14 embed + 全依赖 + 便携 ffmpeg + VC++ DLL + whisper small + ECDICT），构建期强制 `launcher.py --check`。
- **v1.9/v1.10** 生词朗读 + 练习三模式（中译英 / 英译中四选一 / 单词听写），**纯前端**。
- **v1.11** 静默启动（`pythonw.exe` 无窗口）+ 就地更新（`更新 FayeLong.bat` 只换程序不碰 `data/`）。
- **v1.12** 登录门禁 + 学习页一句一页。**v1.13** 移动端自适应（`h-dvh` flex 外壳）。
- **v1.14** 听写区四改（输入框/译文字号、去掉「上次」后的历史文本、下一句按钮）+ **原文「易听错」标记**。
- **v1.15** 媒体库**单层分类**：分类 CRUD + 归类/批量移动 + chips 筛选 + 按类导入（新增 `api/categories.py`、`categories` 表）。
- **v1.16** 听写历史展开即对照（历史提交内容 + 词级错误点 + 高频错误词汇总）。**v1.16.1** 修手机端顶部信息条被压成竖排单字。
- 体量：全量 zip ≈ 816 MB / 解压 1.72 GB（目标机需 ≥3GB 空闲）；`-Light` 轻量包 487.4 MB。

## 4. 关键算法与判据（改动需谨慎）
### 词典三级优先（`services/dict.py::_query`）
**不可只按 `sw` 查**：ECDICT 有「音节拆分条目」（`hel-lo`/`chil-dren`），只查 `sw` 会命中错条目。
① `word = ?` → ② `sw = ? AND word NOT LIKE '%-%'` → ③ `sw = ?`；排序 `collins DESC, frq DESC`。
词形还原：exchange 含 `0:` → 用原型再查（`via=exchange`）；否则 lemminflect+规则候选，**候选必须能命中词库**才采用。

### 听写判据（**服务端唯一判定**）
归一化 `’→'`、忽略大小写与标点，只留 `[0-9a-z']`；正确率 = 正确词数 / 标准答案词数（**多写词不进分母**）；
`is_correct = 正确率 ≥ 100 且 extra == 0`；`attempts` 只追加、**词级明细不落库**；`mastered` = 曾出现过一次 `is_correct`。

### 状态机 `media.status`
`pending → transcoding → ready → asr → translating → clipping → done | failed`；进度区间 0-20 / 20-70 / 70-90 / 90-100。
启动 `requeue_unfinished()` 自愈。前端常量在 `api/client.ts`：`PROCESSING_STATUSES` / `PLAYABLE_STATUSES` / `STATUS_LABEL`。

### 原文「易听错」标记（v1.14）
`sentences.marks` = JSON 闭区间数组 `[[起始词序, 结束词序]]`（0 基，**记词序不记文字**：句中同词重复只有下标唯一；分词正则与前端 `ClickableText` 一致）。
`services/marks.py`：`word_count`/`load`/`dump`。分工不同（**别搞混**）：
- `load`（读 DB 的 `marks` TEXT 列，**真正的脏数据入口**）→ 非法 JSON/非数组/非二元组/非整数/bool **一律安全返回无标记**，只排序不归并。
- `dump`（**唯一入口 `api/sentences.py:157`**）→ **归并（重叠/相邻闭区间合并）+ 夹取（越界裁剪）**；只防御「长度≠2 / 非整数」，**不防御不可迭代元素**。这不是缺陷：它收到的始终是 Pydantic 已校验的 `list[list[int]]`（`schemas/media.py:139 SentenceUpdate.marks`），`[[0,1],5]` 在进 `dump` 前就被判 422。

**原文改写会漂移 → `PATCH text_en` / 拆分 / 合并一律清空 marks。**

## 5. 已确认决策
1. 前端 + 轻量后端本地部署 / 全免费 / 数据本地 SQLite / 字典=浮层 + 跳转牛津朗文。
2. 已适配移动端（手机 / iPad）｜ 单账号登录门禁 ｜ 视频仅取音轨 ｜ 每句切片 ｜ 导出 Markdown。
3. 交付=全量包（自带 Python 运行时）｜ 翻译=免费在线（**废弃 NLLB/PyTorch**：+2.5GB 不可接受）｜ 目标机 8GB。
4. ffmpeg 随包分发 ｜ 允许联网，但依赖服务必须免费。
5. 听写判定**只在服务端**（避免两套 diff 漂移）｜ 隐藏内容**不渲染进 DOM**（防 F12）。

## 6. 目录约定
- `backend/app/`：`main.py`（异常处理器 + 登录守卫中间件 + lifespan）；`api/`：health/auth/media/**categories**/sentences/attempts/dict/vocab/notes/stats（**11 模块 / 42 端点**）；
  `services/`：media/asr/clip/translate/dictation(纯函数)/study(统计)/dict/marks/auth；`core/`：config/paths/tools/files(Range)/tasks/logging；
  `models/entities.py`、`schemas/`、`db.py`。笔记汇总导出挂 `api/media.py`：`GET /api/media/{id}/notes`、`.../notes/export`。
- `frontend/src/`（22 个 ts(x) / 7,564 行）：`pages/`(StudyPage〔含 DictationBox/ClickableText/SentenceStage〕、MediaLibraryPage、VocabPage、VocabPracticePage、LoginPage)；
  `components/`(Layout/PlayerBar/icons/DiffResult/WordPopover/NoteEditor/NotesPanel/ErrorBoundary)；`hooks/useClipPlayer.ts`、`api/client.ts`、`store/player.ts`、`utils/{format,speech}.ts`。
- `scripts/`：`dev.bat`、`start-backend.bat`、`start-frontend.bat`；CDP 端到端验证 `verify_m4`/`verify_m5`/`verify_v1_12`/`verify_mobile`/`verify_vocab_practice`/`verify_marks`/`verify_category`/`verify_attempt_history`/`verify_logo`；
  `lib/session.mjs`（登录：Node fetch 打补丁带 Cookie + CDP `Network.setCookie`；默认账号 `faye`/`FayeLong2026`）。**必须 Node 22**（Node 20 无全局 `WebSocket`）。
- `packaging/`：`build.ps1`（10 步；`-Light`/`-FromPip`/`-NoZip`/`-Force`；**带 UTF-8 BOM**；依赖复用 `backend/.venv`）、`launcher.py`、`update.py`、`bootstrap.py`、`zipdir.py`、`build-update.ps1`、`files/`。
- `docs/`：`ADR-001-技术栈选型与重构决策.md`、`REFACTOR-PLAN-001-执行计划.md`、`media-category-spec.md`。
- 开发地址：后端 http://127.0.0.1:8000/docs、前端 http://localhost:5173。

## 7. 环境事实与踩坑（通用，高频）
- 本机 Python **3.13.14 可直接跑 faster-whisper**（1.2.1 / ctranslate2 4.8.2 / onnxruntime 1.31.0），不必退回 3.11；Node 22.22.2。
- pip 源用**阿里云**（清华对 faster-whisper wheel 403）；**npm install 必须 `--ignore-scripts`**（esbuild postinstall 在托管 node.exe 上 EBUSY）。
- 下载源：ffmpeg 走 npmmirror（gyan.dev 11KB/s）；whisper 模型走 `hf-mirror.com`；GitHub 大文件加 `https://ghfast.top/` 前缀（直连慢且 Range 续传 502）。
- 本环境 **PowerShell 工具不回传 stdout**；`Add-Type`/`cscript` 被拦；会话默认执行策略 `Restricted`。
- **Bash 里 `&` 起的后台进程随调用结束被杀** → 常驻服务必须 `run_in_background`，用完主动停。别误杀 WorkBuddy 自身 node.exe。
- Git Bash：curl 的 `-w "/..."` 被 MSYS 路径转换搞坏（别以 `/` 开头）；`chmod` 对 NTFS 无效；`rm` 被 safe-delete 拦截时 **FAIL_CLOSED 并中断 `&&` 链**。
- ffmpeg `-progress` 的 `out_time_ms` 单位是**微秒**。「改了代码行为没变」→ 先查端口残留（旧 uvicorn 占端口让新实例静默失败）。
- `fastapi.testclient.TestClient` 需要 **httpx**；本机 venv 里只有 `httpx2`（≠ httpx），要用测试客户端必须另装。

### 真机 UI 验证（无头 Chrome + CDP，Node 22 内置 WebSocket，无需 Puppeteer）
- ① 每次换新 `--user-data-dir`（残留 chrome 锁 profile → 新实例即退）；② Chrome 必须**在同一条 Bash 命令内**「启动→测试→收尾」；
  ③ 校验输入框用 `el.value`（textarea 文本不在 DOM 文本节点）；④ 工具输出 >约 30KB 转存文件，Read **截断 >2000 字符的行**。
- **`Runtime.evaluate` 加 `returnByValue` 时返回值不能是 DOM 节点或 window** → `Object reference chain is too long`。修法：辅助脚本末尾 `return true`。
- 注入页面脚本用 `const` 重复声明会 SyntaxError → 包 IIFE 挂 `window`。React 重渲染异步 → 点击后必须 `waitFor`。
- **CDP 脚本的类务必写 `close()`**，`finally` 逐项 try/catch：否则 Chrome 成孤儿、WebSocket 吊住 Node → 脚本永不退出。
- **改完前端源码必须 `vite build`（产物落 `frontend/dist`）再跑浏览器验证**，否则读到旧 bundle。

## 8. 必须自己写、不能靠框架的三处（易复发）
- **embed Python `python313._pth` 是 isolated 模式**：`sys.path` 由该文件完全决定，**`PYTHONPATH` 被忽略**，必须写 `import site`。
- **VC++ 运行库**：embed 版有 `vcruntime140*` 但**无 `msvcp140` 系列**；`ctranslate2.dll`/`onnxruntime.dll` 都需要 → 从 `System32` 拷 5 个到 `runtime/python/`。
- **SQLite 无迁移框架**：`create_all` **只建新表不加列** → 加列必须自己写幂等 `ALTER TABLE`（见 `db.py::_ensure_columns` / `_ADDED_COLUMNS` / `_INDEXES`）。
- **`core/config.py` 的路径是模块级常量**（`DATA_DIR`/`DB_PATH`/`LIBRARY_DIR`… 由 `__file__` 推导，**不读环境变量**）→ 测试要重定向数据目录，必须在 import `app.db` 之前打补丁（`db.py` 在 import 时就 `create_engine(DB_PATH)` 并绑定）。
- 其余打包坑（`SO_REUSEADDR` 误判、zip 中文名要用 `zipdir.py`、PyInstaller 不适用、staging 删不掉就改名保留）见 `2026-10-11.md`。

## 9. 已在 v1.9~v1.16 定下的、别改回去的点
- **移动端布局**：`Layout` = `flex h-dvh flex-col overflow-hidden`，三段 header(`shrink-0`)/main(`flex-1 min-h-0 overflow-y-auto`)/PlayerBar(`shrink-0`)；
  学习页只写 `h-full`，**严禁 `calc(100vh - <像素>)` 魔法数字**（旧版 109/197px 就是被手机顶栏换行搞坏的）。触摸目标**统一 32px**，不按屏宽分档。
  坑：`justify-center` + `overflow` 会顶出顶部内容 → 内套 `min-h-full`。
- **登录门禁**：单账号（`users` 一行，全局共用数据）；密码 **PBKDF2-HMAC-SHA256**（标准库 `hashlib.pbkdf2_hmac`，零新增依赖，见 `services/auth.py`）；
  会话是 **HMAC-SHA256 签名 cookie**，密钥存 `settings.auth.secret`（随 `data/` 迁移）；
  守卫是**中间件**（`main.py::guard_api`，除 `/api/auth/*`+`/api/health` 外未登录 401，**默认拒绝**）；**前端静态资源不拦**。
- **生词练习**：纯前端只吃 `GET /api/vocab`；用 `isSpelling = mode !== 'en2zh'` 分流；中译英填原型也算对；英译中四选一而非手输。
- **朗读** `utils/speech.ts`：音色 `en-US`→`en-GB`→`en-*`；**Chrome `getVoices()` 首次常返回空数组 → 不能缓存空结果**。
- **`Enter` 双触发坑**：「下一题」按钮**不能加 `autoFocus`**。
- 更多细节（A-B 循环、笔记导出、`input()` 在 pythonw 抛 `RuntimeError`、增量更新要比内容不比大小、`install.txt` 必须 UTF-16）见 `2026-10-11.md`。

## 10. 已验证可用的免费服务
- **有道 aidemo**【主力】：`POST https://aidemo.youdao.com/trans`，form `q/from=en/to=zh-CHS` → `translation[]`，`errorCode=="0"`。
- **MyMemory**【兜底，配额有限】：`GET https://api.mymemory.translated.net/get?q=..&langpair=en|zh-CN` → `responseData.translatedText`。
- 实测**不可用**：Google gtx（墙）、腾讯 TranSmart（需 token）、LibreTranslate 与 Lingva 各镜像、Edge auth、有道 fanyi 网页接口。

## 11. 云端部署（腾讯云轻量，2026-10-14 上线）
**http://114.132.173.241/** —— 源码原生部署，与本地 Windows 交付包是**两条独立路线**。实例 `lhins-a0s35jwt` / Ubuntu 24.04 / 2vCPU·2GB；
⚠️ **2026-11-14 到期、未开自动续费**。同机共存 **Hermes Agent**（`/home/ubuntu/.hermes`，勿碰）+ Caddy(`:80`)。
- ⭐ **登录通道**：`ssh -i ~/.ssh/fayelong_deploy root@114.132.173.241` **可用**；**`ubuntu@` 会 Permission denied**，直接用 root。
- ⚠️ **站点是走登录门禁的**（无 cookie `GET /api/media` → 401），并非「公开免登录」。云端账号密码在用户手里，本地默认测试号只对本地库有效。
- 跨平台零改动的关键：`config.py` 路径全由 `__file__` 推导，靠 `backend/requirements.txt` 判定形态 → 服务器排成 `/opt/fayelong/backend/requirements.txt` 即自动得 `ROOT_DIR=/opt/fayelong`。
  服务 `fayelong.service`：`User=root`、`WorkingDirectory=/opt/fayelong/backend`、`/opt/fayelong/venv/bin/uvicorn app.main:app --port 8000`，`FAYELONG_*` 全在 unit 里注入。
- **上线流程（可复用，已跑通 v1.12~v1.16）**：本地 Python `tarfile` 打包（**只含 `backend/app` + `frontend/dist`，排除 `__pycache__`/`.pyc`**）
  → scp 到 `/tmp` → 服务器备份 `data/backups/{app-<tag>-<ts>.db, code-…tar.gz, web-…tar.gz}` → `systemctl stop fayelong`
  → `rm -rf frontend/dist/assets`（清旧 bundle）→ `tar -xzf -C /opt/fayelong` → 清 `__pycache__` + `chown -R root:root` → `systemctl start` → 验证。
  **`data/` 全程只读不覆盖。** 服务器只有 1 个媒体（114 句），本地 4 个 —— 差异是有意的。
- 验证套路：`PRAGMA table_info` 查列 / **公网拉取 bundle 与本地比 md5**（等价于「线上跑的就是本地验过的那份」）/ `journalctl -u fayelong` 查 error。
- 压缩用 Python `lzma`（本机**没有 xz 二进制**）。MCP `execute_command` **单条 ≤2048 字符**且**凡涉及 `/root/.ssh`、`sshd_config`、`/etc/caddy/Caddyfile` 一律 AccessDeny**（不能注公钥）—— 有 `fayelong_deploy` 私钥就别用它。
- 遗留：软 404（`/robots.txt` 被 SPA 回退成 200+HTML）、无 meta/robots/sitemap、单 worker 串行、无 HTTPS。细节见 `2026-10-14.md`。

## 12. 库内媒体与遗留事项
- 库内媒体：1/2/3 为自造示例（可随时删），4=C4T1S1（106 句）。素材来自百度网盘，由用户放入 `data/media/audio/`。
- ⭐ **本机能直连 GitHub**（`git push origin main` 成功，走系统凭据助手）—— 旧记忆里「本机连不通 GitHub」已作废，以后直接 push。
- 建议补 `.gitattributes`（`core.autocrlf=true` 下 `*.sh text eol=lf`）。
- ⚠️ **完整交付 zip 与更新包都已过期**（`dist/FayeLong-v0.1.0-win64.zip` 产出于 M6，不含 v1.9+）；要带上需重跑 `packaging/build.ps1`（约 4 分钟）。
- 后续可选：代码签名 / 分卷压缩 / 首次运行向导；练习记录落库、按记忆曲线加权抽题、错题自动标记、中文释义朗读。

## 13. ⭐ 技术栈决策（ADR-001，2026-10-16 已采纳并锁定）
用户曾考虑趁早期版本全栈重构（他主力 Java + Vue，现为 Python + React）。**结论：不全栈重构。**
- **前端 React 18 → Vue 3 全量重写**（做）。趁 UI 面小；新建 `frontend-vue/`，**不覆盖 `frontend/`**，切换后旧版打 tag `frontend-react-final` 冻结。
- **后端保持 Python/FastAPI（不换 Java）**。理由：实测后端第三方依赖**只有 5 个**（fastapi/uvicorn/sqlalchemy/pydantic-settings/python-multipart），其余全标准库；**语言锁定点只有 ASR 一处**（faster-whisper/ctranslate2 无 Java binding）→ 换 Java 必然引入 Python sidecar，技术栈从 2 涨到 3 且双运行时，「单一技术栈」目标不可达。
- **后端架构债 5 项**（比换语言重要）：① 引入 **Alembic**（现在 9 张表是最便宜时机）② **`jobs` 表 + 独立 `worker.py`**，`requeue_unfinished()` 泛化为 jobs 崩溃恢复 ③ **CPU 池(ASR/ffmpeg) 与 IO 池(翻译/LLM批改) 分池** ④ 测试网（**原零单测**：pytest 覆盖 dictation/dict/marks/study 纯函数 ≥90% + FastAPI TestClient）⑤ health 扩 jobs 积压/模型就绪/磁盘余量。
- **IELTS 走新表族**（`papers/sections/passages/questions/practice_sessions/responses`），`answer`/`detail` 用 **JSON 列**；**旧 media/sentences/attempts 零迁移**，听写降为 `type='dictation'` 的题型之一。
- **题型插件契约**：`QuestionType{code, grade_mode: sync|async, validate, normalize, grade/grade_async}` + `GET /api/question-types` 下发防前后端漂移。
- **Q6 锁定**：云端 2GB **不升配**；写作批改**调外部 AI**（本项目**唯一付费点**，与「零付费」定位冲突，开工前需再确认）。强制：判分走 jobs/IO 池**同步不阻塞**、结果**按 sha1 缓存防重复付费**、外部挂了**降级为参考范文**不得阻塞交卷、API Key 只走 `FAYELONG_*` 环境变量。
- **实测规模（别重新统计）**：后端 42 py / **5,739 行**；前端 22 ts(x) / **7,564 行**；**42 个 REST 端点**；**9 张表**；60 组件定义 / 635 处 className / 96 处 react-query 调用点。
- **Vue 迁移可免费复用约 1,300 行（17%）**：`client.ts` 类型部分（改自动生成）、`icons.tsx` 465 行 SVG、`utils/*` 113 行；`useClipPlayer` 是原生 `HTMLAudioElement` API，**与框架无关可逐行照搬**；`zustand→Pinia` 1 个 store 88 行；`react-query→vue-query` 同 @tanstack 家族。
- **文件**：`docs/ADR-001-技术栈选型与重构决策.md`（决策）+ `docs/REFACTOR-PLAN-001-执行计划.md`（施工，P0–P5 + 闸门 G0–G5 + 回滚）。

## 14. REFACTOR-PLAN-001 执行记录
### 计划偏差（已发现，勿再踩）
1. 计划 §2 G0 / §3 P0-1 写「含全部 **35** 个端点」→ 这是 **v1.14 时期的旧基线**。实测（`frontend/dist` 存在时）= **34 个 path / 42 个 operation**（v1.15 媒体库分类、v1.16 历史对照未计入）。基线一律以**实际导出结果**为准。
2. 计划 §3 P0-4 写「conftest 覆写 `FAYELONG_*` 环境变量指向 tmp」→ ❌ 本代码库**不可行**。正确做法：conftest **模块顶层**、在任何 `app.*` import 之前用 `setattr` 把 `app.core.config` 的 8 个路径常量重指向 `tempfile.mkdtemp()`。另：`tmp_path_factory` **不可用**（fixture 在收集期之后才可用，而 `db.py` 在收集期就建了 engine）。
3. OpenAPI 有**环境相关**差异：`main.py` 末尾 SPA 回退路由 `/` 仅在 `frontend/dist` 不存在时注册且未排除出 schema → 删 dist 会凭空多 1 个 operation。`scripts/check-contract.mjs` 对此**显式打印式容忍**。
4. 计划 §P0-2 验收要求找 `MediaItem`/`SentenceItem` → **后端没有这两个名字**，实际是 `MediaOut`/`SentenceOut`（那是旧前端的手写类型名，见 `frontend/src/api/client.ts:131/150`）。P1-2 前端改用生成的 d.ts 后应同步替换。
5. 计划 §P1-3 写「5 条路由照搬含 `/login`」→ ⚠️ **根本没有 `/login` 路由**。登录是 `frontend/src/App.tsx` 层的**状态门禁**（未认证时整屏渲染 `<LoginPage status={...}/>`，**不进 Router**）；`<Layout>` 包住 `<Routes>`。真实路由 = **4 条 + `*` 兜底**：`/`、`/study/:mediaId`、`/vocab`、`/vocab/practice` → `*` 重定向 `/`。
6. 计划**通篇没提样式迁移** → 必须从 `frontend/` 照搬：`index.html`、`public/`（favicon/apple-touch-icon，v1.16 的 logo 特性）、`postcss.config.js`、`tailwind.config.js`（**只把 `content` 加上 `.vue`**）、`src/index.css`（**仅 16 行**）。⚠️ `tailwind.config.js` 的 `theme.extend` 是**空的**，样式 99% 靠 className → **漏搬 `index.css`/`public/` 才是 P2 页面视觉不一致的真因**。
7. 计划没提**开发期怎么连后端** → 旧前端 `const BASE = '/api'`（**相对路径**）+ `vite.config.ts` 的 `server.proxy['/api'] → http://127.0.0.1:8000`（`changeOrigin: true`）。后端 `cors_origins` **只允许 5173**，而 P1 不许改后端 → **`frontend-vue` 必须照搬这个 proxy**（`port: 5174` + `strictPort: true`），否则浏览器被 CORS 拦。另外 `credentials: 'same-origin'` 也是靠同源代理才成立（别把 BASE 改成绝对 URL）。


### P0 交付物（2026-10-16）
- `scripts/export_openapi.py`、`scripts/gen-api-types.mjs`、`scripts/check-contract.mjs`；根 `package.json`（仅 devDep `openapi-typescript`，与 `frontend/` 隔离）
- `contracts/openapi-v1.json`（96181 B）、`contracts/api-types.d.ts`（83230 B）
- `backend/tests/`：`conftest.py`（含 `client`/`app_client`/`db_session`/`clean_db` fixture + 数据目录重定向护栏）、`test_smoke.py`、`test_dictation.py`(30)、`test_dict.py`(56)、`test_marks.py`(35)、`test_study.py`(14)、`test_media_flow.py`(21)、`test_auth.py`(15) → **173 passed**，dict/dictation/marks/study **100% 覆盖**
- `backend/pytest.ini`（`testpaths = tests`、`pythonpath = .`）、`backend/requirements-dev.txt`（pytest 9.1.1 / pytest-cov 7.1.0 / **httpx 0.28.1**）
- ⚠️ `TestClient` 需要真正的 `httpx`；venv 里的 `httpx2` **不是**它。

### 已裁决的「不改代码」结论（别再重复讨论）
- `marks.dump` 不防御「元素不可迭代」→ **不是缺陷**：唯一入口 `api/sentences.py:157` 的入参被 Pydantic（`SentenceUpdate.marks: list[list[int]]`）先校验，`[[0,1],5]` 直接 422。防御放在 `load`（读 DB TEXT 列）才是对的位置。
- **不存在** `media.status` 的 transition 校验器；该状态机是**描述性**的，强制力来自「哪段代码写哪个状态」。不为此新增校验器。

### 进度
- 2026-10-16：**P0 全部 6 项已交付，G0 = ✅ PASS**（QA 严过关独立复核，4/4 通过）。下一步 **P1**（新建 `frontend-vue/`，不覆盖 `frontend/`）。
- **2026-10-19：前端链 P0–P2 全部完成**（P2-E 生词两页 + P2-F 移动端回归收尾）。`frontend-vue/src` **7,895 行**（旧 React `frontend/src` 7,564 行）、5 条路由全可用。实测：`verify_vocab_practice` **29/29**、`verify_mobile` **36/36**、`verify_m4` 9/12 → **12/12**（P2-D 的 3 项失败归因成立）。下一步 **P3 后端架构债**。
  - ⚠️ **断言数口径**：`verify_vocab_practice.mjs` 里 `record(` 出现 32 次，真实断言 **29** 条（2 次是注入脚本同名钩子、1 次 catch 兜底）。别按 32 记账。
  - ⭐ **迁移方法论（P5 前别松）**：Vue 页必须与旧 React 页保持 **className 字符串 / DOM 层级 / `data-*` 属性逐字一致**，旧的 CDP 套件才能零改动直接打 Vue 版（P2-C 58/58、P2-E 29/29 都是这么来的）。文案比对时注意 **Python `\s` 包含 U+3000**，用 `\s+` 折叠空白会把全角空格吞掉造成假通过。
  - 挂账（不影响闸门）：`verify_category` 批量菜单「未分类」无断言；`verify_m5` 缺「草稿持久化」断言。
- **2026-10-19（续）：P3-1 Alembic 完成，G3-① PASS**。`backend/alembic.ini` + `migrations/`（基线 `0001`，9 表显式 DDL + 8 索引）+ `tests/test_migrations.py`（11 用例）；全量 **184 passed**。副本 `upgrade head` 9 表内容哈希全等、真实库无 `alembic_version`。下一步 **P3-2（jobs 表 + 独立 worker）**。
  - 🔴 **四个不可回退的坑**：① `alembic.ini` **必须纯 ASCII**（alembic 用 `encoding="locale"`，中文 Windows=cp936 → 迁移执行前就 `UnicodeDecodeError`，`PYTHONUTF8=1` 无效）；② Git Bash `/tmp/x.db` 经 `Path.resolve()` 变 `D:\tmp\x.db` → 「迁移成功」到空库，一律 `$(cygpath -w …)` 并核对 env.py 打印的目标 URL；③ 基线必须显式 DDL + `inspect()` 跳过已存在表（否则老库 `upgrade head` 报 `table already exists`）；④ **`compare_server_default` 永远保持关闭**（开了连正确迁移的空库也永久报 `modify_default(sentences.marks)`）。
  - 🔴 **团队纪律（P3-1 事故换来的）**：报哈希前必须冻结文件（改完→测试→`sha256sum`→发报告→不再写）；破坏性验证一律 `cp -r backend/` 到沙箱做，绝不在交付物上「改→还原」（备份放 `versions/` 会被 alembic 当第二个 `0001` 加载）。
  - 开放项：老库 `--autogenerate` 有 1 对假 FK diff（列级内联 FK 反射丢 `ondelete`）→ **已决定不加 `include_object`**，将来另起 batch 迁移归一。
- **2026-10-19（续）：P3-2 jobs+独立 worker + P3-3 CPU/IO 分池 完成，G3-②③ PASS**。`services/jobs.py`(1067) + `worker.py`(772) + `0002` 迁移(204)；**240 passed / 1 skipped**；契约 34/42 不变；真库零写入。设计文档 `docs/DD-001-P3-2-jobs与分池-系统设计.md`。下一步 **P3-4~P3-6**（领域收口 / health 余项 / 打包链 G3-④）。
  - 🔴 **三处推翻计划原文的设计（别改回去）**：① `process_media` 必须**拆 4 个 stage job**（整条链进一个池时，翻译的几分钟 IO 会占住 CPU 槽，云端 cpu=2 时 G3-③ 物理上不可能通过）；② 崩溃恢复判据是 **`租约超时 OR worker 不在在线集合`**（只靠 TTL 时 `kill -9` 后要等 120s，OR 让 ~8s 接管）；③ web 三态 `FAYELONG_WEB_INPROC_WORKER=off|auto|on`（worker 缺失时 web 接管，防双份靠 DB 原子 claim + fencing，不靠 flag）。
  - 🔴 **fencing 必须用 claim 时快照**：`worker.py::_fence()` 返回 `SimpleNamespace`；**不能**用 `db.get(Job)` 的当前归属（会让老执行者迟到写回覆盖接管者），**不能**给 `fresh.attempts` 赋值（ORM dirty 会把计数器 flush 坏）。**media 轴也必须同一张 fence**：`mark_terminal_failure()` 先 `force_failed()` 看返回值、再写 media。
  - 🔴 **判别力陷阱**：G3-③ 的断言只在 **CPU 池=1** 有判别力（cpu≥2 时误放回 CPU 池抓不到）；`cpu_peak<=1`/`io_peak<=2` 是恒真的容量检查、**不是**判别证据；`os.cpu_count()` **不识 cgroup**，云端必须显式配 `JOB_CPU_THREADS=1`。
  - 🔴 **结构性事实**：`test_jobs.py` 跑在 `create_all` 上 → **对迁移脚本退化完全免疫**；守 `migrations/` 的只有 `test_migrations.py` 一个文件。
  - 挂账：`worker.py:597-628` 非 media 分支无 fence（P4 启用 `grade_writing` 前必修）；谓词改窄仅由 `test_migrations.py:497-498` 一句字面量守卫（别删）；`requeue_unfinished()` 与运行中 worker 重叠（UI 进度回 0，自愈不丢数据）。
- **2026-10-20：P3-4/P3-5/P3-6 完成，P3 阶段结项，G3 四项判据达成**。全量 **278 passed / 1 skipped**；契约 34/42；真库零写入。`api/media.py` 682→420 + `media_ops.py`(802)；health 加 `disk`；job_id 贯穿日志；G3-④ 打包链通过。
  - 🔴 **两个「开发全绿、打包必崩」缺陷（只有真跑才暴露）**：① **`python -m app.worker` 在交付包里起不来** —— Windows embeddable Python 的 `python313._pth` 是隔离模式、**忽略 `PYTHONPATH`**，web 5s 后 `auto` 静默降级（功能看着正常、双进程形同虚设、用户零提示）；修法 `packaging/worker_entry.py` + `build.ps1` **与 `build-update.ps1`** 都带上。② **首启两进程 `create_all` 撞车**（checkfirst 两步非原子）；`_create_all_tolerant` 重试 `already exists` 与 `readonly database`/`database is locked` 两组，**其余错误立即抛**。
  - 🔴 **构建期改写过的文件不能用直接 `cmp`**：`build.ps1` 对 `使用说明.txt` 做占位符替换 + CRLF，对**所有 bat** 也做 CRLF。判据必须是归一化后比（这条连续坑了两次）。
  - 🔴 **少而高并发 ≫ 多轮低并发**：G2 并发建表用例 4 进程×4 轮（11.7s/命中 67%）→ **8 进程×1 轮（5.07s/未修版 3/3 全红）**。
  - ⚠️ `with sqlite3.connect(...)` **只提交事务不关闭连接**（不是 `contextlib.closing`）→ Windows 上文件被持有，`rmtree(ignore_errors=True)` 静默失败。
  - 挂账（P4）：非 media 分支无 fence（`grade_writing` 前必修）；`requeue_unfinished()` 与运行中 worker 重叠；`_PoolRunner.idle()` 用全局 `has_active_work`；`停止 FayeLong.bat` 输出为英文（cmd+chcp 65001 解析中文批处理不可靠）。
- **2026-10-22：P4 全部完成（题型插件化 + IELTS 六表 + 写作批改异步化），G4 判据成立**。全量 **369 passed / 1 skipped**；契约 **41/49**；真库零写入。P3 那四条挂账已在本阶段清掉（fence / requeue / idle / bat 文案）。
  - ⭐ **版本库补齐**：`frontend-vue/`、`backend/tests/`、`migrations/`、`contracts/` 此前**全部 untracked**（P1–P4A 两周无基线），已整理成 6 个提交。**纪律第 9 条：阶段结束必须提交进 git。**
  - ⭐ **题型插件**：`services/question_types/`（重复 code 报错、空表不崩）+ `GET /api/question-types` **实时读注册表**；前端 `src/question-types/` 三级降级；`<component :is>` 落在 `SentenceStage.vue` 而非 StudyPage（上移会改 DOM 层级、威胁 `verify_mobile`）
  - ⭐ **IELTS 迁移**：`0003` 只 `CREATE`；全新库 18 表/131 列/20 索引/11 外键；老库副本升级后**老 9 表逐表行哈希不变**（不能只看 TOTAL）。⚠️ **验证「只回退本批」用 `downgrade 0002`，不是 `downgrade base`**（base 在 0001 之前，0001 就是建老 9 表的迁移）
  - 🔴 **report 必须按 `submitted_at` 设闸**（QA 抓到未交卷可读 explanation）：闸放**领域层**（API 层会让导出/SSE/批处理绕过）；`ResponseOut` 删掉 `detail`，判分明细只经 report；判据用 `submitted_at`（单向锁定）而非 status，未来「边答边判」不会绕过
  - ⭐ **写作批改默认降级**：`FAYELONG_GRADING_PROVIDER=off` ⇒ 零付费离线可用，`degraded` 是**成功态**（job `done` 非 `failed`）；缓存不入降级结果；密钥四出口无原文；`ungraded ≠ degraded`，`pending` 只数会被判出来的题
  - 挂账（P5）：`grade_writing` job 的 `ref_id` 指向 `responses.id`，加删除端点时必须清理 job；前端 `QuestionTypeInfo` 可换成生成类型别名；真机断网演练未做。
- ⚠️ **数据安全不变量已换口径（2026-10-16 修正，别再比对文件 md5）**：
  原来记的「`data/app.db` md5 必须恒为 `61fb174d…`」是**错的**。P1 Round B 首次对真实后端跑「登录」验收时，后端 `api/auth.py::login` 成功会写 `users.last_login_at` → 文件 md5 从 `61fb174d40d6aed496800e2c56b1489f` 变为 `0e0a714e919468d3d8db3d922b36a5a6`。
  **这是应用本来就该发生的写，不是数据损坏**（已只读核对：9 张表行数、media 状态、`media/library/` 目录、文件大小 131072 全部未变；DB mtime 恰等于 `last_login_at` 的 +08:00 时刻）。
  ✅ **新口径**：一律以 `scripts/fingerprint_data.py`（只读内容指纹，显式排除 `users.last_login_at` 并打印排除清单，含 `data/media/library/` 目录清单哈希）为准。**永远不要拿文件 md5 当数据安全判据** —— 对一个本来就该被使用的应用，它过脆。
  ⭐ 教训：验收要求本身可能就是污染源。要求「跑一次真实登录」就等于要求写库；要么改用只读的「铸牌」令牌（`session.mjs` 新增导出），要么把口径放宽到「除易变字段外零变更」。
- 契约指纹：`contracts/openapi-v1.json` md5 `55d017196970f40cb68e18acddd4cdc1`（重跑脚本逐字节一致）；`contracts/api-types.d.ts` md5 `37b03802608bac1240a5d79a12318940`。
- **端点全集（别重复数）**：auth 5 / categories 5 / media 14 / sentences 5 / vocab 5 / notes 2 / attempts 1 / dict 1 / health 1 / stats 1 = **42 operation / 34 path**。

### G0 复核的三条「有牙」证据（QA 用**变异测试**验的，不是看绿灯）
- ✅ **护栏有牙**：把 conftest 的重定向补丁注释掉 → `pytest` 在 **fixture setup 阶段**就 AssertionError 中止（「测试数据库危险地指向了真实数据目录」），**没有**静默写真实库；还原后仍 173 passed。
- ✅ **反遮罩有效**：同时制造「`/` 环境差异 **+** 删真端点」→ 门禁仍**退出 1 并点名真端点**；容忍只吃 `"/"` 那一条。
- ✅ **覆盖率未注水**：无 `.coveragerc`/`omit`/`fail_under`；`backend/app/**` 内无 `# pragma: no cover`。
- ⚠️ **有一条测试比它的名字弱**（已修）：`test_lemma_candidate_must_hit_dictionary` 在「去掉候选词库命中校验」的变异下**仍然 PASS**，只被 `test_all_candidates_miss` 兜住。根因：本机装了 lemminflect，`lemma_candidates("running")` 首个候选就是真实收录的 `run`，用例前提不成立 → 修法是 monkeypatch `_lemminflect_candidates → []`。
- 强用例（变异即 FAIL，可作模板）：`test_level2_excludes_hyphenated_split_entry`、`test_extra_word_does_not_enter_denominator`。
- 卫生：`backend/.coverage`、`backend/.pytest_cache/` 原未被 `.gitignore` 覆盖，已补 `.coverage` / `.coverage.*` / `htmlcov/` / `.pytest_cache/`。



# FayeLong 英语学习网站 — 项目记忆

## 定位
个人自用、可联网、零付费依赖 的英语精听/听写学习网站。
**最终部署目标：一台没有开发环境的 Windows 笔记本（8GB 内存）**，要求小白式安装（拷贝文件夹 → 双击启动 → 浏览器使用）。
前端 React + TS + Vite + Tailwind (SPA)，后端 FastAPI (Uvicorn) 同时托管前端静态文件（单端口 8000）。
- ASR：faster-whisper `small`（本地模型，int8，带时间戳）
- 翻译：**免费在线多引擎**（免密钥、免注册）：有道 aidemo → MyMemory 自动回退；结果写 `translations` 表缓存
- 词典：**ECDICT 全量词库**（`data/dict/ecdict.db`，实测 **340 万词条 / 811.9 MB**）+ 词形还原（exchange 反查优先，lemminflect 兜底）
- 生词本 / 笔记：`vocab` 表（幂等去重，带上下文与来源）+ `notes` 表（每句至多一条，空内容即删除）
- 听写校验：**服务端唯一判定**（`services/dictation.py` 纯函数 + `POST /api/attempts`），四类标记 correct/wrong/missing/extra
- 转码/切片：ffmpeg / ffprobe，**便携版随包分发**，放在 `tools/ffmpeg/`

## 数据目录（v1.3 起统一，重要）
**唯一运行时数据根 = 项目根 `data/`**（原先的 `backend/data/` 已废弃删除），拷贝该目录即完成学习数据迁移。
- `data/app.db`：SQLite（7 表：media / sentences / attempts / notes / vocab / settings / translations）
- `data/media/audio/`：**收件箱**，用户投放原始素材，供「从素材目录导入」扫描
- `data/media/library/<media_id>/`：媒体库，`original.<ext>`（原始文件）+ `audio.wav`（16kHz 单声道标准音频）+ `clips/`（M2 句子切片）
- `data/models/`、`data/dict/`、`data/logs/`
- .gitignore 已覆盖：data/app.db、data/media/library/、data/models|dict|logs/；`data/media/audio/*` 忽略但保留 .gitkeep

## 里程碑状态
- **M0 骨架 ✅**、**M1 媒体导入与播放 ✅**（2026-10-10）、**M2 识别与翻译 ✅**、**M3 单句听写页 ✅**、
  **M4 词典 / 生词本 / 笔记 ✅**、**M5 打磨 ✅**、**M6 打包与交付 ✅**（2026-10-11）
  → **全部里程碑完成**；交付包：`dist/FayeLong/`（1.72 GB）+ `dist/FayeLong-v0.1.0-win64.zip`（816.4 MB，
  SHA256 `B8A5D3A6…4D81BD1`）；轻量包模式 487.4 MB（`build.ps1 -Light`）
- M6 已交付：`packaging/build.ps1` 一条命令产出交付包（内置 **Python 3.13.14 embed** + 全部依赖 + 便携 ffmpeg +
  VC++ 运行库 + whisper small + ECDICT）；`启动 FayeLong.bat` 双击即用（自检 → 选端口 → 起服务 → 自动开浏览器）；
  `停止 FayeLong.bat` 按 pid 结束；`使用说明.txt` 6 节；构建期强制跑 `launcher.py --check`（不过则构建失败）
- **v1.9 / v1.10 生词本增强（新增需求，2026-10-11）✅**：生词**可朗读**（FR-A7）+ **生词练习**（FR-A8，三种模式：
  中译英手输拼写 / 英译中四选一 / **单词听写**听发音写拼写；可选范围与题量，结果页给正确率与错题回顾）。
  **纯前端实现，后端零改动**；见设计文档 §22
- **v1.11 静默启动 + 就地更新（新增需求，2026-10-11）✅**：新增 `pythonw.exe` 静默启动（后台无窗口，
  日志落 `data/logs/console.log`）、开机自启三件套、`更新 FayeLong.bat` 就地更新（**只换程序、绝不碰 `data/`**），
  以及轻量更新包（193.4 KB）。见设计文档 §15.6~§15.8
- M3 已交付：听写输入（Enter 提交）→ 词级标红校验 → 正确率与掌握度 → 听写历史；
  卡片徽标 + 头部听写进度条 + 批量显隐；原文/翻译隐藏时**不渲染进 DOM**（防 F12 抄答案）
- M4 已交付：原文按词可点击 → 查词浮层（音标/释义/词形变化/考纲标签/柯林斯星级 + 朗读 + 牛津朗文）→
  一键加入生词本（带上下文与来源）→ 生词本页（搜索/筛选/编辑/掌握/删除/导出 Markdown）；每句笔记可编辑保存
- M5 已交付：**A-B 循环**（句子卡片三态按钮 + 句子级进度条）、**笔记按媒体汇总 + 导出 Markdown**
  （`NotesPanel`，点击条目滚动定位并高亮）、**全局异常处理器 + ErrorBoundary + 请求 30s 超时**、
  媒体库**学习概览四卡 + 搜索 + 排序 + 骨架屏**、听写历史**正确率趋势条**、`GET /api/stats`

## 词典（M4，重要）
- 查询三级优先（`services/dict.py::_query`），**不可只按 `sw` 查**：ECDICT 有「音节拆分条目」（`hel-lo`/`chil-dren`/`bet-ter`），
  其 `sw` 与正常词相同，只查 `sw` 会命中拆分条目（`children` 曾返回「字组拆分到两个音节中去」）。
  ① `word = ?`（走 word 唯一索引）→ ② `sw = ?` 且 `word NOT LIKE '%-%'` → ③ `sw = ?`；排序 `collins DESC, frq DESC`。
- 词形还原：先看命中的 exchange 是否含 `0:`（原型）→ 用原型再查，`via=exchange`；否则 lemminflect + 规则候选，
  **候选必须能命中词库**才采用。实测 `went→go`、`better→good`、`children→child`、`Americans→American` 均正确。
- 词库未安装：接口不报错，返回 `found=false` + 中文提示；词库未收录可选在线翻译兜底（`dict_online_fallback`）。

## 听写判据（M3，重要）
- 归一化：`’→'`，可忽略大小写与标点（`letter.` ≡ `letter`），只留 `[0-9a-z']`
- 分词保留 `display`（带标点，用于显示）+ `norm`（用于比对）双份
- 正确率 = 正确词数 / 标准答案词数；**多写词不进分母**
- `is_correct = 正确率 ≥ dictation_pass_accuracy(默认100) 且 extra == 0`（多写词必须单独排除）
- `attempts` 只追加不覆盖；**词级明细不落库**，提交时即时计算随响应返回
  `mastered` = 该句曾出现过一次 `is_correct`

## 状态机（media.status）
`pending → transcoding → ready → asr → translating → clipping → done | failed`
- M1 终态是 `ready`；M2 会一路推进到 `done`
- 进度区间（config.py）：转码 0-20 / 识别 20-70 / 翻译 70-90 / 切片 90-100
- 服务启动时 `requeue_unfinished()` 会把 `UNFINISHED_STATUSES`（pending/transcoding/ready/asr/translating/clipping）全部重新排队（自愈）
- 前端常量在 `frontend/src/api/client.ts`：`PROCESSING_STATUSES` / `PLAYABLE_STATUSES` / `STATUS_LABEL`

## 已确认决策（v1.3）
第一轮：前端+轻量后端本地部署 / 全免费 / 数据本地 SQLite / 字典=浮层+跳转牛津朗文
第二轮：ASR=small ｜ 视频仅取音轨 ｜ 每句音频切片 ｜ 导出 Markdown ｜ 仅桌面端 ｜ 无需登录
第三轮：交付=**全量包**（自带 Python 运行时）｜ 翻译=**免费在线**（废弃 NLLB/PyTorch）｜ 目标机 8GB
第四轮：ffmpeg 由开发方安装并随包分发 ｜ 允许联网，依赖服务必须免费
第五轮：数据目录统一到 `data/`（便于整体迁移）｜ 后端 M1 即打通单端口静态托管
第六轮（M3）：听写判定**只在服务端**（避免两套 diff 漂移）｜ 默认忽略标点与大小写 ｜
  「完全正确」需正确率达标**且无多写词** ｜ 隐藏的原文/翻译**不渲染进 DOM**

## 关键决策理由
- 翻译选在线而非本地 NLLB：NLLB 依赖 PyTorch（+2.5GB），对「无开发环境笔记本」的分发极不友好；免费在线接口质量更好、包体积从 4GB 降到约 1.2GB。
- ASR 必须本地：没有免密钥的免费在线 ASR。
- 视频「仅取音轨」是一等公民：`ffmpeg -vn` 丢画面流，原始文件仍保留以便日后重处理。

## 已验证可用的免费服务（2026-10-10 实测）
- 有道公开演示接口：`POST https://aidemo.youdao.com/trans`，form: q/from=en/to=zh-CHS → `translation[]`，`errorCode=="0"` 为成功。质量好。【主力】
- MyMemory：`GET https://api.mymemory.translated.net/get?q=..&langpair=en|zh-CN` → `responseData.translatedText`，`responseStatus=="200"`。【兜底，配额有限】
- 实测**不可用**：Google gtx（被墙）、腾讯 TranSmart（需 token）、LibreTranslate 官方与各镜像、Lingva 各镜像、Edge auth、有道 fanyi 网页接口。

## 目录约定
- `backend/app/`：`main.py`（含**全局异常处理器**）、`api/`（health / media / sentences / attempts / dict / vocab / notes / **stats**）、
  `services/`（media.py 转码+编排 / asr.py 识别+切句 / clip.py 切片 / translate.py 在线翻译 /
  dictation.py 词级标红算法（纯函数）/ study.py 听写统计聚合 / dict.py ECDICT 查询+词形还原）、
  `core/`（config.py / paths.py（MediaError+媒体路径）/ tools.py / files.py（Range 响应）/ tasks.py（线程池）/ logging.py）、
  `models/`、`schemas/`（dict.py / vocab.py / note.py / **stats.py**）、`db.py`
  - 笔记汇总与导出挂在 `api/media.py`：`GET /api/media/{id}/notes`、`GET /api/media/{id}/notes/export`
- `backend/scripts/`：`selftest.py`（环境自检：ffmpeg + 翻译 + 数据库 + 词典 + 听写算法 + **接口完整性**）、
  `fetch_dict.py`（下载安装 ECDICT 词库，多镜像 + 续传）
- `frontend/src/`：`pages/`（StudyPage 内含 DictationBox + ClickableText、VocabPage、**VocabPracticePage**、MediaLibraryPage）、
  `components/`（Layout / PlayerBar / icons / DiffResult / WordPopover / NoteEditor / **NotesPanel** / **ErrorBoundary**）、
  `hooks/useClipPlayer.ts`（**含 A-B 循环**）、`api/client.ts`（**30s 超时 + 网络错误包装**）、`store/player.ts`、
  `utils/format.ts`、**`utils/speech.ts`**（Web Speech API 朗读英文）
- `scripts/verify_m4.mjs`（12 项）、**`scripts/verify_m5.mjs`**（15 项）、**`scripts/verify_vocab_practice.mjs`**（**29 项**，含听写）：
  **CDP 端到端验证脚本**（**必须用 Node 22**，Node 20 无全局 `WebSocket`）
- **`packaging/`（M6 交付链，重要）**：
  - `build.ps1`：10 步流水线（前置检查 → 备输出目录 → 取嵌入版 Python → 写 `._pth` → 装配依赖 →
    补 VC++ DLL → 拷代码/前端/脚本 → 建 `data/` → 生成用户文件 → 跑 `--check` → zip + SHA256）。
    参数 `-Light`（不内置模型/词典）/ `-FromPip` / `-NoZip` / `-Force`；**带 UTF-8 BOM**（WinPS 5.1 读中文注释）。
    依赖装配默认复用 `backend/.venv` 的 `site-packages`（保留 `__pycache__`），即「自验过的解释器 = 交付的解释器」。
  - `launcher.py`：打包后位于 `<解压目录>/scripts/`，`HERE.parent` 即根；`--port/--no-browser/--check/--yes/--silent`。
    **静默启动**：`wants_silent()` 靠 `sys.stdout is None` 自动判定（pythonw.exe）；`redirect_stdio_to_log()` 把流接到
    `data/logs/console.log`；`remember_install()` 写 `%LOCALAPPDATA%\FayeLong\install.txt`（**UTF-16**）+ `data/install.json`。
  - `update.py`：**就地更新工具（升级不丢数据）**，打包后在 `scripts/`；`--target`（省略自动查找）/`--dry-run`。
  - `bootstrap.py`：轻量包首启下载模型/词典；`zipdir.py`：UTF-8 文件名安全的 zip 打包器。
  - `check_syntax.py`：对目录下所有 `.py` 做 `ast.parse`（不生成 `__pycache__`），供构建期自检。
  - `build-update.ps1`：**只打包程序文件**的增量更新包 → `dist/FayeLong-update-v{版本}-win64.zip`（约 193 KB）。
    构建期 3 条硬断言：`.py` 语法可解析 / `.vbs` 是 UTF-16LE+BOM / 包里**不得出现 `data/`**。
  - `files/`：`启动 FayeLong.bat` / `停止 FayeLong.bat` / `更新 FayeLong.bat` / `安装开机自启.bat` /
    `取消开机自启.bat`（UTF-8 无 BOM + CRLF）、`静默启动 FayeLong.vbs` / `FayeLong-Autostart.vbs`
    （**构建时转 UTF-16LE**）、`使用说明.txt`（含 `{{VERSION}}/{{BUILD_DATE}}/{{MODE}}` 占位符）
- `packaging/fetch-ffmpeg.ps1`：重下便携 ffmpeg/ffprobe
- 开发启动：`scripts/dev.bat`；后端 http://127.0.0.1:8000/docs，前端 http://localhost:5173

## 环境事实与踩坑
- 本机 Python **3.13.14 可直接跑 faster-whisper**（1.2.1 / ctranslate2 4.8.2 / onnxruntime 1.31.0），**不必退回 3.11**；Node 22.22.2。
- pip 源：清华镜像对 faster-whisper wheel **403**；**用阿里云** `https://mirrors.aliyun.com/pypi/simple/`。
- **npm install 必须加 `--ignore-scripts`**：esbuild postinstall 在托管 node.exe 上 spawnSync 报 EBUSY（沙箱限制）；`@esbuild/win32-x64` 原生包已在，构建正常。
- ffmpeg 源：gyan.dev 极慢（11KB/s）；**npmmirror 快**（25s）：
  `https://registry.npmmirror.com/-/binary/ffmpeg-static/b6.1.1/{ffmpeg,ffprobe}-win32-x64`
- whisper 模型走 **hf-mirror.com**（约 39s 下完 461MB）；`huggingface.co` 直连不通。
- 本环境 **PowerShell 工具不回传 stdout**；且 `Add-Type`、`cscript` 均被安全策略拦截（无法用 SAPI/TTS 造语音）。
- **Bash 工具里用 `&` 起的后台进程会随该次调用结束而被杀**；常驻服务必须用 run_in_background。
  反过来，**`run_in_background` 起的常驻服务会跨轮次持续存活**，用完必须主动停止（否则白占端口与内存）。
  判断某进程是不是工具起的：看其 `ParentProcessId` 的父进程是不是 `bash.exe`，以及启动时间是否吻合。
  注意别误杀 **WorkBuddy 自身的 node.exe**（edge-sync / sheetagent / weixinpay 等 MCP）。
- Git Bash 下 curl 的 `-w "/..."` 会被 MSYS 路径转换搞坏，写法要避免以 `/` 开头。
- ffmpeg 的 `-progress` 输出中 `out_time_ms` 实际单位是**微秒**（与 `out_time_us` 相同），不是毫秒。
- 排查「改了代码但行为没变」：先查端口残留进程（`netstat -ano | grep LISTENING | grep :8000`）；旧 uvicorn 会占住端口让新实例静默启动失败。
- `rm` 被 safe-delete 包装拦截时会 **FAIL_CLOSED 并中断 `&&` 命令链**，后续命令不会执行。
- 设计文档曾出现被回退到旧版本的异常，重要文档改动后需复核落盘内容。
- **真实验证 UI 的办法（本机有 Chrome）**：无头 Chrome + CDP 驱动真实点击，
  Node 22 内置 `WebSocket` 即可，无需装 Puppeteer。两个坑：
  ① 每次必须换新的 `--user-data-dir`（残留 chrome.exe 会锁住 profile，新实例启动即退出、端口不通）；
  ② Chrome 必须在**同一条 Bash 命令内**「启动 → 跑测试 → 收尾」，单独 run_in_background 会被回收
  （只做 `--dump-dom` 静态渲染则不受影响）。
  ③ 校验输入框内容要用 `el.value`（textarea 的文本不在 DOM 文本节点里）。
- **GitHub release 大文件下载**：直连仅 ~230 KB/s（206MB 要 15 分钟，`curl --max-time` 容易半途被切）；
  且源站 `release-assets` 对 **Range 续传请求返回 502**。解法：用 `https://ghfast.top/<原始URL>` 前缀镜像
  （支持 206 续传、实测 ~800KB/s）。`ghproxy.net` 可用，`gh.llkk.cc` / `gh-proxy.com` 返回 502。

## 打包与交付踩坑（M6，重要）
- **Python 嵌入版 `python313._pth` → isolated 模式**：`sys.path` 完全由该文件决定，**环境变量 `PYTHONPATH` 被忽略**；
  必须写 `import site` 才会加载 `Lib\site-packages`。文件内容（结尾要换行）：`python313.zip` / `.` / `Lib\site-packages` / `import site`。
- **VC++ 运行库**：嵌入版带 `vcruntime140*.dll` 但**不含 `msvcp140` 系列**。用 PE 导入表分析得知
  `ctranslate2.dll` 需 `msvcp140/msvcp140_1/msvcp140_2/vcruntime140_1`、`onnxruntime.dll` 需 `msvcp140*`；
  从 `System32` 拷 5 个（`msvcp140` / `msvcp140_1` / `msvcp140_2` / `msvcp140_atomic_wait` / `concrt140`）到 `runtime/python/`（exe 同目录优先加载）。
- **`SO_REUSEADDR` 在 Windows 上允许重复绑定同一端口**：用它的 bind 探测会把「已占用」误判为「空闲」。
  正确做法是「`connect_ex` 测试 + **不设** `SO_REUSEADDR` 的 bind 测试」双信号；并加 `PortBusy` 异常 + 启动重试循环
  （启动瞬间被抢占时自动 `port+1`）。
- **zip 中文文件名编码**：Windows 自带 `tar.exe`（bsdtar）按本机 ANSI（GBK）写文件名且**不置 UTF-8 标志位**（bit 11），
  7-Zip / macOS / 非中文 Windows 全乱码；Python `zipfile` 写 UTF-8 + bit 11。**必须用 `packaging/zipdir.py`**。
- **PowerShell 执行策略**：工具会话默认 `Restricted`，脚本被拦；每次都先 `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force`。
  且该工具**不回传 stdout**，诊断可把输出写文件再读。
- **子进程中文乱码**：根因是「脚本无条件把所有流切 UTF-8，而外层按 GBK 解码」→ 改为**仅当 `not stream.isatty()` 才切 UTF-8**；
  构建脚本自检前设 `[Console]::OutputEncoding = UTF8`。
- **删不掉旧 staging**：safe-delete 批量确认会导致构建中断；改为 try/catch —— 删不掉就**同盘改名保留**（`$Name.old-<时间戳>`），不中断构建。
- **绝对路径重定位**：复制 venv `site-packages` 后，`.pyc` 内嵌的开发机路径只影响 traceback 显示，不影响运行；无 `.pth` 残留。
- **PyInstaller 不适用**：对 ctranslate2（59MB DLL）/onnxruntime/av 等原生扩展很脆，故选择「嵌入版 Python + 直接拷 site-packages」。

## 生词本增强（v1.9 / v1.10，重要）
- **朗读**：`utils/speech.ts` 的 `speakEnglish()`。音色 `en-US` → `en-GB` → 任意 `en-*`；
  **Chrome 的 `getVoices()` 首次调用常返回空数组**（异步加载），所以**不能缓存空结果**，否则第一次点没声音。纯前端，不依赖 isatty。
- **练习出题**（`pages/VocabPracticePage.tsx`，纯前端，数据源只有 `GET /api/vocab`）：
  - 生词池 = **带释义**（`translation` 非空）的生词；
  - 模式分两类：**拼写类**（中译英 / 听写，需要打字）与**选择类**（英译中，点选项）——
    代码里统一用 `isSpelling = mode !== 'en2zh'` 分流，别再写 `isZh2En`；
  - 中译英：题干＝释义，答案 = `{word, lemma}` 归一化去重；`normEn = toLowerCase().replace(/[^a-z0-9']/g,'')`
    → 大小写/标点不计，**填原型也算对**（`went → go`）；
  - 英译中：四选一，干扰项从其他词释义随机抽 3 个；**至少需 2 个带释义的生词**，否则该模式置灰；
  - **为什么英译中不手输**：中文释义是同义词集合，自由文本判分只能「大致对」，四选一才能 100% 准确判分。
  - **可用性**：`enough` 按模式判断（eng 选择类 ≥2，拼写类 ≥1）；整页空态只在**一个带释义生词都没有**时拦截。
- **听写（v1.10）**：
  - 题干**只给发音，单词与音标都不渲染进 DOM**（避免眼睛扫到答案）；只渲染播放控件与「已听 N 次」；
  - **自动播放**：进入每题后 300ms 播一次，用独立 `useEffect` 只依赖 `[phase, index, mode, canSpeak]`，
    题目通过 `questionsRef` 读取（避免把 `questions` 放进依赖数组）；`listen()` 手动播放走同一函数并累加计数；
  - 「慢速重播」固定 `rate=0.6`（正常 `0.9`）；作答后额外显示该词中文释义；
  - **`rate` 是 float32**：`0.6` 实际存成 `0.6000000238418579`，断言必须容差比较。
- 中译英 / 听写题目在作答前**不显示朗读按钮**（等于报答案），作答后才显示。
- **`Enter` 双触发坑**：「下一题」按钮**不能加 `autoFocus`** —— 焦点在按钮上按 Enter 会「按钮 click + 全局 Enter 监听」各触发一次，一次跳两题。
- **改完前端源码必须重新构建再跑浏览器验证**：曾出现 `npm run build` 之后才加 `data-*` 属性，
  验证脚本读到空题干 → 全部答错。排查手段：`grep` 一下 `dist/assets/*.js` 里有没有目标属性。
- 验证脚本会写入 9 个测试生词，默认保留（方便试练），`--wipe-test-words` 删除。
- **听写怎么被自动化验证**：`Page.addScriptToEvaluateOnNewDocument` 注入钩子拦截 `speechSynthesis.speak`，
  记录每次朗读的**文本与语速**——「用程序把听到的声音记下来」，于是既能断言「题干不泄露文字」，又能拿到答案验判分；
  无语音合成的无头环境注入桩实现。**页面代码本身不额外暴露答案**。

## 静默启动与就地更新（v1.11，重要）
- **静默启动的判定不靠参数靠环境**：Python 嵌入版自带 `pythonw.exe`（GUI 子系统，不创建控制台），
  此时 `sys.stdout/stderr is None` → `wants_silent()` 自动为真。用户与快捷方式都不必记参数。
  `--silent` 也可显式指定。**两种方式并存**（默认仍保留控制台窗口，便于排错）。
- **静默不等于失明**：所有输出（含 Uvicorn 日志与未捕获异常 traceback）重定向到
  `data/logs/console.log`（UTF-8 / `buffering=1` / 超 2MB 轮转为 `console.log.1`）。
- **`input()` 在 pythonw 下抛 `RuntimeError`**（不是 `EOFError`）→ 捕获 `(EOFError, OSError, RuntimeError)`，
  静默时交互式询问退化为「已自动跳过」。
- **安装记录 `install.txt` 必须 UTF-16**：`%LOCALAPPDATA%\FayeLong\install.txt`（3 行：路径 / 版本 / 时间），
  VBS 用 `OpenTextFile(path, 1, False, -1)`（`-1`=`TristateTrue` 按 BOM 识别）读它。
  `data/install.json` 只记版本与时间、**不记路径** —— 这样整体迁移 `data/` 后信息依然正确。
- **定位安装目录的兜底链**：自身所在目录 → `install.txt` 第 1 行 → 找不到就 **静默退出**（不打扰开机登录）。
- **就地更新的分类同步策略**（`update.py`）：
  整目录替换 `app/`·`static/`·`scripts/`｜增量复制 `runtime/python`·`runtime/ffmpeg`·`tools`｜
  覆盖顶层 bat/vbs/说明｜数据资源**只补缺失** `data/models`·`data/dict`｜
  **全程不碰** `data/app.db`·`data/media/`·`data/logs/`·`data/backups/`。
- **⚠️ 增量判断不能只比文件大小**：实测存在「尺寸相同、内容不同」的文件（替换过的 `python.exe`），
  只比大小会漏掉 → 必须**分块比对内容**（`_same_content()`，1MB chunk）。
  性能：比对 461MB 仅 0.55s；6126 个文件 / 329MB runtime 读一遍 < 1s。
- **更新前先停服务**：读 `data/logs/fayelong.pid` → `taskkill /PID /T /F` → `sleep 0.8` 释放句柄，
  否则 Windows 因文件占用拒绝覆盖。更新前把 `app.db` 备份到 `data/backups/app-<旧版本>-<时间戳>.db`，留最近 5 份。
- **安全护栏**：目标须「像」安装目录（有 `app/` 或 `runtime/python/python.exe`）；目标不得等于或嵌套新包目录；
  任一检查不过即报错退出、**不做任何写入**；`--dry-run` 只预演。
- **更新包体积**：193.4 KB（对比完整包 816MB）—— 老用户升级不必重发模型与词典；运行时借用旧目录里的 `python.exe`。
- **实测**：模拟目录 **31/31**、真实 1.7GB 目录 **15/15**，`data/` 内 **0 个文件被修改**，耗时 8.1 秒；VBS **8/8**。

## 当前任务上下文
- 用户从百度网盘分享获取英文听力音频作为学习素材；沙箱无法直接下载，由用户本地下载后放入 `data/media/audio/`。
- `data/media/audio/` 现留有 3 个自造示例素材（`_示例-英文听力-11秒.wav` / `_示例-英文听力-带画面.mp4` /
  `_示例-多句听力.wav`（34.4s，6 句，用于听写多句验证）），仅用于冒烟验证，可随时删除。
- **M0–M6 全部完成**，**v1.10 生词本增强（朗读 + 中译英 / 英译中 / 听写）已完成并验证**，
  **v1.11 静默启动 + 就地更新已完成并验证**（均 2026-10-11）。
  笔记 / 听写记录为干净状态（库内仅 3 个示例媒体 + 8 句）；**生词本内有 9 个测试词**
  （abandon / benefit / cautious / diligent / efficient / fragile / genuine / hesitate / went），供立即试练，
  不需要时用 `node scripts/verify_vocab_practice.mjs --wipe-test-words` 清理。
- ⚠️ **完整交付包 zip 已过期**：`dist/FayeLong-v0.1.0-win64.zip`（816MB）产出于 M6，
  **不含**生词增强与静默启动 / 就地更新。`dist/FayeLong/` 目录已在 v1.11 重建（含全部新文件、自检通过）。
  要让 zip 带上新功能需重跑 `packaging/build.ps1`（约 4 分钟）；**未自动执行**（用户可能继续加需求）。
  ✅ 更新包 `dist/FayeLong-update-v0.1.0-win64.zip`（**193.4 KB**）已是最新，可直接给老用户升级。
- **M6（打包与交付）已完成**：`packaging/build.ps1` 一条命令产出交付包；全量包 `dist/FayeLong/`（1.72 GB）与
  `dist/FayeLong-v0.1.0-win64.zip`（816.4 MB，SHA256 `B8A5D3A66AFE131D203A79DEAD0751365E9C1399019548BFA2F2E953C4D81BD1`）；
  轻量包模式（`-Light`）487.4 MB。构建期强制自检 + 交付包内端到端冒烟（导入 → 识别 → 翻译 → 切片 → 听写 100%）均已通过。
  详见设计文档 §15（部署与分发）与 §21（M6 实现说明与验证记录）。
- 后续可选（§21.7）：代码签名 / 分卷压缩（zip 816MB 超某些 4GB 或 2GB 上限场景）/ 首次运行向导美化；
  ~~静默启动~~ ✅ 已完成（v1.11）；自动更新的**联网检查版本**部分未做（本地增量更新已完成）。
- 后续可选（§22.6）：练习记录落库（现只在内存）、按记忆曲线加权抽题（替代纯随机）、错题自动标记待复习、中文释义朗读。
- 注意：词库 811.9 MB + whisper small 461 MB 决定包体量，全量包≈816MB zip、**解压后 1.72 GB**（目标机需 ≥3GB 空闲）。

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
  **M4 词典 / 生词本 / 笔记 ✅**（2026-10-11）
  → 下一步 **M5 打磨**（循环播放、笔记汇总导出、异常处理、UI 优化）→ 之后 **M6 打包交付**
- M3 已交付：听写输入（Enter 提交）→ 词级标红校验 → 正确率与掌握度 → 听写历史；
  卡片徽标 + 头部听写进度条 + 批量显隐；原文/翻译隐藏时**不渲染进 DOM**（防 F12 抄答案）
- M4 已交付：原文按词可点击 → 查词浮层（音标/释义/词形变化/考纲标签/柯林斯星级 + 朗读 + 牛津朗文）→
  一键加入生词本（带上下文与来源）→ 生词本页（搜索/筛选/编辑/掌握/删除/导出 Markdown）；每句笔记可编辑保存

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
- `backend/app/`：`main.py`、`api/`（health / media / sentences / attempts / **dict** / **vocab** / **notes**）、
  `services/`（media.py 转码+编排 / asr.py 识别+切句 / clip.py 切片 / translate.py 在线翻译 /
  dictation.py 词级标红算法（纯函数）/ study.py 听写统计聚合 / **dict.py** ECDICT 查询+词形还原）、
  `core/`（config.py / paths.py（MediaError+媒体路径）/ tools.py / files.py（Range 响应）/ tasks.py（线程池）/ logging.py）、
  `models/`、`schemas/`（+ **dict.py** / **vocab.py** / **note.py**）、`db.py`
- `backend/scripts/`：`selftest.py`（环境自检：ffmpeg + 翻译 + 数据库 + **词典** + 听写算法断言）、
  **`fetch_dict.py`**（下载安装 ECDICT 词库，多镜像 + 续传）
- `frontend/src/`：`pages/`（StudyPage 内含 DictationBox + ClickableText、**VocabPage**）、
  `components/`（Layout / PlayerBar / icons / DiffResult / **WordPopover** / **NoteEditor**）、
  `hooks/useClipPlayer.ts`、`api/client.ts`、`store/player.ts`、`utils/format.ts`
- `scripts/verify_m4.mjs`：**CDP 端到端验证脚本**（查词 → 生词本 → 笔记，12 项）
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

## 当前任务上下文
- 用户从百度网盘分享获取英文听力音频作为学习素材；沙箱无法直接下载，由用户本地下载后放入 `data/media/audio/`。
- `data/media/audio/` 现留有 3 个自造示例素材（`_示例-英文听力-11秒.wav` / `_示例-英文听力-带画面.mp4` /
  `_示例-多句听力.wav`（34.4s，6 句，用于听写多句验证）），仅用于冒烟验证，可随时删除。
- **M0–M4 全部完成**；生词本与笔记已清空为干净状态（验证数据已清理）。
- **下一步 M5（打磨）候选**：循环播放增强、笔记按媒体汇总导出（`GET /api/media/{id}/notes/export`）、
  异常处理与 UI 细节优化；之后 M6 打包（内置 Python 运行时 + 模型/词库内置 + 一键启动脚本）。
- 注意：词库 811.9 MB，M6 打包时需决定「随包内置」还是「首次运行下载」（`fetch_dict.py` 已支持两种路径）。

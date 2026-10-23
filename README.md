# FayeLong 精听

> 本地部署、离线优先的**英语精听 / 听写**学习网站。
> 导入一段英语音频或视频 → 自动切句并生成中英对照 → 按句反复精听、逐句听写、随时查词记笔记。

[![Python](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=white)](https://react.dev/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.6-3178C6?logo=typescript&logoColor=white)](https://www.typescriptlang.org/)
[![License](https://img.shields.io/badge/license-personal%20use-lightgrey)](#数据来源与声明)

---

## 它是什么

一个**给自己用**的英语听力训练工具。核心场景是「把一段英语素材吃透」：

1. 把自己收集的音频 / 视频丢进素材目录；
2. 网站自动完成 **转码 → 语音识别 → 句子切分 → 逐句翻译 → 音频切片**；
3. 然后你就在一个页面里，对着**单句**反复精听、听写、查词、记笔记，直到整段听懂。

设计上有三条硬约束：

- **数据不出本机** —— 语音识别与词典查询全部在本地完成，学习记录存在本机 SQLite 里；
- **零付费依赖** —— 不调用任何需要 API Key 的商业服务；
- **小白可用** —— 提供打包好的 Windows 交付包，目标是一台**没有 Python / Node / ffmpeg 的笔记本**上双击即用。

---

## 核心特性

### 媒体处理
- 导入 **音频**（mp3 / wav / m4a / flac / aac / ogg / opus / wma）与 **视频**（mp4 / mkv / mov / webm / avi / flv / m4v / ts）；视频**只取音轨**参与识别，原始文件保留以便日后重处理。
- 素材「收件箱」机制：丢进 `data/media/audio/` 后由网站扫描导入。
- 处理进度可视化（转码 0–20% / 识别 20–70% / 翻译 70–90% / 切片 90–100%），服务重启后未完成任务**自动重新排队**。

### 语音识别与翻译
- **faster-whisper**（`small`，int8，CPU）本地识别，开启 **Silero VAD** 过滤静音、抑制幻听，并输出**词级时间戳**让切句更稳。
- 切句带三重护栏：过短的句子与下一句合并、过长或字符过多的强制切分；支持手动**拆分 / 合并单句**并重新翻译。
- 逐句中文翻译走**免密钥免费在线引擎链**（有道公开演示接口 → MyMemory 自动回退），结果写入本地缓存表，重复不重复请求。

### 听写与精听
- **逐句听写**：输入听到的内容 → 提交 → **词级标红校验**，四类标记 `correct` / `wrong` / `missing` / `extra`，给出正确率与掌握度。
- **判定权只在服务端**（`services/dictation.py` 纯函数 + `POST /api/attempts`），前端只负责渲染，避免前后端两套 diff 实现漂移。
- **答案零泄漏**：原文与翻译默认隐藏，且**隐藏时不渲染进 DOM**，按 F12 也抄不到答案。
- **A-B 循环**：任意片段反复播放，与单句循环、整段播放器三者互不干扰。
- 听写历史与正确率趋势，逐句掌握度一目了然。

### 词典 · 生词本 · 笔记
- 原文**按词可点击** → 查词浮层：音标 / 释义 / 词形变化 / 考纲标签 / 柯林斯星级，并可跳转牛津、朗文。
- 词库为 **ECDICT 离线词库**（见下方说明），配 **词形还原**两级策略（`exchange` 原型反查 → lemminflect + 规则候选，候选必须能命中词库才采用）。
- 一键加入生词本（自动带上**上下文句子与来源媒体**），生词本支持搜索、按掌握度筛选、编辑释义、导出 Markdown。
- **生词朗读**：用浏览器内置语音合成朗读英文（音色按 `en-US` → `en-GB` → 任意 `en-*` 降级挑选）。
- **生词练习**（`/vocab/practice`）三种模式，纯前端出题判分：
  - **中译英** —— 看中文释义手输英文拼写（大小写与标点不计，填原型也算对）；
  - **英译中** —— 看单词四选一，干扰项取自生词本其它词的释义；
  - **单词听写** —— **只给发音不给任何文字**（单词与音标都不进 DOM），可「再听一次」与「慢速重播」（0.6×），作答后才显示释义。
- 每句可写**笔记**，支持按媒体汇总与导出 Markdown，点击条目可滚动定位并高亮对应句子。

---

## 技术栈

| 层 | 选型 |
| --- | --- |
| 后端 | FastAPI + Uvicorn + SQLAlchemy 2 + SQLite |
| 前端 | React 18 + TypeScript + Vite + Tailwind CSS + React Router + TanStack Query + Zustand |
| 语音识别 | faster-whisper（本地 `small` 模型，ctranslate2 / onnxruntime 推理） |
| 翻译 | 免费在线免密钥引擎（有道 → MyMemory 回退），结果本地缓存 |
| 词典 | ECDICT 离线词库 + lemminflect 词形还原 |
| 音频处理 | ffmpeg / ffprobe（便携版随包分发） |
| 打包交付 | PowerShell 构建脚本 + Python 嵌入版 + 内置全部运行时依赖 |

**为什么 ASR 必须本地**：没有免密钥的免费在线语音识别服务。
**为什么翻译不本地**：本地 NLLB 需依赖 PyTorch（+2.5GB），对「无开发环境的笔记本」分发极不友好；免费在线接口质量更好、包体积从约 4GB 降到约 1.2GB。

---

## 目录结构

```
FayeLong/
├─ backend/                     # FastAPI 后端
│  ├─ app/
│  │  ├─ main.py                # 应用入口（含全局异常处理器、单端口托管前端静态文件）
│  │  ├─ api/                   # health / media / sentences / attempts / dict / vocab / notes / stats
│  │  ├─ services/              # media(转码+编排) asr clip translate dictation dict study
│  │  ├─ core/                  # config paths tools files(Range响应) tasks(线程池) logging
│  │  ├─ models/ schemas/       # ORM 实体与 Pydantic 模型
│  │  └─ db.py
│  ├─ scripts/                  # selftest.py(环境自检)  fetch_dict.py(下载 ECDICT)
│  ├─ requirements.txt          # Web 层依赖
│  └─ requirements-ml.txt       # 语音识别 / 词形还原依赖
├─ frontend/                    # React + Vite 前端
│  └─ src/
│     ├─ pages/                 # MediaLibraryPage / StudyPage / VocabPage / VocabPracticePage
│     ├─ components/            # PlayerBar Layout DiffResult WordPopover NoteEditor NotesPanel ErrorBoundary …
│     ├─ hooks/useClipPlayer.ts # 播放内核（含 A-B 循环）
│     ├─ utils/                 # format.ts  speech.ts(朗读)
│     └─ api/client.ts          # 统一请求（30s 超时 + 中文错误提示）
├─ packaging/                   # 交付链：把源码变成「双击即用」的 Windows 包
│  ├─ build.ps1                 # 构建完整交付包（10 步流水线）
│  ├─ build-update.ps1          # 构建轻量更新包（只含程序文件）
│  ├─ launcher.py               # 打包后的启动器（自检 / 选端口 / 起服务 / 开浏览器 / 静默模式）
│  ├─ bootstrap.py              # 轻量包首启按需下载模型与词典
│  ├─ update.py                 # 就地更新：只换程序文件，绝不碰 data/
│  ├─ check_syntax.py zipdir.py fetch-ffmpeg.ps1
│  └─ files/                    # 交付给用户的 bat / vbs / 使用说明
├─ scripts/                     # 开发与验证脚本
│  ├─ dev.bat start-backend.bat start-frontend.bat
│  └─ verify_m4.mjs verify_m5.mjs verify_vocab_practice.mjs   # 无头 Chrome + CDP 端到端验证
├─ data/                        # ★ 唯一运行时数据根（拷贝此目录即完成数据迁移）
└─ tools/ffmpeg/                # 便携版 ffmpeg / ffprobe
```

---

## 快速开始

### 方式一：使用交付包（推荐给普通用户）

交付包内置 Python 运行时、全部依赖、便携 ffmpeg、语音模型与离线词典，**目标机不需要安装任何东西**。

1. 解压整个压缩包到任意目录（**不要只挑几个文件解压**）；
2. 双击 **`启动 FayeLong.bat`** —— 它会自检环境 → 自动挑一个空闲端口 → 启动服务 → 浏览器自动打开；
3. 结束时双击 **`停止 FayeLong.bat`**（按 PID 结束进程）。

不想看到黑色控制台窗口？双击 **`静默启动 FayeLong.vbs`**（后台运行，所有输出写入 `data/logs/console.log`），或运行 `安装开机自启.bat` 让它开机自动后台启动。

升级到新版本时，用 **`更新 FayeLong.bat`** 指向旧安装目录即可 —— **只替换程序文件，`data/` 一个字节都不动**，且动手前会把 `app.db` 备份到 `data/backups/`。

> 详细操作（含常见问题）见交付包内的 `使用说明.txt`。

### 方式二：从源码运行（开发者）

**环境要求**：Python 3.11+（本机实测 3.13）、Node.js 18+（推荐 22）、ffmpeg 在 PATH 中。

```bash
# 1. 后端依赖
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt -r requirements-ml.txt

# 2. 前端依赖
cd ../frontend
npm install --ignore-scripts      # 见下方「已知踩坑」

# 3. 一键启动（后端 + 前端）
cd ..
scripts/dev.bat
```

- 后端接口文档：<http://127.0.0.1:8000/docs>
- 前端开发服务：<http://localhost:5173>

首次使用还需准备两个大体积资源：

```bash
# 下载 ECDICT 离线词库到 data/dict/（约 812 MB）
python backend/scripts/fetch_dict.py

# 语音模型会在首次识别时自动下载到 data/models/（约 461 MB，默认走 hf-mirror 镜像）
```

跑一次环境自检，确认依赖、模型、词典、数据库与接口完整性都正常：

```bash
python backend/scripts/selftest.py
```

**生产式单端口运行**（后端同时托管前端构建产物）：

```bash
cd frontend && npm run build && cd ..
python backend/app/main.py        # 访问 http://127.0.0.1:8000
```

---

## 配置

配置集中在 `backend/app/core/config.py`，所有字段都可用**环境变量**（前缀 `FAYELONG_`）或 `backend/.env` 覆盖。常用项：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `FAYELONG_HOST` / `FAYELONG_PORT` | `127.0.0.1` / `8000` | 监听地址与端口 |
| `FAYELONG_WHISPER_MODEL` | `small` | 识别模型规格 |
| `FAYELONG_WHISPER_DEVICE` | `cpu` | 推理设备 |
| `FAYELONG_HF_ENDPOINT` | `https://hf-mirror.com` | 模型下载源（国内直连官方源不通） |
| `FAYELONG_TRANSLATE_ENGINES` | `["youdao","mymemory"]` | 翻译引擎链，按顺序回退 |
| `FAYELONG_DICT_ONLINE_FALLBACK` | `true` | 词库未收录时是否用在线引擎兜底 |
| `FAYELONG_WORKER_THREADS` | `2` | 后台转码并发数 |

完整清单与注释见 `backend/.env.example`。

---

## 数据目录

**唯一运行时数据根是项目根下的 `data/`** —— 拷贝该目录就完成了全部学习数据的迁移。

```
data/
├─ app.db                 # SQLite：media / sentences / attempts / notes / vocab / settings / translations
├─ media/
│  ├─ audio/              # ★ 收件箱：你投放原始素材的地方，供「从素材目录导入」扫描
│  └─ library/<id>/       # 媒体库：original.<ext> + audio.wav(16k 单声道) + clips/(句子切片)
├─ models/                # whisper 模型
├─ dict/                  # ECDICT 词库（ecdict.db）
├─ logs/                  # app.log / console.log（静默模式的输出）
├─ backups/               # 就地更新前的 app.db 备份（保留最近 5 份）
└─ install.json           # 安装版本与时间
```

媒体处理状态机：

```
pending → transcoding → ready → asr → translating → clipping → done | failed
```

---

## 打包与交付

```powershell
# 完整交付包：内置模型 + 词典，完全离线可用（约 1.7 GB，zip 约 816 MB）
powershell -ExecutionPolicy Bypass -File packaging/build.ps1

# 轻量包：不含模型与词典，首启按需下载（约 0.5 GB）
powershell -ExecutionPolicy Bypass -File packaging/build.ps1 -Light

# 更新包：只含会变的程序文件（约 200 KB），给已装老版本的用户升级
powershell -ExecutionPolicy Bypass -File packaging/build-update.ps1
```

构建脚本会：取 Python 嵌入版 → 写 `._pth` → 装配依赖 → 补 VC++ 运行库 DLL → 拷代码与前端产物 → 生成用户脚本 → **强制跑 `launcher.py --check`**（不过则构建失败）→ 压缩并输出 SHA256。

更新包的构建期还会**断言包内不含 `data/`**，从设计上杜绝「更新覆盖用户数据」。

> 交付链的完整设计与踩坑记录见 `FayeLong英语学习网站-设计与开发计划-v1.md` 第 15、21 章。

---

## 接口一览

后端统一挂载在 `/api` 下，启动后可访问 `/docs` 查看交互式文档。

| 分组 | 主要接口 |
| --- | --- |
| 健康检查 | `GET /api/health` |
| 媒体 | `GET /api/media`、`GET /api/media/inbox`、`POST /api/media/import`、`GET /api/media/{id}`、`GET /api/media/{id}/stream`、`GET /api/media/{id}/progress`、`POST /api/media/{id}/retry`、`POST /api/media/{id}/retranscribe` |
| 句子 | `GET /api/media/{id}/sentences`、`PATCH /api/sentences/{id}`、`POST /api/sentences/{id}/split`、`merge`、`retranslate`、`GET /api/media/{id}/clips/{idx}` |
| 听写 | `POST /api/attempts`、`GET /api/sentences/{id}/attempts` |
| 词典 | `GET /api/dict/{word}` |
| 生词本 | `GET/POST /api/vocab`、`PATCH/DELETE /api/vocab/{id}`、`GET /api/vocab/export` |
| 笔记 | `GET/PUT /api/sentences/{id}/note`、`GET /api/media/{id}/notes`、`GET /api/media/{id}/notes/export` |
| 统计 | `GET /api/stats` |

---

## 项目状态

**M0–M6 全部里程碑已完成**，并在此基础上完成了三轮增强：

| 阶段 | 内容 |
| --- | --- |
| M0 | 前后端骨架、单端口托管、启动脚本 |
| M1 | 媒体导入与播放（ffprobe 探测 + ffmpeg 转码 + Range 流播放） |
| M2 | 语音识别 + 句子切分 + 逐句翻译 + 音频切片 全流程编排 |
| M3 | 单句听写页与词级标红校验 |
| M4 | ECDICT 离线词典、查词浮层、生词本、笔记 |
| M5 | A-B 循环、笔记汇总导出、全局异常兜底、媒体库概览与搜索排序 |
| M6 | 打包与交付链（完整包 / 轻量包 / 更新包、静默启动、就地更新） |
| 增强 | 生词朗读、三种生词练习模式（含单词听写） |

端到端验证均以「真实浏览器 + CDP 驱动」完成，或使用交付包内的运行时实跑服务冒烟；结果记录在设计文档各章的「验证记录」小节。

---

## 数据来源与声明

本项目为**个人学习自用**，非商业项目。

- **ECDICT** 离线词库：<https://github.com/skywind3000/ECDICT>（MIT），本项目只读取下载到 `data/dict/` 的数据文件，**不随仓库分发**。
- **faster-whisper / Whisper 模型**：<https://github.com/SYSTRAN/faster-whisper>，模型文件按需下载到 `data/models/`，**不随仓库分发**。
- **翻译**：调用有道公开演示接口与 MyMemory 作为兜底。两者均为免密钥公开服务，**请勿用于高频或商业用途**；接口可用性随服务方策略变化，失败时对应句子的翻译会留空而不影响其他功能。
- **ffmpeg**：<https://ffmpeg.org/>，构建与许可条款见其官网；便携版二进制由 `packaging/fetch-ffmpeg.ps1` 下载，**不随仓库分发**。
- 词库、模型、媒体素材等大体积资源已通过 `.gitignore` 排除，仓库内**只包含源代码与文档**。

请确保你导入的音频 / 视频素材拥有合法使用权。

---

## 已知踩坑（开发备忘）

- **npm install 需加 `--ignore-scripts`**：esbuild 的 postinstall 在受管 Node 上可能因沙箱限制失败（`EBUSY`）；原生包 `@esbuild/win32-x64` 已随 lockfile 提供，不影响构建。
- **pip 源**：清华镜像对 faster-whisper wheel 返回 403，改用阿里云镜像。
- **模型下载**：`huggingface.co` 国内直连不通，默认走 `hf-mirror.com`。
- **修改前端后必须先 `npm run build`** 再验证，否则后端托管的是旧产物。
- **`rm` 在本机被 safe-delete 包装拦截时会中断 `&&` 命令链**。
- 更多（含打包期 VC++ 运行库、zip 中文文件名编码、端口探测等）见设计文档的踩坑小节。

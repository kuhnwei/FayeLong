# FayeLong 英语学习网站 — 系统设计与开发计划

> 版本：**v1.6（M0–M4 已完成）**　｜　日期：2026-10-11　｜　状态：**M4 已交付，可进入 M5**
> 依据：《FayeLong英语学习网站需求第一版.md》+ 四轮需求确认结论
>
> **v1.6 关键变更**
> 1. **M4（词典 / 生词本 / 笔记）已完成**：本地 ECDICT 词库查词（含词形还原）→ 查词浮层 → 一键加入生词本 → 生词本页管理 → 导出 Markdown；每句笔记可编辑保存。
> 2. **词库完全离线**：ECDICT `stardict.db`（**340 万词条**，811.9 MB）落地 `data/dict/ecdict.db`，查询走 SQLite 只读连接 + 索引；不产生任何在线依赖。词库未收录时可用免费在线引擎兜底给出「参考释义」（可配置关闭）。
> 3. **词形还原两级策略**：① ECDICT `exchange` 字段 `0:` 原型反查（最准）；② lemminflect 生成候选原型 + 规则兜底，候选**必须能在词库查到**才采用，避免误还原。
> 4. **学习闭环打通**：原文按词可点击 → 浮层展示音标/释义/词形变化/考纲标签 → 加入生词本时自动带上**上下文句子与来源媒体**；生词本支持搜索、按掌握度筛选、编辑释义、导出 Markdown。
> 5. 新增 `scripts/verify_m4.mjs`（无头 Chrome + CDP 驱动）做**真实浏览器交互验证**，查词 → 加生词本 → 生词本页 → 笔记全链路 **12/12 通过**；新增 §19 M4 实现说明与验证记录。
> 6. 踩坑修正：ECDICT 含「音节拆分条目」（`hel-lo` / `chil-dren`），只按 `sw` 查询会命中错误条目；已改为「精确词形 → 排除连字符 → 兜底」三级查询。
>
> **v1.5 关键变更**
> 1. **M3（单句听写页）已完成并验证**：听写输入 → 提交 → **词级标红校验**（correct / wrong / missing / extra 四类）→ 正确率与掌握度 → 听写历史。
> 2. **判定权全部收在服务端**：`services/dictation.py` 是纯函数算法，`POST /api/attempts` 是唯一判定源，前端只负责渲染，避免前后端两套 diff 实现漂移。
> 3. **听写模式做到「答案零泄漏」**：原文/翻译默认隐藏且**不进入 DOM**（实测 `innerText` 不含句子原文），杜绝按 F12 抄答案。
> 4. 新增听写统计内嵌：句子级（尝试次数 / 最佳正确率 / 上次输入 / 是否掌握）与媒体级汇总（已听写 / 已掌握 / 平均最佳）。
> 5. 首次完成**真实浏览器交互验证**（无头 Chrome + CDP 驱动），不再是「仅靠类型检查推断」。
> 6. 新增 §18 M3 实现说明与验证记录。
>
> **v1.4 关键变更**
> 1. **M2（识别与翻译）已完成并验证**：`转码 → 识别 → 翻译 → 切片` 全流程自动跑通，导入后即产出英文原文、中文翻译与逐句音频切片。
> 2. **明确了运行环境实测结论**：Python **3.13 可直接运行** faster-whisper（无需退回 3.11），并移除了 PyAV 解码路径（改为自行解码标准音频），规避 `av` 版本兼容问题。
> 3. whisper `small` 模型（461MB）通过 **hf-mirror 镜像**下载，实测 ~39s 完成，已落地 `data/models/`。
> 4. 句子校对闭环落地：编辑 / 拆分 / 合并 / 单句重译 / 重新识别 / 清理切片。
> 5. 新增 §17 M2 实现说明与验证记录。
>
> **v1.3 关键变更**
> 1. **M1（媒体导入与播放）已完成并验证**：上传 / 收件箱批量导入 → ffprobe 探测 → ffmpeg 统一转码 → 媒体库管理 → Range 流式播放。
> 2. 运行时数据目录**统一到项目根 `data/`**（原先散落在 `backend/data` 与 `data/` 两处），满足 FR-D5「拷贝即迁移」。
> 3. 后端在 M1 阶段即打通**单端口静态托管**（FastAPI 直接服务前端构建产物），为 M6 一键启动提前验证主路径。
> 4. 状态机扩展：新增 `transcoding` / `ready` 两个中间态，M2 继续推进 `asr → translating → clipping → done`。
>
> **v1.2 关键变更**
> 1. 交付目标是**没有开发环境的笔记本** → 新增 §15 部署与分发方案（自带 Python 运行时的全量包 + 一键启动）。
> 2. 翻译由本地 NLLB 改为**免费在线多引擎**（免密钥、开箱即用），移除 PyTorch，包体积从 ~4GB 降到 ~1.2GB。
> 3. ffmpeg / ffprobe **便携版随包分发**，笔记本无需自行安装。

---

## 1. 项目概述

做一个**个人使用、可联网、免付费依赖**的英语精听/听写学习网站。用户导入英语音频（兼容视频，仅取音轨），系统自动生成英文原文与中文翻译；页面按**单句**组织，围绕每句提供「听写练习 → 原文核对 → 翻译查看 → 单词查词 → 笔记」的完整学习闭环。

**核心定位**：个人自用工具，**最终部署在一台没有开发环境的笔记本上**，要求小白式安装（拷贝文件夹 → 双击启动 → 浏览器使用）。数据落本机；语音识别用本地免费模型；翻译用免费在线接口。

---

## 2. 需求确认结论（硬约束）

| # | 决策点 | 结论 |
|---|--------|------|
| 1 | 整体架构 | 前端 + 轻量后端，部署在个人电脑（目标为**无开发环境的笔记本**） |
| 2 | 语音识别 | 本地 faster-whisper `small`（免费、离线） |
| 3 | 翻译 | **免费在线接口**，多引擎 + 缓存 + 自动回退（免密钥，开箱即用） |
| 4 | 数据保存 | 本地保存（本机 SQLite） |
| 5 | 单词字典查询 | 站内浮层释义 + 跳转牛津/朗文 |
| 6 | 视频处理 | **仅提取音轨**，不使用画面 |
| 7 | 句子音频切片 | **需要**，每句裁剪独立音频文件 |
| 8 | 导出 | 生词本、笔记支持导出 Markdown |
| 9 | 端类型 | **仅桌面端** |
| 10 | 账号 | **无需登录**，单用户 |
| 11 | 网络 | 允许联网使用；所依赖的互联网服务**必须免费** |

---

## 3. 功能需求清单

### 3.1 媒体导入与处理（FR-M）

| 编号 | 需求 | 说明 |
|------|------|------|
| FR-M1 | 导入音频文件 | 支持 mp3 / wav / m4a / flac / aac |
| FR-M2 | 兼容视频文件 | 支持 mp4 / mkv / mov / webm；**仅提取音轨**参与识别 |
| FR-M3 | 自动语音识别 | 本地 faster-whisper（默认 `small`）转成英文文本，带句级时间戳 |
| FR-M4 | 自动翻译 | **免费在线多引擎**逐句翻译（有道 → MyMemory 自动回退），结果本地缓存 |
| FR-M5 | 处理进度反馈 | 上传后异步处理，前端显示「解码→识别→翻译→切片」进度 |
| FR-M6 | 结果可校对 | 识别/翻译结果允许人工编辑修正，可拆分/合并句子、调整时间边界 |
| FR-M7 | 媒体库 | 已导入媒体列表，可重进学习页、删除 |

### 3.2 单句学习页（FR-S）

| 编号 | 需求 | 说明 |
|------|------|------|
| FR-S1 | 按句子排列 | 页面以句子为最小单元纵向排列，与音频时间戳联动 |
| FR-S2 | 听写练习 | 每句先播放音频，用户在输入框输入听到的内容，提交后检测对错 |
| FR-S3 | 错误标红 | 与原文比对，**错误的单词标红**；处理缺失/多余/拼错（见 §9.3） |
| FR-S4 | 原文显隐 | 英文原文默认隐藏，点击「显示原文」按钮才展开 |
| FR-S5 | 翻译显隐 | 中文翻译默认隐藏，点击「显示翻译」按钮才展开 |
| FR-S6 | 单词查词 | 选中英文中的单词，弹出释义浮层；另提供跳转牛津/朗文按钮 |
| FR-S7 | 加入生词本 | 同一浮层可一键把单词加入生词本（记录上下文句子） |
| FR-S8 | 句子笔记 | 每句下方有笔记输入框，可编辑保存 |

> **交付状态（M4）**：FR-S1 ~ S8 全部实现并验证（含查词浮层、加入生词本、句子笔记）；FR-A5 生词本管理（查看 / 编辑释义 / 标记掌握 / 删除 / 导出 Markdown）已交付。
> FR-A1 / A2 / A3（逐句播放、变速、播放控制）已在 M1/M2 交付；**FR-A4 听写历史的记录与查询已在 M3 落地**
> （历史面板 + 掌握度统计），其可视化增强留至 M5。**FR-A6 笔记汇总**与 FR-A5 的「按媒体导出」留至 M5。

### 3.3 学习辅助（FR-A）

| 编号 | 需求 | 说明 |
|------|------|------|
| FR-A1 | 逐句播放 | 点击句子播放该句（基于句子音频切片）；支持单句循环、A-B 循环 |
| FR-A2 | 语速调节 | 0.5x ~ 1.5x |
| FR-A3 | 播放控制 | 上一句 / 下一句 / 暂停 / 重播 |
| FR-A4 | 听写历史 | 记录每句听写尝试与正确率，展示掌握情况 |
| FR-A5 | 生词本管理 | 查看/编辑释义/标记已掌握/删除；支持导出 Markdown |
| FR-A6 | 笔记汇总 | 按媒体查看所有句子笔记；支持导出 Markdown |

### 3.4 部署与安装（FR-D）

| 编号 | 需求 | 说明 |
|------|------|------|
| FR-D1 | 零开发环境依赖 | 目标笔记本**无需**安装 Python / Node / ffmpeg |
| FR-D2 | 一键启动 | 双击一个启动脚本即可，自动打开浏览器 |
| FR-D3 | 自带运行时 | 包内自带 Python 运行时、全部依赖、ffmpeg、whisper 模型 |
| FR-D4 | 自检与提示 | 启动时自检依赖并给出清晰的中文提示（缺什么、怎么办） |
| FR-D5 | 数据可迁移 | `data/` 目录独立，拷贝即完成学习数据迁移 |

---

## 4. 非功能需求（NFR）

| 类别 | 要求 |
|------|------|
| 免费 | 全部使用开源/免费组件与免费在线接口，无任何付费调用 |
| 网络 | 允许联网；**翻译与首次模型准备需要网络**，其余功能本地运行 |
| 隐私 | 音视频与学习数据不出本机；仅待翻译的**文本句子**发往免费翻译接口 |
| 性能 | 10 分钟音频识别在 8GB 内存笔记本上可接受（模型 small，int8 量化） |
| 目标机型 | Windows 10/11 x64 笔记本，内存 **8 GB** |
| 端 | 仅桌面端，不做移动端适配 |
| 账号 | 无登录、单用户 |
| 易用 | 双击启动脚本 → 自动打开浏览器，无需命令行操作 |
| 可维护 | 前后端分离、模块清晰、有基础日志与自检脚本 |

---

## 5. 总体架构

**架构模式**：本地单体 —— 后端同时提供 API 与前端静态页面（单端口），浏览器访问 `http://127.0.0.1:8000`。

```
┌──────────────────────── 目标笔记本（无开发环境）────────────────────────┐
│                                                                         │
│   ┌────────────── 浏览器 ──────────────┐                                │
│   │  React SPA（由后端托管静态文件）      │                                │
│   │  媒体库 / 学习页(单句听写) / 生词本   │                                │
│   └──────────────▲─────────────────────┘                                │
│                  │ HTTP  (127.0.0.1:8000)                               │
│   ┌──────────────┴──────────────────────────────────────┐               │
│   │         内置 Python 运行时 + FastAPI                 │               │
│   │  ├─ 媒体服务   : ffmpeg 转码 / 句子音频切片            │               │
│   │  ├─ ASR 服务   : faster-whisper small（本地）          │               │
│   │  ├─ 翻译服务   : 免费在线多引擎 + 本地缓存 + 回退链     │──┐            │
│   │  ├─ 词典服务   : ECDICT 词库 + 词形还原                │  │            │
│   │  ├─ 导出服务   : 生词本 / 笔记 → Markdown              │  │            │
│   │  └─ 数据访问   : SQLAlchemy                           │  │            │
│   └──────────────┬───────────────────────────────────────┘  │            │
│                  │                                          │            │
│      ┌───────────▼───────────┐  ┌────────────────────┐      │            │
│      │ SQLite (data/app.db)  │  │ data/media         │      │            │
│      │ 媒体/句子/笔记/生词/尝试 │  │ 音视频 + 句子切片    │      │            │
│      │ /翻译缓存              │  │ + whisper 模型      │      │            │
│      └───────────────────────┘  └────────────────────┘      │            │
└────────────────────────────────────────────────────────────┼────────────┘
                                                              ▼
                                        Internet（免费、免密钥）
                                        ├─ aidemo.youdao.com   （翻译主力）
                                        └─ api.mymemory.translated.net（兜底）
```

**关键取舍**：ASR 必须本地（无免密钥的免费在线 ASR）；翻译用在线（免费接口质量优于同等体积的本地模型，且省掉 PyTorch 2.5GB，对小白部署友好）。

---

## 6. 技术选型

### 6.1 前端

| 用途 | 选型 | 理由 |
|------|------|------|
| 框架 | React 18 + TypeScript | 组件化、类型安全 |
| 构建 | Vite | 快速；产物为静态文件，交给后端托管 |
| 样式 | Tailwind CSS 3 | 快速搭建、样式可控 |
| 状态 | Zustand | 轻量 |
| 数据请求 | TanStack Query | 缓存 / 请求 / 进度轮询 |
| 音频 | HTML5 Audio + wavesurfer.js（可选波形） | 逐句播放 / 循环 / 变速 |
| 文本比对 | jsdiff (diff-match-patch) | 单词级差异比对标红 |

### 6.2 后端

| 用途 | 选型 | 理由 |
|------|------|------|
| Web 框架 | FastAPI + Uvicorn | 异步、类型友好、适配 Python ML 生态 |
| 语言 | Python **3.11**（打包内置） | ctranslate2/faster-whisper 轮子最稳 |
| ORM/DB | SQLAlchemy + SQLite | 单机零配置，文件即数据库 |
| 音频转码 | **便携版 ffmpeg / ffprobe**（随包） | 视频解码、句子切片；笔记本无需安装 |
| 语音识别 | faster-whisper `small`（int8，CTranslate2 加速） | 免费、离线、8GB 内存可跑 |
| 翻译 | **在线多引擎**：有道公开接口 → MyMemory | 免密钥、免注册、开箱即用；质量由有道保障 |
| HTTP 客户端 | Python 标准库 `urllib` | 零额外依赖，减小打包体积 |
| 词典 | **ECDICT 全量词库**（实测 **340 万词条**，811.9 MB）+ 词形还原（exchange 反查 + lemminflect） | 免费、离线 |
| 后台任务 | FastAPI BackgroundTasks + 线程池 | 识别/翻译耗时长，避免阻塞请求 |
| 静态托管 | FastAPI StaticFiles | 单端口部署，无需 Node 运行时 |

### 6.3 为什么是 Python 后端 + 静态前端

- ASR（faster-whisper）、词形还原的生态在 Python，本地推理必须用 Python；
- 前端构建为静态文件后由 FastAPI 托管，**目标笔记本无需 Node**，端口只有一个，防火墙与"小白化"都更友好。

---

## 7. 关键实现方案

### 7.1 媒体处理管线

```
上传文件 → ffprobe 探测(时长/格式) → ffmpeg 统一转 16kHz 单声道 wav
        → faster-whisper(small) 识别(输出 segments: start/end/text)
        → 句子切分(按 segment + 标点) → 逐句在线翻译（带缓存与限速）
        → 按句子时间戳裁剪音频切片(每句一个 mp3)
        → 写入 SQLite → 前端可进入学习页
```
- 长音频：分块识别并实时回传进度（SSE）。
- 视频：仅提取音轨，原始文件入库保留但学习页不播放画面。

### 7.2 句子切分策略

1. 以 whisper `segments` 为基础切分；
2. 超长 segment 按句末标点（. ? !）二次切分；
3. 保留 `start_ms / end_ms` 用于逐句播放与高亮联动；
4. 提供人工「拆分 / 合并 / 调整时间边界」。

**v1.4 落地细节**：开启 `word_timestamps`，以**词级时间戳**为单位累积成句——遇到句末标点即断句，
并在「超长（>15s）」「超字数（>180 字）」「whisper 分段结束」三处强制断句；
断句后把过短的句子（<0.7s，如单独的 "Yes."）并入相邻句，避免产生碎片。全部阈值可在配置中调整。

### 7.3 语音识别（本地）

- faster-whisper，默认模型 **`small`**，语言 `en`，`device=cpu`、`compute_type=int8`（8GB 笔记本友好）；
- 可在设置中降级为 `base` / `tiny`（低配保底）；
- 模型文件随包分发到 `data/models/`，**首次使用无需下载**。

**工程实现（v1.4 落地）**

| 要点 | 做法 |
|------|------|
| Python 版本 | 实测 **3.13 可用**（faster-whisper 1.2.1 / ctranslate2 4.8.2），无需退回 3.11 |
| 音频输入 | **不使用 PyAV 解码**：标准音频固定为 16k/单声道/s16，直接自行解码为 numpy 数组传给模型，绕开 `av` 版本兼容坑，且省去一次重复解码 |
| 音频兜底 | 非规范 wav 时改用 ffmpeg 解码为裸 PCM 流 |
| 模型获取 | 本地 `data/models/faster-whisper-<规格>/` 优先；缺失时经 `hf_endpoint`（默认 `hf-mirror.com`）按字节粒度下载，**带断点续传** |
| 下载实现 | 直接走镜像 REST 接口 + `urllib`，不依赖 `huggingface_hub` 的参数签名（不同大版本差异大） |
| 延迟导入 | `faster_whisper` 仅在识别时导入，未装 ML 依赖时后端仍可正常启动（M1 功能不受影响） |
| 模型单例 | 进程内按 `(规格, 设备, 精度)` 缓存，避免重复加载（加载一次约 3–5s） |
| 静音处理 | `vad_filter=True`（Silero VAD，随包内置），抑制长静音段的幻听 |
| 上下文 | `condition_on_previous_text=False`，避免长音频把前一错误反复传播 |

### 7.4 翻译（免费在线 + 缓存 + 回退）

**引擎链（按序自动回退，全部免密钥、免注册）**

| 顺序 | 引擎 | 接口 | 特点 |
|------|------|------|------|
| 1 | 有道公开演示接口 | `POST https://aidemo.youdao.com/trans` | 质量好，返回 `translation[]` |
| 2 | MyMemory | `GET https://api.mymemory.translated.net/get` | 配额兜底，可选填邮箱提升额度 |

**工程保障**
1. **本地缓存**：`translations` 表按 `sha1(src|tgt|text)` 缓存，同一句永不重复请求 → 大幅节省免费额度；
2. **限速**：逐句请求间隔 150ms，避免触发限流；
3. **超时与重试**：单引擎 12s 超时，失败自动换下一个；
4. **兜底**：全部引擎失败时保留空翻译，由 `FR-M6` 人工编辑补齐；
5. **可扩展**：引擎以注册表形式实现，后续可插入新的免费引擎或用户自带的免费额度 Key。

> ⚠️ 风险提示：以上均为**非官方公开接口**，存在随时调整或限流的可能。为此设计了「多引擎 + 缓存 + 人工编辑」三重保障；若长期不可用，可在设置中切换引擎顺序或补充自有免费 Key。

### 7.5 句子级音频切片

- 处理阶段按每句 `start_ms/end_ms` 裁剪为独立音频（`data/media/<id>/clips/<idx>.mp3`）；
- 学习页逐句播放直接加载切片，**单句循环零误差**；
- 提供「清理 / 重建切片」入口以回收磁盘。

### 7.6 导出（Markdown）

- 生词本：`单词 | 音标 | 释义 | 上下文句子 | 来源媒体` → Markdown 表格；
- 笔记：按媒体汇总 `句子原文 / 翻译 / 笔记` → Markdown；
- 后端生成 `.md` 供浏览器下载。

---

## 8. 数据模型设计（SQLite）

```sql
media(id, title, type, original_name, file_path, audio_path, size_bytes,
      duration_ms, status, progress, error, origin, source_ref, created_at)
sentences(id, media_id→media, idx, start_ms, end_ms,
          text_en, text_zh, clip_path, is_edited)
attempts(id, sentence_id→sentences, input, accuracy, is_correct, created_at)
notes(id, sentence_id→sentences [unique], content, updated_at)
vocab(id, word, lemma, phonetic, translation,
      media_id, sentence_id, context, mastered, created_at)
settings(key PK, value)
translations(key PK, source_text, target_text, engine, created_at)   -- 翻译缓存
```

`media` 关键字段说明：

| 字段 | 说明 |
|------|------|
| `file_path` | 原始文件（视频也完整保留，便于日后重处理） |
| `audio_path` | **转码后的 16kHz 单声道 wav**，ASR / 切片 / 播放统一用它 |
| `origin` | `upload`（页面上传）/ `inbox`（素材目录导入） |
| `source_ref` | 收件箱导入时的源文件绝对路径，用于「已导入」去重 |
| `size_bytes` / `duration_ms` | 列表展示与进度计算 |

**状态机**：`pending → transcoding → ready → asr → translating → clipping → done | failed`

- `pending` 已入库待处理；`transcoding` 探测 + 转码中（`progress` 0–99）；
- `ready` **M1 的终态**：标准音频就绪、可播放，等待 M2 识别；
- `failed` 任意阶段失败，`error` 记录中文原因，前端提供「重新处理」；
- 服务重启时会把仍处于 `pending` / `transcoding` 的任务**自动重新排队**（自愈）。

`attempts` 使用约定（M3）：

- 每次提交听写**追加**一行（不覆盖），这是「听写历史」与掌握度统计的唯一数据源；词级明细不落库，
  由 `services/dictation.py` 在提交时即时算出并随响应返回（重新计算成本极低，且避免明细格式演进带来的迁移问题）。
- 派生指标：`attempt_count` = 行数；`best_accuracy` = `max(accuracy)`；
  `last_input / last_accuracy` = 最后一行；`mastered` = 存在 `is_correct = true` 的行。

---

## 9. 前端交互设计

### 9.1 页面结构

```
/                 → 媒体库页（导入、列表、处理进度、环境自检）
/study/:mediaId   → 学习页（核心：单句听写）
/vocab            → 生词本页（含导出 Markdown）
```

### 9.2 学习页单句卡片布局（自上而下，M3 已落地）

```
┌──────────────────────────────────────────────────────────────┐
│ [▶/⏸ 本句] [🔁 循环]  0:00–0:10 (10.4s)  [已掌握]   [拆分][合并][重译][编辑] │
├──────────────────────────────────────────────────────────────┤
│ 听写区（浅灰底）                                                │
│  ┌──────────────────────────────────┐  ┌────────┐             │
│  │ 听音频，写下你听到的内容…           │  │  提交   │             │
│  └──────────────────────────────────┘  ├────────┤             │
│                                        │重听│清空│             │
│  正确率 87.5%  正确 7/8 · 错 1   [完全正确]                     │
│  I  received  a  letter  this  morning.        ← 红字=拼错/漏词  │
│  纠错  recieved → received                                      │
│  🕘 听写历史（3）   上次 87.5%「I recieved a letter…」            │
├──────────────────────────────────────────────────────────────┤
│  [显示原文]  →  （点击后展开）I received a letter this morning.   │
├──────────────────────────────────────────────────────────────┤
│  [显示翻译]  →  （点击后展开）我今天早上收到了一封信。             │
└──────────────────────────────────────────────────────────────┘
```

页面头部另有**听写进度条**：`已听写 3/6 句 · 已掌握 1 句 · 提交 7 次 · 平均最佳 92.5%`，
以及「展开全部原文 / 展开全部翻译 / 全部折叠」批量开关与「提交后自动显示原文」偏好。

### 9.3 听写校验与标红算法（M3 已实现）

1. **文本标准化**：`’→'`；按设置决定是否小写化与去标点（`dictation_ignore_case` / `dictation_ignore_punctuation`，默认都忽略）。
   归一化时只保留字母、数字与**词内**撇号（`don't` 不拆），因此 `letter.` ≡ `letter`、`Ask` ≡ `ask`。
2. **分词**：按空白切分；**展示用保留原标点**（`letter.`），**比对用归一化**（`letter`），故标点差异不影响判分也不丢展示信息。
3. **对齐比对**：`difflib.SequenceMatcher` 求最长匹配块，输出四类：
   | 类型 | 含义 | 前端呈现 |
   |------|------|----------|
   | `correct` | 完全正确 | 正常色 |
   | `wrong` | 拼错 / 用错词 | 标红 + 波浪下划线，悬停显示正确形式 |
   | `missing` | 漏掉某词 | 红色**虚线下划线**，显示标准答案里的词 |
   | `extra` | 多写某词 | 灰色**删除线** |
4. **正确率** = 正确词数 / 标准答案词数 × 100%（多写词不参与分母）。
5. **完全正确** = 正确率 ≥ `dictation_pass_accuracy`（默认 100）**且无多写词**。
   注意：多写词不会拉低正确率，因此必须单独排除，否则「多写一个词」会被误判为已掌握。
6. 结果写入 `attempts`；「是否掌握」= 该句**曾出现过一次完全正确**。

### 9.4 组件树（核心，M3 后）

```
<StudyPage>                          // 听写进度汇总 + 批量显隐开关
 ├─ <MediaHeader/>
 ├─ <AudioPlayerController/>         // 播放/循环/语速（基于句子切片）
 └─ <SentenceList>
     └─ <SentenceCard>
         ├─ <DictationBox>           // ★ M3：听写输入 + 提交/重听/清空
         │   ├─ <DiffResult/>        // ★ M3：四类 token 渲染 + 正确率 + 纠错提示
         │   └─ <AttemptHistory/>    // ★ M3：听写历史（折叠）
         ├─ <RevealPanel type="en"/> // 默认隐藏，且不进入 DOM
         ├─ <RevealPanel type="zh"/>
         ├─ <NoteEditor/>            // ★ M4：句子笔记（失焦自动保存）
         └─ <WordPopover/>           // ★ M4：词典浮层 + 加生词本
```

---

## 10. API 接口设计（草案）

| 方法 | 路径 | 说明 | 状态 |
|------|------|------|------|
| GET | `/api/health` | 健康检查与依赖自检（ffmpeg / ffprobe / 数据库 / 翻译引擎 / 数据目录） | ✅ M0 |
| POST | `/api/media` | 上传音频/视频（multipart），返回媒体对象，后台转码 | ✅ M1 |
| GET | `/api/media` | 媒体列表（含状态 / 进度 / 时长 / 大小） | ✅ M1 |
| GET | `/api/media/{id}` | 媒体详情 + 句子列表 | ✅ M1 |
| PATCH | `/api/media/{id}` | 重命名标题 | ✅ M1 |
| DELETE | `/api/media/{id}` | 删除媒体及其数据（含原文件 / 转码音频 / 切片） | ✅ M1 |
| POST | `/api/media/{id}/retry` | 重新处理（失败重试） | ✅ M1 |
| GET | `/api/media/inbox` | 列出收件箱素材及是否已导入 | ✅ M1 |
| POST | `/api/media/import` | 从收件箱批量导入（不传 files 则导入全部新增） | ✅ M1 |
| GET | `/api/media/{id}/stream` | 音频流（**支持 HTTP Range**，供拖动/续播） | ✅ M1 |
| GET | `/api/media/{id}/progress` | **SSE** 推送处理进度（`转码→识别→翻译→切片`），完成/失败后自动结束 | ✅ M2 |
| POST | `/api/media/{id}/retranscribe` | 重新识别（保留已转码音频，重建句表） | ✅ M2 |
| GET | `/api/media/{id}/clips/{idx}` | 获取句子音频切片（**支持 Range**，供单句循环） | ✅ M2 |
| DELETE | `/api/media/{id}/clips` | 清理切片以回收磁盘 | ✅ M2 |
| PATCH | `/api/sentences/{id}` | 编辑原文/翻译/时间边界（改动时间会重切切片） | ✅ M2 |
| POST | `/api/sentences/{id}/split` | 在指定时间点拆分句子（自动重译 + 重切） | ✅ M2 |
| POST | `/api/sentences/{id}/merge` | 与相邻句合并（默认向后） | ✅ M2 |
| POST | `/api/sentences/{id}/retranslate` | 重新翻译单句 | ✅ M2 |
| GET | `/api/dict/{word}` | 词典查询（ECDICT 词库 + 词形还原；未收录可在线兜底） | ✅ M4 |
| GET | `/api/vocab` | 生词本列表（可按掌握度筛选 / 关键词搜索） | ✅ M4 |
| POST | `/api/vocab` | 加入生词本（同词幂等，自动补全上下文与来源） | ✅ M4 |
| PATCH | `/api/vocab/{id}` | 修改释义 / 上下文 / 标记已掌握 | ✅ M4 |
| DELETE | `/api/vocab/{id}` | 删除生词 | ✅ M4 |
| GET | `/api/vocab/export` | 导出整个生词本为 Markdown | ✅ M4 |
| GET | `/api/notes/{sentenceId}` | 读取笔记 | ✅ M4 |
| PUT | `/api/notes/{sentenceId}` | 保存笔记（空内容即删除） | ✅ M4 |
| GET | `/api/media/{id}/notes/export` | 导出该媒体笔记为 Markdown | ⏳ M5 |
| POST | `/api/attempts` | 提交一次听写（服务端词级校验 + 落库，返回标红明细与统计） | ✅ M3 |
| GET | `/api/sentences/{id}/attempts` | 某句的听写历史（倒序，供「听写历史」面板） | ✅ M3 |

---

## 11. 项目目录结构

```
FayeLong/                          # 开发仓库
├─ backend/
│  ├─ app/
│  │  ├─ main.py                   # FastAPI 入口（同时托管前端静态文件，单端口）
│  │  ├─ api/                      # health.py / media.py / sentences.py
│  │  │                            #   / attempts.py(听写提交+历史，M3)
│  │  │                            #   （dict / vocab / note / attempts 已就绪）
│  │  ├─ services/                 # media.py(转码+流程编排) / asr.py(识别+切句)
│  │  │                            #   / clip.py(切片) / translate.py(在线翻译+缓存)
│  │  │                            #   / dictation.py(词级标红算法，M3，纯函数)
│  │  │                            #   / study.py(听写统计聚合，M3)
│  │  ├─ core/                     # config.py / paths.py(路径+MediaError)
│  │  │                            #   / tools.py(ffmpeg解析) / files.py(Range响应)
│  │  │                            #   / tasks.py(线程池) / logging.py
│  │  ├─ models/  schemas/  db.py
│  ├─ scripts/selftest.py          # 环境自检（含听写算法断言，M3）
│  ├─ requirements.txt             # 运行依赖
│  └─ requirements-ml.txt          # 推理依赖（faster-whisper 等，M2）
├─ frontend/                       # Vite + React 源码
│  └─ src/{pages,components,api,store,hooks,utils}
│      ├─ components/DiffResult.tsx    # ★ M3：四类 token 渲染
│      └─ pages/StudyPage.tsx          # ★ M3：含 DictationBox 听写区
├─ data/                           # ★ 唯一运行时数据目录（拷贝即迁移，FR-D5）
│  ├─ app.db                       # SQLite
│  ├─ media/audio/                 # 收件箱：用户投放原始素材
│  ├─ media/library/<id>/          # 媒体库：original.* + audio.wav + clips/<idx>.mp3
│  ├─ models/                      # whisper 模型（faster-whisper-small，约 461MB）
│  ├─ dict/  logs/
├─ tools/ffmpeg/                   # 便携版 ffmpeg.exe / ffprobe.exe
├─ scripts/                        # dev.bat / start-backend.bat / start-frontend.bat
└─ packaging/                      # 打包脚本（见 §15）
```

---

## 12. 开发计划（里程碑）

| 里程碑 | 内容 | 交付物 | 复杂度 |
|--------|------|--------|--------|
| **M0 骨架** ✅ | 前后端工程初始化、自检、连通 | 页面可开、`/api/health` 通 | 低 |
| **M1 媒体导入与播放** ✅ | 上传、ffmpeg 转码、媒体库、播放器 | 能导入音频并播放 | 中 |
| **M2 识别与翻译** ✅ | faster-whisper(small)、句子切分、在线翻译+缓存、音频切片、进度 SSE | 导入后自动出原文+翻译+切片 | 高 |
| **M3 单句听写页** ✅ | 听写输入、词级标红校验、正确率/掌握度、原文/翻译显隐、听写历史 | 核心学习页可用 | 中 |
| **M4 词典/生词本/笔记** ✅ | ECDICT、词形还原、浮层、生词本、笔记 | 查词与笔记闭环 | 中 |
| **M5 打磨** | 循环播放、Markdown 导出、异常处理、UI 优化 | 稳定可长期使用 | 中 |
| **M6 打包与交付** ⭐ | 内置 Python 运行时、依赖冻结、模型内置、一键启动脚本、自检、说明文档、生成 zip | **可在无开发环境笔记本上一键跑起来的交付包** | 高 |

> ⭐ M6 是「交付到笔记本」的关键里程碑，依赖 M1–M2 的能力全部就绪。**M1–M2 已完成，M6 的前置条件已满足**；建议 M3–M5 收敛后再打包，避免重复打包。

**M3 完成情况（2026-10-11）**：听写闭环与标红校验全链路已跑通，并通过**真实浏览器交互测试**验证；
「句子笔记」与「单词查词/生词本」仍属 M4。

---

## 13. 风险与应对

| 风险 | 影响 | 应对 |
|------|------|------|
| 免费在线翻译接口失效/限流 | 翻译拿不到 | 多引擎回退 + 本地缓存 + 人工编辑兜底；引擎可配置 |
| 8GB 笔记本 CPU 识别较慢 | 长音频等待久 | 模型 small（int8）；可降 base/tiny；分块 + 进度反馈 |
| 打包体积较大（含模型 ~1.2GB） | 拷贝慢 | 模型与代码分离，可分卷；或改为首次自动下载模型 |
| 目标机器缺 VC++ 运行库 | 二进制无法加载 | 打包时检测并附带安装指引 |
| 句子切片占磁盘 | 大媒体占用翻倍 | 提供「清理 / 重建切片」入口 |
| 端口被占用 | 启动失败 | 启动脚本自动探测空闲端口并提示 |
| 打包后路径变化 | ffmpeg/模型找不到 | `core/tools.py` 多候选路径 + 环境变量覆盖 |

---

## 14. 已确认决策汇总（方案冻结依据）

**第一轮（核心 4 项）**
1. 架构：前端 + 轻量后端，本地部署。
2. ASR/翻译：全免费，不调用付费 API。
3. 数据：本地保存（SQLite）。
4. 字典：站内浮层释义 + 跳转牛津/朗文。

**第二轮（补充 7 项）**

| # | 决策点 | 结论 |
|---|--------|------|
| 1 | ASR 模型 | faster-whisper `small` |
| 2 | 翻译引擎 | ~~NLLB-200~~ → 见第三轮修正 |
| 3 | 视频处理 | 仅提取音轨 |
| 4 | 句子音频切片 | 需要 |
| 5 | 导出 | 生词本、笔记导出 Markdown |
| 6 | 端类型 | 仅桌面端 |
| 7 | 账号 | 无需登录 |

**第三轮（部署形态 3 项）**

| # | 决策点 | 结论 |
|---|--------|------|
| 1 | 交付包形态 | **全量包**（自带 Python 运行时 + 依赖 + ffmpeg + 模型） |
| 2 | 翻译方案 | **免费在线翻译**（免密钥多引擎），移除 PyTorch/NLLB |
| 3 | 目标机内存 | **8 GB**（模型 small + int8 量化） |

**第四轮（补充）**

| # | 决策点 | 结论 |
|---|--------|------|
| 1 | ffmpeg | 由开发方安装并**随包分发便携版** |
| 2 | 网络 | 允许联网使用；依赖的互联网服务必须**免费** |

**第五轮（M3 实现期确定，2026-10-11）**

| # | 决策点 | 结论 | 理由 |
|---|--------|------|------|
| 1 | 听写判定位置 | **服务端唯一判定**（`POST /api/attempts`） | 避免前后端两套 diff 漂移；本机往返毫秒级，无性能代价 |
| 2 | 标点与大小写 | 默认**都忽略**，可用配置项关闭 | 听写关注「听没听清」，不考标点书写 |
| 3 | 「完全正确」判据 | 正确率 ≥ 阈值（默认 100）**且无多写词** | 多写词不参与正确率分母，必须单独排除 |
| 4 | 显示与比对 | 分词保留 `display` + `norm` 双份 | 判分忽略标点，界面仍原样显示 `letter.` |
| 5 | 原文/翻译隐藏方式 | **不渲染进 DOM**（而非 CSS 遮挡） | 否则 F12 即可看到答案，听写练习失去意义 |

---

## 15. 部署与分发方案（v1.2 新增）

### 15.1 目标与约束

- 目标机：Windows 10/11 x64 笔记本，8GB 内存，**无 Python / Node / ffmpeg，无开发经验**。
- 用户操作应只有：**解压 → 双击 → 浏览器自动打开**。

### 15.2 交付包结构

```
FayeLong/                          # 解压即得，整体可拷贝
├─ 启动 FayeLong.bat              # ★ 用户唯一需要双击的文件
├─ runtime/
│  ├─ python/                     # 内置 Python 3.11 运行时（embeddable）
│  ├─ site-packages/              # 预装全部依赖（faster-whisper 等）
│  └─ ffmpeg/ffmpeg.exe, ffprobe.exe
├─ app/                           # 后端代码（app/ 包）
├─ static/                        # 前端构建产物（Vite build）
├─ models/
│  └─ faster-whisper-small/       # 随包分发的本地模型
├─ data/                          # 运行时生成：app.db / media / clips
├─ 使用说明.txt                   # 图文说明（首次使用、常见问题）
└─ 卸载.bat                       # 说明如何彻底删除
```

### 15.3 启动流程（`启动 FayeLong.bat`）

1. 检测 Python 运行时与依赖是否完整，缺失则给出中文提示；
2. 检测 ffmpeg/ffprobe 是否可执行；
3. 检测端口（默认 8000），被占用则自动改用 8001 等；
4. 启动 Uvicorn（不弹黑框，日志写入 `data/logs/`）；
5. 自动打开默认浏览器到 `http://127.0.0.1:<port>`；
6. 托盘/窗口提供「停止服务」入口。

### 15.4 打包流程（开发机执行，`packaging/build.ps1`）

1. 下载 Python 3.11 embeddable 包 → `runtime/python`；
2. `pip install --target runtime/site-packages -r requirements.txt`（锁定版本号）；
3. 复制已下载的 `tools/ffmpeg` → `runtime/ffmpeg`；
4. 前端 `npm run build` → 产物复制到 `static/`；
5. 下载 faster-whisper `small` 模型 → `models/`；
6. 生成启动脚本与说明文档；
7. 压缩为 `FayeLong-v{版本}-win64.zip`（可分卷）并输出校验值。

### 15.5 可选简化模式（网络良好时）

若不想携带 ~1GB 模型：交付包去掉 `models/`，改为**首次启动自动下载模型**（显示进度）。两个模式由打包脚本的参数切换，用户按网络情况二选一。

---

> M0、M1、M2 已完成并验证通过，下一阶段进入 **M3 单句听写页**。

---

## 16. M1 实现说明（媒体导入与播放）

### 16.1 已交付能力

| 能力 | 实现 |
|------|------|
| 上传导入 | 页面选择文件 / 拖拽上传，`multipart` 流式落盘，带上传进度条 |
| 收件箱导入 | 文件放进 `data/media/audio/` → 面板扫描 → 勾选或全部导入（原文件保留） |
| 媒体探测 | `ffprobe` 读取时长、格式、音视频轨道数，识别「有画面」还是「纯音频」 |
| 统一转码 | `ffmpeg` 转 **16kHz / 单声道 / pcm_s16le wav**（视频自动丢画面流），实时回传进度 |
| 媒体库 | 列表（状态 / 进度 / 时长 / 大小 / 来源）、展开式详情、重命名、删除（含文件）、失败重传 |
| 播放 | 底部常驻播放条：播放/暂停、前后跳 5 秒、进度拖动、**0.5x–1.5x 变速**、单曲循环 |
| 进度反馈 | 处理中列表每 1.5s 自动轮询；页面刷新后进度不丢（进度落库） |
| 单端口托管 | FastAPI 直接服务 `frontend/dist`，非 `/api` 路径做 SPA 回退 |

### 16.2 关键工程决策

1. **播放走 `Range` 请求**：`core/files.py` 自行实现 `206 Partial Content` + `Content-Range`
   （不依赖框架版本行为），否则浏览器无法拖动进度、变速、续播。已实测
   `Range: bytes=100-999` → `206 Content-Range: bytes 100-999/384078`。
2. **转码进度从 `ffmpeg -progress pipe:1` 读取**：错误信息写临时文件而非管道，
   避免管道缓冲区互锁导致的假死；`out_time_us/out_time_ms` 均按微秒处理（ffmpeg 的已知命名坑）。
3. **播放源自动降级**：转码完成前播放原始音频文件；完成后自动切换到标准 wav。
   视频在处理中不提供播放（无可用音轨）。
4. **失败可诊断**：`ffprobe` / `ffmpeg` 的 stderr 末行会作为中文原因写进 `media.error`，
   直接展示给用户，而不是只报「处理失败」。
5. **重启自愈**：服务启动时把 `pending` / `transcoding` 的任务重新入队，
   长时间音频被中断后不必手工重来。
6. **数据目录统一到 `data/`**：原 `backend/data` 已废弃（该目录下仅有自动生成的空结构库）。

### 16.3 验证记录（2026-10-10）

| 用例 | 结果 |
|------|------|
| mp3 上传（12s / 283KB） | ✅ 转码完成，时长 12042ms，`audio.wav` 384KB |
| mp3 收件箱导入 | ✅ 导入并被识别为「已导入」，重复导入自动跳过 |
| mp4（h264 + aac）导入 | ✅ `type=video`，产物 wav 仅含 1 条 `pcm_s16le` 音轨（画面已丢弃） |
| 不支持格式（.txt） | ✅ 400 + 中文提示支持的格式清单 |
| `Range: bytes=100-999` | ✅ `206`，`Content-Range: bytes 100-999/384078` |
| 重命名 / 删除 | ✅ 删除后媒体库目录一并清除 |
| 单端口 SPA | ✅ `/`、`/vocab`、`/study/1` 均返回前端；`/api/xxx` 返回 404 而非 HTML |
| 前端构建 | ✅ `tsc --noEmit` 无错误，91 模块 |

### 16.4 留给 M2 的接口预留

- `Sentence` 表与 `clip_path` 字段已就位，`/api/media/{id}` 已返回 `sentences`（当前为空数组）；
- `clips_dir(media_id)` 与 `GET /api/media/{id}/clips/{idx}` 的 URL 约定已定，M2 直接落实现；
- 状态机 `ready → asr → translating → clipping → done` 前端已能渲染（`STATUS_LABEL` 已覆盖）。

---

## 17. M2 实现说明（识别与翻译）

### 17.1 已交付能力

| 能力 | 实现 |
|------|------|
| 语音识别 | 本地 faster-whisper `small`（CPU/int8），词级时间戳 + Silero VAD |
| 句子切分 | 按句末标点断句 + 超长/超字数强制断句 + 过短合并（§7.2） |
| 逐句翻译 | 有道 → MyMemory 引擎链自动回退 + `translations` 表缓存 + 150ms 限速 |
| 句子切片 | 每句裁成 `clips/<idx>.mp3`（64kbps，首尾各留 120ms），单句循环零误差 |
| 流程编排 | `pending → transcoding → asr → translating → clipping → done`，进度落库 |
| 进度反馈 | `GET /api/media/{id}/progress` **SSE** 推送（含阶段中文名与已切句数），前端另有轮询兜底 |
| 结果校对 | 编辑原文/翻译/时间边界、按播放位置拆分、与下句合并、单句重译、重新识别、清理切片 |
| 重启自愈 | 启动时把 `pending/transcoding/ready/asr/translating/clipping` 的任务全部重新排队 |

### 17.2 关键工程决策（含踩坑记录）

1. **Python 3.13 直接可用**：faster-whisper 1.2.1 + ctranslate2 4.8.2 + onnxruntime 1.31.0 在 3.13 下均有轮子，
   **不需要退回 3.11**（`requirements-ml.txt` 里的旧提示已删除）。
2. **绕开 PyAV 解码**：faster-whisper 1.2.1 内部调用 `av.open(..., metadata_errors=...)`，
   而 PyAV 19 已移除该参数 → 传文件路径会直接 `TypeError`。
   由于标准音频固定为 16k/单声道/s16，改为**自行解码为 numpy 数组**传入模型，
   彻底避开版本兼容问题，并省掉一次重复解码。
3. **模型下载不依赖 `huggingface_hub`**：其 2.x 大版本移除了 `endpoint` 参数，
   故直接用镜像的 REST 接口（`/api/models/<repo>` 列文件 + `resolve/main/<file>` 下载）配合 `urllib`，
   自带**断点续传**与字节级进度回报；实测 hf-mirror 约 39s 下载完 461MB。
4. **数据完整性**：为 SQLite 打开 `PRAGMA foreign_keys=ON`（默认关闭），
   使 `sentences/notes/attempts` 的 `ON DELETE CASCADE` 真正生效，避免孤儿数据。
5. **切片文件名跟随 `idx`**：拆分/合并后需要重排 `idx`，切片的文件名也必须跟着改。
   采用**两阶段改名**（先统一改临时名，再落到最终名）避免互相覆盖。
6. **`services/clip.py` 不反向依赖 `services/media.py`**：把 `MediaError` 与路径工具抽到
   `core/paths.py`，消除循环依赖。
7. **未安装 ML 依赖不影响 M1**：`faster_whisper` 延迟导入，`/api/health` 如实报告 `asr: false`。

### 17.3 验证记录（2026-10-11）

| 用例 | 结果 |
|------|------|
| 模型下载（461MB，hf-mirror） | ✅ 39s 完成，`data/models/faster-whisper-small/` 就位 |
| 11s 英文语音识别 | ✅ 4.9s 完成（含首次加载），译文逐字正确 |
| 句子切分 | ✅ 长句按标点/时长正确断句，过短句自动合并 |
| 在线翻译 | ✅ 有道返回「因此，我的美国同胞们，不要问国家能为你们做些什么……」 |
| 翻译缓存 | ✅ 同一句第二次请求命中缓存（`engine=cache`），不重复占用免费额度 |
| mp3 切片 | ✅ `libmp3lame` 可用，产物 84KB / 10.4s，`audio/mpeg` |
| 切片 Range 播放 | ✅ `Range: bytes=1000-2999` → `206`，`Content-Range: bytes 1000-2999/85869` |
| 视频素材（mp4 带画面） | ✅ `type=video`，仅音轨参与识别，切片正常 |
| SSE 进度 | ✅ 依次收到 `asr 20% → clipping 90% → done 100%`（翻译命中缓存，阶段极短） |
| 拆分 / 合并 / 重译 / 编辑 | ✅ 均生效，`idx` 与切片文件名同步重排 |
| 清理切片 / 重新识别 | ✅ 清理后 `clip_url` 变 `null`；重新识别后切片与句子恢复 |
| 重启自愈 | ✅ 服务重启后自动续做未完成任务（M2 全流程随之跑完） |
| 单端口托管 | ✅ `/`、`/study/1` 返回前端；`/api/nope` 返回 404 JSON |
| 前端构建 | ✅ `tsc --noEmit` 无错误，92 模块，JS 250KB（gzip 78KB） |

### 17.4 留给 M3/M4 的接口预留

- `attempts` 表已就位，`POST /api/attempts` 待 M3 实现（听写记录与正确率）；
- `notes` 表已就位（每句至多一条），M4 直接落实现与导出；
- 学习页已按「句子卡片」结构组织，M3 只需在卡片内加入听写输入框与标红校验区。

---

## 18. M3 实现说明（单句听写页）

### 18.1 已交付能力

| 能力 | 实现 |
|------|------|
| 听写练习 | 每句一张卡片内置输入框，`Enter` 提交、`Shift+Enter` 换行，支持输入法组词不误触 |
| 词级标红校验 | `services/dictation.py` 纯函数算法，输出 `correct / wrong / missing / extra` 四类标记 |
| 正确率与纠错 | 正确率 + 分类计数（对/错/漏/多）+ 底部「纠错」chip（`recieved → received`） |
| 答案防泄漏 | 原文/翻译默认隐藏，**隐藏时不渲染进 DOM**（实测 `innerText` 不含句子原文） |
| 提交后自动展开原文 | 默认开启，可在页面顶部关闭 |
| 掌握度 | 卡片徽标（`已掌握` / `最佳 xx%`）；媒体级汇总条（已听写 / 已掌握 / 提交次数 / 平均最佳） |
| 听写历史 | 折叠面板，按句拉取最近 20 条（输入内容 + 正确率 + 相对时间） |
| 批量显隐 | 头部「展开全部原文 / 展开全部翻译 / 全部折叠」 |
| 统计内嵌 | 句子级 `attempt_count / best_accuracy / last_accuracy / last_input / mastered` 随媒体详情一并返回 |

### 18.2 关键工程决策

1. **判定权收在服务端**：算法只在 Python 实现一份，接口返回 token 明细，前端纯渲染。
   若前端也做一遍 diff，两套实现迟早漂移（例如「忽略标点」的边界处理不一致），
   而本地 HTTP 往返只有毫秒级，没有性能理由做客户端重复计算。
2. **展示与比对分离**：分词时同时保留 `display`（带标点、原大小写）与 `norm`（归一化），
   于是既能「忽略标点判分」，又能在界面上原样显示 `letter.`，不必二选一。
3. **`extra` 必须单独排除**：多写的词不参与正确率分母，所以「正确率 100% 但多写一个词」
   会被朴素实现误判为已掌握。故 `is_correct = 正确率 ≥ 阈值 且 extra == 0`。
4. **纯函数 + 无 I/O**：`services/dictation.py` 不碰数据库，可直接在 `selftest.py` 离线断言，
   也便于 M5 加「本地预校验」时复用。
5. **聚合与算法分层**：DB 统计放在 `services/study.py`，算法放 `services/dictation.py`，
   避免把查询逻辑混进纯算法模块。
6. **提交后就地更新统计**：接口返回该句累计统计，前端用 `StatOverride` 叠加在服务端数据上，
   避免每次提交都全量重拉媒体详情（长音频场景下能省掉明显卡顿）。
7. **浏览器验证方式可复用**：本机装有 Chrome，用 `--remote-debugging-port` + CDP
   （Node 22 内置 `WebSocket`，无需装 Puppeteer）驱动无头浏览器完成真实点击测试。
   注意：**每次要用全新的 `--user-data-dir`**，否则残留进程会锁住 profile 目录导致新实例启动即退出。

### 18.3 验证记录（2026-10-11）

后端算法与接口（`services/dictation.py` + `POST /api/attempts`）：

| 用例 | 输入 | 结果 |
|------|------|------|
| 完全正确 | 与原文完全一致 | ✅ 100%，`is_correct=true` |
| 忽略大小写与标点 | `ask what you can do for your country` | ✅ 100%（`Ask … country.` 判为一致） |
| 拼错单词 | `… for your contry` | ✅ 87.5%，1 个 `wrong`，`expected` 保留 `country.` |
| 漏词 | `Ask what you can do` | ✅ 62.5%，3 个 `missing` |
| 多写单词 | 末尾多加 `please` | ✅ 正确率 100% 但 `is_correct=false`（`extra=1`） |
| 用错词 | `your` → `you` | ✅ 87.5%，1 个 `wrong` |
| 空输入 | `""` | ✅ 0%，8 个 `missing` |
| 句子不存在 / 超长输入 | id=99999 / 5000 字符 | ✅ HTTP 404 / 422 |
| 掌握判定 | 先 35.7% 再全对 | ✅ 先 `mastered=false`，第二次后 `true` |

真实浏览器交互测试（无头 Chrome + CDP，媒体 3 · 6 句）：

| 步骤 | 结果 |
|------|------|
| 学习页渲染 | ✅ 6 个听写框、6 张句卡渲染完成 |
| 答案防泄漏 | ✅ `innerText` 含「原文已隐藏」，**不含**任何句子原文 |
| 提交「多写一个词」 | ✅ 界面显示 `正确率 100%`、`正确 8/8 · 多 1`、`纠错`，多写词出现删除线 |
| 提交「漏词」 | ✅ `正确率 62.5%`、`正确 5/8 · 漏 3`，出现 3 处虚线下划线 |
| 提交「全对」 | ✅ `100%`、出现掌握徽标、原文**自动展开**、头部变「已掌握 1 句」 |
| 听写历史 | ✅ 展开后按时间倒序列出 `100% / 62.5% / 100%` |
| 页面脚本错误 | ✅ 无 |

其他：

| 用例 | 结果 |
|------|------|
| 环境自检 | ✅ `selftest.py` 新增「听写校验」段，5 条断言全 OK |
| 前端构建 | ✅ `tsc --noEmit` 无错误，93 模块，JS 260KB（gzip 80KB） |
| 单端口托管 | ✅ `/study/3` 200；`/api/nope` 404 JSON；静态产物 hash 与构建一致 |

### 18.4 留给 M4/M5 的接口预留

- `notes` 表已就位（每句至多一条 + `updated_at` 自动刷新），M4 直接落 `GET/PUT /api/notes/{sentenceId}`；
- 学习页卡片内已预留笔记位置（紧接翻译区下方），插入 `<NoteEditor/>` 即可；
- 单词浮层可复用 `DictationBox` 内的 `DiffResult` token 渲染思路（按词包裹 `<span>`）；
- 听写历史接口已支持 `limit`，M5 做「掌握度统计/导出」时可直接聚合 `attempts`。

---

## 19. M4 实现说明与验证记录（词典 / 生词本 / 笔记）

### 19.1 交付范围

| 需求 | 实现 |
|------|------|
| FR-S6 单词查词 | 学习页原文按词渲染为可点击元素 → `GET /api/dict/{word}` → 浮层展示音标 / 中文释义 / 英文释义 / 词形变化 / 考纲标签 / 柯林斯星级，并提供「朗读」「跳牛津」「跳朗文」 |
| FR-S7 加入生词本 | 浮层内一键加入，自动携带**上下文句子**与**来源媒体**；同词幂等，不产生重复记录 |
| FR-S8 句子笔记 | 卡片底部 `<NoteEditor>`：失焦自动保存、`Ctrl/Cmd+Enter` 立即保存、清空即删除 |
| FR-A5 生词本管理 | 生词本页：关键词搜索、按掌握度筛选、编辑释义、标记已掌握、删除、导出 Markdown |

### 19.2 词库与词形还原

- 词库：**ECDICT**（`ecdict-sqlite-28.zip` → `data/dict/ecdict.db`，**340 万词条 / 811.9 MB**，SQLite 格式）。
  安装脚本 `backend/scripts/fetch_dict.py`：多镜像自动回退 + 断点续传 + 复用已下载压缩包 + 写入「词条数 / 体积 / 安装时间」元数据。
- 查询：`services/dict.py` 用**单只读连接 + 线程锁**访问 SQLite，不把词库加载进内存，对 8GB 笔记本友好。
- **音节条目陷阱**：ECDICT 除正常词条外还有「音节拆分」条目（如 `hel-lo`、`-running`、`chil-dren`），
  它们的 `sw`（去符号规范化词形）与正常词相同。若只按 `sw` 查询会优先命中这些拆分条目（实测 `children` 曾返回
  “字组拆分到两个音节中去”）。因此查询改为三级优先：
  ① `word = ?` 精确词形（走唯一索引，必然命中正常词条）→ ② `sw = ?` 且排除含连字符者 → ③ `sw = ?` 兜底；
  结果按柯林斯星级 / 词频降序，保证取到质量更高的释义。
- 词形还原两级：
  1. **ECDICT `exchange` 反查**：查询词命中后若 `exchange` 含 `0:`（原型），取原型再查一次，`via=exchange`（最准）；
  2. **lemminflect + 规则兜底**：未命中时生成候选原型，**候选必须能命中词库**才采用（`via=lemminflect` / `rule`），避免误还原（如误把 `less` 还原成 `le`）。
- 未收录兜底：可选用免费在线引擎给出「参考释义」（`settings.dict_online_fallback`，默认开启），浮层会标注「在线参考」。
- 词库未安装：接口**不报错**，返回 `found=false` + 中文提示；浮层仍提供牛津 / 朗文跳转，功能降级但不中断。

### 19.3 查词浮层（`WordPopover`）

- 用 `createPortal` 挂到 `document.body`，避免被卡片容器裁剪或受 `overflow` 影响；
- 定位策略：优先显示在单词下方，视口空间不足则上移，左右夹在视口内；点击遮罩 / `Esc` / 关闭按钮均可关闭；
- 朗读用浏览器内置 `speechSynthesis`（免费，离线可用，实际音色取决于系统语音包）；
- 失败降级：查询报错时显示错误文案，牛津 / 朗文链接始终可用。

### 19.4 句子笔记（`NoteEditor`）

- `notes` 表每句至多一条（`sentence_id` 唯一索引 + `onupdate` 自动刷新 `updated_at`）；
- `PUT /api/notes/{sentenceId}` 是 upsert，内容空白等价于删除；
- 前端折叠态展示笔记预览，展开后编辑；失焦自动保存，切换句子时重新拉取，避免串行错位。

### 19.5 文件清单（M4 新增 / 修改）

**后端**
- 新增：`app/services/dict.py`、`app/api/dict.py`、`app/api/vocab.py`、`app/api/notes.py`、
  `app/schemas/dict.py`、`app/schemas/vocab.py`、`app/schemas/note.py`、`scripts/fetch_dict.py`
- 修改：`app/core/config.py`（新增 `dict_online_fallback`）、`app/api/health.py`（新增 `dict` 自检）、
  `app/main.py`（注册 3 个路由）、`scripts/selftest.py`（新增「词典」自检段）

**前端**

- 新增：`src/components/WordPopover.tsx`、`src/components/NoteEditor.tsx`
- 重写：`src/pages/VocabPage.tsx`
- 修改：`src/pages/StudyPage.tsx`（`ClickableText` 按词拆分 + 接入 `NoteEditor` / `WordPopover`）、
  `src/api/client.ts`（词典 / 生词本 / 笔记类型与调用）、`src/components/icons.tsx`（新增 9 个图标）

**验证脚本**

- 新增：`scripts/verify_m4.mjs`（无头 Chrome + CDP 驱动，覆盖查词 / 生词本 / 笔记全链路）

### 19.6 验证记录

**接口级（curl 直连真实后端）**

| 用例 | 结果 |
|------|------|
| 词库未安装时的降级 | ✅ 返回 `found=false` + 中文提示，牛津 / 朗文链接仍可用（不报 5xx） |
| 非法查询（含空格 / 非单词） | ✅ 400「一次只能查询一个英文单词」 |
| 笔记写入 → 回读 | ✅ `PUT` 后 `GET` 内容与 `updated_at` 一致 |
| 笔记内容为空白 | ✅ 视为删除，`exists=false` |
| 加入生词本 | ✅ 自动带上「上下文句子 + 来源媒体标题」，`duplicated=false` |
| 同词重复加入 | ✅ 幂等：`duplicated=true`，词库不产生第二条记录 |
| 按掌握度筛选 / 中文搜索 / 前缀搜索 | ✅ 命中正确（`?mastered=true`、`?q=国家`、`?q=coun`） |
| 导出 Markdown | ✅ 表头（单词 / 音标 / 释义 / 上下文 / 来源 / 掌握）与中文统计行正确 |
| 删除生词 | ✅ 204，列表随即为空 |

**词形还原实测（对真实 340 万词条词库）**

| 查询词 | 命中主词形 | 还原方式 | 说明 |
|--------|-----------|---------|------|
| `hello` | hello | exact | 直接命中 |
| `received` | receive | exchange | 过去式 → 原型 |
| `running` | run | exchange | 现在分词 → 原型 |
| `children` | child | exchange | 不规则复数 → 原型 |
| `studies` | study | exchange | 三单 / 复数 → 原型 |
| `went` | go | exchange | 不规则过去式 → 原型 |
| `better` | good | exchange | 比较级 → 原型 |
| `Americans` | American | exchange | 复数 → 原型 |
| `country` | country | exact | 直接命中 |

**UI 级：无头 Chrome + CDP 真实交互（脚本 `scripts/verify_m4.mjs`，12/12 通过）**

| 用例 | 结果 |
|------|------|
| 学习页渲染句子卡片 | ✅ 原文展开后 14 个可点击单词 |
| 点击单词弹出查词浮层 | ✅ 首词 `And`：`/ænd/`、牛津核心、柯林斯 ★★★★★、中考 / 高考标签、`conj. 和, 与` |
| 浮层含音标与中文释义 | ✅ |
| 浮层含牛津 / 朗文跳转 | ✅ 链接指向 `oxfordlearnersdictionaries.com` / `ldoceonline.com` |
| 一键加入生词本 | ✅ 按钮变为「已加入生词本」（重复点击提示「已在生词本」） |
| `Esc` 关闭浮层 | ✅ |
| 句子笔记保存 | ✅ 失焦自动保存，出现「笔记已保存」 |
| 刷新后笔记回显 | ✅ 重新加载页面后内容仍在（已落库） |
| 生词本页有生词 | ✅ 列表出现刚收藏的词，来源媒体正确 |
| 掌握 / 删除操作 | ✅ 按钮均存在且可用 |
| 导出 Markdown 链接 | ✅ `/api/vocab/export` |
| 导出接口返回 Markdown | ✅ HTTP 200，含表头与统计行 |

> 验证脚本可复用：`node scripts/verify_m4.mjs --url http://127.0.0.1:8000 --media 3`（需本机 Chrome）。
> 验证后产生的测试生词与笔记已清理，交付库为干净状态。




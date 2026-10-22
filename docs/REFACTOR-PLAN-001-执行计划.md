# REFACTOR-PLAN-001 执行计划

> 派生自 `docs/ADR-001-技术栈选型与重构决策.md`（已采纳）。ADR 定「做什么、为什么」，本文定「怎么做、做完怎么验」。
> 计划性质：**施工文件**。每完成一项，把 `[ ]` 改成 `[x]` 并填实际耗时，本文随进度演进。

---

## 0. 怎么用这份计划

1. **按闸门走，不按心情走**。每个阶段结束有质量闸门（§2），闸门不过不进入下一阶段 —— 这是本计划唯一的纪律要求。
2. **一个任务 = 一次可提交的改动**。任务粒度已按「能独立验收」切好，不建议合并执行。
3. **验收必须跑命令，不靠肉眼看**。每个任务的「验收」栏都是可直接执行的。
4. **阻塞时立刻停下标记**，不要带着未验收的任务往后走（Vue 重写最大的失败模式就是「先都写完再一起调」）。
5. **交付报告里的哈希必须现场取、且发出后不再写文件**（P3-1 教训：先报完成、后又跑变异，导致三个 sha256 在复核时已失效，整套「已冻结」证明作废）。正确顺序：**改完 → 全量测试 → `sha256sum` → 同一轮内发报告 → 冻结**。
6. **破坏性验证一律在副本/沙箱里做**，绝不在交付物上「改→还原」（P3-1 教训：变异备份放在 `migrations/versions/` 里，被 alembic 当成第二个 `0001` 迁移加载；且与另一方的写入互相覆盖）。做法：`cp -r backend/ → 临时根`，在沙箱里变异。
7. **验证进行中不得给实现者下发新批次**（P3-2 教训：终验已开始后才把「最后 4 项」发给工程师，导致 3 个文件在验证窗口内被改，QA 只能作废重测、白跑一轮）。纪律是「**一批实现 → 冻结 → 验证 → 结论**」闭环；发现还要补，就**等本轮结论出来再开下一批**，不要在验证中途插入。
8. **不要用「重跑导出脚本」来校验契约基线**（P3-2 教训：`export_openapi.py` 的产物**就是** `check-contract.mjs` 的基线文件，重跑一次等于把「校验」变成「自比」）。确需重导出时，先把基线 `cp` 到临时路径再 diff。**校验契约的正确做法**：live `app.openapi()` 与基线逐 operation 比对（注意在副本里跑会因找不到 `frontend/dist` 多注册一个 `/`，得到 35/43 —— 要用真实 `backend/` 只重定向 DB）。

---

## 1. 关键路径与并行结构

```
        ┌────────────────────────── 前端链（串行，必须一次做完）─────────────────────────┐
P0 契约冻结 ──► P1 Vue 骨架 ──► P2-A 简单页 ──► P2-B 媒体库 ──► P2-C 学习页 ──► P2-D 生词 ──► P5 切换
   (2d)          (2d)             (1.5d)           (2.5d)          (4d)          (2d)        (1.5d)

        ┌────────────── 后端链（可与前端链并行，但内部必须串行）──────────────┐
P0 测试网 ──► P3 Alembic ──► P3 jobs 表+worker ──► P3 分池/health ──► P4 题型插件 ──► P4 IELTS 模型
   (含在P0)      (1d)             (1.5d)                (1d)             (2d)           (3d)
                                    │
                                    └──► P5 切换（后端须先于前端完成，否则切换无收益）
```

**工期合计**：19–25 个**全日制**工作日。
⚠️ **对 ADR §5.0 的诚实修正**：ADR 写的「业余约 4–6 周」隐含每天 4–5 小时有效工时，偏乐观。按每天 2–3 小时折算，实际约 **8–12 周**。请按后者做心理预期，否则中期必然挫败。

**建议的并行方式**：前端链与后端链**由同一个人交替推进**也可以（两条链无文件冲突，`frontend-vue/` 与 `backend/app/` 完全隔离），但**不要同时开两个 P2 页面**。

---

## 2. 质量闸门（Gate）

| 闸门 | 位置 | 通过条件（全部满足才放行） |
|---|---|---|
| **G0** | P0 结束 | ① `contracts/openapi-v1.json` 已入库且含全部端点（实测 **34 path / 42 operation**，见 §3 偏差说明） ② `contracts/api-types.d.ts` 生成成功 ③ `node scripts/check-contract.mjs` 能捕获人为改动 ④ `pytest` 全绿且纯函数覆盖率 ≥90% |
| **G1** | P1 结束 | ① `frontend-vue` 能 `dev` 起来并且 **4 条业务路由 + `*` 兜底**可空转（登录是 App 层状态门禁，**不是路由**） ② 登录后能拿到真实数据渲染 ③ `npm run build` 通过（含 `vue-tsc --noEmit`） |
| **G2** | 每个 P2 页面 | ① 该页所有旧功能逐一对照通过 ② 该页对应的 `scripts/verify_*.mjs` 脚本重跑通过 ③ 手机宽度（375px）下无横向滚动、无顶出 |
| **G3** | P3 结束 | ① 老库能被 Alembic 正确 `upgrade head`（用 `data/app.db` 的副本实测）② `kill -9` worker 后重启能自动恢复未完成任务 ③ ASR 与翻译并发时不再互锁 ④ 打包链 `packaging/build.ps1 -NoZip` 仍能通过 |
| **G4** | P4 结束 | ① 新增一个「占位题型」只需新增一个模块 + 前端一个组件，**不修改核心代码** ② 写作批改的降级路径实测生效（断网时不阻塞交卷） |
| **G5** | P5 结束 | ① 云端与新前端 bundle 的 md5 一致 ② 旧前端已打 tag 并停止维护 ③ 回滚演练成功一次 |

---

## 3. P0 —— 契约冻结与测试网（2 天）· 一切的前提

> 为什么先做这个：Vue 重写之所以低风险，**唯一原因**是后端不动。因此必须先把契约固化成可校验的基线，否则重写过程中任何一次后端改动都可能静默破坏前端。

> **⚠️ 施工中发现的六处偏差（2026-10-16，按实测修正）**
> 1. 本计划的「35 个端点」是 v1.14 时期的旧基线。实测（`frontend/dist` 存在时）为 **34 个 path / 42 个 operation**（v1.15 媒体库分类、v1.16 历史对照未计入）。基线一律以**实际导出结果**为准。
> 2. P0-4 原写「conftest 覆写 `FAYELONG_*` 环境变量指向 tmp」**在本代码库不可行**：`core/config.py` 的 `DATA_DIR`/`DB_PATH` 等是**模块级常量**（由 `__file__` 推导、不读环境变量），且 `db.py` 在 **import 时**即 `create_engine(DB_PATH)`。实际做法见 P0-4。
> 3. OpenAPI 含一处**环境相关**差异：`main.py` 末尾的 SPA 回退路由 `/` 仅在 `frontend/dist` 不存在时注册、且未排除出 schema → 删掉 `dist` 会凭空多 1 个 operation。`check-contract.mjs` 对该差异**显式打印式容忍**，不静默吞任何差异。
> 4. **文件级 md5 不是可靠的数据安全不变量**：`data/app.db` 是**本来就会被正常使用**的应用库 —— 任一次真实登录都会写 `users.last_login_at`，md5 必然漂移（P1 Round B 实测：`61fb174d…` → `0e0a714e…`，经核对**仅该时间戳变化**，九表行数与文件大小均未变）。后续一律以 `scripts/fingerprint_data.py` 的**内容指纹**为准：逐表逐行规范化 sha256 + `data/media/library/` 目录清单哈希，且**显式排除** `users.last_login_at`（排除清单会打印，不静默）。**2026-10-16 新内容指纹基线：`TOTAL = 278bcd28b2c37a98ffb123004b2d38823d5676b13104c90ff4d32dad697f3b4f`**。
> 5. **本机 Vite dev 只绑 IPv6 `[::1]`**：`npm run dev` 之后用 `127.0.0.1:5174` 会命中代理报 **502** → 所有浏览器/接口验证**一律用 `http://localhost:5174`**（`scripts/verify_vue_*.mjs` 的默认 URL 即此）。
> 6. **新增 `scripts/run_isolated_backend.py`（隔离后端）**：用临时根 + `data/app.db` 副本起一个独立端口（默认 **8010**，不占 8000）的后端，**绝不碰真实 `data/`**；`data/models`、`data/dict`（体积巨大）**只读指回**真实目录。**破坏性验证（上传/批量移动/删除/拆分合并）必须跑在它上面**；dev 侧用 `FAYELONG_API_TARGET` 把 `/api` 代理指到它。

### P0-1 导出 OpenAPI 基线
- [x] 产出：`scripts/export_openapi.py`、`contracts/openapi-v1.json`
- 做法：脚本内直接 `from app.main import app` 后 `json.dump(app.openapi())`，**不依赖服务运行**（避免端口残留坑：改了行为没变先查旧 uvicorn 占端口）
- 验收：
  ```bash
  backend/.venv/Scripts/python.exe scripts/export_openapi.py
  # 断言 operation 数为 42（path 数为 34）
  python -c "import json;d=json.load(open('contracts/openapi-v1.json'));print(len(d['paths']), sum(len(v) for v in d['paths'].values()))"
  ```
- 工时：0.25 天 → **实际 0.5 天**

### P0-2 生成 TS 类型，替换手写类型
- [x] 产出：`contracts/api-types.d.ts`、`scripts/gen-api-types.mjs`
- 做法：`openapi-typescript` 生成。⚠️ **`npm install` 必须加 `--ignore-scripts`**（本机托管 node.exe 上 esbuild postinstall 会 EBUSY）
- 验收：生成的 d.ts 中能找到与后端 schema 对应的类型 —— `AttemptResult`（同名）、`MediaOut` / `MediaDetailOut` / `MediaListResponse` / `SentenceOut`。
  ⚠️ 注意：`MediaItem` / `SentenceItem` **不是后端 schema 名**，它们是旧 React 前端手写的类型名（见 `frontend/src/api/client.ts`）。P1-2 前端改用自动生成的 `contracts/api-types.d.ts` 后，这些手写名应整体替换掉。
- 工时：0.25 天 → **实际 0.5 天**

### P0-3 契约 diff 门禁
- [x] 产出：`scripts/check-contract.mjs`
- 做法：重新导出 → 与基线做结构化 diff → **有差异即非零退出**并打印差异点
- 验收：手工删掉 `api/vocab.py` 里一个端点 → 脚本报错；恢复 → 脚本通过
- 工时：0.25 天 → **实际 0.5 天**

### P0-4 pytest 基建
- [x] 产出：`backend/tests/__init__.py`、`backend/tests/conftest.py`、`backend/pytest.ini`、`backend/requirements-dev.txt`
- 做法：conftest 在**模块顶层**、于任何 `app.*` import **之前**，用 `setattr` 把 `app.core.config` 的 8 个路径常量（`DATA_DIR`/`MEDIA_DIR`/`INBOX_DIR`/`LIBRARY_DIR`/`MODELS_DIR`/`DICT_DIR`/`LOG_DIR`/`DB_PATH`）重指向 `tempfile.mkdtemp()` 建的临时根，**再** import `app.db`/`app.main`；提供 `client` fixture（`with TestClient(app)` 触发 lifespan）与 `db_session` fixture。另加 **session 级 autouse 护栏**断言 `DB_PATH` **不在**真实 `data/` 下。
  原因：① 这些路径是**模块级常量**、不读 `FAYELONG_*`（`Settings` 只管 host/port/model 之类）；② `db.py` 在 **import 时**即 `create_engine(DB_PATH)` 并绑定，故必须在 import 前打补丁。⚠️ `tmp_path_factory` **不可用**（fixture 在收集期之后才可用，而 engine 在收集期已绑定）→ 改用模块顶层 `tempfile.mkdtemp()`。
- 验收：`cd backend && .venv/Scripts/python -m pytest -q` 能跑（0 用例也 OK，只要不报错）；**不得触碰 `data/app.db`**（收尾验 md5 不变）
- 工时：0.25 天 → **实际 1 天**（重定向是难点）

### P0-5 纯函数单测（**本次重构最高价值的安全网**）
- [x] 产出：`backend/tests/test_dictation.py`、`test_dict.py`、`test_marks.py`、`test_study.py`
- 必须覆盖的既有陷阱（对照 `MEMORY.md` §4，这些都是历史踩过的）：
  - `dictation`：`’→'` 归一化、忽略标点大小写、**多写词不进分母**、`is_correct` 需 `accuracy≥100 且 extra==0`
  - `dict._query`：**三级优先 `word=` → `sw= AND word NOT LIKE '%-%'` → `sw=`**；**音节拆分条目陷阱**（`hel-lo`/`chil-dren` 必须不被 `sw` 误命中）
  - `dict` 词形还原：`exchange` 含 `0:` → 用原型再查（`via=exchange`）；lemminflect 候选**必须能命中词库**才采用
  - `marks`：`load/dump` 的归并 + 夹取；脏数据当无标记
  - `study`：统计口径
- 验收：`pytest --cov=app.services --cov-report=term-missing`，纯函数模块覆盖率 **≥90%**（实测：dictation/dict/marks/study **均 100%**）
- 工时：0.5 天 → **实际 1 天**

### P0-6 API 层测试
- [x] 产出：`backend/tests/test_media_flow.py`、`test_auth.py`
- 必须覆盖：媒体状态机 `pending→transcoding→ready→asr→translating→clipping→done` 的合法流转、`requeue_unfinished()` 自愈、**未登录访问任意 `/api/*` 得 401**（守卫是默认拒绝的中间件）、`/api/auth/*` 与 `/api/health` 豁免
- 验收：pytest 全绿；故意删掉守卫中间件的一条豁免项 → 有测试失败
- 工时：0.25 天 → **实际 0.5 天**

**⚡ G0 闸门检查通过后方可进入 P1。**

---

## 4. P1 —— Vue 骨架与基础设施（2 天）

> 原则：**新建 `frontend-vue/`，绝不覆盖 `frontend/`**。旧版全程可运行、可回滚。

### P1-1 脚手架
- [ ] 产出：`frontend-vue/`（`npm create vite@latest` → vue-ts 模板）
- 依赖（对应旧栈逐项）：
  ```
  dependencies:   vue@^3.5  vue-router@^4  pinia@^2  @tanstack/vue-query@^5
  devDependencies: vite@^5  typescript@~5.6  vue-tsc  tailwindcss@^3  postcss  autoprefixer
  ```
- ⚠️ `npm install --ignore-scripts`
- 验收：`npm run dev` 起在 **5174**（错开旧的 5173，便于双跑）
- 工时：0.25 天

### P1-2 请求层（对应旧 `api/client.ts` 的 699 行）
- [ ] 产出：`frontend-vue/src/api/request.ts`、`src/api/client.ts`
- 做法：
  - `request<T>()` 沿旧实现语义：默认带 cookie、统一错误解析、**401 时派发 `fayelong:unauthorized`**（换成 mitt 或 Pinia action）
  - 3 个易漏点：`uploadMedia` 的上传进度（XHR）、`openProgressStream` 的 SSE、`/{media_id}/stream` 的 Range 播放（交给原生 `<audio>` 的 src 即可）
  - 类型**不再手写**，从 `contracts/api-types.d.ts` 引
- 验收：登录后 `listMedia()` 能拿到真实数据
- 工时：0.5 天

### P1-3 路由与外壳
- [ ] 产出：`src/router/index.ts`、`src/App.vue`、`src/main.tsx`→`main.ts`
- 5 条路由照搬：`/login`、`/`（媒体库）、`/study/:id`、`/vocab`、`/vocab/practice`
- `ErrorBoundary.tsx` → `onErrorCaptured` 全局错误捕获
- 工时：0.25 天

### P1-4 Pinia player store（对应 80 行 zustand）
- [ ] 产出：`src/stores/player.ts`
- 注意保留原设计：**`<audio>` 元素由 `PlayerBar` 持有**，store 只存「意图 + 时间轴」，通过 `bindAudioElement()` 注册 DOM 元素供 seek/nudge
- `PLAYBACK_RATES = [0.5, 0.75, 1, 1.25, 1.5]` 原样保留
- 工时：0.25 天

### P1-5 Layout 三段式外壳（**历史踩坑区，重点**）
- [ ] 产出：`src/components/Layout.vue`
- 必须照搬的既有结构：`flex h-dvh flex-col overflow-hidden`；header `shrink-0` / main `flex-1 min-h-0 overflow-y-auto` / PlayerBar `shrink-0`；学习页只写 `h-full`
- ⛔ **严禁 `calc(100vh - <像素>)` 魔法数字**（旧版 109/197px 就是被手机顶栏换行搞坏的）
- ⚠️ `justify-center` + `overflow` 会顶出顶部内容 → 需要内套 `min-h-full`
- 触摸目标**统一 32px，不按屏宽分档**
- 工时：0.25 天

### P1-6 图标迁移（**近零成本**）
- [ ] 产出：`src/components/icons/`（由 465 行 `icons.tsx` 拆成 Vue 组件）
- 做法：SVG 内容原样搬入 `<template>`，逐个去掉 JSX 语法即可
- 工时：0.25 天

**⚡ G1 闸门检查通过后方可进入 P2。**

---

## 5. P2 —— 页面迁移（6–8 天）

> 顺序按「依赖少 → 依赖多」。**每页做完立即跑闸门 G2，不批量收尾。**

### P2-A 登录页（0.5 天）
- [x] `LoginPage`（151 行）→ `src/pages/LoginPage.vue`（**只含 setup + 登录**）
- ⚠️ **范围更正**：**改密 / 登出不在 `LoginPage`**，而在 `Layout` 的 `AccountMenu`（本轮一并补完改密弹窗）。
- 验收：`scripts/verify_vue_login.mjs`（A1–A11，跑**隔离后端**）；旧 `scripts/verify_v1_12.mjs` **不动**（P5 回滚仍要用它）
- 工时：0.5 天 → **实际 0.5 天**

### P2-B 播放条与整段播放（1 天）
- [ ] `PlayerBar`（197 行）、`useClipPlayer`（205 行）→ `src/composables/useClipPlayer.ts`
- ⭐ **这是最容易被高估的难点，实际很低**：内部是**原生 `HTMLAudioElement` API**（`timeupdate`/`loadedmetadata`/`ended`/`error` + A-B 循环 + 与整段播放互斥），与框架无关，**可逐行照搬**；只把手握方式从 `useState/useRef/useCallback` 换成 `shallowRef/reactive + onMounted/onUnmounted`
- 保留三个语义：单句循环、A-B 循环（切句自动失效）、句子播放与整段播放互斥
- 工时：1 天

### P2-C 媒体库页（2.5 天）
- [x] `MediaLibraryPage`（1162 行）+ `CategoryManager`（334 行）+ `CategoryChips`
  （Vue 侧拆为 8 个文件：`MediaLibraryPage.vue` + `MediaRow`/`CategoryChips`/`CategorySelect`/`CategoryManager`/`StatCard`/`ListSkeleton` + `category.ts` 类型；MediaRow 内联的 TypeBadge/CategoryBadge/StatusLine 收进 MediaRow.vue）
  ⚠️ 计划原文写「分类筛选/**拖拽排序**」—— 旧实现**有意不做拖拽**（新依赖 + 移动端误触，注释写明），用 ↑/↓ 按钮，照搬。
- 覆盖：列表、分类筛选/拖拽排序、批量移动分类（`POST /batch-category`）、收件箱扫描导入（`GET /inbox` → `POST /import`）、上传进度、**SSE 进度订阅**、删除确认
- 验收：`scripts/verify_category.mjs` **58/58 通过**（原套件零改动直接打 Vue 版 —— 因迁移时刻意保持 DOM 结构与 className 一致，旧回归套件原样可用；跑在隔离后端上，零写真实库）。
  ⚠️ `verify_attempt_history.mjs` 的 **UI 层依赖学习页**（历史行展开/词级标红，属 P2-D 范围）→ 挪到 P2-D 验收；其接口层（A 段）与 P2-C 无关。

### P2-D 学习页（**4 天，占前端 45% 工作量**）
- [x] `StudyPage`（1683 行）+ `DictationBox` + `ClickableText` + `SentenceStage` + `WordPopover`（295）+ `NoteEditor`（155）+ `NotesPanel` + `DiffResult`
  （Vue 侧拆为 9 个文件：`StudyPage.vue` 729 行本体 + 7 个子组件 SFC + `types/study.ts`（共享类型/常量/纯函数 + 「下一题按钮永不聚焦」铁律）+ `utils/speech.ts`；
  ⭐ 分词正则与后端 `marks.py` 已程序化逐字比对；隐藏内容零 `v-show`/`v-html`（全仓 grep 证据））
- 建议**拆成独立 SFC**（旧版是内联子组件，1683 行是维护负担，趁重写拆开）
- 三个真实风险点：
  1. **输入法交互**：`compositionstart/end`、`Enter` 提交 —— 历史已知「`Enter` 双触发坑」：**「下一题」按钮不能加 `autofocus`**，必须重新验证
  2. **`ClickableText` 的「易听错」标记**：分词正则**必须与后端 `services/marks.py` 完全一致**，否则词序下标错位。这是**隐藏的一致性契约**，务必对照实现 + 用 P0-5 的 marks 单测对拍
  3. **隐藏内容不渲染进 DOM**（防 F12 看答案）—— 旧版刻意不渲染，重写时不要图省事用 CSS 隐藏
- 验收：`scripts/verify_m4.mjs`、`verify_m5.mjs`、`verify_marks.mjs` 通过
- 工时：4 天

### P2-E 生词与练习页（2 天）
- [x] `VocabPage`（363）+ `VocabPracticePage`（861）
  （Vue 侧拆为 7 个文件 / **1,340 行**：`pages/VocabPage.vue` 210 + `pages/VocabPracticePage.vue` 708 +
  `components/VocabRow.vue` 186 + `VocabPracticeHeader/Field/Choice.vue` 48/20/42 + `types/vocab.ts` 126（纯函数与类型））
- 保留既有约定：练习三模式（中译英 / 英译中四选一 / 单词听写）、`isSpelling = mode !== 'en2zh'` 分流、中译英填原型也算对
- 朗读 `utils/speech.ts` **零改动照搬**，但注意：音色 `en-US→en-GB→en-*`；**Chrome `getVoices()` 首次常返回空数组，不能缓存空结果**
- 验收：`scripts/verify_vocab_practice.mjs` **29/29 通过**（原套件零改动直接打 Vue 版，只传 `--url http://localhost:5174`；跑在隔离后端，零写真实库）
  - ⚠️ **断言数口径**：脚本里 `record(` 文本出现 32 次，但其中 2 次是注入脚本内的同名钩子（`const record = (u) => …` / `record(u)`）、1 次是 catch 兜底（正常不触发）→ **真实断言 29 条**。别按 32 记账。
  - 变异测试（有牙证明）：`data-practice-phase="result"` 改值 → **26/29 FAIL**，点名 3 条结果页断言；删 `data-practice-next` → **6/7 中断**。还原后 sha256 逐字节一致且复跑全绿。
- 工时：2 天 → **实际 ≈0.5 天**

### P2-F 移动端全量回归（1 天）
- [x] 375 / 768 宽度全页遍历，`h-dvh` 外壳在各页表现一致
- 验收：`scripts/verify_mobile.mjs` **36/36 全绿**（375×667 / 393×852 / 820×1180 三视口 × 12 项；媒体 #4，106 句）
  - 关键量测：375px 下四页横向溢出均为 `375≤375`；学习页文档高 = 视口高（无纵向滚动）；顶部信息条每段仍是 1 行（未被压成竖排单字）；听写框底 435 / 下一句底 542 / 宫格底 646（视口 667，全在视口内）；触摸目标 32px
- 工时：1 天 → **实际 ≈0.3 天**

**⚡ 每个页面都要过 G2。**

---

## 6. P3 —— 后端架构债（4–5 天）· 比换语言重要

### P3-1 引入 Alembic（1 天）
- [x] 产出：`backend/alembic.ini`、`backend/migrations/`（`env.py` 245 行 + `script.py.mako`）、首个基线版本 `versions/0001_baseline.py`（344 行）
- 做法：
  - SQLite 必须用 `batch_alter_table`（重建表方式改列）
  - 把现有 `db.py::_ADDED_COLUMNS` / `_INDEXES` 转为对应的基线迁移
  - `_ensure_columns()` **降级为兼容垫片**（老交付包就地更新时仍需要），加注释说明它只服务于「无迁移框架的旧库」
- **实际做法与补充**（施工中确立，勿改回去）：
  - **启动路径零改动**：`init_db()` 仍是 `create_all + 补列 + 补索引`，本阶段**不**在启动时跑 `alembic upgrade`。迁移由开发/部署时显式执行。
  - 目标库通过 **`-x db_path=`** 注入（`config.py` 的路径是模块级常量、不读环境变量；`db.py` 在 import 时就绑 engine）。默认回落到 `data/app.db`，且 `env.py` 每次迁移都 INFO 打印解析后的目标库 URL —— **这条日志是防止「迁错文件还显示成功」的唯一依据，别删**。
  - 基线**不能**用 `create_all` 一句话糊过去：必须显式 DDL（9 表 + 8 索引），且 `upgrade()` 先 `inspect()`，已存在的表跳过 DDL → 老库 `upgrade head` 是 no-op 而非报错。
  - ⚠️ **`alembic.ini` 必须纯 ASCII**：alembic 用 `encoding="locale"` 读 ini，中文 Windows 下 locale 是 cp936 → 一个中文注释就会在任何迁移执行前抛 `UnicodeDecodeError`（且 `PYTHONUTF8=1` 也救不了，它走 `locale.getencoding()`）。中文说明一律放 `env.py`（Python 源文件恒 UTF-8）。
  - ⚠️ **Git Bash 的 `/tmp/x.db` 会被 `Path.resolve()` 解析成 `D:\tmp\x.db`** → 「迁移成功」其实迁的是新建空库。传路径一律用 `"$(cygpath -w …)"`，并核对 env.py 打印的 URL。
- 验收（G3-①）：**用 `data/app.db` 的副本**跑 `alembic upgrade head`，数据无损、表结构一致
  - 实测：9 表**行数 / `PRAGMA table_info` / 索引集合 / 内容哈希**全部一致，`alembic_version=('0001',)`，仅多出 `alembic_version` 一张表
  - 空库迁移后与 `Base.metadata` **列级 + 索引级 + 默认值级 + 外键级**零差异（63 列 / 8 索引 / 4 外键）；`alembic check` 输出 `No new upgrade operations detected.`
  - 测试：`backend/tests/test_migrations.py` **11 用例**；全量 **184 passed**（原 173 零退步）
- **已知开放项（不阻塞，但别忘）**：
  1. **老库上 `--autogenerate` 必出一对假 FK diff**（`remove_fk` + `add_fk` on `media.category_id`）：老库该列是 v1.15 `ALTER ADD COLUMN ... REFERENCES` 的**列级内联外键**，SQLite 反射会丢 `ondelete`。**不要用 `include_object` 消音**（会静默阉割未来所有真实外键退化检测）；正解是将来另起一版 batch 迁移把列级内联 FK 归一成表级命名 FK。
  2. **`sentences.marks` 老库可空 / 新库 NOT NULL**（v1.14 补列时 SQLite 只能加可空列）。已确认全仓无写 NULL 的路径，老库上 `alembic check` 会永久报 1 条 `modify_nullable` —— 属**预期噪音**。
  3. **`compare_server_default` 必须保持关闭**：`created_at`×6 与 `notes.updated_at` 模型侧只有 `func.now()`、`marks` 只有 Python 端 `default=""`，开启后连**正确迁移的空库**也会永久报 `modify_default` → 门禁被假阳性卡死。默认值一致性改由「结构断言 + ORM 插入冒烟」双网保证。
- ⚠️ 先备份 `data/backups/`
- 工时：1 天 → **实际 ≈0.7 天**

### P3-2 `jobs` 表 + 独立 worker（1.5 天）
- [x] 产出：`backend/app/models/entities.py`（新增 `Job` 14 列 / `Worker` 7 列）、`backend/app/services/jobs.py`（1067 行）、`backend/app/worker.py`（772 行）、`migrations/versions/0002_jobs_and_workers.py`（204 行）
- 表结构：`id / kind / ref_id / status(pending|running|done|failed) / progress / error / priority / payload(JSON) / attempts / created_at / started_at / finished_at`
  - **实际在上表基础上加了 `worker_id` + `heartbeat_at`**（fencing 与崩溃检测必需）；**刻意不加** `updated_at`（每条 UPDATE 都要记得写它，漏一处就成会撒谎的字段）、`pool`（kind→pool 是常量映射，入库=两份真相）、外键（`ref_id` 是多态引用，P4 要复用）
  - **必须有一个部分唯一索引** `uq_jobs_active(kind, ref_id) WHERE status IN ('pending','running')`：既做入队幂等，也保证「同一 stage 同一对象」只有一条活跃任务。⚠️ 写成普通 `unique=True` 会变成「一个媒体一生只能跑一次任务」且**不报错**
- 做法：
  - 把 `requeue_unfinished()` 泛化为 **jobs 表的崩溃恢复**（启动时把 `running` 中超过心跳阈值的任务重置为 `pending`）
    - **实际偏差**：`requeue_unfinished()` **一字未改**（计划明令签名/返回条数/入队方式不变，且 `test_media_flow.py` 有 2 例依赖它）；崩溃恢复另起 `recover_stale()`，判据是「租约超时 **OR** worker 不在在线集合」——**OR 关系是关键**：`kill -9` 后死 worker 心跳可能只过去 5s，只靠 TTL 要等满 120s，OR 分支让重启后 ~8s 就能接管
  - 现有 `ThreadPoolExecutor` 保留为**进程内执行器**，只是任务来源改为从 jobs 表取
    - **实际偏差**：`core/tasks.py` 改为 `new_executor()` 工厂 + 兼容签名；真正的执行器在 `worker.py::_PoolRunner`（信号量限流 + 认领线程 + executor），任务来源是 jobs 表的原子 `claim()`
  - 入口 `python -m app.worker`，与 web 进程**分开**（web 进程不再跑长任务）
    - **实际偏差**：改为三态 `FAYELONG_WEB_INPROC_WORKER=off|auto|on`。**理由**：云端 systemd 只起一个 uvicorn、开发时常有人只跑 `start-backend.bat`，若 web 彻底不跑任务，worker 没起时上传会**永远 pending 且无报错**（本阶段不许改前端、不能加 503）。`auto` = worker 不在线时 web 5s 后接管（小池 cpu=1/io=2），worker 一上线就让位；**防双份不靠 flag，靠 DB 原子 claim + fencing token**
- **fencing 协议（本任务真正的技术核心）**：claim 成功时把 `attempts` 当 token 记在内存，**所有写回都带 `WHERE id=? AND attempts=? AND worker_id=?`**；`rowcount==0` → 放弃写回（不写 media、不入队下一 stage）。
  - ⚠️ **写回必须用 claim 时的快照，不能用 `db.get(Job)` 读回的当前归属**——这是施工中 QA 抓到的 P1 缺陷（`worker.py::_fence()`），修前实测：老执行者迟到的 `handle_success` 会把**接管者正在跑的**任务写成 `done` 并顺手入队下一 stage；迟到的 `handle_failure` 会把接管者的 `running` 打回 `pending` 并串上自己的失败原因
  - ⚠️ **media 轴也要同一张 fence**：`mark_terminal_failure()` 必须**先** `force_failed()`（看返回值）**再**写 `media.status`；反过来（先无条件写 media 再看结果）会让「两轴一起收敛」变成「一轴被污染」
- 验收（G3-②）：启动 worker 后 `kill -9`，重启能自动恢复
  - 实测：`attempts=2`、恢复耗时 **9.4s**、`media` 最终 `done/100`；独立探针进一步证明接管不依赖租约 TTL（把 `lease_ttl` 调到 3600 仍 7.7s 接管 → 走的是「不在线集合」分支）
  - **假超时防双跑**：A 还活着但租约过期 → B 接管（attempts=2）→ A 醒来 `touch` rowcount=0 自杀；证据 `hold-aborted` 出现、`hold-completed` 不出现
- 工时：1.5 天 → **实际 ≈1.5 天**（含 D1 返工一轮）

### P3-3 负载分池（含在 P3-2 内）
- [x] **CPU 池**：ASR / ffmpeg 转码 / 切片 —— 线程数 = 物理核数（本地 8 GB 笔记本与云端 2 vCPU 都要压住）
- [x] **IO 池**：翻译（有 `translate_delay_ms=150` 限流）/ 将来的写作批改 —— 可高并发
- 动机：ASR 是分钟级 CPU 密集任务，若与翻译同池会**互相饿死**
- **实际做法（计划的「分池」按字面做不出来，必须改）**：
  - 原 `process_media()` 是一条链在一个线程里跑完 `transcode → asr → translate → clip`，**一条链里既有 CPU 又有 IO**。若整条链算一个 job，翻译那几分钟网络 IO 会占住 CPU 槽；云端 CPU 池 = 2 时，两个媒体进 translate 就把池占满 → **第三个媒体的转码起不来，G3-③ 物理上不可能通过**
  - 解法：**拆 4 个 stage job**，`media_transcode / media_asr / media_clip → CPU`，`media_translate → IO`；上一 stage `done` 时**同一事务**插入下一 stage（**绝不能两次提交**，中间崩溃 = 任务凭空消失）
  - 每个 translate job **内部串行 + 保留 150ms 限流**：并发是「跨媒体」的，不是「跨句子」的（免费引擎按 IP 限流，扇出必炸）
- 验收（G3-③）：同时启动一个 ASR 任务与一批翻译任务，翻译不被 ASR 阻塞
  - 实测（cpu=1/io=2）：`max(translate_end) - asr_end = -0.662s`（翻译全部早于 ASR 结束）、`overlapped=[101,102,103]`、`cpu_peak=1`、`io_peak=2`、`done=4/4`
  - ⚠️ **判别力边界（必须知道）**：这个断言的判别力**只在 CPU 池 = 1 槽时成立**。实测矩阵 cpu∈{1,2,4,8}：cpu=1 时把 `translate` 误放回 CPU 池会被抓到（`all_before=False`）；**cpu≥2 时抓不到**（ASR 只占 1 槽，3×0.05s 翻译挤得进剩余槽）。云端 unit 已显式钉 `FAYELONG_JOB_CPU_THREADS=1` —— 这不只是省资源，它恰好是这条测试唯一有判别力的档位。**不许为了「对齐生产默认」改成 `0/auto`**
  - ⚠️ `os.cpu_count()` **不识别 cgroup 配额**（容器/云主机拿到宿主核数），所以生产必须显式配，不能依赖 `auto`
  - ⚠️ `cpu_peak<=1` / `io_peak<=2` 是**恒真的容量检查，不是判别证据**；判别证据只有「早于结束」+「区间重叠」
- 工时：含上

### P3-4 领域分层收口（1 天）
- [x] `api/*.py` 只做协议转换（入参校验 → 调 service → 序列化），**不承载领域规则**
- 现状 `api/media.py` 676 行偏厚，拆分下推至 `services/media.py`
- 目的：为 P4 的题型插件层腾出干净的接入面
- **实际做法**：`api/media.py` **682 → 420 行**；新增 `services/media_ops.py`（802 行）承载请求侧领域动作。
  - **为什么不塞进 `services/media.py`**：后者是 **worker 热路径**（4 个 stage + fencing，跑在 CPU/IO 池里），本模块是**请求侧**（web 进程、HTTP 触发）。调用者、生命周期、失败语义都不同，合在一起会让「改流水线」和「改接口语义」互相踩。依赖单向：`media_ops → services.media`，无循环 import。
  - 留在 api 的三样：`serialize/serialize_detail/sentence_out`（响应形状，`api/sentences.py` 还在 import）、`STAGE_LABEL`、SSE 分帧。
  - **错误翻译**：领域层用 `MediaOpsError(detail, status_code)` + 子类（**不 import fastapi**），api 侧一个 contextmanager 统一转 `HTTPException` → 14 处 detail 文案一字未改。
- 验收（实测）：契约 **34/42**；**278 passed**；16 operations / 13 paths 对账一致；**路由注册顺序**保持（`/inbox`/`/import`/`/batch-category` 必须在 `/{media_id}` 前，否则被当 media_id 解析成 422）；19 项错误路径黑盒断言全中；前端套件 `verify_category` **59 项**、`verify_m5` **19 项**打隔离后端全过；monkeypatch 有牙（改替身成抛异常 → 用例变红）。
- 工时：1 天 → **实际 ≈0.4 天**

### P3-5 可观测性轻量扩展（0.5 天）
- [x] `/api/health` 增加：jobs 积压数（按 status 分组）、whisper 模型就绪、`data/` 磁盘余量
- [x] 结构化日志：任务 ID 贯穿（web 侧入队 → worker 侧执行）
- ⛔ **不引入 Prometheus/Grafana 等重监控栈**（保持零付费定位）
- **实际做法**：
  - `jobs` / `worker` 两块在 P3-2 已加；本轮补 **`disk` 块**（`total/used/free/free_percent`，`shutil.disk_usage(DATA_DIR)`，失败回落全 0 且端点仍 200）。`checks.asr_model` 已等于 `(whisper_model_dir()/"model.bin").is_file()`，**未重复加**。
  - job_id 用 `contextvars.ContextVar` + **挂在 handler 上的 `JobIdFilter`**（logger 的 filter 不管子 logger 的 propagate，这是 logging 的既定行为）+ `JobAwareFormatter`：**无 job_id 时走原生 Formatter，格式逐字不变**；有 job_id 时只插入 `[job:N] `。
  - ⚠️ **`ThreadPoolExecutor.submit` 不传播 contextvars**（与 `asyncio.to_thread` 不同）。所以不在提交侧 `copy_context().run()`，而是**在工作线程内部** `with job_log_context(ctx.job_id)` 包住整段执行 —— set/reset 同线程，无「提交方上下文搬运」，也无「future 被取消导致没复位」的漏洞。
- 验收（实测）：`disk` 块字段与取值域正确、mock 抛异常仍 200；**普通记录 + traceback 记录**两种都与旧格式逐字相等；跨线程复用不串号、异常路径也复位；`app.log` 与 `worker.log` 能按同一 job id 对上。
- 工时：0.5 天 → **实际 ≈0.3 天**

### P3-6 打包链回归（0.5 天）
- [x] 验收（G3-④）：`packaging/build.ps1 -NoZip` 能通过，且构建期 `launcher.py --check` 通过
- 注意：新增 `worker.py` 后需同步更新 `packaging/launcher.py` 的启动逻辑（**起两个进程：uvicorn + worker**），并确认 `pythonw.exe` 静默启动下 `worker` 不弹窗、`input()` 不被调用（历史坑：`input()` 在 pythonw 下抛 `RuntimeError`）
- **G3-④ 四项判据 · 实测结果**：
  1. `build.ps1 -NoZip` 通过（9/9 `[OK]` + `构建完成`，约 2.9 分钟，1.74 GB；**判据用日志内容，不用 exit code**——uvicorn 往 stderr 写 INFO 会被 PowerShell 包成 `NativeCommandError`）
  2. 构建期与产物 runtime 的 `launcher.py --check` 均「环境自检通过」
  3. **双进程实证**：恰好 2 个 python 进程、worker 命令行含 `worker_entry.py --parent-pid`、`/api/health.worker.mode == "external"`（**不是 `web-inproc`**）、停止后 `residual=0` 且 pid 文件清空
  4. `pythonw --silent`：两进程 `MainWindowHandle=0`、`console.log` 有 startup complete、`worker.log` 有启动行、不弹窗不卡输入
- 🔴 **本轮抓到并修掉的两个「开发全绿、打包必崩」缺陷**（都不在计划里，只有真跑才暴露）：
  1. **`python -m app.worker` 在交付包里根本起不来**。交付包用 **Windows embeddable Python**，`python313._pth` 把解释器变成隔离模式 → **忽略 `PYTHONPATH`**，`sys.path` 的 `.` 指向 `runtime\python\` 而非 cwd。后果：worker 从不启动、web 5s 后按 `auto` 静默降级 → **功能看着正常，G3-④ 双进程形同虚设且用户零提示**（实测 `health` 报 `mode=web-inproc` 就是这么骗过去的）。
     修法：新增 `packaging/worker_entry.py`（80 行，`runpy.run_module`，语义与 `-m` 一致），`launcher` 经垫片启动，`build.ps1` 与 **`build-update.ps1`** 都拷贝它（就地更新也必须带上，否则老用户更新后 worker 起不来）。
  2. **首启两进程同时 `create_all` 撞车**。`create_all(checkfirst=True)` 是「反射查存在性 → CREATE TABLE」两步、**非原子**；全新安装首启（打包版首启、云端两 unit 同时起）会一方崩。老库永不暴露（表已存在直接跳过）→ 开发/回归全绿。
     修法：`db.init_db()` 加 `_create_all_tolerant()`，只重试「already exists / duplicate column / index already exists / **readonly database / database is locked**」两类（≤6×0.25s），**其余错误立即抛**。
     ⚠️ 第二组是 QA 补的：毫秒对齐双进程实测 **10 轮 3 轮**出现 `attempt to write a readonly database`（症状与前者完全相同：worker 死、web 静默降级）。QA 用 12 进程×5 轮 80+ 次**未能复现** `table notes already exists` —— 所以 docstring 只写「机制推断 + 并发实验复现（readonly/locked）」，**不声称复现过 notes already exists**。
- **打包版是否打进 `migrations/`：决定不打**。运行时走 `init_db()`（create_all + 补列 + 补索引），完全不依赖 alembic；打进去只多 40 KB 但引入「用户能改 schema」的新故障面。迁移是开发/部署动作（云端 tar 只含 `backend/app`）。
- ⚠️ `build.ps1` 会对**所有** bat 与 `使用说明.txt` 做占位符替换 + `Write-TextFile -Crlf`。验收「产物与源一致」**必须归一化比较**（`使用说明.txt`：去 CR + 把实际值换回占位符；bat：仅去 CR）。直接 `cmp` 必然假红 —— 这条已连续坑了两次。
- 工时：0.5 天 → **实际 ≈0.9 天**（两个缺陷 + 两轮重打包）

**⚡ G3 闸门通过后方可进入 P4。**

---

## 7. P4 —— 题型插件化与 IELTS 数据模型（4–6 天）

### P4-1 题型契约与注册表（2 天）
- [ ] 产出：`backend/app/services/question_types/`（`base.py` + `registry.py` + `dictation.py` 包装器）
- 契约见 `ADR-001 §5.5.1` + **§7.1 的异步修订**（`grade_mode: sync|async`、`grade_async()`）
- 关键：**现有 `services/dictation.py` 的纯函数原样包装成 `dictation` 题型，逻辑零改动** —— 这是「听写降级为一种题型」的落地动作
- [ ] `GET /api/question-types` 下发注册表（code / grade_mode / 是否需要外部服务），**防前后端题型清单漂移**
- 验收：现有听写功能无任何行为变化（P0-5 的 `test_dictation.py` 必须全绿）

### P4-2 前端题型动态挂载（1 天）
- [ ] 产出：`frontend-vue/src/question-types/`，每个题型 = 一个作答组件 + 一个结果渲染组件，按 `code` 动态挂载（`<component :is>`）
- 验收（G4-①）：新增一个占位题型只需加模块 + 组件，不改核心

### P4-3 IELTS 数据模型（1.5 天）
- [ ] 产出：6 张新表（见 `ADR-001 §5.5.2`）：`papers / sections / passages / questions / practice_sessions / responses`
- 强制约定：
  - ✅ `answer` / `detail` 用 **JSON 列**（不同题型答案形状差异大，硬拆列会不断 `ALTER TABLE`）
  - ✅ **不改 `media/sentences/attempts`**（Q4 锁定）
  - ✅ 听力 section 复用现有音频：`questions.type='dictation'` + `ref_sentence_id`
  - ⚠️ `media.status` 状态机（素材处理）与考试会话状态（作答流程）是**两条独立的轴**，不要合并
- 全部通过 **Alembic 迁移**（P3-1 的成果）
- [ ] 新增端点：`/api/papers`、`/api/papers/{id}`、`/api/papers/{id}/sessions`、`/api/sessions/{id}/responses`、`/api/sessions/{id}/submit`、`/api/sessions/{id}/report`
- 验收：提交后 `check-contract.mjs` 提示契约变更 → 显式确认并更新基线

### P4-4 写作批改异步化（1–1.5 天，Q6 强制约束）
- [ ] `kind='grade_writing'` 的 job，走 **IO 池**
- 四条硬约束（见 `ADR-001 §7.1`）：
  1. 交卷请求只**入队**并返回 `status='grading'`，前端轮询/SSE 取结果（**绝不同步阻塞**）
  2. 结果**按 `(question_id, normalized_response)` 缓存**（参照 `translations` 表的 sha1 key 模式），避免重复付费
  3. **降级路径**：外部服务不可用时返回「参考范文 + 评分标准 + 自评清单」，`status='degraded'` —— **绝不能因第三方挂掉导致无法交卷**
  4. API Key 走 `FAYELONG_*` 环境变量，**不写入 `data/`、不写数据库**
- 成本闸：按会话计数调用次数/token，超阈值拒绝并提示
- 验收（G4-②）：**断网实测**交卷仍可用，写作题降级为参考范文
- ⚠️ **开工前需再确认一次**：外部 AI 批改是本项目**唯一付费点**，与「零付费依赖」的既有定位冲突。若不愿付费，此任务改为「只给参考范文 + 评分标准」。

**⚡ G4 闸门通过后方可进入 P5。**

---

## 8. P5 —— 切换上线（1.5 天）

### P5-1 双跑比对（0.5 天）
- [ ] 旧 Vue? 否 —— 旧 React 跑 5173、新 Vue 跑 5174，**连同一后端**逐页比对
- ⚠️ 改完前端源码**必须 `vite build` 再跑浏览器验证**，否则读到旧 bundle（历史高频坑）

### P5-2 切换机制（0.5 天）
- [ ] `core/config.py` 的 `STATIC_CANDIDATES` 增加 `frontend-vue/dist` 候选（**先放第二位**，验证后再提到第一位）
- [ ] 云端 Caddy 灰度后再切；切换后校验**公网拉取 bundle 与本地 md5 一致**（等价于「线上跑的就是本地验过的那份」）

### P5-3 冻结旧前端（0.5 天）
- [ ] 打 tag `frontend-react-final` 并推远端
- [ ] 在 `frontend/README` 顶部标注「已被 `frontend-vue/` 取代，仅作历史参考，不再维护」
- ⛔ **绝不长期并行维护两套 SPA**（那是双倍成本，比不重构更糟）

### P5-4 打包与云端发布
- [ ] 本地全量包：`packaging/build.ps1`（约 4 分钟）
- [ ] 云端：沿用已跑通的流程（tar 只含 `backend/app` + 新前端产物，排除 `__pycache__`/`.pyc`）→ scp → 备份 → `systemctl stop fayelong` → 清旧 assets → 解包 → `chown` → 启 → 验证
- [ ] ⚠️ `data/` 全程只读不覆盖
- [ ] 首次启用需在 systemd unit 里注入写作批改的 `FAYELONG_*` 密钥（若启用）

---

## 9. 回滚预案

| 阶段 | 回滚动作 | 耗时 |
|---|---|---|
| P0–P4 期间 | 前端未上线，后端改动均有 Alembic 可 downgrade + `data/backups/` 备份 | 分钟级 |
| P5 切换后 | `STATIC_CANDIDATES` 改回 `frontend/dist` + `systemctl restart fayelong`（后端零改动，旧前端随时可用） | < 5 分钟 |
| 后端恶化 | `data/backups/{app-<tag>-<ts>.db, code-*.tar.gz, web-*.tar.gz}` 还原 | 分钟级 |

**回滚演练**（G5-③）：切换完成后主动演练一次，确认真的能回滚 —— 未演练的回滚方案等于没有。

---

## 10. 进度记录表

| 阶段 | 计划工时 | 实际 | 状态 | 备注 |
|---|---|---|---|---|
| P0 契约冻结与测试网 | 2d | ≈4 天（0.5+0.5+0.5+1+1+0.5） | ✅ G0 PASS（2026-10-16，QA 独立复核 4/4） | 实测 34 path / 42 op；六处偏差见 §3；G0 三项有牙证据见 QA 报告；数据安全基线=内容指纹 `scripts/fingerprint_data.py`（`TOTAL=278bcd28…`）|
| P1 Vue 骨架 | 2d | ≈2 天（Round A+B） | ✅ G1 PASS（2026-10-16，QA 独立复核） | 4 业务路由+兜底（登录非路由）；Round C/D 另含隔离后端 + 指纹基建 |
| P2-A 登录页 | 0.5d | ≈0.5 天 | ✅ G2 PASS（2026-10-16，QA 独立复核） | LoginPage(setup+登录) + AccountMenu 改密弹窗；`verify_vue_login` 默认 copy+fresh **19/19**（隔离后端，零写库）；已修 A7 跨导航等待谓词 |
| P2-B 播放条 | 1d | ≈1 天（Round E+F+G） | ✅ G2 PASS（2026-10-16，QA 独立复核） | `verify_vue_player` **15/15**（隔离后端 + 无头下真实音频推进）；变异测试证明 B3 有牙（删 A-B 失效逻辑 → FAIL） |
| P2-C 媒体库页 | 2.5d | ≈1.5 天（主理人接手） | ✅ G2 PASS（2026-10-16，QA 独立复核） | verify_category **58/58** 直接打 Vue 版；⚠️ 变异测试暴露覆盖缺口：批量菜单「未分类」选项无断言（已派补） |
| P2-D 学习页 | 4d | ≈2 天（Round H1+H2） | ✅ G2 PASS（2026-10-19 补验） | verify_m5 **15/15**、verify_marks **19/19**；原 verify_m4 9/12 的 3 项失败**归因成立**（生词页当时是占位），P2-E 完成后 **12/12** |
| P2-E 生词练习 | 2d | ≈0.5 天 | ✅ G2 PASS（2026-10-19，QA 独立复核） | 拆 7 文件 / 1,340 行；verify_vocab_practice **29/29**（零改动打 Vue 版）；两次变异测试证明有牙；空态/IME/导出参数/回车两态均补测 |
| P2-F 移动端回归 | 1d | ≈0.3 天 | ✅ G2 PASS（2026-10-19，QA 独立复核） | verify_mobile **36/36**（3 视口 × 12 项）；375px 四页零横向溢出 |
| P3-1 Alembic | 1d | ≈0.7 天 | ✅ G3-① PASS（2026-10-19，QA 独立复核） | 11 用例 / 184 passed；副本 upgrade 内容哈希全等；变异 C/D/E/F 四个全红（结构断言点名 `categories.created_at`，行为冒烟复现 `IntegrityError`）；⚠️ ini 必须纯 ASCII、`-x db_path` 要走 `cygpath` |
| P3-2 jobs+worker | 1.5d | ≈1.5 天 | ✅ G3-② PASS（2026-10-19，QA 独立复核） | 240 passed；`kill -9` 后 9.4s 接管、`attempts=2`；**QA 抓出 P1 fencing 写回缺陷并返工**（老执行者迟到写回能覆盖接管者）；变异/探针全红 |
| P3-3 CPU/IO 分池 | 含上 | 含上 | ✅ G3-③ PASS（2026-10-19，QA 独立复核） | 拆 4 stage job；`max(translate_end)-asr_end=-0.662s`、`overlapped=[101,102,103]`；⚠️ 判别力仅 cpu=1（云端已钉） |
| P3-4 领域收口 | 1d | ≈0.4 天 | ✅ PASS（2026-10-20，QA 独立复核） | `api/media.py` 682→420；新增 `media_ops.py`(802)；契约 34/42；前端套件 `verify_category` 59 项 + `verify_m5` 19 项全过 |
| P3-5 可观测性 | 0.5d | ≈0.3 天 | ✅ PASS | health 加 `disk` 块；job_id 贯穿（contextvars + handler Filter）；无 job_id 时日志格式逐字不变 |
| P3-6 打包链 G3-④ | 0.5d | ≈0.9 天 | ✅ G3-④ PASS | 9/9 `[OK]`；双进程 `mode=external`；停后 0 残留；🔴 修掉 2 个「开发绿/打包崩」缺陷（embeddable `_pth` 致 `-m app.worker` 失效、首启并发 `create_all` 撞车） |
| P4 题型插件化 | 4–6d | | ⬜ | |
| P5 切换上线 | 1.5d | | ⬜ | |
| **合计** | **19–25d** | **已用 ≈15.6 天**（前端链 P0–P2 ≈11.8 + P3 后端债 ≈3.8；P4/P5 未开工） | | 业余约 8–12 周；**P3 已全部完成，G3 四项判据达成** |

**⚠️ 前端链（P0–P2）至此全部完成。** P2 收尾时仍挂账的 2 项覆盖缺口（不影响已过闸门的结论，属回归套件增强）：
1. `verify_category.mjs` 批量菜单「未分类」选项**无断言**（P2-C 变异测试暴露）。
2. `verify_m5.mjs` 缺「草稿持久化」断言（P2-D 时期挂账；其中「键盘回车」「宫格触摸」两项已由 P2-E 的回车两态实测与 P2-F 的 `verify_mobile` 覆盖）。

### P3-2/P3-3 收尾挂账（均不阻塞，但别丢）

1. **【P4 启用 `grade_writing` 前必修】非 media 分支没有 fence**：`worker.py:597-628` 的 `_write_terminal_failure` 走 `db.get(Job)` + `force_failed(job)`（当前归属）。**当前不可达**（`recover_stale` 会把 `attempts>=max` 的 running 直接判 failed，且本阶段无人入队 `grade_writing`），但 P4 一旦启用写作批改，这就是 D1 的翻版。修法：把 `worker_id`/`attempts` 传进去（`force_failed` 本来就支持裸 id + 显式 fence）。
2. **【记账】部分索引谓词「改窄」只有一条字面量断言守着**：通用四元组只比 `partial` 布尔位，`alembic check` 也仍绿 → 把 `('pending','running')` 改成 `('pending')` 只有 `test_migrations.py::test_fresh_database_creates_all_indexes` 里 `'pending' in ddl and 'running' in ddl` 一句能抓。**别删那句**；删了这类退化会静默通过（`running` 行脱离唯一约束保护 → 同一任务可被并发双入队）。
3. **【P4】`requeue_unfinished()` 与运行中 worker 重叠**：P3-2 之后 worker 能活过 web 重启，而该函数仍会把 `media.status` 重置为 `pending` 并额外入队一条 `media_transcode`（跨 kind 不撞 `uq_jobs_active`）。可自愈、不丢数据（`_ensure_audio` 会命中「wav 已存在」早退），但 UI 进度会回 0。**已裁决本阶段行为不改**（签名/返回条数/入队方式），代码里已把注释改成实话并标注 P4 修法（入队前查活跃 job 则跳过）。
4. **【P4】`_PoolRunner.idle()` 用全局 `has_active_work`**：`--once` 在「有本池接不了的 job」时会空转到 drain timeout（最多 5s，无正确性问题）。改它要动 `has_active_work` 签名，故本阶段不做。
5. **【工具边界】** `alembic check` 罩不住 SQLite 部分索引谓词（摘掉 `sqlite_where` 后它仍绿）；已由显式断言兜底，属工具能力边界。
6. **【环境事实】** `os.cpu_count()` 不识别 cgroup 配额 → `FAYELONG_JOB_CPU_THREADS=0(auto)` 在容器化部署下不可依赖；云端 unit 已显式钉 1。

### P3-4~P3-6 收尾挂账（均不阻塞）

1. **【P4】`停止 FayeLong.bat` 只有 worker.pid 时的文案**：已从 `FayeLong is not running.` 改为 `Stopped leftover task worker.`（launcher 被任务管理器强杀的场景）。
2. **【记账】构建期改写过的文件不能用直接 `cmp` 校验**：`build.ps1` 对 `使用说明.txt` 做占位符替换 + CRLF 归一，对所有 bat 也做 CRLF 归一。正确判据：`使用说明.txt` 去 CR 后把实际值换回 `{{VERSION}}/{{BUILD_DATE}}/{{MODE}}` 再比；bat 仅去 CR 后比。**这条已连续坑了两次**（P3-6 两轮验收）。
3. **【记账】`_create_all_tolerant` 的重试组必须保持两组语义分开**：`already exists` 类（幂等）与 `readonly/locked` 类（瞬时）——日志与排查语义不同。**绝不能把 `disk I/O error` / `no such table` 塞进去**（那是真错误，必须立刻抛）。
4. **【记账】`table notes already exists` 这条事故记录不可复现**：QA 用 12 进程×5 轮 + 毫秒屏障 80+ 次未复现，仓库/产物/日志无残留。docstring 只保留「机制推断 + readonly/locked 类并发实验复现」，**不要**再声称复现过那个具体报错。
5. **【P4】`停止 FayeLong.bat` 的输出是英文**：`cmd.exe` 在 `chcp 65001` 下按字节解析批处理，含中文会让 `goto`/括号块错位（实测出鬼影错误行）。停止脚本又必须在 runtime 损坏时可用，所以刻意**不依赖 Python 打印中文**；中文引导在 `使用说明.txt`（第 36 行 + Q10）。

---

## 附：本计划明确不做的事（范围护栏）

- ❌ 不换后端语言、不引入 JVM / Python sidecar（Q1）
- ❌ 不改 ASR / ffmpeg / ECDICT 三处引擎
- ❌ 不重写 Windows 打包链（仅追加 worker 进程的启动逻辑）
- ❌ 不做历史数据迁移（Q4）
- ❌ 不引入重监控栈
- ❌ 重写期间不开发任何 IELTS 新功能（Q2）
- ❌ 不长期并行维护 React 与 Vue 两套前端

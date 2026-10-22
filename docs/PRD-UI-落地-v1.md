# PRD · FayeLong UI 落地 v1

> 版本 v1 · 2026-10-22 · 负责人：许清楚（产品）
> 需求源头：`design/UI-落地执行计划.md`（下称「计划」）；本 PRD 只做**增量定义**（范围、验收、交付节奏），技术细节引用计划章节号，不重复。
> 设计契约：`design/design-contract.md`（下称「契约」）
> 当前基线：v1.16.1 / main / `7e53f45`（`c921de3` 之上一次 docs 提交）

---

## 1. 产品目标

**一句话**：把 `design/` 的 6 页高保真稿落到 `frontend-vue/`，补齐统计页真值能力，全程不破坏既有 7 个 verify 与数据指纹。

| # | 可衡量指标 | 判定方式 | 基线 → 目标 |
|---|---|---|---|
| M1 | 6 页视觉统一到 logo 风格 | 6 页人工截图比对设计稿，逐页 checklist 通过；页面源码内**零硬编码色值**（`grep -E "#[0-9a-fA-F]{6}" src/pages src/components` 仅命中 token 层与 SVG 描边例外清单） | 现在 5 页为 slate 灰蓝体系 → 6 页全 token 化 |
| M2 | 既有 verify 全绿不回退 | 7 个脚本（`verify_mobile` / `verify_m4` / `verify_m5` / `verify_marks` / `verify_attempt_history` / `verify_vue_login` / `verify_vue_skeleton`）通过项数 ≥ 改动前基线 | 先记录基线，再逐阶段对账 |
| M3 | 统计页 7 区块全部真值出图 | `GET /api/stats/overview` 返回值与手工 SQL 逐项对数一致；7 区块无「假数据/占位数字」；空库走空态不报 NaN | 现在无统计页 → 7/7 真值 |

---

## 2. 用户故事

唯一用户 = 站点所有者（本人，单机自用）。角色按「使用时刻」拆，不虚构第二用户。

| # | 用户故事 |
|---|---|
| US-1 | 作为学习者，我希望**媒体库首页**一眼看到今日已听/连续天数/待复习数，并直接点「继续学习」，以便打开站点 3 秒内就能进入听写，而不是先找入口 |
| US-2 | 作为学习者，我希望**学习页**在 390px 手机上不出现横向滚动、触摸目标够大、播放条不遮最后一句，以便通勤时单手逐句精听 |
| US-3 | 作为学习者，我希望**提交听写后**才看到原文 diff 与错误词高亮，以便不提前被答案剧透（原文只在服务端，提交接口返回） |
| US-4 | 作为学习者，我希望**生词本**按「待复习/已掌握」筛出今天该看的词并一键进练习，以便不用自己判断该复习哪些 |
| US-5 | 作为学习者，我希望**生词练习**判分后立刻看到对错反馈与会话正确率，以便知道自己这轮练得怎么样 |
| US-6 | 作为学习者，我希望**登录页**明白「账号与学习记录只存在本机」，以便放心把它当私人工具用 |
| US-7 | 作为学习者，我希望**统计页**看到 14 天听写量、正确率趋势、连续天数、课程完成度，以便判断「我的练习量到底够不够」，而不是凭感觉 |

---

## 3. 范围与不做的事

### 3.1 In scope

| 阶段 | 内容 | 对应计划章节 |
|---|---|---|
| **P0** | token 基建（`:root` 变量 + tailwind 挂接 + 通用类基座 + 奶油底纹）+ verify 断言解耦 | §6 Phase 0 |
| **P1** | 全局外壳 + 6 页换皮（登录/统计/媒体库/生词本/练习/学习） | §6 Phase 1 |
| **P2** | `GET /api/stats/overview` + 契约基线更新 + `StatsPage.vue` + 4 个 SVG 图表组件 | §4.3 / §5 |

### 3.2 Out of scope（本期明确不做）

| 不做项 | 原因 |
|---|---|
| **P3-1 生词 SRS 字段**（`review_count` / `last_result` / `next_review_at` / `stage`） | 涉及 `data/app.db` 真表结构变更 → 必须单独评审 + 迁移前后指纹比对；本期不做可让统计页与生词本先以两态成立（计划 §4.2 结论） |
| **P3-2 练习结果落库**（`VocabPracticeLog` + `POST /api/vocab/practice-log`） | 同上，且会引入新的写入路径，与「换皮不改业务逻辑」冲突 |
| **P3-3 学习时长埋点**（`StudyEvent` + 播放器心跳） | 计划 §4.2 已判定「建议独立小立项，不阻塞本期」 |
| 引入组件库 / 图表库 | 计划 §1；图表全 SVG 自绘（契约 §10 v3） |
| 后端业务逻辑与既有 API 契约语义变更 | 只新增 `/api/stats/overview`，其余端点零改动 |
| 旧 React 回滚通道调整 | `dist` 备份与 tag 保持不动（计划 §8-5） |
| 记忆曲线队列 UI / 五态标签全量启用 | 数据未就位，降级两态（计划 §4.2、§8-2） |

---

## 4. 需求池

> 优先级：P0 = 必须（阻断后续）/ P1 = 应该（本期主体）/ P2 = 应该（本期收尾）
> 验收标准全部可被脚本或人工 checklist 判定。

### 4.1 P0 · token 基建（6 条）

| 编号 | 需求 | 验收标准 | 涉及文件 |
|---|---|---|---|
| **P0-1** | 建立 token 层：`:root` 写入契约 §1 色板、§3 形状、§2 字体栈；新增 6 档间距/圆角/硬阴影变量 | 变量名与取值与契约 §1–§3 **逐字一致**（人工 diff 一遍）；`grep` 确认 `--lemon-400: #FFD93B` 存在 | 新建 `frontend-vue/src/styles/tokens.css`（由 `index.css` `@import`） |
| **P0-2** | tailwind `theme.extend` 挂接：`colors`（lemon 100→500 / ink / ink-2 / ink-3 / leaf / leaf-1 / peach / peach-1 / cream / cream-2 / card）、`borderRadius`（card 20 / control 14 / pill 999）、`boxShadow`（`sticker: 0 3px 0 var(--ink)`）、`fontFamily` | `npm run build` 通过；临时写一个 `<div class="bg-lemon-400 text-ink rounded-card shadow-sticker">` 能在产物 CSS 中查到对应声明 | `frontend-vue/tailwind.config.js`、`src/styles/tokens.css` |
| **P0-3** | 通用类基座：`.btn`（primary/secondary/disabled/hover/active 全态）、`.card`、`.pill`、`.bar`、`.chip`、`.input`、`.nav-pill`；**只加类不改任何页面** | 本阶段 `git diff --stat` 中 `src/pages/**`、`src/components/**` 零改动；类定义符合契约 §4 各项尺寸（按钮 46px / 移动 48px、描边 2px、药丸） | `src/styles/components.css` 或 `index.css` `@layer components` |
| **P0-4** | 画布底：body 换 `--cream` + 18px 点阵纹理（纯 CSS，无外网资源）；`--ink` 主文字色 | 页面底色为 `#FFFBF0`；`grep` 无 http(s) 外链资源 | `src/index.css` |
| **P0-5** | **verify 断言解耦（前置改造）**：把脚本里与视觉类耦合的断言改为语义锚点 —— ① `verify_m5` 4 处 `bg-slate-900/bg-emerald-100/bg-amber-100/bg-slate-100` 改为读 `data-state` 或 `getComputedStyle`；② `verify_vue_skeleton` 导航高亮 `bg-slate-900` 同上；③ 导航条数断言 `length === 2` 改为「按文本定位 + 至少包含」 | 改造后**在未改页面源码的前提下**重跑这两个脚本仍全绿（证明解耦未引入回归）；`data-*` 零删除（仅允许新增 `data-state`） | `scripts/verify_m5.mjs`、`scripts/verify_vue_skeleton.mjs`、`src/components/SentenceStage.vue`（补 `data-state`） |
| **P0-6** | 基线快照记录：跑一遍 7 个 verify + `pytest` + `check-contract` + 指纹，把通过项数/退出码写进阶段记录 | 记录文件含 5 项数字：pytest passed 数、契约退出码、7 verify 各自通过项、`TOTAL` 指纹、build 状态 | `docs/records/P0-token基建.md` |

> **P0-5 是本期最关键的顺序决策**：不做它，P1 换皮时 M2 指标无法判定「视觉改动导致红」还是「产品逻辑退化」。

### 4.2 P1 · 六页换皮 + 公共外壳（7 条）

实现顺序按计划 §6 Phase 1「风险从低到高」，第 2 条是跨页公共件，故插在统计页之前。

| 顺序 | 编号 | 页面 / 范围 | 需求 | 验收标准 | 涉及文件 | 主要风险点 |
|---|---|---|---|---|---|---|
| 1 | **P1-1** | 登录页 | 按 `page-5-login.html` 重排：左品牌面（奶油+三色光斑+大 logo+slogan+三条特性）/ 右白卡表单（26px 圆角、50px 输入框、focus 黄光环）/ 右上探头小龙贴纸 / 底部「账号与学习记录只存在本机」 | `verify_vue_login` 全绿；**placeholder 文案一字不改**（`当前密码`、`新密码…`、`例如 faye`）；按钮文案 `修改密码`/`保存`/`取消` 不变；`form button[type=submit]` 仍唯一 | `src/pages/LoginPage.vue`、`src/App.vue` | 低。`verify_vue_login` 靠 placeholder 与按钮文案定位 —— 换皮时最容易「顺手优化文案」而红 |
| 2 | **P1-2** | 公共外壳（跨 6 页） | `Layout.vue` 按契约 §4「导航」重做：顶栏药丸导航（选中黄底+棕描边）、移动端底部 Tab Bar（48px + 10.5px 文字 + `env()` 安全区）、`--cream` 背景 | `verify_vue_skeleton` 三段式断言全绿（header shrink-0 / main flex-1 min-h-0 / footer shrink-0）；外壳高度 = `dvh`；375px 无横向溢出；**无 `calc(100vh - …)`**（`grep` 零命中） | `src/components/Layout.vue`、`src/components/PlayerBar.vue`（仅容器定位） | **中高**。①底栏 Tab 是新增的第四个 flex 块，与 `PlayerBar`（现充当 footer）抢位置；②`main h2` 文案须保持含「媒体库/学习页/生词本/生词练习」；③触摸目标 ≥44px |
| 3 | **P1-3** | 统计页（新） | 见 P2-4 骨架部分；本阶段先落「路由 + 顶栏入口 + 页面骨架 + 空态」，图表数据接口可后接 | 路由 `/stats` 可直达不报错；顶栏「统计」高亮；导航由 2 项变 3 项后 `verify_vue_skeleton` 仍绿（依赖 P0-5） | `src/router/index.ts`、`src/pages/StatsPage.vue`、`src/components/Layout.vue` | 中。导航项数变化是 `verify_vue_skeleton` 的历史断言点，P0-5 未完成则必红 |
| 4 | **P1-4** | 媒体库 | 按 `page-1-library.html` 重排（契约 §6 八区层级）：Hero + 数据条 + 继续学习卡 + 筛选 chip + 课程网格 + 上传区；移动端课程卡变横排列表行（86px 封面在左） | `verify_vue_skeleton` 中 `/` 的 `h2` 含「媒体库」；上传/分类/搜索交互零改动；骨架屏（`ListSkeleton`）仍可见；390px 单列 | `src/pages/MediaLibraryPage.vue`(853行)、`MediaRow.vue`、`CategoryChips.vue`、`StatCard.vue`、`ListSkeleton.vue` | **中**。853 行为最大单页，含上传/分类/排序/搜索；`verify_m4` 笔记流程从此页进入，`data-testid="toggle-note"` 不可动 |
| 5 | **P1-5** | 生词本 | 按 `page-3-vocab.html` 重排；**状态标签降级两态**（已掌握 / 未掌握），记忆曲线队列与五态标签本期不启用 | `verify_m5` 全绿（含宫格着色与笔记面板断言）；`data-vocab-row` 保留；两态筛选可切换并生效 | `src/pages/VocabPage.vue`、`VocabRow.vue`、`src/components/category.ts` | **中**。`verify_m5` 断言「笔记」入口文案以 `笔记` 开头；`data-vocab-row` 是筛选断言锚点；超前设计（SRS/五态）需产品侧确认降级边界 |
| 6 | **P1-6** | 练习页 | 按 `page-4-practice.html` 重排（选择题对/错/漏高亮、会话统计） | `verify_vocab_practice` 全绿；**15 个 `data-practice-*` 全部保留**；判分逻辑零改动（仍前端本地判分，不落库） | `src/pages/VocabPracticePage.vue`(708行)、`VocabPracticeChoice/Field/Header.vue`、`src/question-types/**` | **中高**。`data-practice-*` 密度最高（accuracy/badge/feedback/input/next/option/phase/play…），重排时任一丢失直接红 |
| 7 | **P1-7** | 学习页 | 按 `page-2-study.html` 重排：逐句舞台 + 右侧句子列表 + 播放条；diff 卡只在**提交后**渲染 | `verify_mobile`(36项) + `verify_m5` + `verify_marks` + `verify_attempt_history` **四个脚本同时全绿**；390px 无横向滚动、触摸 ≥44、`h-dvh` 三段式；`data-testid` 15 个全保留；提交前 DOM 中不含听写原文 | `src/pages/StudyPage.vue`(765行)、`SentenceStage.vue`(609行)、`ClickableText.vue`、`PlayerBar.vue` | **最高**。铁律集中地：`calc(100vh-Npx)` 禁令、隐藏内容不进 DOM、宫格着色、AB 循环/播放器交互零改动；一改可能触发多脚本连环红 |

### 4.3 P2 · 统计页前后端（7 条）

| 编号 | 需求 | 验收标准 | 涉及文件 |
|---|---|---|---|
| **P2-1** | 后端 `OverviewOut` 响应模型 + `GET /api/stats/overview?days=14`（聚合口径与字段见计划 §4.3） | 手工 SQL 逐项对数一致；`days` 缺省 14；空库返回全零数组（**非 404**，计划 §4.3）；路由挂在现有 `stats.py` 不新开文件（计划 §4.3） | `backend/app/schemas/stats.py`、`backend/app/api/stats.py` |
| **P2-2** | 后端单测：覆盖 ①空库全零 ②有数据时的 daily/kpi/courses/recent ③`days` 参数边界 | `pytest backend/tests -q` passed 数 **≥ 378 且只增不减**（计划 §7 基线） | `backend/tests/` 新增用例文件 |
| **P2-3** | 契约基线更新：重生成 `contracts/openapi-v1.json` + `contracts/api-types.d.ts` | `node scripts/check-contract.mjs` 退出码 **0**；diff 仅含 `/api/stats/overview` 一条新增，无其它端点结构变化 | `contracts/openapi-v1.json`、`contracts/api-types.d.ts` |
| **P2-4** | 前端 `StatsPage.vue` 七区块（KPI 四卡 / 柱状 / 折线 / 热力图 / 环形 / 课程完成度 / 最近听写）+ 路由 + 顶栏实链 | 7 区块在真实库上全部渲染出图、无占位数字；区块优先级顺序与计划 §5.1 一致；KPI 数值与 P2-1 接口返回值逐字相等 | `src/pages/StatsPage.vue`、`src/api/stats.ts`（新建）、`src/router/index.ts`、`Layout.vue` |
| **P2-5** | 4 个 SVG 图表组件（`BarChart` / `LineChart` / `Heatmap` / `Donut`），零图表库 | 组件内部零第三方 import；色板只取 token（柱 `--lemon-400`、折线 `--leaf`、目标线 `--peach` 虚线、热力 lemon 100→500 五档）；数据系列 ≤3 色；柱顶有数值、时间轴隔日标注（计划 §5.2） | `src/components/charts/{BarChart,LineChart,Heatmap,Donut}.vue` |
| **P2-6** | 空态与响应式：`daily` 全零时柱状区显示引导卡（「先去媒体库上传一段音频」+ 主按钮跳转），KPI 显示 0 非 NaN，热力图全灰；≥1024 / ≤767 两档栅格见计划 §5.3 | 空库（零数据副本）下无 NaN/undefined 出现在 UI；390px 图表区横向可滚、不缩格、页面无横向溢出 | `StatsPage.vue` + 4 图表组件 |
| **P2-7** | 云端冒烟：部署后实跑一次统计页 | 云端 Python 3.12 下 `/api/stats/overview` 返回结构与本地一致；页面无脚本错误（计划 §6 Phase 2 末项） | `deploy/`（不动，仅记录结果） |

**需求条目合计：P0 6 条 + P1 7 条 + P2 7 条 = 20 条**

---

## 4.5 每阶段交付定义（DoD）

> 用户本次额外要求「每个阶段都形成记录以及代码提交」。以下 7 项**逐项勾完才算该阶段交付**，缺一不可。

### 4.5.1 通用 DoD（三阶段共用）

| # | 项 | 判定命令 / 动作 | 通过标准 |
|---|---|---|---|
| D1 | 实现完成 | 对照需求池条目逐条自查 | 该阶段全部条目验收标准命中 |
| D2 | 构建通过 | `cd frontend-vue && npm run build` | 退出码 0（含 `vue-tsc --noEmit` 类型检查） |
| D3 | 相关 verify 通过 | 见下表「阶段必跑脚本」 | 通过项数 ≥ P0-6 记录的基线 |
| D4 | 数据指纹不变 | `python scripts/fingerprint_data.py` | `TOTAL` 仍为 `278bcd28…` 基线 |
| D5 | 阶段记录已写 | 新建 `docs/records/<阶段ID>-<名称>.md` | 含：做了什么 / 验收证据（命令+输出摘要）/ 与计划的偏差 / 遗留项 |
| D6 | git 提交完成 | 见 §4.5.3 提交信息规范 | 每阶段至少 1 个提交；`git status` 干净 |
| D7 | 后端测试不回退（仅 P2 必跑） | `backend/.venv/Scripts/python.exe -m pytest backend/tests -q` | passed ≥ 378 / skipped ≤ 1 |

> **D3 与 D4 存在操作冲突，必须按顺序执行**：verify 脚本会写笔记、听写、生词（`verify_m4`/`verify_m5`/`verify_marks` 均落库）。
> 因此 **verify 一律跑在隔离副本上**（`data/app.db` 的副本库 + 独立数据根，参考 `verify_vue_player.mjs --iso-root` 的做法），
> 跑完 verify 再对**真实库**跑指纹。若在真实库上跑 verify，指纹必然变化，D4 会被误判为「数据被污染」。

### 4.5.2 阶段专属 DoD

| 阶段 | 必跑 verify | 额外门禁 | 记录文件 |
|---|---|---|---|
| **P0** | `verify_vue_skeleton`、`verify_m5`（因为改了这两个脚本，必须证明改造后仍绿） | `grep` 确认 `src/pages/**` 等业务文件零改动 | `docs/records/P0-token基建.md` |
| **P1**（每页一个子 DoD） | 逐页：登录→`verify_vue_login`；外壳→`verify_vue_skeleton`；统计→`verify_vue_skeleton`；媒体库→`verify_vue_skeleton`+`verify_m4`；生词本→`verify_m5`；练习→`verify_vocab_practice`；学习→`verify_mobile`+`verify_m5`+`verify_marks`+`verify_attempt_history` | 每页 390px 宽人工 checklist（无横向滚动 / 触摸 ≥44 / `h-dvh` / 底栏不遮内容）+ 截图存 `docs/records/assets/` | `docs/records/P1-<序号>-<页面>.md`（7 份） |
| **P2** | `verify_vue_skeleton`（路由 + 导航 3 项后仍绿） | `node scripts/check-contract.mjs` 退出码 0；`pytest` ≥378 passed；空库副本走一遍空态 | `docs/records/P2-统计页.md` |

### 4.5.3 git 提交规范

```
<type>(<scope>): <中文简述>

- 做了什么（1–3 条）
- 验收：<脚本名> <通过项数> / build 通过 / 指纹 278bcd28…
```

| 阶段 | type | scope 示例 | 提交粒度 |
|---|---|---|---|
| P0 | `feat` / `test` | `ui-p0-token`、`ui-p0-verify` | 建议拆 2 个：token 基建 1 个、verify 解耦 1 个 |
| P1 | `feat` | `ui-p1-login`、`ui-p1-shell`、`ui-p1-stats`、`ui-p1-library`、`ui-p1-vocab`、`ui-p1-practice`、`ui-p1-study` | **每页 1 个提交**（计划 §9-1 推荐逐页，回滚粒度细） |
| P2 | `feat` / `test` / `chore` | `ui-p2-stats-api`、`ui-p2-stats-page`、`ui-p2-contract` | 建议拆 3 个：后端接口、前端页面+图表、契约基线 |

---

## 5. UI 设计稿索引

| 设计稿 | 页面 | 对应 Vue 页面 | 行数 | 配套组件 | 计划章节 |
|---|---|---|---|---|---|
| `design/page-5-login.html` | 登录 | `src/pages/LoginPage.vue` | 144 | `App.vue`（状态门禁，登录非路由） | §6 P1 |
| `design/page-1-library.html` | 媒体库首页 | `src/pages/MediaLibraryPage.vue` | 853 | `MediaRow` `CategoryChips` `StatCard` `ListSkeleton` `CategoryManager` | §6 P1 / 契约 §6 |
| `design/page-2-study.html` | 学习页 | `src/pages/StudyPage.vue` | 765 | `SentenceStage` `ClickableText` `PlayerBar` `NotesPanel` `note-editor` `WordPopover` | §6 P1 |
| `design/page-3-vocab.html` | 生词本 | `src/pages/VocabPage.vue` | 210 | `VocabRow` `category.ts` | §4.2（降级两态） |
| `design/page-4-practice.html` | 生词练习 | `src/pages/VocabPracticePage.vue` | 708 | `VocabPracticeChoice` `VocabPracticeField` `VocabPracticeHeader` `question-types/**` | §4.2（不落库） |
| `design/page-6-stats.html` | 学习统计 | `src/pages/StatsPage.vue`（**新建**） | — | `components/charts/{BarChart,LineChart,Heatmap,Donut}.vue`（**新建**） | §4.3 / §5 |
| `design/design-contract.md` | 全局 token | `src/styles/tokens.css`（**新建**）、`tailwind.config.js`、`index.css` | 16 | `Layout.vue` | §1–§4 |
| `design/color-compare.html` | 主色决策记录 | — | — | — | 已定 A `#FFD93B`，不再改 |

---

## 6. 待确认问题

| # | 问题 | 为什么影响实现 | 默认建议 |
|---|---|---|---|
| **Q1** | verify 脚本与**视觉类名**硬耦合（`verify_m5` 4 处颜色类：`bg-slate-900`/`bg-emerald-100`/`bg-amber-100`/`bg-slate-100`；`verify_vue_skeleton` 导航高亮 `bg-slate-900`），换皮后这些 class 必然消失 —— 是否允许改脚本？ | 铁律只保 `data-*`，未保 class；但改脚本会改变「验收基准」的定义，属产品/工程共同决策 | **允许**，走 P0-5 一次性解耦：改为 `data-state`（新增属性）或 `getComputedStyle`，改造后先证明「不改页面仍全绿」再进 P1 |
| **Q2** | 加「统计」导航项后，`verify_vue_skeleton` 的 `header nav a.length === 2` 断言必红 —— 放宽为几条？ | 直接决定 P1-3 能否提交 | 放宽为「按文本定位 `媒体库`/`生词本`/`统计` 三项，按文本判高亮」，不做条数硬校验（并入 P0-5） |
| **Q3** | 移动端底栏 Tab Bar（新增）与 `PlayerBar`（现为 Layout 第三个 flex 块）在底部的叠放关系？ | 影响 `verify_vue_skeleton` 的「footer 底部不超视口」断言与学习页首屏高度 | Tab 常驻占位；`PlayerBar` 无 current 时不渲染，有 current 时叠在 Tab 上方（`bottom: tab 高度`），Tab 与 PlayerBar 同时存在时 main 可视区不因叠加而裁切 |
| **Q4** | 生词本「记忆曲线队列 + 五态标签」是超前设计，本期降级到什么程度？ | 决定 P1-5 的模板结构与是否需要占位骨架 | 只渲染两态（已掌握/未掌握），**不渲染**五态占位；环形图第一版也用两态（计划 §5.1 已定），P3 数据到位再升级 |
| **Q5** | 统计页顶栏入口是否本期直接实链？ | 计划 §9-2 已推荐「直接实链」，但需确认非分批发布 | **实链**（`/stats`），不保留占位态；若后续要灰度，另开需求 |

---

## 7. 产品侧风险提示（与计划 §8 互补，仅列计划未覆盖的）

| # | 风险 | 说明 | 缓解 |
|---|---|---|---|
| R-A | **契约门禁会「假红」** | `scripts/check-contract.mjs` 是 diff 门禁（对比冻结基线 `contracts/openapi-v1.json`），新增 `/api/stats/overview` 必然非零退出，容易被误判为「接口写错」 | P2-3 与 P2-1 放同一提交内，先跑通再用新基线；记录里写明「diff 仅 1 条新增」 |
| R-B | **verify 污染真实库 → 指纹假红** | 4 个 verify 脚本会写笔记/听写/生词 | DoD 强制「verify 跑副本、指纹跑真实库」，见 §4.5.1 注 |
| R-C | **P3 不做导致设计稿与实现有可见落差** | 生词本五态标签、复习排期、环形三态、实际学习时长在稿里有、实现没有 | P1-5/P2-4 完成后在记录里附「与设计稿的已知差异清单」，交用户确认接受，避免后续被当成 bug |

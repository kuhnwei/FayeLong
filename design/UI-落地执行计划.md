# FayeLong UI 落地执行计划（设计稿 → frontend-vue）

> 版本 v1 · 2026-10-22 · 主色已定 **A `#FFD93B`**
> 设计稿：`design/`（6 页 + 契约 + 对比页），本计划回答「怎么落、按什么顺序、验收什么」。
> **本次不执行**，仅评审与排期。

---

## 1. 目标与范围

把 `design/` 里按 logo 风格产出的 6 页高保真稿落到 `frontend-vue/`，同时补齐统计页所需的后端数据能力。

**明确不做**（本期）：
- 不引入组件库、不引入图表库（图表全部 SVG 自绘）
- 不改任何业务逻辑、不改 API 契约语义（只新增统计端点）
- 不动 `data/app.db` 真实数据（指纹基线 `278bcd28…` 必须不变）

## 2. 设计交付物现状

| 文件 | 状态 | 备注 |
|---|---|---|
| `design-contract.md` | ✅ 定稿 | token 唯一入口；主色 A；2px 描边 |
| `page-1-library.html` | ✅ 定稿 | 媒体库首页 |
| `page-2-study.html` | ✅ 定稿 | 精听 + 听写 diff + 播放条 |
| `page-3-vocab.html` | ✅ 定稿 | ⚠️ 含超前设计（见 §4 缺口） |
| `page-4-practice.html` | ✅ 定稿 | 同上 |
| `page-5-login.html` | ✅ 定稿 | 登录 |
| `page-6-stats.html` | ✅ 定稿 | 统计页（本计划新增，规格见 §5） |

## 3. 核心约束（历史铁律，违反必炸）

1. **`data/app.db` 唯一真实数据**：所有开发/验证用副本；收尾跑 `scripts/fingerprint_data.py` 对基线。
2. **verify 脚本靠 `data-*` 属性驱动**（`verify_mobile` 36 项、`verify_m4` 12 项等共 7 个）。**换皮期间 `data-*` 一个都不许删改**；模板重排后必须全量跑 7 个脚本。
3. **学习页布局严禁 `calc(100vh - Npx)`**：外壳用 `h-dvh` 三段式；触摸目标 ≥44px。
4. **隐藏内容不进 DOM**：听写原文、答案判定只在服务端 —— 设计稿里的 diff 卡是「提交后」状态，实现时原文由提交接口返回，绝不能提前渲染进页面。
5. **云端 Python 3.12 / 本地 3.13**：新后端代码避免依赖 CPython 版本差异行为；上线前本地全绿 ≠ 云端可用，需云端实测。
6. **迁移策略**：云端不走 alembic，靠 `init_db()` 的 `create_all` + `_ensure_columns` 自愈 —— 新增列必须同时写进 `_ensure_columns` 清单。
7. **npm 必须 `--ignore-scripts`**；pip 用阿里云源；改完前端源码必须 `vite build` 再验。

## 4. 数据支撑矩阵（统计页 & 生词本的「真值」从哪来）

### 4.1 现有数据可直接算出 ✅

| 展示项 | 来源 | 说明 |
|---|---|---|
| 今日/每日听写句数 | `Attempt.created_at` 按日 count | 表已有时间戳 |
| 听写正确率（今日/趋势） | `Attempt.accuracy`（0–1 浮点，已存）按日 avg | **字段现成，此前没暴露** |
| 累计听写 / 已掌握句 | `stats.py` 现有逻辑 | 已有 |
| 今日新学生词 / 新增趋势 | `Vocab.created_at` 按日 count | 已有 |
| 连续学习天数 | `Attempt.created_at` 按日 distinct 聚合推算 | ⚠️ 近似：「打开但没听写」的日子不计；可接受，文案标注 |
| 课程完成度 | 每 `Media` 的 `Attempt.distinct(sentence_id)` / `Sentence` 总数 | 聚合 SQL 一次可出 |
| 最近听写列表 | `Attempt` 按 `created_at desc` + join 句子 | 已有 |
| 笔记数 / 素材状态 | `Note` / `Media.status` | 已有 |

### 4.2 需要后端新增 ❌（设计稿里的超前项）

| 缺口 | 现状 | 需要做什么 |
|---|---|---|
| **复习排期**（下次复习时间、复习次数、间隔） | `Vocab` 只有 `mastered` 布尔 + `created_at`，**没有任何 SRS 字段** | `Vocab` 加列：`review_count INT`、`last_result TEXT`、`next_review_at DATETIME`、`stage INT`；写入 `_ensure_columns` |
| **生词练习落库** | 练习是前端本地判分，结果不保存 | 新表 `VocabPracticeLog`（vocab_id、mode、is_correct、created_at）+ `POST /api/vocab/practice-log` |
| **实际学习时长** | 无任何「听了多久」的记录 | 新表 `StudyEvent`（media_id、sentence_id、duration_ms、created_at），学习页播放器心跳上报；**建议独立小立项，不阻塞本期** |
| 「连续答对 3 次 = 已掌握」 | `mastered` 目前是手动标记 | 由练习日志推导，或保留手动 + 自动建议 |

> **结论**：统计页第一版用 §4.1 的数据就完整成立；§4.2 属于「生词本/练习页的真值化」，放 Phase 3。落地生词本时，状态标签先降级为两态（已掌握 / 未掌握），记忆曲线队列等 Phase 3 数据到位再启用。

### 4.3 后端新增清单（本期唯一后端改动）

```
GET /api/stats/overview?days=14        # 一次聚合返回（延续 stats.py「一处聚合」理念）
  → daily:   [{date, attempts, accuracy, new_vocab}]        # 柱状图/折线/热力图同源
  → kpi:     {today_attempts, today_accuracy, today_new_vocab, streak_days}
  → courses: [{media_id, title, total, attempted, pct}]     # 前 10
  → recent:  [{sentence_text, created_at, accuracy}]        # 最近 6 条
```

实现要点：
- SQLite 按日聚合用 `func.date(Attempt.created_at)`；`created_at` 是服务器本地时间，聚合按本地日即可（个人站单机部署，无时区坑）
- 空数据（新用户）返回全零数组而非 404 —— 前端空态依赖这个
- 响应模型进 `app/schemas/stats.py`，路由挂现有 `stats.py`，不新开文件
- 契约测试：`contracts/` 补 `/api/stats/overview` 一条（49 → 50）

## 5. 统计页规格（page-6-stats.html）

### 5.1 信息架构（优先级从高到低）

| 区块 | 内容 | 数据 |
|---|---|---|
| KPI 四卡 | 今日听写 / 今日正确率 / 今日新学生词 / 连续天数 | §4.1，全部第一版可真值 |
| 每日听写量柱状图 | 14 根柱，0 值日空柱 | `daily.attempts` |
| 正确率趋势折线 | 14 点 + 80% 目标虚线 | `daily.accuracy` |
| 学习热力图 | 12 周 × 7 格，5 档明度 | `daily.attempts` 映射 |
| 生词构成环形图 | 已掌握 / 待复习 / 新词 | 第一版降级两态（见 §4.2） |
| 课程完成度 | 前 5 + 进度条 | `courses` |
| 最近听写 | 6 条 + 分数着色 | `recent` |

### 5.2 图表实现约定

- 全部内联 SVG / DOM 格子，**零图表库**；设计稿里已有可参考的 JS 生成逻辑（柱 22px 宽 rx6、折线 3px 圆头、格子 13px 圆角 3.5）
- 色板只用 token：柱 = `--lemon-400`、折线/正确 = `--leaf`、目标线 = `--peach` 虚线、热力 = lemon 100→500 明度阶梯、环形 = leaf/lemon-400/peach
- 数据系列 ≤3 色，坐标轴必须有单位与数值标签（柱顶数字、时间轴隔日标注）
- 折线 0 值日（没听写）贴底处理并在 tooltip 注明「休息日」，不画假数据
- 热力图移动端横向可滚，不缩格

### 5.3 响应式

- ≥1024：KPI 4 列；柱状+折线 1.6:1；热力+环形 1:1；课程+记录 1.5:1
- ≤767：全部单列；KPI 2 列；图表横向滚动容器包裹

### 5.4 空态（新用户）

`daily` 全零时：柱状图区域显示引导卡（「先去媒体库上传一段音频」+ 主按钮跳转），KPI 显示 0 而不是 NaN，热力图全灰。设计稿已含空态样式（复用 page-1 的 `.empty`）。

## 6. 分阶段执行计划

### Phase 0 · token 基建（半天）
- [ ] `frontend-vue/src/index.css`（或新建 `styles/tokens.css`）写入契约 `:root` 变量（色板/圆角/描边/字体栈），与 `design-contract.md` 逐字一致
- [ ] tailwind `theme.extend` 挂接关键变量（color: lemon-400 等），让现有 utility 可引用
- [ ] 通用类基座：`.btn`（四态）、`.card`、`.pill`、`.bar`、`.chip` —— 先加类不改页面
- **验收**：`npm run build` 通过；现有 7 个 verify 全绿（此阶段不动 DOM）

### Phase 1 · 逐页换皮（2–3 天，每页独立提交）
顺序（风险从低到高）：**登录页 → 统计页(新) → 媒体库 → 生词本 → 练习 → 学习页**
- [ ] 每页：按设计稿重排模板，**保留全部 `data-*` 与业务逻辑**，样式类换成 token 体系
- [ ] 每页完成后：`vite build` + 跑该页对应 verify（如学习页 `verify_mobile` + `verify_m4`）+ 截图比对设计稿
- [ ] 学习页最后做（DOM 最复杂、铁律最多）；播放器/AB 循环等交互逻辑零改动
- **验收**：7 个 verify 全绿 + 指纹不变 + 移动端 390 宽人工过一遍

### Phase 2 · 统计页前后端（1–1.5 天）
- [ ] 后端：`schemas/stats.py` 加 `OverviewOut`；`api/stats.py` 加 `/overview`（§4.3）；契约测试补 1 条
- [ ] 前端：新 `StatsPage.vue` + `api/stats.ts` 类型；路由与顶栏入口（顶栏「统计」从占位变实链）
- [ ] 图表：按 §5.2 用 SVG 自绘，封装 `components/charts/`（BarChart/LineChart/Heatmap/Donut 四个小组件）
- [ ] 本地全绿后部署云端实测（Python 3.12 差异点：无，纯 SQL 聚合；但仍走一遍云端冒烟）
- **验收**：真实库出图正确（和手工 SQL 对数）+ 新契约 50/50 + 指纹不变

### Phase 3 · 生词真值化（独立小立项，本期不做）
- [ ] `Vocab` 加 4 列 + `_ensure_columns`；练习提交落库端点；练习页提交时上报
- [ ] 生词本/练习页从两态升级为记忆曲线队列；统计页环形图启用三态
- **前置**：Phase 1、2 已合入；数据迁移前后跑指纹比对

## 7. 验收清单（每阶段收尾必跑）

```bash
# 1. 后端测试（基线 378 passed / 1 skipped，只增不减）
backend/.venv/Scripts/python.exe -m pytest backend/tests -q
# 2. 契约（Phase 2 后 50/50）
node scripts/verify_contract.mjs   # 或现有契约脚本
# 3. 前端 7 个 verify 全绿
node scripts/verify_mobile.mjs --url http://localhost:5174   # 等
# 4. 数据指纹
python scripts/fingerprint_data.py   # TOTAL 必须仍为 278bcd28… 基线
# 5. 构建
cd frontend-vue && npm run build
```

移动端人工检查项：390 宽无横向滚动、触摸目标 ≥44、`h-dvh` 无 `calc(100vh-…)`、底部导航不遮内容。

## 8. 风险与决策点

| # | 风险 | 对策 |
|---|---|---|
| 1 | **verify 选择器失效**（最大风险）：模板重排可能碰到脚本依赖的 class/结构 | 铁律只保 `data-*`；每页改完立即跑对应 verify，红了当场修；Phase 1 从登录页（无 verify 依赖）起步试探影响面 |
| 2 | 生词本「记忆曲线」是超前设计，落地时没数据 | 按本文档降级两态；Phase 3 再启用，不阻塞 |
| 3 | 连续天数是近似值（打开≠学习） | 文案标注「以听写记录计」；Phase 3 有 StudyEvent 后转真值 |
| 4 | 云端 3.12 与本地 3.13 | 新代码纯 SQL 聚合无版本敏感；仍按惯例云端冒烟 |
| 5 | 旧 React 回滚通道 | 不受影响（dist 备份与 tag 均未动） |

## 9. 待拍板

1. Phase 1 每页独立提交（推荐）还是整体一个大 PR？—— **推荐逐页**，回滚粒度细
2. 统计页顶栏入口：现在导航「统计」是占位，Phase 2 直接实链 —— 无异议即执行
3. Phase 3 的练习落库是否要做（涉及真实数据表变更）—— 单独评审

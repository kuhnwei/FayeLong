# P0 · token 基建 + verify 断言解耦 · 阶段记录

> 阶段：UI 落地 P0（T01 基线快照 / T02 token 基建 / T03 verify 断言解耦）
> 版本基线：v1.16.1 / `7e53f45`
> 依据：`docs/ARCH-UI-落地-v1.md` §2（token 设计）、§3（断言解耦）、§7.1（T01–T03 任务与验收判据）；
> 　　　`docs/PRD-UI-落地-v1.md` §4.1（P0-1…P0-6）、§4.5（DoD）；`design/design-contract.md`（token 契约）
> 记录人：寇豆码（工程师）· 2026-10-22

---

## 一、本阶段做了什么

| 任务 | 内容 | 产出 |
|---|---|---|
| **T01** | **先跑再动**：跑全部门禁记基线，重点核实 U1（footer 断言现状） | 本文件第二节 |
| **T02** | token 层 + tailwind 挂接 + 通用类基座 + 奶油画布底，**不动任何页面** | `src/styles/tokens.css`(新) / `src/index.css` / `tailwind.config.js` |
| **T03** | 把 verify 里「视觉类名 / 导航条数」耦合改为语义锚点（自带 className fallback），**页面源码零改动** | `scripts/verify_{m5,vue_skeleton,vocab_practice,vue_login,vue_roundB,v1_12,category}.mjs` |

---

## 二、T01 · 基线快照（实测，非引用）

### 2.1 五项门禁

| # | 项 | 命令 | 实测基线 |
|---|---|---|---|
| 1 | 后端单测 | `backend/.venv/Scripts/python.exe -m pytest backend/tests -q` | **377 passed, 1 skipped**（68.01s；skip 项为 `test_worker_recovery.py:431` Windows `terminate()` 无优雅退出） |
| 2 | 契约门禁 | `node scripts/check-contract.mjs` | **退出码 0**（`paths = 41, operations = 49`） |
| 3 | 7 个 verify | 见 2.2 | 见 2.2 |
| 4 | 数据指纹 | `backend/.venv/Scripts/python.exe scripts/fingerprint_data.py` | **TOTAL `278bcd28b2c37a98ffb123004b2d38823d5676b13104c90ff4d32dad697f3b4f`**（与基线一致） |
| 5 | 前端构建 | `cd frontend-vue && npm run build` | **通过**（含 `vue-tsc --noEmit`；226 modules；css 29.14 kB / js 308.71 kB） |

### 2.2 七个 verify 各自通过项（隔离环境实测）

跑法（**全部跑在隔离副本上，真实 `data/app.db` 零写入**）：

```bash
# 后端型脚本（脚本内 BASE 同时供 API 与静态 dist）
backend/.venv/Scripts/python.exe scripts/run_isolated_backend.py --port 8010 --root /tmp/fayelong-iso-p0
node scripts/verify_m5.mjs --url http://127.0.0.1:8010
# dev 型脚本
cd frontend-vue && FAYELONG_API_TARGET=http://127.0.0.1:8010 npm run dev   # 5174
node scripts/verify_vue_skeleton.mjs --url http://localhost:5174    # 必须用 localhost，127.0.0.1 会 502
node scripts/verify_vue_login.mjs                                   # 自启隔离后端(8010) + dev(5174)
```

| 脚本 | 基线通过项 | 备注 |
|---|---|---|
| `verify_m5` | **19 / 19** | 全绿 |
| `verify_vue_skeleton` | **8 / 20**（原样）→ **18 / 20**（补登录会话后） | 见 2.3「U1 与脚本缺口」 |
| `verify_vocab_practice` | **29 / 29** | 全绿 |
| `verify_vue_login` | **19 / 19** | copy + fresh 双形态全绿 |
| `verify_m4` | **12 / 12** | 全绿 |
| `verify_marks` | **19 / 19** | 全绿 |
| `verify_attempt_history` | **19 / 19** | 全绿 |

### 2.3 U1 结论（架构 §5.8 待核项）——**footer 断言当前是红的**

**结论：红。** 三段式断言的四项里，header/main 四项全绿，只有 footer 一项红：

```
FAIL  三段式：header shrink-0 / main flex-1 min-h-0 overflow-y-auto / footer shrink-0
      header.flexShrink=0  main.flexGrow=1  main.minHeight=0px  main.overflowY=auto  footer.flexShrink=null
```

原因与架构预判一致：`.h-dvh` 的直接子元素只有 `<header>` 与 `<main>`，`PlayerBar` 根节点是 `<div>`
（不是 `<footer>`），因此 `el.querySelector(':scope > footer')` 取不到元素 → `flexShrink=null`。
**P1-2 引入真实 `<footer>`（Tab Bar）后该项转绿，属「改善」而非回退**，不计入本阶段回退。

**同一脚本还有第二项基线红（新发现，架构未预判）**：

```
FAIL  路由 /study/1 可渲染「学习页」且无脚本错误  —— h2="_示例-英文听力-11秒" path=/study/1
```

`StudyPage` 的 `main h2` 是**媒体标题**，不含「学习页」。这条属「不可动的业务断言」，
本阶段**未改、也不允许改**；P1-7 换皮时须保证 `main h2` 含「学习页」（可保留媒体标题做副标题）。
两个红项都不是本阶段造成的，属既有缺口。

### 2.4 附带发现：`verify_vue_skeleton` 缺登录会话注入（脚本缺口，非业务缺陷）

`v1.12` 起站点有登录门禁（`App.vue` 未登录整屏渲染 `<LoginPage/>`，不经过 Router）。
`verify_mobile` / `verify_m4` / `verify_m5` / `verify_marks` / `verify_attempt_history` /
`verify_vocab_practice` 都调用了 `installSessionInBrowser(cdp, BASE)`，**只有 `verify_vue_skeleton`
没有**（它停在登录页 → `.h-dvh`/`main h2`/导航全部取不到 → 12 项红）。

实测两档基线：

| 形态 | 通过项 | 红项 |
|---|---|---|
| 原样（无会话） | 8 / 20 | 12 项全部因「停在登录页」 |
| 补会话注入后（临时探针实测，未改脚本） | **18 / 20** | 仅 2.3 的两项页面级缺口 |

→ 该脚本此前**不可能作为 P1-2/P1-3 的验收门禁**。T03 已补上这 2 行（与其余脚本同款），
详见第四节「与架构方案的偏差 D1」。

---

## 三、T02 · token 基建

### 3.1 改动文件清单

| 文件 | 状态 | 内容 |
|---|---|---|
| `frontend-vue/src/styles/tokens.css` | **新增** | `:root` 15 个色板变量（契约原名，逐字一致）+ 描边/圆角/硬阴影/焦点光环/字体栈/间距基数/点阵纹理 |
| `frontend-vue/src/index.css` | 重写 | `@import` token（在 `@tailwind` 之前）→ `@layer base` 画布（cream 底 + 18px 点阵 + ink 文字 + 系统字体）→ `@layer components` 通用类基座 |
| `frontend-vue/tailwind.config.js` | 修改 | `theme.extend`：`colors{lemon,ink,leaf,peach,cream,card}` / `borderRadius{card,control,pill}` / `boxShadow{sticker,sticker-lift,ring}` / `fontFamily.sans` / `borderWidth.stroke` |

> **刻意不挂 `spacing`**：契约 §3 的 7 档间距（8/12/14/18/22/26/34）已在 `tokens.css` 以
> `--fl-space-*` 提供。若挂进 `spacing`，`14` 会覆盖 tailwind 默认的 `p-14 = 3.5rem`（56px），
> 存量页面可能被静默改距 —— 与本阶段「不动任何页面」冲突。已实测存量 `.vue` 里
> `(p|px|py|gap|m|w|h)-(14|18|22|26|34)` **零命中**，且挂/不挂两次构建产物完全同体积（31.13 kB），
> 故确认无视觉影响后移除该键。ARCH §2.2 的挂接清单本身也不含 spacing。

**通用类基座（P0-3，只加类不改页面）**：`.btn` `.btn-primary` `.btn-secondary` `.btn[disabled]`、
`.card` `.card-interactive`、`.pill` `.pill-easy/.pill-mid/.pill-hard`、`.bar` `.bar-lg` `.bar-fill`、
`.chip`（含 `[data-selected="true"]` 选中态）、`.input` `.input-area`（含 focus 黄光环）、
`.nav-pill`（含 `[data-active="true"]` 选中态）。移动端（≤767px）`.btn` 抬到 48px。
选择器里预留的 `[data-selected]` / `[data-active]` 与 ARCH §3.2 的属性名一致，
P1 换皮补上属性即自动生效，不需要再改 CSS。

### 3.2 验收证据

**① 构建通过（含 `vue-tsc --noEmit` 类型检查）**

```
> vue-tsc --noEmit && vite build
✓ 226 modules transformed.
dist/assets/index-Cf805y4H.css   31.13 kB │ gzip: 6.55 kB
dist/assets/index-DiZICUnd.js   308.71 kB │ gzip: 99.81 kB
✓ built in 7.60s
```

**② token 变量 grep 命中且与契约逐字一致**

```
$ grep -r -- '--lemon-400' frontend-vue/src/styles/tokens.css
  --lemon-400: #FFD93B; /* 主色：主按钮底、选中 chip、品牌重点 */
```

15 个色板变量逐个与契约 §1 比对：**15/15 全等，0 处不一致**
（`#FFD93B` `#FFE566` `#EFC01A` `#FFEFB4` `#FFF8DE` / `#4A2B14` `#6E4E35` `#8A6A50` /
`#9FBE33` `#E2EDB4` / `#F79E93` `#FFE0DA` / `#FFFBF0` `#FFF4DC` `#FFFFFF`）。

**③ 临时探针验证 token 工具类能编出对应声明（验证后已删除，未进任何提交）**

临时新建 `src/components/__token_probe.vue` 写入
`class="bg-lemon-400 text-ink rounded-card shadow-sticker border-stroke"` → 构建 → 产物 CSS 查到：

```css
.bg-lemon-400{background-color:var(--lemon-400)}
.text-ink{color:var(--ink)}
.rounded-card{border-radius:var(--radius-card)}
.shadow-sticker{--tw-shadow: var(--shadow-sticker);…;box-shadow:…}
.border-stroke{border-width:var(--fl-stroke)}
```

删除探针后重新构建（css 31.49 → 31.13 kB，回到无探针体积），`git status` 无残留。

**④ 本任务不动任何页面视觉**

```
$ git diff --stat frontend-vue/src/pages frontend-vue/src/components
(空)
```

---

## 四、T03 · verify 断言解耦（只改脚本，页面源码零改动）

### 4.1 逐条对照（ARCH §3.1 的 17 条）

| # | 文件 | 原断言 | 改后断言（语义锚点 + fallback） | 状态 |
|---|---|---|---|---|
| 1–4 | `verify_m5.mjs`（宫格着色） | `className.includes('bg-slate-900'/'bg-emerald-100'/'bg-amber-100'/'bg-slate-100')` | 局部 `stateOf(b)`：优先 `b.dataset.state`，缺失回落原 4 个类名 | ✅ |
| 5 | `verify_m5.mjs`（舞台高亮） | `card.className.includes('ring-2')` | `card.dataset.highlight === 'true'` 兜底 `ring-2` | ✅ |
| 6 | `verify_m5.mjs`（A-B 激活） | `/sky/.test(b2.className)` | `b2.dataset.state === 'ab-active'` 兜底 `sky` | ✅ |
| 7 | `verify_vue_skeleton.mjs`（导航高亮） | `a.classList.contains('bg-slate-900')` | `a.dataset.active === 'true'` 兜底原类名 | ✅ |
| 8 | `verify_vue_skeleton.mjs`（`/` 高亮） | `navHome.length === 2 && [0]=媒体库 && [1] 非 active` | **按文本定位**：存在含「媒体库」且 active 的链接，其余链接非 active；**去条数硬校验** | ✅ |
| 9 | `verify_vue_skeleton.mjs`（`/vocab` 高亮） | `navVocab[1].active && !navVocab[0].active`（下标定位） | 按文本「生词本」定位 + `data-active` 兜底类名 | ✅ |
| 10–11 | `verify_vocab_practice.mjs`（模式按钮 ×2） | `modeBtn.className.includes('bg-slate-900')` | `modeBtn.dataset.selected === 'true'` 兜底原类名 | ✅ |
| 12 | `verify_vocab_practice.mjs`（选项正确态） | `/emerald/.test(marked.className)` | `marked.dataset.tone === 'correct'` 兜底 `emerald` | ✅ |
| 13–14 | `verify_vue_login.mjs`（copy / fresh 两处） | `navLinks.length === 2` | `navLinks.length >= 2` | ✅ |
| 15 | `verify_vue_roundB.mjs` | `navLinks.length === 2` | `>= 2` | ✅ |
| 16 | `verify_v1_12.mjs`（宫格按钮） | `b.className.includes('rounded-md')` | `b.hasAttribute('data-grid-cell')` 兜底 `rounded-md` | ✅ |
| 17 | `verify_category.mjs`（按标题找行） | `(s.className \|\| '').includes('font-medium')` | `s.hasAttribute('data-media-title')` 兜底 `font-medium` | ✅ |

**「不可动的业务断言」逐条保留、零弱化**：A-B 三段 `title` 文本、笔记面板 5 项、听写历史趋势条、
`h-dvh` 高度、四路由 `main h2` 文案、375px 无横向滚动、15 个 `data-practice-*`、`[data-vocab-row]`、
`data-testid` 全家桶 —— 全部原样未动（复跑结果见 4.3，相关项仍全绿）。

### 4.2 复跑结果（页面源码零改动，`git diff --stat src/pages src/components` 为空）

| 脚本 | T01 基线 | T03 改后 | 对比 |
|---|---|---|---|
| `verify_m5` | 19 / 19 | **19 / 19** | 持平（fallback 生效，未引入回归） |
| `verify_vocab_practice` | 29 / 29 | **29 / 29** | 持平 |
| `verify_vue_skeleton` | 8 / 20（原样）／18 / 20（补会话后） | **18 / 20** | ≥ 基线；红的仍是 2.3 的两项页面级缺口 |
| `verify_vue_login` | 19 / 19 | **19 / 19** | 持平 |
| `verify_v1_12`（建议同批） | 未纳入 7 项门禁 | **22 / 22** | 全绿 |
| `verify_category`（建议同批） | 未纳入 7 项门禁 | **59 / 59** | 全绿 |
| `verify_vue_roundB`（建议同批） | 未纳入 7 项门禁 | **6 / 7** | 唯一红项是 4.4 的既有缺口，与本次改动无关 |

### 4.3 与架构方案的偏差（3 处，均已在下方说明理由）

**D1（重要）·`verify_vue_skeleton` 补登录取会话注入（2 行）**
架构 §3.1 只列了它的 2 条导航断言，但该脚本**完全没注入登录会话**，实测全程停在登录页、
20 项里 12 项红（详见 2.4）。不补这 2 行，它无法充当 P1-2/P1-3 的门禁。
改动与 `verify_mobile` / `verify_m4` 等 6 个脚本完全同款：

```js
import { installSessionInBrowser } from './lib/session.mjs'
…
await installSessionInBrowser(cdp, BASE)
```

**不加断言、不删断言、不改业务语义**，纯粹把「环境缺口」补上（8/20 → 18/20）。

**D2 ·第 17 条的实际语义与架构描述不符**
架构写「`verify_category.mjs:221` … 找**选中分类**」，实际该行在 `findRowByTitle()` 里，
用 `font-medium` 找**媒体行的标题 span**（不是分类项）。已按真实语义解耦为
`data-media-title` 优先 + `font-medium` 兜底；分类项的选中态另有断言，本次未动（它不看类名）。

**D3 ·第 16/17 条属「半径 / 字重」类名，严格说不在「颜色类名 + 导航条数」两类之内**
按架构「建议同批修（避免遗留红）」执行，且实现方式是**纯增量 fallback**
（有 `data-*` 才走新分支，没有则完全等价于原判断），因此不可能把绿变红；
实测 `verify_v1_12` 22/22、`verify_category` 59/59 全绿可作证。
若团队认为越界，可单独 `git revert` 这两个文件的两行改动，不影响其余 15 条。

### 4.4 遗留的既有缺口（非本阶段引入，需 P1 收口）

| # | 缺口 | 证据 | 收口任务 |
|---|---|---|---|
| 1 | 外壳无真实 `<footer>` | `footer.flexShrink=null` | P1-2（Tab Bar 落成 `<footer>`） |
| 2 | `/study/1` 的 `main h2` 是媒体标题，不含「学习页」 | `h2="_示例-英文听力-11秒"` | P1-7 |
| 3 | `verify_vue_roundB` 的「未登录 → 渲染登录门禁占位」红 | `h2=""`（登录页无 `h2`），断言要求 `h2` 含「登录」 | 该脚本自身断言与登录页结构不符，建议随 P1-1（登录页换皮）一并校正；本次未动（不属授权改动范围） |

---

## 五、门禁复跑（提交前）

| 项 | 结果 |
|---|---|
| `pytest backend/tests -q` | 377 passed / 1 skipped（本阶段无后端改动，未重跑变化） |
| `node scripts/check-contract.mjs` | 退出码 **0**（paths = 41 / operations = 49，与基线一致） |
| `python scripts/fingerprint_data.py` | **TOTAL `278bcd28…`** 未变（verify 全跑隔离副本，真实库零写入） |
| `cd frontend-vue && npm run build` | 通过 |
| `git diff --stat frontend-vue/src/pages frontend-vue/src/components` | 空 |

---

## 六、提交记录

| # | 提交信息 | 内容 | hash |
|---|---|---|---|
| ① | `feat(ui-p0): token 基建 + 基线快照` | `src/styles/tokens.css`(新) / `src/index.css` / `tailwind.config.js` / 本文件 | **`704c7a2`** |
| ② | `test(ui-p0): verify 断言与视觉类名解耦` | 7 个 `scripts/verify_*.mjs` + 本文件的两处回填（提交 hash 与 D 系列偏差） | 本记录所在提交（即 `git log --oneline -1` 的首条） |

> **为什么 ② 的 hash 不写成字面值**：git 的 hash 由提交内容算出，本文件本身在 ② 里被修改，
> 因此「把 ② 的 hash 写进 ② 自身」在数学上不可能（写完 hash 就变了）。
> 硬约束是「严格 2 次提交」，所以选择：① 的 hash 字面写入、② 用 `git log --oneline -1` 指代。
> 两枚 hash 的最终值以 `git log --oneline -3` 为准，并已在交付报告里给出。
>
> 说明：`frontend-vue/dist/` 是 `.gitignore` 里的构建产物（`dist/` 全局忽略，仓库内 0 个被跟踪文件），
> 本阶段构建产物**未提交**。

---

## 七、偏差与遗留问题汇总（交主理人决策）

1. **D1** `verify_vue_skeleton` 补了登录会话注入（超出「只改颜色类名 + 导航条数」的字面范围，但不加它该脚本 12/20 恒红、无法当门禁）。建议接受。
2. **D3** 第 16/17 条（`rounded-md` / `font-medium`）不属「颜色类名」，按架构「建议同批」执行，纯增量 fallback、零风险；如需严格守边界可单独回滚这两处。
3. **基线已红 2 项**（footer 三段式、`/study/1` h2），需 P1-2 / P1-7 收口；`verify_vue_roundB` 的登录门禁断言建议随 P1-1 校正。
4. 真实库里 `vocab` 有 12 条、其中 9 条是 verify 造出来的测试生词（`verify_vocab_practice` 日志提示「已保留，可用 `--wipe-test-words` 删除」）。指纹未变，故未清理；如需清理请单独确认（会改指纹）。

# QA 最终独立全量验收报告 · FayeLong UI 落地改造

> 验收人：严过关（QA 工程师）· 2026-10-22 · 独立实跑，不采信任何既有报告
> 基线版本：`7e53f45` → 现 HEAD `bbbfd1c`（P0 两提交 + P1 七提交 + P2 三提交）
> 环境：Node v22.22.2 / Python 3.13.14 / 本机 Chrome

---

## 一、最终判定

## ✅ **通过（NoOne）—— 零回退，全部硬门禁 ≥ 基线**

| 维度 | 结论 |
|---|---|
| 后端测试 | 385 passed / 1 skipped（+8，只增不减）✅ |
| 契约门禁 | 退出码 0，paths=42 / operations=50 ✅ |
| 前端构建 | vue-tsc + vite build 通过 ✅ |
| 11 个 verify 脚本 | 全部达标，两项历史红转绿（skeleton 20/20、roundB 7/7）✅ |
| 数据指纹 | `TOTAL` 逐字节等于基线 `278bcd28…` ✅ |
| 静态铁律 | 3 项 grep 全部零命中 ✅ |

**回退项数量：0。**

---

## 二、逐门禁实测表

### 2.1 后端测试

```text
backend/.venv/Scripts/python.exe -m pytest backend/tests -q
→ 385 passed, 1 skipped in 73.50s
  SKIPPED [1] backend\tests\test_worker_recovery.py:431:
             Windows 上 terminate() 是 TerminateProcess，没有优雅退出的机会
```

| 基线 | 预期 | 实测 | 通过 |
|---|---|---|---|
| 377 passed / 1 skipped | 385 passed / 1 skipped | **385 passed / 1 skipped** | ✅ |

- `+8` 来自新增 `backend/tests/test_stats_overview.py`（8585 字节，已确认存在）。
- 唯一 skip 是既有 Windows 平台限制，与本次改造无关。

### 2.2 契约门禁

```text
node scripts/check-contract.mjs
→ [check-contract] ✅ 契约与基线一致（paths = 42, operations = 50）。
→ 退出码 0
```

| 基线 | 预期 | 实测 | 通过 |
|---|---|---|---|
| 退出码 0（paths=42/operations=50） | 退出码 0 | **退出码 0，paths=42 / operations=50** | ✅ |

### 2.3 前端构建

```text
cd frontend-vue && npm run build
→ vue-tsc --noEmit && vite build
→ ✓ 238 modules transformed / built in 7.73s
→ 退出码 0
```

| 预期 | 实测 | 通过 |
|---|---|---|
| vue-tsc 类型检查 + vite build 通过 | **通过（退出码 0）** | ✅ |

### 2.4 verify 脚本（隔离副本：隔离后端 8010 + dev 5174 代理到 8010）

**运行方式**：
- 隔离后端：`backend/.venv/Scripts/python.exe scripts/run_isolated_backend.py --port 8010`（临时根 + `data/app.db` 副本）
- dev：`cd frontend-vue && FAYELONG_API_TARGET=http://127.0.0.1:8010 npm run dev`（5174）
- dev 型脚本 `--url http://localhost:5174`（本机 Vite 只绑 IPv6 `[::1]`，用 127.0.0.1 会 502）；其余 `--url http://127.0.0.1:8010`（隔离后端托管已构建 SPA）

| 脚本 | 基线 | 预期 | 实测 | 通过 |
|---|---|---|---|---|
| `verify_vue_skeleton` | 8/20 | 20/20 | **20/20** | ✅ |
| `verify_vue_login` | 19/19 | 19/19 | **19/19**（copy+fresh 双形态） | ✅ |
| `verify_mobile` | 36/36 | 36/36 | **36/36** | ✅ |
| `verify_m5` | 19/19 | 19/19 | **19/19** | ✅ |
| `verify_m4` | 12/12 | 12/12 | **12/12** | ✅ |
| `verify_category` | 59/59 | 59/59 | **59/59** | ✅ |
| `verify_vocab_practice` | 29/29 | 29/29 | **29/29** | ✅ |
| `verify_marks` | 19/19 | 19/19 | **19/19** | ✅ |
| `verify_attempt_history` | 19/19 | 19/19 | **19/19** | ✅ |
| `verify_vue_roundB` | 6/7 | 7/7 | **7/7** | ✅ |
| `verify_v1_12`（附跑） | 22/22 | 22/22 | **22/22** | ✅ |

合计 **261 项断言，261 项通过，0 项失败**。

---

## 三、数据指纹比对结果（真实库，未碰副本）

```text
python scripts/fingerprint_data.py
→ TOTAL  278bcd28b2c37a98ffb123004b2d38823d5676b13104c90ff4d32dad697f3b4f
```

| 项 | 基线 | 实测 | 结论 |
|---|---|---|---|
| `TOTAL` | `278bcd28b2c37a98ffb123004b2d38823d5676b13104c90ff4d32dad697f3b4f` | `278bcd28b2c37a98ffb123004b2d38823d5676b13104c90ff4d32dad697f3b4f` | **逐字节一致 ✅** |

**顺序铁律遵守**：verify 全程跑隔离副本（`run_isolated_backend.py` 临时根；`verify_vue_login` 自启 copy/fresh 隔离后端），指纹只对真实 `data/app.db` 跑。真实库各表行数（media=4 / sentences=114 / vocab=12 / attempts=9 / notes=2 / categories=0）在验收前后完全未变。

---

## 四、静态铁律抽查

| 检查 | 命令 | 实测 | 通过 |
|---|---|---|---|
| `calc(100vh` 全站零命中 | `grep -rn "calc(100vh" frontend-vue/src` | **0 命中** | ✅ |
| 图表零第三方库 | `grep -rE "echarts\|chart\.js\|d3\|recharts" frontend-vue/src/components/charts` | **0 命中** | ✅ |
| 换皮页面零硬编码色值 | `grep -rnE "#[0-9A-Fa-f]{3,8}" frontend-vue/src/pages frontend-vue/src/components` | **0 命中** | ✅ |

补充核验：`frontend-vue/src/components/charts/` 含 `BarChart / Donut / Heatmap / LineChart / theme.ts` 五个文件，`import` 仅有 `vue` 与 `./theme`（相对路径），确认为纯 SVG/DOM 自绘、零第三方依赖。

---

## 五、发现的问题

**无。** 全部硬门禁达标，未发现任何源码回退、测试环境异常或数据污染。

---

## 六、验收范围与边界说明

- 本轮验收范围 = 任务派单指定的 **6 类硬门禁**（后端测试 / 契约 / 构建 / verify / 指纹 / 静态铁律），全部独立实跑复核。
- 未覆盖（不在派单范围）：P1 收口记录 §「范围边界」声明的 **DOM 结构级设计稿重排**（Hero 大图、数据条三卡横排、卡片 hover 上浮、diff 卡粉删除线等）—— 这是已记录的「待用户决策」项，非本次回退。
- 数据指纹为内容级指纹（`fingerprint_data.py` 只读，排除易变字段 `users.last_login_at`），已显式打印排除清单，非静默。

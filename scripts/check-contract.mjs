#!/usr/bin/env node
/**
 * 契约 diff 门禁：把「当前代码实际产出的 OpenAPI」与冻结基线做结构化比对，
 * 有任何非容忍差异即**非零退出**，并打印到具体 path / operation / 字段。
 *
 * 流程
 * ----
 *   1. 调 scripts/export_openapi.py 把当前 `app.openapi()` 导出到临时文件；
 *   2. 与 contracts/openapi-v1.json 做递归结构化 diff；
 *   3. 打印差异点并设置退出码。
 *
 * 环境相关差异的显式容忍（不静默吞掉）
 * ----------------------------------
 * `app/main.py` 里的 SPA 回退路由 `"/"` 只在 `frontend-vue/dist/index.html`
 * **不存在**时才注册，且未加 `include_in_schema=False`。因此当 dist 被删时，
 * `openapi()` 会凭空多出一个 `"/"` 的 GET operation。这不是契约变更，
 * 故本脚本对 `"/"` 路径的「存在与否」差异做**显式**容忍，并打印一条
 * 「已忽略」通知（含原因），绝不静默。
 *
 * 用法
 * ----
 *     cd <repo>
 *     node scripts/check-contract.mjs
 *
 * 退出码：0 = 契约一致；1 = 检测到差异；2 = 环境错误（基线缺失 / 导出失败）。
 */

import { spawnSync } from "node:child_process";
import { existsSync, readFileSync, unlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(__dirname, "..");

const BASELINE_PATH = join(REPO_ROOT, "contracts", "openapi-v1.json");
const EXPORT_SCRIPT = join(REPO_ROOT, "scripts", "export_openapi.py");
const PYTHON =
  process.env.FAYELONG_PYTHON ||
  join(REPO_ROOT, "backend", ".venv", "Scripts", "python.exe");

const HTTP_METHODS = new Set([
  "get",
  "post",
  "put",
  "delete",
  "patch",
  "options",
  "head",
  "trace",
]);

/** 被显式容忍的环境相关路径（SPA 回退路由）。 */
const TOLERATED_PATHS = new Set(["/"]);

/**
 * 把值转成单行、限长的可读片段。
 * @param {unknown} value
 * @returns {string}
 */
function short(value) {
  let text;
  try {
    text = JSON.stringify(value);
  } catch {
    text = String(value);
  }
  if (text === undefined) text = String(value);
  return text.length > 160 ? `${text.slice(0, 157)}...` : text;
}

/**
 * 递归比较两个值，把差异写入 out（JSON 指针风格路径）。
 * @param {unknown} base 基线侧值
 * @param {unknown} now 当前侧值
 * @param {string} ptr 路径前缀
 * @param {string[]} out 差异收集器
 */
function diffValues(base, now, ptr, out) {
  if (base === now) return;

  const baseIsArr = Array.isArray(base);
  const nowIsArr = Array.isArray(now);
  if (baseIsArr || nowIsArr) {
    if (!baseIsArr || !nowIsArr || base.length !== now.length) {
      out.push(
        `${ptr}: 数组长度/类型不同\n    基线: ${short(base)}\n    实际: ${short(now)}`,
      );
      return;
    }
    for (let i = 0; i < base.length; i += 1) {
      diffValues(base[i], now[i], `${ptr}[${i}]`, out);
    }
    return;
  }

  const bothObjects =
    base && now && typeof base === "object" && typeof now === "object";
  if (bothObjects) {
    const keys = new Set([...Object.keys(base), ...Object.keys(now)]);
    for (const key of [...keys].sort()) {
      const inBase = Object.prototype.hasOwnProperty.call(base, key);
      const inNow = Object.prototype.hasOwnProperty.call(now, key);
      if (!inBase) {
        out.push(`${ptr}.${key}: 新增字段 (${short(now[key])})`);
        continue;
      }
      if (!inNow) {
        out.push(`${ptr}.${key}: 缺失字段 (基线为 ${short(base[key])})`);
        continue;
      }
      diffValues(base[key], now[key], `${ptr}.${key}`, out);
    }
    return;
  }

  out.push(
    `${ptr}: 值不同\n    基线: ${short(base)}\n    实际: ${short(now)}`,
  );
}

/**
 * 比较 paths 段。
 * @param {Record<string, any>} basePaths
 * @param {Record<string, any>} nowPaths
 * @param {string[]} out
 */
function diffPaths(basePaths, nowPaths, out) {
  const allPaths = new Set([...Object.keys(basePaths), ...Object.keys(nowPaths)]);
  for (const p of [...allPaths].sort()) {
    const inBase = Object.prototype.hasOwnProperty.call(basePaths, p);
    const inNow = Object.prototype.hasOwnProperty.call(nowPaths, p);
    if (!inBase) {
      out.push(`path 新增: ${p}`);
      continue;
    }
    if (!inNow) {
      out.push(`path 缺失: ${p}`);
      continue;
    }
    const baseOps = basePaths[p] || {};
    const nowOps = nowPaths[p] || {};
    const methods = new Set([...Object.keys(baseOps), ...Object.keys(nowOps)]);
    for (const m of [...methods].sort()) {
      if (!HTTP_METHODS.has(m.toLowerCase())) continue;
      const inBaseOp = Object.prototype.hasOwnProperty.call(baseOps, m);
      const inNowOp = Object.prototype.hasOwnProperty.call(nowOps, m);
      if (!inBaseOp) {
        out.push(`operation 新增: ${m.toUpperCase()} ${p}`);
        continue;
      }
      if (!inNowOp) {
        out.push(`operation 缺失: ${m.toUpperCase()} ${p}`);
        continue;
      }
      diffValues(baseOps[m], nowOps[m], `${m.toUpperCase()} ${p}`, out);
    }
  }
}

/**
 * 完整规范 diff（paths 之外还有 components / info 等根级字段）。
 * @param {Record<string, any>} base
 * @param {Record<string, any>} now
 * @returns {string[]}
 */
function diffSpec(base, now) {
  const out = [];

  const basePaths = { ...(base.paths || {}) };
  const nowPaths = { ...(now.paths || {}) };

  // —— 显式容忍 SPA 回退路由 "/"：仅对「存在与否」差异容忍，且必须打印通知 ——
  const toleratedNotes = [];
  for (const p of TOLERATED_PATHS) {
    const inBase = Object.prototype.hasOwnProperty.call(basePaths, p);
    const inNow = Object.prototype.hasOwnProperty.call(nowPaths, p);
    if (inBase !== inNow) {
      const present = inBase ? basePaths[p] : nowPaths[p];
      const methods = Object.keys(present || {}).filter((m) =>
        HTTP_METHODS.has(m.toLowerCase()),
      );
      const onlyGet = methods.length === 1 && methods[0].toLowerCase() === "get";
      if (onlyGet) {
        toleratedNotes.push(
          `[已忽略] 路径 "${p}" 的差异：环境相关（frontend-vue/dist 存在与否决定 ` +
            `SPA 回退路由是否注册，见 app/main.py 末尾），仅多余一个 GET，非契约变更。`,
        );
        delete basePaths[p];
        delete nowPaths[p];
      }
      // 若 "/" 含非 GET 方法，则不作容忍，正常进入 diff 报告。
    }
  }

  diffPaths(basePaths, nowPaths, out);

  // 根级其余字段（info / components / servers ...）
  const baseRest = { ...base };
  const nowRest = { ...now };
  delete baseRest.paths;
  delete nowRest.paths;
  diffValues(baseRest, nowRest, "$(root)", out);

  return { diffs: out, toleratedNotes };
}

/**
 * 调用导出脚本，把当前 OpenAPI 写到指定临时文件。
 * @param {string} outFile
 */
function runExport(outFile) {
  const result = spawnSync(PYTHON, [EXPORT_SCRIPT, outFile], {
    cwd: REPO_ROOT,
    encoding: "utf8",
  });
  if (result.error) {
    throw new Error(`无法启动导出脚本：${result.error.message}\n解释器：${PYTHON}`);
  }
  if (result.status !== 0) {
    throw new Error(
      `导出脚本非零退出（code=${result.status}）。\n` +
        `解释器：${PYTHON}\n` +
        `stdout:\n${result.stdout || ""}\nstderr:\n${result.stderr || ""}`,
    );
  }
}

function main() {
  if (!existsSync(BASELINE_PATH)) {
    console.error(
      `[check-contract] 基线缺失：${BASELINE_PATH}\n` +
        `请先运行：python scripts/export_openapi.py 生成基线。`,
    );
    process.exit(2);
  }

  const tmpOut = join(
    tmpdir(),
    `fayelong-openapi-now-${process.pid}-${Date.now()}.json`,
  );

  try {
    runExport(tmpOut);
    const base = JSON.parse(readFileSync(BASELINE_PATH, "utf8"));
    const now = JSON.parse(readFileSync(tmpOut, "utf8"));

    const { diffs, toleratedNotes } = diffSpec(base, now);

    for (const note of toleratedNotes) {
      console.log(`[check-contract] ${note}`);
    }

    if (diffs.length === 0) {
      const pathCount = Object.keys(base.paths || {}).length;
      const opCount = Object.values(base.paths || {}).reduce(
        (n, item) =>
          n +
          Object.keys(item).filter((m) => HTTP_METHODS.has(m.toLowerCase()))
            .length,
        0,
      );
      console.log(
        `[check-contract] ✅ 契约与基线一致（paths = ${pathCount}, operations = ${opCount}）。`,
      );
      return 0;
    }

    console.error(
      `[check-contract] ❌ 检测到 ${diffs.length} 处契约差异（相对 contracts/openapi-v1.json）：`,
    );
    for (const d of diffs) {
      console.error(`  - ${d}`);
    }
    console.error(
      `[check-contract] 若为有意变更，请复核后重新生成基线：` +
        `python scripts/export_openapi.py`,
    );
    return 1;
  } finally {
    if (existsSync(tmpOut)) {
      try {
        unlinkSync(tmpOut);
      } catch {
        /* 临时文件清理失败不影响结论 */
      }
    }
  }
}

process.exit(main());

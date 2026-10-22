#!/usr/bin/env node
/**
 * 从 `contracts/openapi-v1.json` 生成 TypeScript 类型 → `contracts/api-types.d.ts`。
 *
 * 为什么放在仓库根目录跑
 * --------------------
 * 使用仓库根的 `package.json`（`openapi-typescript` 装在根 `node_modules`），
 * 与 `frontend/` 完全隔离 —— 不改动旧 React 前端的依赖、不影响其 `npm run build`。
 * 本脚本用 `.mjs` 扩展名，显式以 ESM 运行，无需依赖根 `package.json` 的 `type` 字段。
 *
 * 用法
 * ----
 *     cd <repo>            # 仓库根目录
 *     npm install --ignore-scripts
 *     node scripts/gen-api-types.mjs
 *
 * ⚠️ `npm install` 必须加 `--ignore-scripts`：本机托管 node.exe 上
 *    esbuild 的 postinstall 会报 EBUSY。
 */

import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import openapiTS, { astToString } from "openapi-typescript";

const __dirname = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(__dirname, "..");

const SPEC_PATH = join(REPO_ROOT, "contracts", "openapi-v1.json");
const OUT_PATH = join(REPO_ROOT, "contracts", "api-types.d.ts");

/**
 * 读取并解析 OpenAPI 基线。
 * @returns {Record<string, unknown>} 解析后的 OpenAPI 规范对象。
 */
function loadSpec() {
  let raw;
  try {
    raw = readFileSync(SPEC_PATH, "utf8");
  } catch (err) {
    throw new Error(
      `无法读取基线文件：${SPEC_PATH}\n` +
        `请先运行：python scripts/export_openapi.py（使用 backend/.venv 解释器）\n` +
        `原始错误：${err.message}`,
    );
  }
  return JSON.parse(raw);
}

async function main() {
  const spec = loadSpec();

  // openapi-typescript v7 编程式 API：传入规范对象 → AST → 字符串。
  const ast = await openapiTS(spec);
  const contents = astToString(ast);

  // 生成物带一条「自动生成，勿手改」的醒目提示。
  const header =
    "// 本文件由 scripts/gen-api-types.mjs 自动生成，请勿手改。\n" +
    "// 数据来源：contracts/openapi-v1.json（后端 app.openapi() 的冻结基线）。\n" +
    "// 重新生成：node scripts/gen-api-types.mjs\n\n";

  mkdirSync(dirname(OUT_PATH), { recursive: true });
  writeFileSync(OUT_PATH, header + contents, "utf8");

  const schemaCount = Object.keys(spec.components?.schemas ?? {}).length;
  const pathCount = Object.keys(spec.paths ?? {}).length;
  console.log(`[gen-api-types] 已写入：${OUT_PATH}`);
  console.log(
    `[gen-api-types] 来源基线：paths = ${pathCount}, components.schemas = ${schemaCount}`,
  );
}

main().catch((err) => {
  console.error("[gen-api-types] 生成失败：", err.message);
  process.exit(1);
});

/** 「媒体库分类机制」端到端验证（Node 接口层 + CDP 真机 + 数据清理）。
 *
 * 由独立验证工程师（QA）编写：不读实现细节做结论，一切以实跑为准。
 * 规格卡：docs/media-category-spec.md（字段名已冻结）。
 *
 * 三段：
 *   A. 后端接口层（Node + 会话）：分类 CRUD / 单项归类 / 批量移动 / 列表过滤 / 删除回落 / 排序
 *   B. 浏览器真机（无头 Chrome + CDP，登录态）：chips / 管理面板 / 归类 badge / 筛选 / 批量移动 /
 *      删除回落 / 按类导入选择器 / ↑↓ 排序持久化 / 管理面板无渲染死循环
 *   C. 数据清理与终态核对：categories 归零、media.category_id 全 NULL、标题未变
 *
 * 依赖：托管 Node 22 + 本机 Chrome + 已启动后端（默认 http://127.0.0.1:8000）
 *       + 托管 Python（仅用于只读快照 data/app.db）。
 * 用法（项目根目录）：
 *   node scripts/verify_category.mjs [--url http://127.0.0.1:8000] [--port 9338]
 *
 * 本脚本可重复运行：开跑前清空分类、跑完自动清理测试数据（分类归零、素材回未分类）。
 */

import { spawn, spawnSync } from 'node:child_process'
import { copyFileSync, mkdtempSync, mkdirSync, existsSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { installSessionInBrowser, patchFetchForSession } from './lib/session.mjs'

const argv = process.argv.slice(2)
const arg = (name, fallback) => {
  const i = argv.indexOf(name)
  return i >= 0 && argv[i + 1] ? argv[i + 1] : fallback
}

const BASE = arg('--url', 'http://127.0.0.1:8000').replace(/\/$/, '')
patchFetchForSession(BASE)
const PORT = Number(arg('--port', '9338'))
const CHROME = arg('--chrome', 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe')
const PYTHON = arg(
  '--python',
  'C:\\Users\\kuhn\\.workbuddy\\binaries\\python\\versions\\3.13.12\\python.exe',
)
const DB_PATH = arg('--db', join(process.cwd(), 'data', 'app.db'))

const results = []
const record = (name, ok, detail = '') => {
  results.push({ name, ok })
  console.log(`${ok ? 'OK  ' : 'FAIL'}  ${name}${detail ? `  —— ${detail}` : ''}`)
}
const check = (name, cond, detail = '') => record(name, Boolean(cond), detail)

// --------------------------- HTTP 小工具 ---------------------------

async function req(path, init = {}) {
  const res = await fetch(`${BASE}${path}`, init)
  const text = await res.text()
  let body = null
  try {
    body = text ? JSON.parse(text) : null
  } catch {
    body = text
  }
  return { status: res.status, body }
}
const jsonInit = (obj, method = 'POST') => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(obj),
})

// --------------------------- 只读快照（托管 Python）---------------------------

const SNAPSHOT_PY = `
import json, sqlite3, sys
db = sqlite3.connect(sys.argv[1])
c = db.cursor()
out = {}
c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='categories'")
out["categories_table_exists"] = c.fetchone() is not None
if out["categories_table_exists"]:
    c.execute("SELECT COUNT(*) FROM categories")
    out["categories_rows"] = c.fetchone()[0]
else:
    out["categories_rows"] = None
c.execute("SELECT COUNT(*) FROM media")
out["media_rows"] = c.fetchone()[0]
c.execute("SELECT COUNT(*) FROM media WHERE category_id IS NULL")
out["media_uncategorized"] = c.fetchone()[0]
c.execute("SELECT COUNT(*) FROM media WHERE category_id IS NOT NULL")
out["media_categorized"] = c.fetchone()[0]
c.execute("SELECT id, title, category_id FROM media ORDER BY id")
out["media"] = [{"id": r[0], "title": r[1], "category_id": r[2]} for r in c.fetchall()]
db.close()
print(json.dumps(out, ensure_ascii=False))
`

let snapshotPyPath = null
function snapshot() {
  if (!snapshotPyPath) {
    snapshotPyPath = join(tmpdir(), `qa-snapshot-${process.pid}.py`)
    writeFileSync(snapshotPyPath, SNAPSHOT_PY, 'utf8')
  }
  const r = spawnSync(PYTHON, [snapshotPyPath, DB_PATH], { encoding: 'utf8' })
  if (r.error) throw new Error(`快照失败（无法启动 Python）：${r.error.message}`)
  if (r.status !== 0) throw new Error(`快照失败：${(r.stderr || '').trim() || `退出码 ${r.status}`}`)
  return JSON.parse(r.stdout)
}

// --------------------------- 极简 CDP 客户端 ---------------------------

class CDP {
  constructor(ws) {
    this.ws = ws
    this.seq = 0
    this.pending = new Map()
    this.handlers = new Map()
  }

  static async connect(url) {
    const ws = new WebSocket(url)
    await new Promise((resolve, reject) => {
      ws.addEventListener('open', resolve, { once: true })
      ws.addEventListener('error', reject, { once: true })
    })
    const client = new CDP(ws)
    ws.addEventListener('message', (event) => {
      const msg = JSON.parse(event.data)
      if (msg.id) {
        const slot = client.pending.get(msg.id)
        if (!slot) return
        client.pending.delete(msg.id)
        msg.error ? slot.reject(new Error(msg.error.message)) : slot.resolve(msg.result)
      } else if (msg.method) {
        const fn = client.handlers.get(msg.method)
        if (fn) {
          try {
            fn(msg.params)
          } catch {
            /* 事件处理器异常不影响主流程 */
          }
        }
      }
    })
    return client
  }

  on(method, fn) {
    this.handlers.set(method, fn)
  }

  send(method, params = {}, timeout = 30000) {
    const id = ++this.seq
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        if (this.pending.delete(id)) reject(new Error(`CDP 超时：${method}`))
      }, timeout)
      this.pending.set(id, {
        resolve: (value) => {
          clearTimeout(timer)
          resolve(value)
        },
        reject: (err) => {
          clearTimeout(timer)
          reject(err)
        },
      })
      this.ws.send(JSON.stringify({ id, method, params }))
    })
  }

  async evaluate(expression, timeout = 30000) {
    const res = await this.send(
      'Runtime.evaluate',
      { expression, awaitPromise: true, returnByValue: true },
      timeout,
    )
    if (res.exceptionDetails) {
      throw new Error(res.exceptionDetails.exception?.description || '页面脚本异常')
    }
    return res.result.value
  }

  close() {
    try {
      this.ws.close()
    } catch {
      /* 忽略 */
    }
  }
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

async function waitForJson(url, timeoutMs = 20000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    try {
      const res = await fetch(url)
      if (res.ok) return await res.json()
    } catch {
      /* 还没起来 */
    }
    await sleep(250)
  }
  throw new Error(`等待 ${url} 超时`)
}

// --------------------------- 页面内脚本片段 ---------------------------

const HELPERS = `
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const waitFor = async (fn, timeout = 12000) => {
  const t0 = Date.now();
  while (Date.now() - t0 < timeout) {
    try { const v = fn(); if (v) return v; } catch (e) {}
    await sleep(120);
  }
  return null;
};
const byText = (root, text) =>
  [...root.querySelectorAll('button, a')].find((el) => el.textContent.trim().includes(text)) || null;
const findRowByTitle = (title) => {
  const span = [...document.querySelectorAll('span')].find(
    (s) => s.textContent.trim() === title && (s.className || '').includes('font-medium'),
  );
  if (!span) return null;
  let row = span;
  for (let i = 0; i < 8 && row; i++) {
    if (row.querySelector && row.querySelector('a[href^="/study/"]')) return row;
    row = row.parentElement;
  }
  return null;
};
const visibleIds = () =>
  [...document.querySelectorAll('a[href^="/study/"]')].map((a) => a.getAttribute('href').replace('/study/', ''));
const chipGroup = () => document.querySelector('[role="group"][aria-label="按分类筛选素材"]');
const chipEntries = () =>
  [...chipGroup().querySelectorAll('button')].map((b) => {
    const spans = [...b.querySelectorAll('span')];
    return { label: spans[0] ? spans[0].textContent.trim() : b.textContent.trim(), count: spans[1] ? spans[1].textContent.trim() : null };
  });
const managerDialog = () => document.querySelector('[role="dialog"][aria-label="管理分类"]');
const closeManager = () => { const d = managerDialog(); if (d) { const b = d.querySelector('button[aria-label="关闭"]'); if (b) b.click(); } };
`

// --------------------------- 主流程 ---------------------------

async function resetAll() {
  const list = await req('/api/categories')
  const ids = (list.body?.items ?? []).map((c) => c.id)
  for (const id of ids) await req(`/api/categories/${id}`, { method: 'DELETE' })
  const media = await req('/api/media')
  const categorized = (media.body?.items ?? []).filter((m) => m.category_id !== null).map((m) => m.id)
  if (categorized.length) {
    await req('/api/media/batch-category', jsonInit({ ids: categorized, category_id: null }))
  }
}

async function main() {
  const profile = mkdtempSync(join(tmpdir(), 'fayelong-cat-'))
  let chrome = null
  let cdp = null
  let baseline = null
  const pageErrors = []
  let lastDialog = null

  // ---- C0：备份 + 基线快照 ----
  try {
    const backupsDir = join(process.cwd(), 'data', 'backups')
    if (!existsSync(backupsDir)) mkdirSync(backupsDir, { recursive: true })
    const stamp = new Date()
      .toISOString()
      .replace(/[-:T]/g, '')
      .slice(0, 14)
    copyFileSync(DB_PATH, join(backupsDir, `app.db.qa-cat-${stamp}.bak`))
    record('C0 备份 data/app.db 到 data/backups/', true, `app.db.qa-cat-${stamp}.bak`)
  } catch (err) {
    record('C0 备份 data/app.db 到 data/backups/', false, String(err?.message ?? err))
  }

  try {
    baseline = snapshot()
  } catch (err) {
    record('C0 读取基线快照', false, String(err?.message ?? err))
  }

  try {
    // 先清空可能残留的分类，保证基线干净（终态要求 categories=0）
    await resetAll()
    const clean = snapshot()
    check(
      'A0 基线：categories 归零、media.category_id 全 NULL',
      clean.categories_rows === 0 && clean.media_categorized === 0,
      `categories=${clean.categories_rows} categorized=${clean.media_categorized}`,
    )

    // ============================================================
    // A. 后端接口层
    // ============================================================

    const baseList = await req('/api/media')
    const baseIds = (baseList.body?.items ?? []).map((m) => m.id)
    check(
      'A1 GET /api/media 无参数返回全部素材',
      baseList.status === 200 && baseList.body.total === baseIds.length && baseIds.length > 0,
      `total=${baseList.body?.total} ids=${baseIds}`,
    )
    check(
      'A1 MediaOut 含 category_id 字段（追加，不改既有字段）',
      (baseList.body?.items ?? []).every((m) => 'category_id' in m) &&
        (baseList.body?.items ?? []).every((m) => 'title' in m && 'stream_url' in m),
    )

    const mIds = baseIds.slice().sort((a, b) => a - b)
    const titleOf = (id) => baseList.body.items.find((m) => m.id === id)?.title
    const mA = mIds[0]
    const mB = mIds[1]
    const mC = mIds[2]
    const mD = mIds[3]

    // --- 分类 CRUD ---
    const cat0 = await req('/api/categories')
    check(
      'A2 GET /api/categories 空态：items 空、total=0',
      cat0.status === 200 && Array.isArray(cat0.body.items) && cat0.body.items.length === 0 && cat0.body.total === 0,
      `items=${cat0.body?.items?.length} total=${cat0.body?.total}`,
    )
    const nullCount = baseList.body.items.filter((m) => m.category_id === null).length
    check(
      'A2 空态 uncategorized_count == category_id IS NULL 素材数',
      cat0.body.uncategorized_count === nullCount,
      `uncategorized_count=${cat0.body?.uncategorized_count} null=${nullCount}`,
    )

    const c1 = await req('/api/categories', jsonInit({ name: 'QA-Alpha' }))
    const alphaId = c1.body?.id
    check(
      'A2 新建第 1 个分类 → 201 且 sort_order=0（空表 COALESCE 生效）',
      c1.status === 201 && c1.body.sort_order === 0,
      `status=${c1.status} sort_order=${c1.body?.sort_order}`,
    )
    const c2 = await req('/api/categories', jsonInit({ name: 'QA-Beta' }))
    const betaId = c2.body?.id
    check(
      'A2 新建第 2 个分类 → 201 且 sort_order=1',
      c2.status === 201 && c2.body.sort_order === 1,
      `status=${c2.status} sort_order=${c2.body?.sort_order}`,
    )
    const l2 = await req('/api/categories')
    check(
      'A2 列表按 sort_order ASC 排序',
      (l2.body?.items ?? []).map((c) => c.name).join(',') === 'QA-Alpha,QA-Beta',
      JSON.stringify((l2.body?.items ?? []).map((c) => ({ n: c.name, s: c.sort_order }))),
    )
    check(
      'A2 CategoryOut 字段齐全（id/name/sort_order/media_count/created_at）',
      (l2.body?.items ?? []).every((c) =>
        ['id', 'name', 'sort_order', 'media_count', 'created_at'].every((k) => k in c),
      ),
    )

    // --- 校验：同名 / 空名 / 超长 ---
    const dup = await req('/api/categories', jsonInit({ name: 'QA-Alpha' }))
    check('A3 同名 → 409', dup.status === 409, `status=${dup.status}`)
    const dupCase = await req('/api/categories', jsonInit({ name: 'qa-alpha' }))
    check('A3 大小写变体（qa-alpha vs QA-Alpha）→ 409', dupCase.status === 409, `status=${dupCase.status}`)
    const empty1 = await req('/api/categories', jsonInit({ name: '   ' }))
    check('A3 全空格空名 → 400', empty1.status === 400, `status=${empty1.status}`)
    const empty2 = await req('/api/categories', jsonInit({ name: '' }))
    check('A3 空串 → 400', empty2.status === 400, `status=${empty2.status}`)
    const ok32 = await req('/api/categories', jsonInit({ name: 'x'.repeat(32) }))
    check('A3 32 字符 → 201', ok32.status === 201, `status=${ok32.status}`)
    const bad33 = await req('/api/categories', jsonInit({ name: 'y'.repeat(33) }))
    check('A3 33 字符 → 400', bad33.status === 400, `status=${bad33.status}`)
    if (ok32.body?.id) await req(`/api/categories/${ok32.body.id}`, { method: 'DELETE' })

    // --- 单项归类 ---
    const p1 = await req(`/api/media/${mA}`, jsonInit({ category_id: alphaId }, 'PATCH'))
    check(
      'A4 PATCH /api/media/{id} 单项归类生效',
      p1.status === 200 && p1.body.category_id === alphaId,
      `status=${p1.status} category_id=${p1.body?.category_id}`,
    )
    const p2 = await req(`/api/media/${mA}`, jsonInit({ category_id: null }, 'PATCH'))
    check(
      'A4 传 category_id=null 移回未分类',
      p2.status === 200 && p2.body.category_id === null,
      `status=${p2.status} category_id=${p2.body?.category_id}`,
    )
    await req(`/api/media/${mA}`, jsonInit({ category_id: alphaId }, 'PATCH'))
    const p3 = await req(`/api/media/${mA}`, jsonInit({ title: titleOf(mA) }, 'PATCH'))
    check(
      'A4 只传 title 时不误改已有分类（且标题未变）',
      p3.status === 200 && p3.body.category_id === alphaId && p3.body.title === titleOf(mA),
      `category_id=${p3.body?.category_id} title=${p3.body?.title}`,
    )

    // --- 批量移动 ---
    const b1 = await req(
      '/api/media/batch-category',
      jsonInit({ ids: [mB, mC, 999999], category_id: betaId }),
    )
    check(
      'A5 批量移动 updated/missing 正确，非空校验通过',
      b1.status === 200 &&
        b1.body.updated === 2 &&
        JSON.stringify(b1.body.missing) === '[999999]' &&
        b1.body.category_id === betaId,
      JSON.stringify(b1.body),
    )
    const b2 = await req('/api/media/batch-category', jsonInit({ ids: [], category_id: betaId }))
    check('A5 批量 ids 为空 → 400', b2.status === 400, `status=${b2.status}`)
    const b3 = await req('/api/media/batch-category', jsonInit({ ids: [mB], category_id: 9999999 }))
    check('A5 批量目标分类不存在 → 404', b3.status === 404, `status=${b3.status}`)
    const b4 = await req('/api/media/batch-category', jsonInit({ ids: [mB], category_id: null }))
    check(
      'A5 批量 category_id=null 移到未分类',
      b4.status === 200 && b4.body.updated === 1 && b4.body.category_id === null,
      JSON.stringify(b4.body),
    )

    // --- 列表过滤 ---
    const f1 = await req(`/api/media?category_id=${alphaId}`)
    check(
      'A6 ?category_id=<id> 只返回该类素材',
      f1.status === 200 && (f1.body?.items ?? []).every((m) => m.category_id === alphaId) &&
        (f1.body?.items ?? []).some((m) => m.id === mA),
      `ids=${(f1.body?.items ?? []).map((m) => m.id)}`,
    )
    const f2 = await req('/api/media?category_id=none')
    check(
      'A6 ?category_id=none 只返回未分类素材',
      f2.status === 200 && (f2.body?.items ?? []).every((m) => m.category_id === null) &&
        (f2.body?.items ?? []).some((m) => m.id === mB) &&
        !(f2.body?.items ?? []).some((m) => m.id === mA),
      `ids=${(f2.body?.items ?? []).map((m) => m.id)}`,
    )
    const f3 = await req('/api/media?category_id=abc')
    check('A6 ?category_id=非法（非整数且非 none）→ 400', f3.status === 400, `status=${f3.status}`)
    const f4 = await req('/api/media')
    check(
      'A6 不带参数与改动前一致（全量、total 不变）',
      f4.status === 200 && f4.body.total === baseIds.length &&
        JSON.stringify((f4.body?.items ?? []).map((m) => m.id).sort()) === JSON.stringify(baseIds.slice().sort()),
      `total=${f4.body?.total} base=${baseIds.length}`,
    )
    const f5 = await req('/api/media?category_id=9999999')
    check(
      'A6 ?category_id=不存在的整数 → 200 空列表（不误报 400）',
      f5.status === 200 && (f5.body?.items ?? []).length === 0,
      `status=${f5.status} n=${f5.body?.items?.length}`,
    )

    // --- 删除回落 ---
    await req('/api/media/batch-category', jsonInit({ ids: [mB, mC], category_id: betaId }))
    const d1 = await req(`/api/categories/${betaId}`, { method: 'DELETE' })
    check(
      'A7 DELETE 分类 → released 计数正确',
      d1.status === 200 && d1.body.released === 2 && d1.body.id === betaId && d1.body.name === 'QA-Beta',
      JSON.stringify(d1.body),
    )
    const afterDel = await req('/api/media')
    check(
      'A7 删除后旗下素材回落未分类，且素材未被删除',
      (afterDel.body?.items ?? []).filter((m) => [mB, mC].includes(m.id)).every((m) => m.category_id === null) &&
        afterDel.body.total === baseIds.length,
      `total=${afterDel.body?.total} 回落=${JSON.stringify(
        (afterDel.body?.items ?? []).filter((m) => [mB, mC].includes(m.id)).map((m) => [m.id, m.category_id]),
      )}`,
    )
    const lAfter = await req('/api/categories')
    check(
      'A7 删除后分类列表不再含 QA-Beta',
      !(lAfter.body?.items ?? []).some((c) => c.id === betaId),
      `names=${(lAfter.body?.items ?? []).map((c) => c.name)}`,
    )

    // --- 排序 ---
    const gamma = await req('/api/categories', jsonInit({ name: 'QA-Gamma' }))
    const gammaId = gamma.body?.id
    const o1 = await req('/api/categories/order', jsonInit({ ids: [gammaId, alphaId] }, 'PATCH'))
    check(
      'A8 PATCH /api/categories/order 全量重排生效（0 基）',
      o1.status === 200 &&
        (o1.body?.items ?? []).length === 2 &&
        o1.body.items[0].id === gammaId && o1.body.items[0].sort_order === 0 &&
        o1.body.items[1].id === alphaId && o1.body.items[1].sort_order === 1,
      JSON.stringify((o1.body?.items ?? []).map((c) => ({ n: c.name, s: c.sort_order }))),
    )
    const o2 = await req('/api/categories/order', jsonInit({ ids: [alphaId] }, 'PATCH'))
    check('A8 排序缺项 → 400', o2.status === 400, `status=${o2.status}`)
    const o3 = await req('/api/categories/order', jsonInit({ ids: [alphaId, gammaId, 9999999] }, 'PATCH'))
    check('A8 排序含未知 id → 400', o3.status === 400, `status=${o3.status}`)
    const o4 = await req('/api/categories/order', jsonInit({ ids: [alphaId, alphaId] }, 'PATCH'))
    check('A8 排序含重复 id → 400', o4.status === 400, `status=${o4.status}`)

    // ============================================================
    // B. 浏览器真机
    // ============================================================
    await resetAll()

    // B 前置：建 BBC / VOA，把素材分好组
    const bbc = await req('/api/categories', jsonInit({ name: 'BBC' }))
    const voa = await req('/api/categories', jsonInit({ name: 'VOA' }))
    await req('/api/media/batch-category', jsonInit({ ids: [mA, mB], category_id: bbc.body.id }))
    await req('/api/media/batch-category', jsonInit({ ids: [mC, mD], category_id: voa.body.id }))

    chrome = spawn(
      CHROME,
      [
        '--headless=new',
        `--remote-debugging-port=${PORT}`,
        `--user-data-dir=${profile}`,
        '--no-first-run',
        '--no-default-browser-check',
        '--disable-gpu',
        '--window-size=1360,900',
        'about:blank',
      ],
      { stdio: 'ignore' },
    )

    await waitForJson(`http://127.0.0.1:${PORT}/json/version`)
    const targets = await waitForJson(`http://127.0.0.1:${PORT}/json/list`)
    const page = targets.find((t) => t.type === 'page')
    if (!page) throw new Error('没有找到可用的页面目标')
    cdp = await CDP.connect(page.webSocketDebuggerUrl)
    await cdp.send('Page.enable')
    await cdp.send('Runtime.enable')
    // 会话注入必须在 navigate 之前
    await installSessionInBrowser(cdp, BASE)

    cdp.on('Page.javascriptDialogOpening', (params) => {
      lastDialog = params.message
      cdp.send('Page.handleJavaScriptDialog', { accept: true }).catch(() => {})
    })
    cdp.on('Runtime.consoleAPICalled', (params) => {
      if (params.type === 'error') {
        pageErrors.push((params.args || []).map((a) => a.value ?? a.description ?? '').join(' '))
      }
    })
    cdp.on('Runtime.exceptionThrown', (params) => {
      pageErrors.push(params.exceptionDetails?.exception?.description || 'page exception')
    })

    await cdp.send('Page.navigate', { url: `${BASE}/` })
    await sleep(2200)

    // ---- B7 chips 渲染 ----
    const chipsProbe = await cdp.evaluate(`(async () => { ${HELPERS}
      const group = await waitFor(() => chipGroup(), 12000);
      if (!group) return { error: '未渲染分类 chips 条' };
      await waitFor(() => chipGroup().querySelectorAll('button').length >= 4, 8000);
      return { entries: chipEntries(), hasManage: [...group.querySelectorAll('button')].some((b) => b.textContent.includes('管理分类')) };
    })()`)
    const names = (chipsProbe?.entries ?? []).map((e) => e.label)
    const countOf = (label) => (chipsProbe?.entries ?? []).find((e) => e.label === label)?.count
    check(
      'B7 分类 chips 条渲染（全部 / 未分类 / 各分类 + 管理分类）',
      ['全部', '未分类', 'BBC', 'VOA'].every((n) => names.includes(n)) && chipsProbe?.hasManage,
      JSON.stringify(chipsProbe?.entries),
    )
    check(
      'B7 chips 计数正确（全部=4 / 未分类=0 / BBC=2 / VOA=2）',
      countOf('全部') === '4' && countOf('未分类') === '0' && countOf('BBC') === '2' && countOf('VOA') === '2',
      `全部=${countOf('全部')} 未分类=${countOf('未分类')} BBC=${countOf('BBC')} VOA=${countOf('VOA')}`,
    )

    // ---- B16 / B8：打开管理面板（渲染死循环专项）----
    await cdp.evaluate(
      `(() => { window.__qaMut = 0; window.__qaObs = new MutationObserver((m) => { window.__qaMut += m.length }); window.__qaObs.observe(document.body, { childList: true, subtree: true, characterData: true, attributes: true }); return true })()`,
    )
    let mgr = null
    try {
      mgr = await cdp.evaluate(`(async () => { ${HELPERS}
        const group = chipGroup();
        const manage = [...group.querySelectorAll('button')].find((b) => b.textContent.includes('管理分类'));
        if (!manage) return { error: '未找到「管理分类」按钮' };
        manage.click();
        const dlg = await waitFor(() => managerDialog(), 6000);
        if (!dlg) return { error: '管理分类面板未打开' };
        const t0 = performance.now();
        const mutBefore = window.__qaMut;
        let frames = 0;
        await new Promise((res) => {
          const tick = () => { frames++; if (performance.now() - t0 < 1500) requestAnimationFrame(tick); else res(); };
          requestAnimationFrame(tick);
        });
        const mutDuring = window.__qaMut - mutBefore;
        const rowNames = [...dlg.querySelectorAll('button[title="重命名"]')].map((b) => (b.getAttribute('aria-label') || ''));
        return { opened: true, frames, mutDuring, rowNames };
      })()`, 20000)
    } catch (err) {
      mgr = { error: `打开面板时 evaluate 异常/超时：${String(err?.message ?? err)}` }
    }
    check('B8 真点击「管理分类」→ 面板打开', Boolean(mgr?.opened), mgr?.error ?? JSON.stringify(mgr?.rowNames))
    check(
      'B16 面板打开无渲染死循环（主线程帧率正常）',
      (mgr?.frames ?? 0) >= 20,
      `frames=${mgr?.frames} mutDuring=${mgr?.mutDuring} err=${mgr?.error ?? ''}`,
    )
    check(
      'B16 面板打开后 DOM 变更未失控',
      mgr?.mutDuring !== undefined && mgr.mutDuring < 2000,
      `mutDuring=${mgr?.mutDuring}`,
    )

    const createProbe = await cdp.evaluate(`(async () => { ${HELPERS}
      const dlg = managerDialog();
      if (!dlg) return { error: '面板未打开' };
      const input = dlg.querySelector('input[aria-label="新分类名"]');
      const btn = [...dlg.querySelectorAll('button')].find((b) => b.textContent.trim() === '新建');
      if (!input || !btn) return { error: '未找到新建输入框/按钮' };
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      setter.call(input, 'QA-UI');
      input.dispatchEvent(new Event('input', { bubbles: true }));
      await sleep(180);
      btn.click();
      const chip = await waitFor(() => {
        const g = chipGroup();
        return g && [...g.querySelectorAll('button')].find((b) => b.textContent.includes('QA-UI'));
      }, 8000);
      return { chipFound: !!chip, chipText: chip ? chip.textContent.trim() : null };
    })()`)
    check(
      'B8 面板内新建分类 → chips 实时更新',
      Boolean(createProbe?.chipFound),
      createProbe?.error ?? createProbe?.chipText,
    )

    // ---- B9：真点击给素材归类 → 行出现分类名 badge ----
    const assignProbe = await cdp.evaluate(`(async () => { ${HELPERS}
      closeManager();
      await waitFor(() => !managerDialog(), 4000);
      const batch = await waitFor(() => [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === '批量管理'));
      if (!batch) return { error: '未找到「批量管理」' };
      batch.click();
      await sleep(250);
      const row = findRowByTitle(${JSON.stringify(titleOf(mA))});
      if (!row) return { error: '未找到素材行' };
      const cb = row.querySelector('input[type=checkbox]');
      if (!cb) return { error: '该行无 checkbox' };
      cb.click();
      await sleep(250);
      const moveBtn = [...document.querySelectorAll('button')].find((b) => b.textContent.includes('移动到分类'));
      if (!moveBtn) return { error: '未找到「移动到分类」' };
      moveBtn.click();
      const menu = await waitFor(() => document.querySelector('div[role="menu"]'), 4000);
      if (!menu) return { error: '移动菜单未出现' };
      const item = [...menu.querySelectorAll('button[role="menuitem"]')].find((b) => b.textContent.trim() === 'QA-UI');
      if (!item) return { error: '菜单缺少 QA-UI' };
      item.click();
      const ok = await waitFor(() => { const r = findRowByTitle(${JSON.stringify(titleOf(mA))}); return r && r.textContent.includes('QA-UI'); }, 8000);
      const notice = [...document.querySelectorAll('[role="status"]')].map((e) => e.textContent.trim()).join(' | ');
      return { badge: !!ok, notice };
    })()`)
    check(
      'B9 真点击给素材归类 → 该行出现分类名 badge',
      Boolean(assignProbe?.badge),
      assignProbe?.error ?? assignProbe?.notice,
    )

    // ---- B10：真点击 chip 筛选 ----
    const filterProbe = await cdp.evaluate(`(async () => { ${HELPERS}
      const exit = [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === '退出批量');
      if (exit) exit.click();
      await sleep(300);
      const chip = [...chipGroup().querySelectorAll('button')].find((b) => b.textContent.includes('QA-UI'));
      if (!chip) return { error: '没有 QA-UI chip' };
      chip.click();
      await sleep(900);
      return { ids: visibleIds(), scope: chipGroup() && document.body.innerText.includes('· QA-UI') };
    })()`)
    check(
      'B10 真点击分类 chip → 列表只剩该分类素材',
      Array.isArray(filterProbe?.ids) && filterProbe.ids.length === 1 && filterProbe.ids[0] === String(mA),
      `ids=${JSON.stringify(filterProbe?.ids)} scope=${filterProbe?.scope} err=${filterProbe?.error ?? ''}`,
    )

    // ---- B11：批量管理 → 勾 2 项 → 移动 ----
    const batchProbe = await cdp.evaluate(`(async () => { ${HELPERS}
      const allChip = [...chipGroup().querySelectorAll('button')].find((b) => b.textContent.trim().startsWith('全部'));
      allChip.click();
      await sleep(800);
      const batch = [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === '批量管理');
      batch.click();
      await sleep(300);
      const t1 = ${JSON.stringify(titleOf(mB))};
      const t2 = ${JSON.stringify(titleOf(mD))};
      const r1 = findRowByTitle(t1);
      const r2 = findRowByTitle(t2);
      if (!r1 || !r2) return { error: '未找到目标行 t1=' + t1 + ' t2=' + t2 };
      r1.querySelector('input[type=checkbox]').click();
      r2.querySelector('input[type=checkbox]').click();
      await sleep(300);
      const selected = document.querySelectorAll('input[type=checkbox]:checked').length;
      const moveBtn = [...document.querySelectorAll('button')].find((b) => b.textContent.includes('移动到分类'));
      moveBtn.click();
      const menu = await waitFor(() => document.querySelector('div[role="menu"]'), 4000);
      const item = [...menu.querySelectorAll('button[role="menuitem"]')].find((b) => b.textContent.trim() === 'VOA');
      item.click();
      await sleep(1400);
      const notice = [...document.querySelectorAll('[role="status"]')].map((e) => e.textContent.trim()).join(' | ');
      const exited = ![...document.querySelectorAll('button')].some((b) => b.textContent.trim() === '退出批量');
      return { selected, notice, exited };
    })()`)
    check(
      'B11 批量管理：勾选 2 项并移动 → notice 文案正确',
      batchProbe?.selected === 2 && /已移动 2 个素材到「VOA」/.test(batchProbe?.notice ?? ''),
      `selected=${batchProbe?.selected} notice=${batchProbe?.notice ?? batchProbe?.error} exited=${batchProbe?.exited}`,
    )

    // ---- B12：删除分类 → 素材回落未分类，确认文案明示不删素材 ----
    lastDialog = null
    const delProbe = await cdp.evaluate(`(async () => { ${HELPERS}
      const manage = [...chipGroup().querySelectorAll('button')].find((b) => b.textContent.includes('管理分类'));
      manage.click();
      const dlg = await waitFor(() => managerDialog(), 6000);
      if (!dlg) return { error: '面板未打开' };
      const delBtn = dlg.querySelector('button[aria-label="删除「QA-UI」"]');
      if (!delBtn) return { error: '未找到 QA-UI 的删除按钮' };
      delBtn.click();
      await sleep(1200);
      const notice = [...document.querySelectorAll('[role="status"]')].map((e) => e.textContent.trim()).join(' | ');
      const chipGone = ![...chipGroup().querySelectorAll('button')].some((b) => b.textContent.includes('QA-UI'));
      closeManager();
      await sleep(400);
      const noneChip = [...chipGroup().querySelectorAll('button')].find((b) => b.textContent.includes('未分类'));
      noneChip.click();
      await sleep(900);
      return { notice, chipGone, ids: visibleIds(), hasRelocated: visibleIds().includes(String(${mA})) };
    })()`)
    check(
      'B12 删除确认文案明示「素材不会被删除」',
      /不会被删除/.test(lastDialog ?? ''),
      `dialog=${lastDialog ?? '(未捕获)'}`,
    )
    check(
      'B12 删除分类 → 素材回到「未分类」，notice 报出回落数量',
      Boolean(delProbe?.chipGone) &&
        /已删除分类「QA-UI」/.test(delProbe?.notice ?? '') &&
        /1 个素材已移入「未分类」/.test(delProbe?.notice ?? '') &&
        Boolean(delProbe?.hasRelocated),
      `notice=${delProbe?.notice ?? delProbe?.error} ids=${JSON.stringify(delProbe?.ids)}`,
    )

    // ---- B13：按类导入选择器（上传区 + inbox 面板）----
    const importProbe = await cdp.evaluate(`(async () => { ${HELPERS}
      const uploadSel = document.querySelector('select[aria-label="导入到分类"]');
      if (!uploadSel) return { error: '上传区没有分类选择器' };
      const uploadOpts = [...uploadSel.querySelectorAll('option')].map((o) => o.textContent.trim());
      const inboxBtn = [...document.querySelectorAll('button')].find((b) => b.textContent.includes('从素材目录导入'));
      if (!inboxBtn) return { error: '未找到「从素材目录导入」' };
      inboxBtn.click();
      await sleep(1400);
      const sels = [...document.querySelectorAll('select[aria-label="导入到分类"]')];
      const inboxSel = sels[sels.length - 1];
      if (sels.length < 2 || !inboxSel) return { error: '未渲染 inbox 分类选择器', uploadOpts };
      const inboxOpts = [...inboxSel.querySelectorAll('option')].map((o) => o.textContent.trim());
      const target = [...inboxSel.querySelectorAll('option')].find((o) => o.textContent.trim() === 'BBC');
      if (!target) return { error: 'inbox 选择器缺少 BBC 选项', uploadOpts, inboxOpts };
      const setS = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, 'value').set;
      setS.call(inboxSel, target.value);
      inboxSel.dispatchEvent(new Event('change', { bubbles: true }));
      await sleep(250);
      return { uploadOpts, inboxOpts, picked: inboxSel.value, targetVal: target.value, optionsCount: inboxOpts.length };
    })()`)
    check(
      'B13 上传区分类选择器存在且含未分类与各分类',
      Array.isArray(importProbe?.uploadOpts) &&
        importProbe.uploadOpts.includes('未分类') &&
        importProbe.uploadOpts.includes('BBC') &&
        importProbe.uploadOpts.includes('VOA'),
      JSON.stringify(importProbe?.uploadOpts),
    )
    check(
      'B13 收件箱面板分类选择器存在且可选中（受控状态生效）',
      Boolean(importProbe?.picked && importProbe.picked === importProbe.targetVal) &&
        importProbe?.optionsCount >= 3,
      `picked=${importProbe?.picked} opts=${JSON.stringify(importProbe?.inboxOpts)} err=${importProbe?.error ?? ''}`,
    )

    // ---- B14：↑/↓ 排序真点击 + 刷新保持 ----
    const orderProbe = await cdp.evaluate(`(async () => { ${HELPERS}
      closeManager();
      await sleep(300);
      const manage = [...chipGroup().querySelectorAll('button')].find((b) => b.textContent.includes('管理分类'));
      manage.click();
      const dlg = await waitFor(() => managerDialog(), 6000);
      if (!dlg) return { error: '面板未打开' };
      const orderOf = () => [...dlg.querySelectorAll('button[title="重命名"]')].map((b) => (b.getAttribute('aria-label') || '').replace('重命名「', '').replace('」', ''));
      const before = orderOf();
      const downs = [...dlg.querySelectorAll('button[title="下移"]')];
      if (!downs.length) return { error: '没有下移按钮' };
      downs[0].click();
      await sleep(1200);
      const after = orderOf();
      closeManager();
      return { before, after };
    })()`)
    check(
      'B14 真点击 ↓ 排序 → 面板顺序改变',
      Array.isArray(orderProbe?.before) &&
        orderProbe.before.length === 2 &&
        orderProbe.before[0] !== orderProbe.after[0] &&
        orderProbe.before[0] === orderProbe.after[1],
      `before=${JSON.stringify(orderProbe?.before)} after=${JSON.stringify(orderProbe?.after)} err=${orderProbe?.error ?? ''}`,
    )

    await cdp.send('Page.navigate', { url: `${BASE}/` })
    await sleep(2200)
    const persistProbe = await cdp.evaluate(`(async () => { ${HELPERS}
      const group = await waitFor(() => chipGroup(), 12000);
      if (!group) return { error: 'chips 未渲染' };
      await waitFor(() => chipGroup().querySelectorAll('button').length >= 4, 8000);
      const labels = chipEntries().map((e) => e.label).filter((n) => n && !['全部', '未分类', '管理分类'].includes(n));
      return { labels };
    })()`)
    check(
      'B14 排序刷新后保持（chips 顺序反映新 sort_order）',
      JSON.stringify(persistProbe?.labels) === JSON.stringify(orderProbe?.after),
      `刷新后=${JSON.stringify(persistProbe?.labels)} 排序后=${JSON.stringify(orderProbe?.after)}`,
    )

    // ---- B 段附加：控制台错误 ----
    const realErrors = pageErrors.filter((e) => e && !/favicon|Download the React DevTools/i.test(e))
    check(
      'B15 浏览器控制台无异常报错（含 React 死循环告警）',
      realErrors.length === 0,
      realErrors.length ? realErrors.slice(0, 4).join(' || ') : '无',
    )

    // ---- B16b 专项：分类数据「尚未加载」时打开管理面板（复现原始 bug 场景）----
    // 通过 addScriptToEvaluateOnNewDocument 让 /api/categories 延迟 3s，
    // 在数据仍在 loading 的窗口内打开面板 —— 这正是「categoriesQuery.data?.items ?? []」
    // 每次渲染造新数组 + 面板 effect 以其为依赖 → 无限重渲染 的触发条件。
    const injected = await cdp.send('Page.addScriptToEvaluateOnNewDocument', {
      source: `(() => {
        const orig = window.fetch;
        window.fetch = function (input, init) {
          const url = typeof input === 'string' ? input : (input && input.url) || '';
          const p = orig.apply(this, arguments);
          if (url.indexOf('/api/categories') >= 0) {
            return new Promise((res) => setTimeout(() => res(p), 3000));
          }
          return p;
        };
      })();`,
    })
    const errBeforeSlow = pageErrors.length
    await cdp.send('Page.navigate', { url: `${BASE}/` })
    await sleep(600)
    let slowProbe = null
    try {
      slowProbe = await cdp.evaluate(`(async () => { ${HELPERS}
        window.__qaMut2 = 0;
        const obs = new MutationObserver((m) => { window.__qaMut2 += m.length });
        obs.observe(document.body, { childList: true, subtree: true, characterData: true, attributes: true });
        const group = await waitFor(() => chipGroup(), 6000);
        if (!group) return { error: 'chips 未在早期渲染' };
        await waitFor(() => chipGroup().querySelectorAll('button').length >= 2, 4000);
        const manage = [...chipGroup().querySelectorAll('button')].find((b) => b.textContent.includes('管理分类'));
        if (!manage) return { error: '未找到管理分类按钮（加载中）' };
        manage.click();
        const dlg = await waitFor(() => managerDialog(), 6000);
        if (!dlg) return { error: '面板未在数据加载完成前打开' };
        const mutBefore = window.__qaMut2;
        const t0 = performance.now();
        let frames = 0;
        await new Promise((res) => {
          const tick = () => { frames++; if (performance.now() - t0 < 1500) requestAnimationFrame(tick); else res(); };
          requestAnimationFrame(tick);
        });
        const mutDuring = window.__qaMut2 - mutBefore;
        const emptyState = dlg.textContent.includes('还没有分类');
        obs.disconnect();
        return { opened: true, frames, mutDuring, emptyState };
      })()`, 20000)
    } catch (err) {
      slowProbe = { error: `加载期打开面板时 evaluate 异常/超时：${String(err?.message ?? err)}` }
    }
    check(
      'B16b 分类数据「尚未加载」时打开管理面板不卡死（原 bug 场景）',
      Boolean(slowProbe?.opened) && (slowProbe?.frames ?? 0) >= 20,
      `frames=${slowProbe?.frames} mutDuring=${slowProbe?.mutDuring} emptyState=${slowProbe?.emptyState} err=${slowProbe?.error ?? ''}`,
    )
    check(
      'B16b 加载期面板 DOM 变更未失控',
      slowProbe?.mutDuring !== undefined && slowProbe.mutDuring < 2000,
      `mutDuring=${slowProbe?.mutDuring}`,
    )
    const slowErrors = pageErrors.slice(errBeforeSlow).filter((e) => e && !/favicon|Download the React DevTools/i.test(e))
    check(
      'B16b 加载期无 React「Maximum update depth」等报错',
      slowErrors.length === 0,
      slowErrors.length ? slowErrors.slice(0, 3).join(' || ') : '无',
    )
    await cdp.send('Page.removeScriptToEvaluateOnNewDocument', { identifier: injected.identifier }).catch(() => {})
  } catch (err) {
    record('B 段验证流程', false, String(err?.stack ?? err?.message ?? err))
  } finally {
    // ---- 收尾：关 Chrome / CDP ----
    try {
      cdp?.close()
    } catch {
      /* 忽略 */
    }
    try {
      chrome?.kill()
    } catch {
      /* 忽略 */
    }
    await sleep(300)
    try {
      rmSync(profile, { recursive: true, force: true })
    } catch {
      /* 忽略 */
    }

    // ---- C. 数据清理与终态核对 ----
    try {
      await resetAll()
      record('C 执行测试数据清理（分类归零 + 素材回未分类）', true)
    } catch (err) {
      record('C 执行测试数据清理', false, String(err?.message ?? err))
    }
    try {
      const final = snapshot()
      check('C 终态 categories 行数 = 0', final.categories_rows === 0, `categories=${final.categories_rows}`)
      check('C 终态 media.category_id 全为 NULL', final.media_categorized === 0, `categorized=${final.media_categorized}`)
      check(
        'C 终态素材条数与标题未被改动',
        baseline &&
          final.media_rows === baseline.media_rows &&
          JSON.stringify(final.media.map((m) => [m.id, m.title])) ===
            JSON.stringify(baseline.media.map((m) => [m.id, m.title])),
        `final=${final.media_rows} baseline=${baseline?.media_rows}`,
      )
    } catch (err) {
      record('C 终态快照核对', false, String(err?.message ?? err))
    }
    if (snapshotPyPath) {
      try {
        rmSync(snapshotPyPath, { force: true })
      } catch {
        /* 忽略 */
      }
    }
  }

  const failed = results.filter((r) => !r.ok)
  console.log('\n' + '='.repeat(60))
  console.log(
    failed.length === 0
      ? `全部通过 ✔（${results.length} 项）`
      : `未通过 ${failed.length}/${results.length} 项 ✘  →  ${failed.map((f) => f.name).join('；')}`,
  )
  console.log('='.repeat(60))
  process.exit(failed.length === 0 ? 0 : 1)
}

main()

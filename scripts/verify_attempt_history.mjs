/** 听写历史「展开即对照」验证。
 *
 * 覆盖本次需求：展开听写历史时，同时显示历史提交的原文与词级错误点，
 * 并可按记录纵向对比（高频错误词汇总）。
 *
 * 分两层：
 *   A. 接口层（Node + 会话）—— GET /api/sentences/{id}/attempts 的每条记录
 *      是否带上 tokens / 四类计数，以及这些标记**内部是否自洽**。
 *      这里刻意不复刻后端对齐算法（复刻就等于第二套实现，没意义），
 *      只做「不变量」校验：correct 两侧归一化后必须相等、wrong 必须不等、
 *      missing 只有 expected、extra 只有 actual，且计数与 tokens 长度吻合。
 *   B. UI 层（真实 Chrome + CDP）—— 历史行默认折叠、点击展开后能看到
 *      完整提交内容与词级标红、高频错误词 chip 出现、展开区不横向溢出。
 *
 * 依赖：本机 Chrome + 已启动的后端（单端口 8000）+ Node 22（全局 WebSocket）。
 * 用法（项目根目录）：
 *   node scripts/verify_attempt_history.mjs [--url http://127.0.0.1:8000] [--media 3] [--port 9339]
 *
 * 副作用：只读，不写库（不新增听写记录、不改原文标记）。
 */

import { spawn } from 'node:child_process'
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { installSessionInBrowser, patchFetchForSession } from './lib/session.mjs'

const argv = process.argv.slice(2)
const arg = (name, fallback) => {
  const i = argv.indexOf(name)
  return i >= 0 && argv[i + 1] ? argv[i + 1] : fallback
}

const BASE = arg('--url', 'http://127.0.0.1:8000').replace(/\/$/, '')
const MEDIA_ID = Number(arg('--media', '3'))
const PORT = Number(arg('--port', '9339'))
const CHROME = arg('--chrome', 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe')

patchFetchForSession(BASE)

const VIEWPORT = { width: 1280, height: 900 }
const MOBILE = { width: 375, height: 720 }

const results = []
const record = (name, ok, detail = '') => {
  results.push({ name, ok, detail })
  console.log(`${ok ? 'OK  ' : 'FAIL'}  ${name}${detail ? `  —— ${detail}` : ''}`)
}

/** 与服务端同口径的归一化（只为校验不变量，不用于判定对错） */
const norm = (w) =>
  String(w ?? '')
    .replace(/[\u2018\u2019]/g, "'")
    .toLowerCase()
    .replace(/[^0-9a-z']+/g, '')
    .replace(/^'+|'+$/g, '')

// --------------------------- 极简 CDP 客户端 ---------------------------

class CDP {
  constructor(ws) {
    this.ws = ws
    this.seq = 0
    this.pending = new Map()
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
      const slot = msg.id ? client.pending.get(msg.id) : null
      if (!slot) return
      client.pending.delete(msg.id)
      msg.error ? slot.reject(new Error(msg.error.message)) : slot.resolve(msg.result)
    })
    return client
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

  async evaluate(expression) {
    const res = await this.send('Runtime.evaluate', {
      expression,
      awaitPromise: true,
      returnByValue: true,
    })
    if (res.exceptionDetails) {
      throw new Error(res.exceptionDetails.exception?.description || '页面脚本异常')
    }
    return res.result.value
  }

  /** 真实点击（历史行是 button，键盘也可达，但这里走指针路径更贴近真人） */
  async clickAt(x, y) {
    for (const type of ['mousePressed', 'mouseReleased']) {
      await this.send('Input.dispatchMouseEvent', {
        type,
        x: Math.round(x),
        y: Math.round(y),
        button: 'left',
        buttons: type === 'mouseReleased' ? 0 : 1,
        clickCount: 1,
      })
    }
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

const HELPERS = `
(() => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const waitFor = async (fn, timeout = 10000) => {
    const t0 = Date.now();
    while (Date.now() - t0 < timeout) {
      try { const v = fn(); if (v) return v; } catch (e) {}
      await sleep(120);
    }
    return null;
  };
  const byText = (text) =>
    [...document.querySelectorAll('button, a')].find((el) => el.textContent.trim().includes(text)) || null;
  const rect = (el) => { if (!el) return null; const r = el.getBoundingClientRect();
    return { w: Math.round(r.width), h: Math.round(r.height), top: Math.round(r.top), left: Math.round(r.left) }; };
  const center = (el) => { const r = el.getBoundingClientRect();
    return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; };
  Object.assign(window, { sleep, waitFor, byText, rect, center });
  return true;
})();
`

// --------------------------- 辅助 ---------------------------

async function detail() {
  const res = await fetch(`${BASE}/api/media/${MEDIA_ID}`)
  if (!res.ok) throw new Error(`读取媒体详情失败：HTTP ${res.status}`)
  return res.json()
}

async function attemptsOf(sentenceId) {
  const res = await fetch(`${BASE}/api/sentences/${sentenceId}/attempts?limit=200`)
  if (!res.ok) throw new Error(`读取听写历史失败：HTTP ${res.status}`)
  return res.json()
}

// --------------------------- A. 接口层 ---------------------------

async function verifyApi(sentences) {
  const target = sentences.find((s) => s.attempt_count > 0)
  if (!target) throw new Error('该媒体没有任何听写记录，无法验证历史对照')
  console.log(`接口目标：句子 #${target.id}（idx ${target.idx}，共 ${target.attempt_count} 次尝试）\n`)

  const data = await attemptsOf(target.id)
  record('接口返回 200 且 items 非空', Array.isArray(data.items) && data.items.length > 0,
    `items=${data.items.length} / total=${data.total}`)

  const NEED = ['id', 'input', 'accuracy', 'is_correct', 'created_at',
    'tokens', 'total_words', 'correct', 'wrong', 'missing', 'extra']
  const missingKeys = []
  for (const item of data.items) {
    for (const k of NEED) if (!(k in item)) missingKeys.push(`#${item.id}.${k}`)
  }
  record('每条记录都带齐 11 个字段（含 tokens 与四类计数）', missingKeys.length === 0,
    missingKeys.length ? `缺：${missingKeys.slice(0, 6).join(', ')}` : `${data.items.length} 条全部就位`)

  record('每条记录的 tokens 是数组', data.items.every((i) => Array.isArray(i.tokens)),
    `样例 #${data.items[0].id} tokens=${data.items[0].tokens.length} 项`)

  // 计数与 tokens 长度吻合
  const countMismatch = data.items.filter((i) =>
    i.correct + i.wrong + i.missing + i.extra !== i.tokens.length)
  record('四类计数之和 == tokens 长度', countMismatch.length === 0,
    countMismatch.length ? `${countMismatch.length} 条不符` : '全部吻合')

  // expected 侧总数
  const totalMismatch = data.items.filter((i) => i.correct + i.wrong + i.missing !== i.total_words)
  record('correct+wrong+missing == total_words（标准答案词数）', totalMismatch.length === 0,
    totalMismatch.length ? `${totalMismatch.length} 条不符` : '全部吻合')

  // 四类标记的内部不变量
  const bad = []
  for (const item of data.items) {
    for (const t of item.tokens) {
      if (t.type === 'correct' && !(t.expected != null && t.actual != null && norm(t.expected) === norm(t.actual)))
        bad.push(`#${item.id} correct ${t.expected}/${t.actual}`)
      if (t.type === 'wrong' && !(t.expected != null && t.actual != null && norm(t.expected) !== norm(t.actual)))
        bad.push(`#${item.id} wrong ${t.expected}/${t.actual}`)
      if (t.type === 'missing' && !(t.expected != null && t.actual == null))
        bad.push(`#${item.id} missing ${t.expected}/${t.actual}`)
      if (t.type === 'extra' && !(t.actual != null && t.expected == null))
        bad.push(`#${item.id} extra ${t.expected}/${t.actual}`)
      if (!['correct', 'wrong', 'missing', 'extra'].includes(t.type))
        bad.push(`#${item.id} 未知类型 ${t.type}`)
    }
  }
  record('四类标记语义自洽（correct 两侧相等 / wrong 不等 / missing 只有答案 / extra 只有提交）',
    bad.length === 0, bad.length ? bad.slice(0, 4).join(' | ') : `共校验 ${data.items.reduce((n, i) => n + i.tokens.length, 0)} 个 token`)

  // accuracy 是历史快照：与「重算 tokens 推出的正确率」比对（原文未改时应一致）
  const inconsistent = data.items.filter((i) => {
    if (!i.total_words) return false
    const recomputed = Math.round((i.correct / i.total_words) * 1000) / 10
    return Math.abs(recomputed - i.accuracy) > 0.11
  })
  record('历史 accuracy 与重算明细一致（原文字段未被改写时成立）',
    inconsistent.length === 0,
    inconsistent.length
      ? `${inconsistent.length} 条不一致（原文可能被校对改过）：` +
        inconsistent.slice(0, 3).map((i) => `#${i.id} 库 ${i.accuracy}% vs 重算 ${Math.round((i.correct / i.total_words) * 1000) / 10}%`).join(', ')
      : `${data.items.length} 条一致`)

  // 高频错误词口径（与前端一致）：wrong/missing 取 expected、extra 取 actual，单条内去重后跨条累加
  const counts = new Map()
  for (const item of data.items) {
    const seen = new Set()
    for (const t of item.tokens) {
      const w = t.type === 'extra' ? t.actual : t.type === 'wrong' || t.type === 'missing' ? t.expected : null
      const k = w?.trim()
      if (k) seen.add(k)
    }
    for (const k of seen) counts.set(k, (counts.get(k) ?? 0) + 1)
  }
  const ranked = [...counts.entries()].sort((a, b) => b[1] - a[1])
  record('可聚合出高频错误词（wrong/missing 取 expected、extra 取 actual，条内去重）',
    ranked.length > 0,
    ranked.slice(0, 5).map(([w, c]) => `${w}×${c}`).join(', ') || '无错误词')

  return { target, data, ranked }
}

// --------------------------- B. UI 层 ---------------------------

async function verifyUi(target, apiData, profile) {
  const chrome = spawn(
    CHROME,
    [
      '--headless=new',
      `--remote-debugging-port=${PORT}`,
      `--user-data-dir=${profile}`,
      '--no-first-run',
      '--no-default-browser-check',
      '--disable-gpu',
      `--window-size=${VIEWPORT.width},${VIEWPORT.height}`,
      'about:blank',
    ],
    { stdio: 'ignore' },
  )

  let cdp = null
  try {
    await waitForJson(`http://127.0.0.1:${PORT}/json/version`)
    const targets = await waitForJson(`http://127.0.0.1:${PORT}/json/list`)
    const page = targets.find((t) => t.type === 'page')
    if (!page) throw new Error('没有找到可用的页面目标')
    cdp = await CDP.connect(page.webSocketDebuggerUrl)
    await cdp.send('Page.enable')
    await cdp.send('Runtime.enable')
    await cdp.send('Network.enable')
    await cdp.send('Emulation.setDeviceMetricsOverride', {
      width: VIEWPORT.width, height: VIEWPORT.height, deviceScaleFactor: 1, mobile: false,
    })

    await installSessionInBrowser(cdp, BASE)
    await cdp.send('Page.navigate', { url: `${BASE}/study/${MEDIA_ID}` })
    await sleep(1500)
    await cdp.evaluate(HELPERS)
    await cdp.evaluate(
      `window.waitFor(() => document.querySelector('[data-testid="dictation-input"]'), 15000).then(() => true)`,
    )

    // 切到「有听写记录」的那一句
    const index = target.idx
    await cdp.evaluate(`(() => {
      document.querySelectorAll('[data-testid="sentence-grid"] button')[${index}]?.click();
      return true;
    })()`)
    await sleep(900)

    // 展开历史面板
    await cdp.evaluate(`(() => { window.byText('听写历史')?.click(); return true; })()`)
    const panelUp = await cdp.evaluate(
      `window.waitFor(() => document.querySelector('[data-testid^="dictation-history-item-"]'), 10000).then(Boolean)`,
    )
    record('点击「听写历史」后历史列表出现', panelUp === true)

    // 高频错误词汇总
    const chips = await cdp.evaluate(`(() => {
      const box = document.querySelector('[data-testid="dictation-error-words"]');
      if (!box) return null;
      const spans = [...box.querySelectorAll('span')].filter((s) => /×\\d+$/.test(s.textContent.trim()));
      return { count: spans.length, sample: spans.slice(0, 5).map((s) => s.textContent.trim()) };
    })()`)
    record('面板顶部出现「高频错误词」汇总 chip', !!chips && chips.count > 0,
      chips ? `${chips.count} 个：${chips.sample.join(', ')}` : '找不到 dictation-error-words')

    // 默认折叠
    const collapsed = await cdp.evaluate(`(() => {
      const rows = [...document.querySelectorAll('[data-testid^="dictation-history-item-"]')];
      const opened = [...document.querySelectorAll('[data-testid^="dictation-history-input-"]')];
      const first = rows[0];
      return {
        rows: rows.length,
        opened: opened.length,
        tag: first ? first.tagName : null,
        aria: first ? first.getAttribute('aria-expanded') : null,
        h: first ? Math.round(first.getBoundingClientRect().height) : 0,
      };
    })()`)
    record('历史记录默认全部折叠（无展开内容）', collapsed.opened === 0 && collapsed.aria === 'false',
      `rows=${collapsed.rows} opened=${collapsed.opened} aria-expanded=${collapsed.aria}`)
    record('历史行是可点击按钮且触摸目标 ≥ 32px', collapsed.tag === 'BUTTON' && collapsed.h >= 32,
      `${collapsed.tag} / ${collapsed.h}px`)

    // 点开第一条
    const firstId = apiData.items[0].id
    const pt = await cdp.evaluate(`(() => {
      const el = document.querySelector('[data-testid="dictation-history-item-${firstId}"]');
      if (!el) return null;
      el.scrollIntoView({ block: 'center' });
      return window.center(el);
    })()`)
    if (!pt) throw new Error(`找不到第一条历史记录 #${firstId}`)
    await cdp.clickAt(pt.x, pt.y)
    await sleep(600)

    const opened = await cdp.evaluate(`(() => {
      const row = document.querySelector('[data-testid="dictation-history-item-${firstId}"]');
      const input = document.querySelector('[data-testid="dictation-history-input-${firstId}"]');
      if (!row || !input) return null;
      const box = input.parentElement.parentElement;
      const marks = [...box.querySelectorAll('span')].filter((s) => {
        const c = getComputedStyle(s);
        return c.textDecorationLine.includes('line-through') || c.textDecorationLine.includes('underline');
      });
      const reds = [...box.querySelectorAll('span')].filter((s) =>
        getComputedStyle(s).color === 'rgb(220, 38, 38)' || getComputedStyle(s).color === 'rgb(239, 68, 68)');
      return {
        aria: row.getAttribute('aria-expanded'),
        text: input.textContent,
        width: Math.round(input.getBoundingClientRect().width),
        scrollW: input.scrollWidth,
        clientW: input.clientWidth,
        marked: marks.length,
        reds: reds.length,
        hint: box.textContent.includes('对照基准'),
      };
    })()`)
    record('点击后该条展开（aria-expanded=true）', opened?.aria === 'true', `aria-expanded=${opened?.aria}`)
    record('展开区显示「当时提交」的完整内容且与接口一致',
      !!opened && opened.text.trim() === apiData.items[0].input.trim(),
      opened ? `页面「${opened.text.trim().slice(0, 40)}」` : '展开区缺失')
    record('展开区渲染出词级错误标注（下划线/删除线 + 红色）',
      !!opened && opened.marked > 0 && opened.reds > 0,
      opened ? `标注 ${opened.marked} 处 / 红字 ${opened.reds} 处` : '')
    record('展开区给出「对照基准为当前原文」提示', opened?.hint === true)
    record('展开区文本不横向溢出（长句自动换行）',
      !!opened && opened.scrollW <= opened.clientW + 1,
      opened ? `scrollW=${opened.scrollW} clientW=${opened.clientW}` : '')

    // 同一条再点一次 → 收起。展开后行下方的 DOM 变高，重新取一次坐标再点，
    // 避免用展开前的旧坐标点到别处（那是脚本的锅，不是页面的）。
    const before2 = await cdp.evaluate(`(() => {
      const row = document.querySelector('[data-testid="dictation-history-item-${firstId}"]');
      return row ? row.getAttribute('aria-expanded') : null;
    })()`)
    const pt2 = await cdp.evaluate(`(() => {
      const el = document.querySelector('[data-testid="dictation-history-item-${firstId}"]');
      if (!el) return null;
      el.scrollIntoView({ block: 'center' });
      return window.center(el);
    })()`)
    await sleep(300)
    await cdp.clickAt(pt2.x, pt2.y)
    await sleep(800)
    const reclosed = await cdp.evaluate(
      `(() => {
        const row = document.querySelector('[data-testid="dictation-history-item-${firstId}"]');
        const input = document.querySelector('[data-testid="dictation-history-input-${firstId}"]');
        return { aria: row ? row.getAttribute('aria-expanded') : null, has: !!input };
      })()`,
    )
    record('再次点击可收起（明细从 DOM 移除）', reclosed.aria === 'false' && reclosed.has === false,
      `点前 aria-expanded=${before2} → 点后 ${reclosed.aria} / 明细在 DOM=${reclosed.has}`)

    // 桌面截图（展开状态）
    await cdp.clickAt(pt.x, pt.y)
    await sleep(600)
    const shot = await cdp.send('Page.captureScreenshot', { format: 'png' })
    const shotPath = join(profile, 'history-desktop.png')
    writeFileSync(shotPath, Buffer.from(shot.data, 'base64'))
    console.log(`\n截图（桌面 1280）：${shotPath}\n`)

    // 移动端：375px 下展开区是否横向溢出
    await cdp.send('Emulation.setDeviceMetricsOverride', {
      width: MOBILE.width, height: MOBILE.height, deviceScaleFactor: 2, mobile: true,
    })
    await sleep(600)
    const mobile = await cdp.evaluate(`(() => {
      const input = document.querySelector('[data-testid="dictation-history-input-${firstId}"]');
      const box = input ? input.parentElement.parentElement : null;
      return {
        docScroll: document.documentElement.scrollWidth,
        docClient: document.documentElement.clientWidth,
        boxScroll: box ? box.scrollWidth : null,
        boxClient: box ? box.clientWidth : null,
      };
    })()`)
    record('移动端 375px 下面板不横向溢出',
      mobile.docScroll <= mobile.docClient + 1 &&
        (mobile.boxScroll === null || mobile.boxScroll <= mobile.boxClient + 1),
      `页面 scrollW=${mobile.docScroll}/clientW=${mobile.docClient}；明细 scrollW=${mobile.boxScroll}/clientW=${mobile.boxClient}`)

    const shotMobile = await cdp.send('Page.captureScreenshot', { format: 'png' })
    const shotMobilePath = join(profile, 'history-mobile.png')
    writeFileSync(shotMobilePath, Buffer.from(shotMobile.data, 'base64'))
    console.log(`截图（移动 375）：${shotMobilePath}\n`)
  } finally {
    try {
      cdp?.close()
    } catch {
      /* 忽略 */
    }
    try {
      chrome.kill()
    } catch {
      /* 忽略 */
    }
  }
}

// --------------------------- 主流程 ---------------------------

async function main() {
  console.log(`目标：${BASE}   媒体：#${MEDIA_ID}\n`)

  const boot = await detail()
  if (!boot.sentences?.length) throw new Error('该媒体还没有句子，无法验证听写历史')

  const { target, data } = await verifyApi(boot.sentences)
  console.log('')
  const profile = mkdtempSync(join(tmpdir(), 'fayelong-history-'))
  try {
    await verifyUi(target, data, profile)
  } finally {
    await sleep(400)
    // 截图留一份到系统临时目录之外会污染项目，这里保留在 profile 里随清理删除；
    // 若要人工查看，脚本已在上面打印路径。
  }

  const failed = results.filter((r) => !r.ok)
  console.log(`\n合计 ${results.length} 项，通过 ${results.length - failed.length} 项，失败 ${failed.length} 项`)
  if (failed.length) {
    console.log('\n失败明细：')
    for (const f of failed) console.log(`  FAIL  ${f.name}  ${f.detail}`)
    process.exitCode = 1
  }
}

main().catch((err) => {
  console.error('验证脚本异常：', err)
  process.exitCode = 1
})

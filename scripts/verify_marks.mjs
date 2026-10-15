/** 学习页 UI 调整 + 原文「易听错」标记验证（v1.14）。
 *
 * 覆盖本次四条需求里可被机器断言的部分：
 *   1. 听写输入框与其中字体变大、中文翻译字号变大
 *   2. 「上次 X%」后面不再跟输入历史文本
 *   3. 原文可手动标记容易听错的部分（点词 / 拖选整段），且持久化到服务端
 *   4. 「下一句」按钮变大
 *
 * 为什么必须真点：标记是「按住从左拖到右」的指针交互，jsdom 里点不出来 ——
 * 只有真实 Chrome + CDP `Input.dispatchMouseEvent` 才能造出 pointerdown /
 * pointerenter / pointerup 这条链，才能真正验证拖选没有坏。
 *
 * 依赖：本机 Chrome + 已启动的后端 + Node 22（全局 WebSocket）。
 * 用法（项目根目录）：
 *   node scripts/verify_marks.mjs [--url http://127.0.0.1:8000] [--media 4] [--port 9338]
 *
 * 副作用：会在该媒体第一句上临时写标记，结束时无论成败都会清空。
 */

import { spawn } from 'node:child_process'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { installSessionInBrowser, patchFetchForSession } from './lib/session.mjs'

const argv = process.argv.slice(2)
const arg = (name, fallback) => {
  const i = argv.indexOf(name)
  return i >= 0 && argv[i + 1] ? argv[i + 1] : fallback
}

const BASE = arg('--url', 'http://127.0.0.1:8000').replace(/\/$/, '')
const MEDIA_ID = Number(arg('--media', '4'))
const PORT = Number(arg('--port', '9338'))
const CHROME = arg('--chrome', 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe')

patchFetchForSession(BASE)

const VIEWPORT = { width: 1280, height: 900 }

const results = []
const record = (name, ok, detail = '') => {
  results.push({ name, ok, detail })
  console.log(`${ok ? 'OK  ' : 'FAIL'}  ${name}${detail ? `  —— ${detail}` : ''}`)
}

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

  /** 真实鼠标按下 / 移动 / 抬起（用于拖选） */
  async mouse(type, x, y) {
    await this.send('Input.dispatchMouseEvent', {
      type,
      x: Math.round(x),
      y: Math.round(y),
      button: 'left',
      buttons: type === 'mouseReleased' ? 0 : 1,
      clickCount: 1,
    })
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
  const px = (el, prop) => el ? parseFloat(getComputedStyle(el)[prop]) : null;
  const rect = (el) => { if (!el) return null; const r = el.getBoundingClientRect();
    return { w: Math.round(r.width), h: Math.round(r.height), top: Math.round(r.top), left: Math.round(r.left) }; };
  const center = (el) => { const r = el.getBoundingClientRect();
    return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; };
  const word = (i) => document.querySelector('[data-word-index="' + i + '"]');
  const marksOf = () => [...document.querySelectorAll('[data-word-index]')]
    .filter((el) => el.dataset.marked === '1')
    .map((el) => Number(el.dataset.wordIndex));
  const wordCount = () => document.querySelectorAll('[data-word-index]').length;
  Object.assign(window, { sleep, waitFor, byText, px, rect, center, word, marksOf, wordCount });
  return true;
})();
`

// --------------------------- 辅助 ---------------------------

async function detail() {
  const res = await fetch(`${BASE}/api/media/${MEDIA_ID}`)
  if (!res.ok) throw new Error(`读取媒体详情失败：HTTP ${res.status}`)
  return res.json()
}

/** 读当前舞台显示的是第几句（宫格高亮 / #序号） */
async function currentSentenceIndex(cdp) {
  return cdp.evaluate(`(() => {
    const chip = [...document.querySelectorAll('span')].find((s) => /^#\\d+$/.test(s.textContent.trim()));
    return chip ? Number(chip.textContent.trim().slice(1)) - 1 : 0;
  })()`)
}

async function wordCenter(cdp, i) {
  return cdp.evaluate(`window.center(window.word(${i}))`)
}

// --------------------------- 主流程 ---------------------------

async function main() {
  console.log(`目标：${BASE}   媒体：#${MEDIA_ID}\n`)

  const boot = await detail()
  const mediaSentenceCount = boot.sentences.length
  if (mediaSentenceCount === 0) throw new Error('该媒体还没有句子，无法验证听写区')

  const profile = mkdtempSync(join(tmpdir(), 'fayelong-marks-'))
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
  let targetSentenceId = boot.sentences[0].id
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
      width: VIEWPORT.width,
      height: VIEWPORT.height,
      deviceScaleFactor: 1,
      mobile: false,
    })

    await installSessionInBrowser(cdp, BASE)
    await cdp.send('Page.navigate', { url: `${BASE}/study/${MEDIA_ID}` })
    await sleep(1200)
    await cdp.evaluate(HELPERS)
    await cdp.evaluate(
      `window.waitFor(() => document.querySelector('[data-testid="dictation-input"]'), 15000).then(() => true)`,
    )

    const index0 = await currentSentenceIndex(cdp)
    let targetSentenceId0 = boot.sentences[index0]?.id ?? targetSentenceId

    // ---------- 需求 1：输入框与字号 ----------
    const box = await cdp.evaluate(`(() => {
      const el = document.querySelector('[data-testid="dictation-input"]');
      return { fontSize: window.px(el, 'fontSize'), rect: window.rect(el), rows: el.rows };
    })()`)
    record(
      '听写输入框调大（高度 ≥ 100px）',
      box.rect.h >= 100,
      `实际 ${box.rect.h}px`,
    )
    record(
      '听写输入框字体调大（≥ 22px）',
      box.fontSize >= 22,
      `实际 ${box.fontSize}px`,
    )
    record('听写输入框 3 行起', box.rows >= 3, `rows=${box.rows}`)

    // 中文翻译需要可见：先点「显示翻译」（若已显示则跳过）
    await cdp.evaluate(`(() => {
      const btn = window.byText('显示翻译');
      if (btn) btn.click();
      return true;
    })()`)
    await sleep(400)
    const zh = await cdp.evaluate(`(() => {
      const el = document.querySelector('[data-testid="sentence-zh"]');
      if (!el) return null;
      return { fontSize: window.px(el, 'fontSize'), text: el.textContent.trim().length };
    })()`)
    record(
      '中文翻译字号调大（≥ 20px）',
      !!zh && zh.fontSize >= 20,
      zh ? `实际 ${zh.fontSize}px（译文 ${zh.text} 字）` : '找不到译文节点',
    )

    // ---------- 需求 2：默认不显示听写历史 ----------
    const meta = await cdp.evaluate(`(() => {
      const row = document.querySelector('[data-testid="dictation-meta"]');
      return row ? { text: row.textContent.replace(/\\s+/g, ' ').trim() } : { text: null };
    })()`)
    record(
      '听写信息行不含历史输入文本',
      meta.text !== null && !meta.text.includes('「'),
      `该行文案：${meta.text ?? '(缺失)'}`,
    )
    const historyOpen = await cdp.evaluate(
      `document.body.innerText.includes('收起历史') || document.body.innerText.includes('还没有听写记录')`,
    )
    record('听写历史默认收起', historyOpen === false, historyOpen ? '历史面板默认展开了' : '')

    // 换到一句**已经有听写记录**的句子，这才真正验证「上次 X%」后面不再跟输入文本
    const withHistory = boot.sentences.findIndex((s) => s.attempt_count > 0)
    if (withHistory > 0) {
      await cdp.evaluate(`(() => {
        document.querySelectorAll('[data-testid="sentence-grid"] button')[${withHistory}]?.click();
        return true;
      })()`)
      await sleep(800)
      const meta2 = await cdp.evaluate(`(() => {
        const row = document.querySelector('[data-testid="dictation-meta"]');
        return row ? row.textContent.replace(/\\s+/g, ' ').trim() : null;
      })()`)
      record(
        '有记录的句子：「上次 X%」后不再跟输入历史文本',
        !!meta2 && meta2.includes('上次') && !meta2.includes('「'),
        `该行文案：${meta2 ?? '(缺失)'}`,
      )
      await cdp.evaluate(`(() => {
        document.querySelectorAll('[data-testid="sentence-grid"] button')[0]?.click();
        return true;
      })()`)
      await sleep(800)
    } else {
      record('有记录的句子：「上次 X%」后不再跟输入历史文本', true, '该媒体暂无听写记录，跳过')
    }

    // ---------- 需求 4：下一句按钮 ----------
    const nav = await cdp.evaluate(`(() => {
      const next = window.byText('下一句');
      const prev = window.byText('上一句');
      return { next: next && { fontSize: window.px(next, 'fontSize'), ...window.rect(next) },
               prev: prev && { fontSize: window.px(prev, 'fontSize'), ...window.rect(prev) } };
    })()`)
    record(
      '「下一句」按钮调大（高 ≥ 44px 且字号 ≥ 16px）',
      !!nav.next && nav.next.h >= 44 && nav.next.fontSize >= 16,
      nav.next ? `${nav.next.w}×${nav.next.h}px / ${nav.next.fontSize}px` : '找不到按钮',
    )
    record(
      '「上一句」按钮同步调大（高 ≥ 36px）',
      !!nav.prev && nav.prev.h >= 36,
      nav.prev ? `${nav.prev.w}×${nav.prev.h}px / ${nav.prev.fontSize}px` : '找不到按钮',
    )

    // ---------- 需求 3：标记易听错 ----------
    const index = await currentSentenceIndex(cdp)
    targetSentenceId = boot.sentences[index]?.id ?? targetSentenceId0
    await cdp.evaluate(`(() => { window.byText('标记难点')?.click(); return true; })()`)
    await sleep(500)

    const words = await cdp.evaluate(`window.wordCount()`)
    record('标记模式下原文单词可点（≥ 6 个词）', words >= 6, `共 ${words} 个词`)
    if (words < 6) throw new Error('当前句词数太少，无法完成拖选验证')

    const hint = await cdp.evaluate(
      `!!document.querySelector('[data-testid="mark-hint"]')`,
    )
    record('开启后出现标记模式提示条', hint === true)

    // 单击第 1 个词（index 1）
    const c1 = await wordCenter(cdp, 1)
    await cdp.mouse('mousePressed', c1.x, c1.y)
    await cdp.mouse('mouseReleased', c1.x, c1.y)
    await sleep(700)
    const afterClick = await cdp.evaluate(`window.marksOf()`)
    record(
      '单击单词即标记该词',
      JSON.stringify(afterClick) === JSON.stringify([1]),
      `已标记词：${JSON.stringify(afterClick)}`,
    )

    let persisted = (await detail()).sentences.find((s) => s.id === targetSentenceId)
    record(
      '标记已持久化到服务端',
      JSON.stringify(persisted?.marks) === JSON.stringify([[1, 1]]),
      `接口返回 marks=${JSON.stringify(persisted?.marks)}`,
    )

    // 拖选 2 → 5
    const from = await wordCenter(cdp, 2)
    await cdp.mouse('mousePressed', from.x, from.y)
    for (const i of [3, 4, 5]) {
      const p = await wordCenter(cdp, i)
      await cdp.mouse('mouseMoved', p.x, p.y)
      await sleep(60)
    }
    const to = await wordCenter(cdp, 5)
    await cdp.mouse('mouseReleased', to.x, to.y)
    await sleep(800)

    const afterDrag = await cdp.evaluate(`window.marksOf()`)
    record(
      '拖选可标一整段（2–5 共 4 个词）',
      JSON.stringify(afterDrag) === JSON.stringify([1, 2, 3, 4, 5]),
      `已标记词：${JSON.stringify(afterDrag)}`,
    )
    persisted = (await detail()).sentences.find((s) => s.id === targetSentenceId)
    record(
      '拖选结果也已持久化（服务端归并为 [[1,5]]）',
      JSON.stringify(persisted?.marks) === JSON.stringify([[1, 5]]),
      `接口返回 marks=${JSON.stringify(persisted?.marks)}`,
    )

    // 刷新后仍在（标记模式已随页面重置，这里重新进入；进标记模式会自动亮出原文）
    await cdp.send('Page.reload', { ignoreCache: false })
    await sleep(1500)
    await cdp.evaluate(HELPERS)
    await cdp.evaluate(
      `window.waitFor(() => document.querySelector('[data-testid="dictation-input"]'), 15000).then(() => true)`,
    )
    await cdp.evaluate(`(() => { window.byText('标记难点')?.click(); return true; })()`)
    await sleep(700)
    const afterReload = await cdp.evaluate(`window.marksOf()`)
    record(
      '刷新页面后标记仍在',
      JSON.stringify(afterReload) === JSON.stringify([1, 2, 3, 4, 5]),
      `已标记词：${JSON.stringify(afterReload)}`,
    )

    // 再点已标记的词 → 取消
    const c3 = await wordCenter(cdp, 3)
    await cdp.mouse('mousePressed', c3.x, c3.y)
    await cdp.mouse('mouseReleased', c3.x, c3.y)
    await sleep(700)
    const afterUnmark = await cdp.evaluate(`window.marksOf()`)
    record(
      '再点已标记的词即取消（拆成 1–2 与 4–5 两段）',
      JSON.stringify(afterUnmark) === JSON.stringify([1, 2, 4, 5]),
      `已标记词：${JSON.stringify(afterUnmark)}`,
    )

    // 清除全部
    await cdp.evaluate(`(() => {
      const btn = [...document.querySelectorAll('[data-testid="mark-hint"] button')]
        .find((b) => b.textContent.includes('清除全部'));
      btn?.click();
      return true;
    })()`)
    await sleep(800)
    const afterClear = await cdp.evaluate(`window.marksOf()`)
    persisted = (await detail()).sentences.find((s) => s.id === targetSentenceId)
    record(
      '「清除全部」清空标记',
      afterClear.length === 0 && JSON.stringify(persisted?.marks) === '[]',
      `页面 ${JSON.stringify(afterClear)} / 接口 ${JSON.stringify(persisted?.marks)}`,
    )

    // 退出标记模式
    await cdp.evaluate(`(() => {
      const btn = [...document.querySelectorAll('[data-testid="mark-hint"] button')]
        .find((b) => b.textContent.includes('完成'));
      btn?.click();
      return true;
    })()`)
    await sleep(300)
    const hintGone = await cdp.evaluate(
      `!!document.querySelector('[data-testid="mark-hint"]')`,
    )
    record('「完成」退出标记模式', hintGone === false)
  } finally {
    // 无论成败都别在用户数据里留下标记
    try {
      await fetch(`${BASE}/api/sentences/${targetSentenceId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ marks: [] }),
      })
    } catch {
      /* 尽力而为 */
    }
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
    await sleep(400)
    try {
      rmSync(profile, { recursive: true, force: true })
    } catch {
      /* Chrome 可能还占着 profile */
    }
  }

  const failed = results.filter((r) => !r.ok)
  console.log(
    `\n合计 ${results.length} 项，通过 ${results.length - failed.length} 项，失败 ${failed.length} 项`,
  )
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

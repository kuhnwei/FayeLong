/** P1 Round B 验证：请求层 + 门禁接线（真实无头 Chrome + CDP + 真实后端）。
 *
 * 覆盖（G1 ②③）：
 *   1. 未登录态 → 渲染**登录门禁占位**，且**不渲染** Layout（三分支第一支走对）
 *   2. 注入会话后 → 渲染 **Layout**（已登录分支）
 *   3. `window.__fayeApi.listMedia()` 返回**真实数据**，条数与后端一致（本机 4 个媒体）
 *   4. `getAuthStatus().authenticated === true`
 *   5. `openProgressStream(mediaId, …)` **真连一次**（EventSource 打开并收到至少一帧）
 *   6. Layout 里的 `BackendStatus` 显示「后端正常」
 *
 * 依赖：已启动后端(8000) + `frontend-vue` dev(5174) + Node 22 + 本机 Chrome。
 * 用法（项目根）：node scripts/verify_vue_roundB.mjs [--url http://localhost:5174] [--port 9341]
 *
 * ⚠️ 历史坑：Chrome 必须与测试同一条命令内「启动→测试→收尾」；每次换新 --user-data-dir；
 *    CDP 类必须 close() + finally 逐项 try/catch。
 */

import { spawn } from 'node:child_process'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { apiFetch, installSessionInBrowser } from './lib/session.mjs'

const argv = process.argv.slice(2)
const arg = (name, fallback) => {
  const i = argv.indexOf(name)
  return i >= 0 && argv[i + 1] ? argv[i + 1] : fallback
}

const BASE = arg('--url', 'http://localhost:5174').replace(/\/$/, '')
const PORT = Number(arg('--port', '9341'))
const CHROME = arg('--chrome', 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe')

const results = []
const record = (name, ok, detail = '') => {
  results.push({ name, ok })
  console.log(`${ok ? 'OK  ' : 'FAIL'}  ${name}${detail ? `  —— ${detail}` : ''}`)
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

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
        resolve: (v) => {
          clearTimeout(timer)
          resolve(v)
        },
        reject: (e) => {
          clearTimeout(timer)
          reject(e)
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
  close() {
    try {
      this.ws.close()
    } catch {
      /* 忽略 */
    }
  }
}

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

async function goto(cdp, path, wait = 1600) {
  await cdp.send('Page.navigate', { url: `${BASE}${path}` })
  await sleep(wait)
}

async function main() {
  console.log(`目标：${BASE}\n`)

  // 后端真实媒体数（带会话，经 5174 代理）
  const mediaRes = await apiFetch(BASE, '/api/media')
  const backendMedia = await mediaRes.json()
  const backendTotal = backendMedia.total
  console.log(`后端媒体数（经 5174 代理）= ${backendTotal}\n`)

  const profile = mkdtempSync(join(tmpdir(), 'fayelong-roundb-'))
  const chrome = spawn(
    CHROME,
    [
      '--headless=new',
      `--remote-debugging-port=${PORT}`,
      `--user-data-dir=${profile}`,
      '--no-first-run',
      '--no-default-browser-check',
      '--disable-gpu',
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

    // ---------- 1. 未登录：登录门禁占位（不是 Layout） ----------
    await cdp.send('Network.clearBrowserCookies')
    await goto(cdp, '/', 1700)
    const anon = await cdp.evaluate(`(() => ({
      hasLayout: !!document.querySelector('.h-dvh'),
      h2: (document.querySelector('h2') || {}).textContent || '',
      body: (document.body.innerText || '').slice(0, 200),
    }))()`)
    record(
      '未登录 → 渲染登录门禁占位、且不渲染 Layout',
      anon.hasLayout === false && anon.h2.includes('登录'),
      `hasLayout=${anon.hasLayout} h2="${anon.h2.trim()}"`,
    )

    // ---------- 2. 注入会话 ----------
    await installSessionInBrowser(cdp, BASE)

    // ---------- 3. 已登录：Layout 渲染 ----------
    await goto(cdp, '/', 1900)
    const authed = await cdp.evaluate(`(() => ({
      hasLayout: !!document.querySelector('.h-dvh'),
      hasLogin: (document.querySelector('h2') || {}).textContent?.includes('登录') || false,
      navLinks: [...document.querySelectorAll('header nav a')].map((a) => a.textContent.trim()),
      backendText: [...document.querySelectorAll('header span')].map((s) => s.textContent.trim()).find((t) => t.includes('后端')) || '',
      hasProbe: typeof window.__fayeApi === 'object',
    }))()`)
    record(
      '登录后 → 渲染 Layout（三分支走对）',
      authed.hasLayout === true && authed.navLinks.length === 2,
      `hasLayout=${authed.hasLayout} nav=${JSON.stringify(authed.navLinks)}`,
    )
    record('Layout 里 BackendStatus 显示「后端正常」', authed.backendText.includes('后端正常'), `"${authed.backendText}"`)
    record('DEV 探针 window.__fayeApi 存在', authed.hasProbe === true)

    // ---------- 4. 真实数据：listMedia / getAuthStatus ----------
    const media = await cdp.evaluate(`(async () => {
      const res = await window.__fayeApi.listMedia();
      return { total: res.total, firstId: res.items[0] && res.items[0].id, ids: res.items.map((m) => m.id) };
    })()`)
    record(
      'window.__fayeApi.listMedia() 返回真实数据且与后端一致',
      media.total === backendTotal && backendTotal > 0,
      `前端 total=${media.total} / 后端 total=${backendTotal} / ids=${JSON.stringify(media.ids)}`,
    )

    const status = await cdp.evaluate(`window.__fayeApi.getAuthStatus().then((s) => s)`)
    record(
      'getAuthStatus().authenticated === true',
      status.authenticated === true,
      `authenticated=${status.authenticated} username=${status.username}`,
    )

    // ---------- 5. openProgressStream 真连一次 ----------
    const mediaId = media.firstId
    const sse = await cdp.evaluate(`(async () => {
      const frames = [];
      let errored = false;
      const cancel = window.__fayeApi.openProgressStream(
        ${mediaId},
        (e) => frames.push(e),
        () => { errored = true; },
      );
      await new Promise((r) => setTimeout(r, 3000));
      cancel();
      return { frames: frames.length, first: frames[0] || null, errored };
    })()`)
    record(
      `openProgressStream(${mediaId}) 真连并收到帧`,
      sse.frames >= 1 && sse.first && sse.first.media_id === mediaId,
      `frames=${sse.frames} first=${JSON.stringify(sse.first)} errored=${sse.errored}`,
    )

    // ---------- 结论 ----------
    const failed = results.filter((r) => !r.ok)
    console.log(`\n===== 结果：${results.length - failed.length}/${results.length} 通过 =====`)
    if (failed.length) {
      console.log('失败项：')
      for (const f of failed) console.log(`  - ${f.name}`)
    }
    process.exitCode = failed.length ? 1 : 0
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
    await sleep(300)
    try {
      rmSync(profile, { recursive: true, force: true })
    } catch {
      /* 忽略 */
    }
  }
}

main().catch((err) => {
  console.error('验证脚本异常：', err)
  process.exitCode = 1
})

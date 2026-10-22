/** v2 站点 Logo 接入验证（柚子龙吉祥物，真实渲染）。
 *
 * 覆盖：
 *   1. 五个静态资产（favicon.ico / favicon-32/16.png / apple-touch-icon.png / logo.png）不登录也 200
 *   2. index.html 里的 icon / apple-touch-icon link 齐全
 *   3. 登录后真实页面：页眉出现 img[src="/logo.png"]，尺寸正确（移动 24 / 桌面 28），
 *      且在 Logo 之前没有其它图片（保证是「标题前面」）
 *   4. 页眉不因加图产生横向溢出（桌面 1280 / 手机 375 两种视口）
 *   5. 截图页眉区块，人工复核（Logo 无底部文字、抠图干净）
 *
 * 依赖：本机 Chrome + 已启动后端 + Node 22（内置 WebSocket）。
 * 用法：node scripts/verify_logo.mjs [--url http://127.0.0.1:8010] [--port 9341]
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

const BASE = arg('--url', 'http://127.0.0.1:8010').replace(/\/$/, '')
const PORT = Number(arg('--port', '9341'))
const CHROME = arg('--chrome', 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe')
const SHOT = arg('--out', 'D:\\code\\FayeLong\\brand-logo\\mascot\\_chk')

patchFetchForSession(BASE)

let failures = 0
const record = (name, ok, detail = '') => {
  if (!ok) failures += 1
  console.log(`${ok ? 'OK  ' : 'FAIL'}  ${name}${detail ? `  —— ${detail}` : ''}`)
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

  close() {
    try {
      this.ws.close()
    } catch {
      /* 忽略 */
    }
  }
}

async function goto(cdp, path, wait = 2200) {
  await cdp.send('Page.navigate', { url: `${BASE}${path}` })
  await sleep(wait)
}

// --------------------------- 1. 静态资产（不登录） ---------------------------

const ASSETS = ['/favicon.ico', '/favicon-32.png', '/favicon-16.png', '/apple-touch-icon.png', '/logo.png']
console.log(`目标：${BASE}\n`)
for (const p of ASSETS) {
  const res = await fetch(`${BASE}${p}`)
  const len = (await res.arrayBuffer()).byteLength
  const ok = res.ok && len > 500
  record(`资产 ${p}`, ok, `HTTP ${res.status} · ${len}B`)
}

const idx = await (await fetch(`${BASE}/`)).text()
const iconLinks = (idx.match(/<link rel="icon"/g) || []).length
const hasApple = idx.includes('apple-touch-icon')
record('index.html 图标声明', iconLinks >= 3 && hasApple, `icon link ${iconLinks} 条 · apple-touch ${hasApple}`)

// --------------------------- 2. 真机页眉 ---------------------------

const profile = mkdtempSync(join(tmpdir(), 'fayelong-logo-'))
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
  await installSessionInBrowser(cdp, BASE)

  for (const vp of [
    { name: '桌面 1280', width: 1280, height: 800, dsf: 1, mobile: false },
    { name: '手机 375', width: 375, height: 667, dsf: 2, mobile: true },
  ]) {
    await cdp.send('Emulation.setDeviceMetricsOverride', {
      width: vp.width,
      height: vp.height,
      deviceScaleFactor: vp.dsf,
      mobile: vp.mobile,
    })
    await goto(cdp, '/')
    const probe = await cdp.evaluate(`(async () => {
      const img = document.querySelector('header img[src="/logo.png"]')
      if (img && !img.complete) { try { await img.decode() } catch {} }
      const h1 = document.querySelector('header h1')
      const visible = h1 ? [...h1.querySelectorAll('span')].filter((s) => s.offsetParent !== null).map((s) => s.textContent.trim()) : []
      const r = img ? img.getBoundingClientRect() : null
      const hr = document.querySelector('header').getBoundingClientRect()
      const container = img ? img.parentElement : null
      const before = img && container ? [...container.children].indexOf(img) : -1
      const offenders = [...document.querySelectorAll('body *')]
        .map((el) => ({ el, r: el.getBoundingClientRect() }))
        .filter((x) => x.r.width > 0 && x.r.right > window.innerWidth + 1)
        .slice(0, 5)
        .map((x) => x.el.tagName.toLowerCase())
      return {
        hasImg: !!img,
        loaded: img ? img.complete && img.naturalWidth > 0 : false,
        natural: img ? [img.naturalWidth, img.naturalHeight] : null,
        shown: r ? [Math.round(r.width), Math.round(r.height)] : null,
        firstChildIsImg: before === 0,
        title: visible.join(' | ') || (h1 ? h1.textContent.trim() : ''),
        overflow: document.documentElement.scrollWidth <= window.innerWidth + 1,
        offenders,
        headerRect: [Math.round(hr.left), Math.round(hr.top), Math.round(hr.width), Math.round(hr.height)],
      }
    })()`)
    const expect = vp.mobile ? 24 : 28
    record(
      `${vp.name} 页眉出现 Logo`,
      probe.hasImg && probe.loaded && probe.firstChildIsImg,
      `加载 ${probe.loaded} · 原始 ${probe.natural} · 是标题前第一个元素 ${probe.firstChildIsImg}`,
    )
    record(
      `${vp.name} Logo 尺寸 ${expect}px`,
      probe.shown && Math.abs(probe.shown[0] - expect) <= 1 && Math.abs(probe.shown[1] - expect) <= 1,
      `实际 ${probe.shown}`,
    )
    record(`${vp.name} 标题未被改动`, probe.title.startsWith('FayeLong'), `「${probe.title}」`)
    record(`${vp.name} 无横向溢出`, probe.overflow, probe.overflow ? '' : `越界：${probe.offenders.join(', ')}`)

    // 截页眉区块，人工复核
    const [hx, hy, hw, hh] = probe.headerRect
    const shot = await cdp.send('Page.captureScreenshot', {
      format: 'png',
      clip: { x: hx, y: hy, width: hw, height: Math.max(48, hh), scale: 2 },
    })
    const { writeFileSync } = await import('node:fs')
    const file = join(SHOT, `header-${vp.mobile ? 'mobile' : 'desktop'}.png`)
    writeFileSync(file, Buffer.from(shot.data, 'base64'))
    console.log(`      截图 → ${file}`)
  }
} catch (err) {
  failures += 1
  console.log('FAIL  ', err.message)
} finally {
  if (cdp) cdp.close()
  try {
    chrome.kill()
  } catch {
    /* 忽略 */
  }
  try {
    rmSync(profile, { recursive: true, force: true })
  } catch {
    /* Windows 上偶发被占用，留着也无妨 */
  }
}

console.log(failures === 0 ? '\n全部通过 ✓' : `\n${failures} 项未通过 ✗`)
process.exit(failures === 0 ? 0 : 1)

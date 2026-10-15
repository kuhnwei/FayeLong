/** 移动端自适应验证（CDP 模拟手机 / iPad 视口，真实渲染 + 真实点击）。
 *
 * 为什么不能靠「看起来对了」：移动端布局出问题的方式是横向溢出、内容被裁掉、
 * 触摸目标太小 —— 这些在桌面浏览器里全都看不见。所以这里用 CDP 把视口真的切成
 * 手机尺寸，再逐条量。
 *
 * 覆盖三种典型视口：
 *   iPhone SE  375×667   —— 目前仍在用的最窄主流机型，是布局的下限
 *   iPhone 14  393×852   —— 当前主流尺寸
 *   iPad Air   820×1180  —— 平板竖屏
 *
 * 每个视口检查：
 *   1. 登录页：能正常渲染、无横向溢出
 *   2. 媒体库 / 生词本 / 生词练习：无横向溢出
 *   3. 学习页：无横向溢出、整页无纵向滚动条
 *   4. 学习页：听写输入框与「下一句」仍在视口内（没被裁掉）—— 这是小屏上最容易坏的点
 *   5. 学习页：宫格格子与翻页按钮的触摸目标 ≥ 32px
 *   6. 学习页：正文字号落在合理区间（14–50px），没有小到看不清也没大到溢出
 *   7. 整段播放条：不溢出、控件都在
 *
 * 依赖：本机 Chrome + 已启动的后端 + Node 22。
 * 用法（项目根目录）：
 *   node scripts/verify_mobile.mjs [--url http://127.0.0.1:8000] [--media 3] [--port 9337]
 */

import { spawn } from 'node:child_process'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { installSessionInBrowser } from './lib/session.mjs'

const argv = process.argv.slice(2)
const arg = (name, fallback) => {
  const i = argv.indexOf(name)
  return i >= 0 && argv[i + 1] ? argv[i + 1] : fallback
}

const BASE = arg('--url', 'http://127.0.0.1:8000').replace(/\/$/, '')
const MEDIA_ID = Number(arg('--media', '3'))
const PORT = Number(arg('--port', '9337'))
const CHROME = arg('--chrome', 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe')

/** 触摸目标的最小边长（Apple HIG 建议 44，这里取 32 作为「可用」下限） */
const MIN_TAP = 32

const VIEWPORTS = [
  { name: 'iPhone SE 375x667', width: 375, height: 667, dsf: 2 },
  { name: 'iPhone 14 393x852', width: 393, height: 852, dsf: 3 },
  { name: 'iPad Air 820x1180', width: 820, height: 1180, dsf: 2 },
]

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
  if (window.__mHelpers) return;
  window.__mHelpers = true;
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
  Object.assign(window, { byText, sleep, waitFor });
  /** 横向溢出检测：返回文档 scrollWidth 与超出视口的元素（最多 5 个，便于定位） */
  window.hOverflow = () => {
    const inner = window.innerWidth;
    const offenders = [...document.querySelectorAll('body *')]
      .map((el) => ({ el, r: el.getBoundingClientRect() }))
      .filter((x) => x.r.width > 0 && x.r.right > inner + 1)
      .slice(0, 5)
      .map((x) => x.el.tagName.toLowerCase() + (x.el.className ? '.' + String(x.el.className).split(' ')[0] : ''));
    return { scrollW: document.documentElement.scrollWidth, inner, offenders };
  };
  /** 某个元素是否完整落在视口内 */
  window.inViewport = (el) => {
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return {
      top: Math.round(r.top), bottom: Math.round(r.bottom),
      left: Math.round(r.left), right: Math.round(r.right),
      w: Math.round(r.width), h: Math.round(r.height),
      fits: r.left >= -1 && r.right <= window.innerWidth + 1,
      fullyVisible: r.top >= -1 && r.bottom <= window.innerHeight + 1,
    };
  };
  window.rectOf = (el) => window.inViewport(el);
  window.resetScroll = () => {
    document.querySelector('main')?.scrollTo(0, 0);
    window.scrollTo(0, 0);
  };
})();
`

// --------------------------- 单项检查 ---------------------------

/** 横向溢出一致性检查 */
async function checkNoHOverflow(cdp, label) {
  const info = await cdp.evaluate(`window.hOverflow()`)
  record(
    `${label} 无横向溢出`,
    info.scrollW <= info.inner + 1,
    info.scrollW <= info.inner + 1
      ? `内容 ${info.scrollW}px / 视口 ${info.inner}px`
      : `内容 ${info.scrollW}px > 视口 ${info.inner}px；越界元素：${info.offenders.join(', ')}`,
  )
}

async function goto(cdp, path, wait = 2200) {
  await cdp.send('Page.navigate', { url: `${BASE}${path}` })
  await sleep(wait)
  await cdp.evaluate(HELPERS)
}

// --------------------------- 主流程 ---------------------------

async function main() {
  console.log(`目标：${BASE}   媒体：#${MEDIA_ID}\n`)

  const profile = mkdtempSync(join(tmpdir(), 'fayelong-mobile-'))
  const chrome = spawn(
    CHROME,
    [
      '--headless=new',
      `--remote-debugging-port=${PORT}`,
      `--user-data-dir=${profile}`,
      '--no-first-run',
      '--no-default-browser-check',
      '--disable-gpu',
      '--autoplay-policy=no-user-gesture-required',
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
    await cdp.send('Emulation.setTouchEmulationEnabled', { enabled: true, maxTouchPoints: 5 })

    for (const vp of VIEWPORTS) {
      console.log(`\n================ ${vp.name} ================`)
      await cdp.send('Emulation.setDeviceMetricsOverride', {
        width: vp.width,
        height: vp.height,
        deviceScaleFactor: vp.dsf,
        mobile: true,
      })

      // ---------- 1. 未登录：登录页 ----------
      await cdp.send('Network.clearBrowserCookies')
      await goto(cdp, '/', 1800)
      const loginProbe = await cdp.evaluate(`(() => ({
        pw: document.querySelectorAll('input[type=password]').length,
        btn: !!byText('登录') || !!byText('创建并进入'),
        ov: window.hOverflow(),
      }))()`)
      record(
        `${vp.name} 登录页可用且不溢出`,
        loginProbe.pw >= 1 && loginProbe.btn && loginProbe.ov.scrollW <= loginProbe.ov.inner + 1,
        `密码框 ${loginProbe.pw} / 提交按钮 ${loginProbe.btn} / 宽 ${loginProbe.ov.scrollW}≤${loginProbe.ov.inner}`,
      )

      // ---------- 建立会话，后续都在登录态下检查 ----------
      await installSessionInBrowser(cdp, BASE)

      // ---------- 2. 各页面横向溢出 ----------
      await goto(cdp, '/')
      await checkNoHOverflow(cdp, `${vp.name} 媒体库`)

      await goto(cdp, '/vocab')
      await checkNoHOverflow(cdp, `${vp.name} 生词本`)

      await goto(cdp, '/vocab/practice')
      await checkNoHOverflow(cdp, `${vp.name} 生词练习`)

      // ---------- 3. 学习页 ----------
      await goto(cdp, `/study/${MEDIA_ID}`, 2600)
      await checkNoHOverflow(cdp, `${vp.name} 学习页`)

      const scroll = await cdp.evaluate(`(() => ({
        scrollH: document.documentElement.scrollHeight,
        inner: window.innerHeight,
        mainScrollH: (() => { const m = document.querySelector('main'); return m ? m.scrollHeight : 0; })(),
      }))()`)
      record(
        `${vp.name} 学习页无纵向滚动条`,
        scroll.scrollH <= scroll.inner + 2,
        `文档 ${scroll.scrollH}px / 视口 ${scroll.inner}px`,
      )

      // 关键：小屏上最容易坏的就是「听写框 / 翻页按钮被挤出视口」
      const critical = await cdp.evaluate(`(() => {
        const ta = document.querySelector('[data-testid="dictation-input"]');
        const next = byText('下一句');
        const grid = document.querySelector('[data-testid="sentence-grid"]');
        return {
          ta: window.rectOf(ta),
          next: window.rectOf(next),
          grid: window.rectOf(grid),
          inner: window.innerHeight,
        };
      })()`)
      const criticalOk =
        critical.ta?.fullyVisible && critical.next?.fullyVisible && critical.grid?.fullyVisible
      record(
        `${vp.name} 听写框 / 翻页 / 宫格都在视口内`,
        Boolean(criticalOk),
        criticalOk
          ? `听写框底 ${critical.ta.bottom}、下一句底 ${critical.next.bottom}、宫格底 ${critical.grid.bottom}（视口 ${critical.inner}）`
          : `听写框底 ${critical.ta?.bottom}、下一句 ${critical.next?.bottom}、宫格 ${critical.grid?.bottom}（视口 ${critical.inner}）`,
      )

      // ---------- 4. 触摸目标 ----------
      const taps = await cdp.evaluate(`(() => {
        const cells = [...document.querySelectorAll('[data-testid="sentence-grid"] button')];
        const nav = [...document.querySelectorAll('header a')];
        const measure = (el) => { const r = el.getBoundingClientRect(); return { w: Math.round(r.width), h: Math.round(r.height) }; };
        const cellRects = cells.map(measure);
        const navRects = nav.map(measure);
        const next = byText('下一句');
        return {
          cellMin: cellRects.length ? Math.min(...cellRects.map((c) => Math.min(c.w, c.h))) : 0,
          navMin: navRects.length ? Math.min(...navRects.map((c) => Math.min(c.w, c.h))) : 0,
          next: next ? measure(next) : null,
        };
      })()`)
      record(
        `${vp.name} 宫格触摸目标 ≥ ${MIN_TAP}px`,
        taps.cellMin >= MIN_TAP,
        `最小边 ${taps.cellMin}px`,
      )
      record(
        `${vp.name} 顶部导航触摸目标 ≥ ${MIN_TAP}px`,
        taps.navMin >= MIN_TAP,
        `最小边 ${taps.navMin}px`,
      )

      // ---------- 5. 正文字号 ----------
      await cdp.evaluate(`(() => { const b = byText('显示原文'); if (b) b.click(); return true; })()`)
      await sleep(400)
      const font = await cdp.evaluate(`(() => {
        const p = document.querySelector('[data-testid="sentence-text"]');
        if (!p) return null;
        const r = p.getBoundingClientRect();
        return { size: parseFloat(getComputedStyle(p).fontSize), w: Math.round(r.width), fits: r.right <= window.innerWidth + 1 };
      })()`)
      record(
        `${vp.name} 正文字号合理且不溢出`,
        Boolean(font) && font.size >= 14 && font.size <= 50 && font.fits,
        font ? `${font.size}px，块宽 ${font.w}px` : '未渲染正文',
      )

      // ---------- 6. 播放条 ----------
      // 用 data-testid 定位：学习页自己也有一个隐藏的 <audio>（句子播放器），
      // 直接找 audio 会抓到它，所以必须精确定位到播放条容器
      await cdp.evaluate(
        `(() => { const b = document.querySelector('[data-testid="open-player"]'); if (b) b.click(); return true; })()`,
      )
      await sleep(1000)
      const bar = await cdp.evaluate(`(() => {
        const barEl = document.querySelector('[data-testid="player-bar"]');
        if (!barEl) return null;
        const r = barEl.getBoundingClientRect();
        const range = barEl.querySelector('input[type=range]');
        const rate = barEl.querySelector('select');
        return {
          w: Math.round(r.width), bottom: Math.round(r.bottom), inner: window.innerHeight,
          rangeW: range ? Math.round(range.getBoundingClientRect().width) : 0,
          hasRate: !!rate,
          overflowW: barEl.scrollWidth,
        };
      })()`)
      record(
        `${vp.name} 播放条不溢出且进度条可用`,
        Boolean(bar) && bar.overflowW <= bar.w + 1 && bar.rangeW >= 40 && bar.hasRate,
        bar
          ? `宽 ${bar.w}px、进度条 ${bar.rangeW}px、语速可选 ${bar.hasRate}`
          : '未出现播放条',
      )

      // 关掉播放器，避免影响下一个视口
      await cdp.evaluate(`(() => {
        const barEl = document.querySelector('[data-testid="player-bar"]');
        if (!barEl) return true;
        const buttons = [...barEl.querySelectorAll('button')];
        buttons[buttons.length - 1].click();
        return true;
      })()`)
      await sleep(300)
    }
  } finally {
    // 清理必须「尽力而为」：任一步抛错都不能让 Chrome 变成孤儿进程，
    // 否则未关闭的 WebSocket 会一直吊着 Node 的事件循环，脚本永远不退出。
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

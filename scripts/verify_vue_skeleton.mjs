/** Vue 骨架验证（P1 Round A）：真实无头 Chrome + CDP，量结构与布局，不靠肉眼。
 *
 * 覆盖：
 *   1. 外壳是 `h-dvh` 三段式（header shrink-0 / main flex-1 min-h-0 overflow-y-auto / footer shrink-0）且 overflow-hidden
 *   2. 4 条路由逐个可访问、能空转、无页面脚本错误；`*` 兜底重定向到 `/`
 *   3. 375px 宽下无横向滚动、顶部内容没被顶出
 *   4. 导航高亮逻辑（`/` 高亮「媒体库」、`/vocab*` 高亮「生词本」）
 *
 * 依赖：Node 22（内置 WebSocket）+ 本机 Chrome + 已启动 `frontend-vue` dev（默认 5174）。
 * 用法（项目根）：node scripts/verify_vue_skeleton.mjs [--url http://localhost:5174] [--port 9340]
 *
 * ⚠️ 历史坑：Chrome 必须与测试同一条命令内「启动→测试→收尾」；每次换新 --user-data-dir；
 *    CDP 类必须 close() + finally 逐项 try/catch，否则 Chrome 成孤儿、脚本永不退出。
 */

import { spawn } from 'node:child_process'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const argv = process.argv.slice(2)
const arg = (name, fallback) => {
  const i = argv.indexOf(name)
  return i >= 0 && argv[i + 1] ? argv[i + 1] : fallback
}

const BASE = arg('--url', 'http://localhost:5174').replace(/\/$/, '')
const PORT = Number(arg('--port', '9340'))
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

async function goto(cdp, path, wait = 900) {
  await cdp.send('Page.navigate', { url: `${BASE}${path}` })
  await sleep(wait)
}

async function main() {
  console.log(`目标：${BASE}\n`)
  const profile = mkdtempSync(join(tmpdir(), 'fayelong-vue-'))
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
    // 收集页面脚本错误（每次导航前注入）
    await cdp.send('Page.addScriptToEvaluateOnNewDocument', {
      source:
        "window.__errs=[];" +
        "window.addEventListener('error',e=>window.__errs.push(String(e.message)));" +
        "window.addEventListener('unhandledrejection',e=>window.__errs.push('rej:'+String(e.reason)));",
    })

    // ================= 桌面视口：结构 + 路由 =================
    await cdp.send('Emulation.setDeviceMetricsOverride', {
      width: 1280,
      height: 800,
      deviceScaleFactor: 1,
      mobile: false,
    })

    await goto(cdp, '/', 1200)
    const shell = await cdp.evaluate(`(() => {
      const el = document.querySelector('.h-dvh');
      if (!el) return { found: false };
      const cs = getComputedStyle(el);
      const header = el.querySelector(':scope > header');
      const main = el.querySelector(':scope > main');
      const footer = el.querySelector(':scope > footer');
      const cls = (n) => (n ? [...n.classList] : null);
      const hcs = header ? getComputedStyle(header) : null;
      const mcs = main ? getComputedStyle(main) : null;
      const fcs = footer ? getComputedStyle(footer) : null;
      return {
        found: true,
        display: cs.display,
        direction: cs.flexDirection,
        overflow: cs.overflow,
        height: Math.round(el.getBoundingClientRect().height),
        innerH: window.innerHeight,
        headerCls: cls(header),
        mainCls: cls(main),
        footerCls: cls(footer),
        headerShrink: hcs && hcs.flexShrink,
        mainGrow: mcs && mcs.flexGrow,
        mainMinH: mcs && mcs.minHeight,
        mainOverflowY: mcs && mcs.overflowY,
        footerShrink: fcs && fcs.flexShrink,
        headerTop: header ? Math.round(header.getBoundingClientRect().top) : null,
        mainBottom: main ? Math.round(main.getBoundingClientRect().bottom) : null,
        footerBottom: footer ? Math.round(footer.getBoundingClientRect().bottom) : null,
      };
    })()`)

    record('外壳存在 .h-dvh', shell.found === true)
    record(
      '外壳 = flex / column / overflow-hidden',
      shell.display === 'flex' && shell.direction === 'column' && shell.overflow === 'hidden',
      `display=${shell.display} direction=${shell.direction} overflow=${shell.overflow}`,
    )
    record(
      '三段式：header shrink-0 / main flex-1 min-h-0 overflow-y-auto / footer shrink-0',
      shell.headerShrink === '0' &&
        shell.mainGrow === '1' &&
        shell.mainMinH === '0px' &&
        shell.mainOverflowY === 'auto' &&
        shell.footerShrink === '0',
      `header.flexShrink=${shell.headerShrink} main.flexGrow=${shell.mainGrow} main.minHeight=${shell.mainMinH} main.overflowY=${shell.mainOverflowY} footer.flexShrink=${shell.footerShrink}`,
    )
    record(
      '外壳高度 = 视口高度（h-dvh 生效）',
      Math.abs(shell.height - shell.innerH) <= 1,
      `shell=${shell.height}px innerH=${shell.innerH}px`,
    )
    record(
      '顶部内容没被顶出（header.top≈0、footer 底部不超视口）',
      shell.headerTop >= -1 && shell.footerBottom <= shell.innerH + 1,
      `header.top=${shell.headerTop} footer.bottom=${shell.footerBottom} innerH=${shell.innerH}`,
    )

    // 导航高亮：/ 应该高亮「媒体库」（bg-slate-900）
    const navHome = await cdp.evaluate(`(() => {
      const links = [...document.querySelectorAll('header nav a')];
      return links.map((a) => ({ text: a.textContent.trim(), active: a.classList.contains('bg-slate-900') }));
    })()`)
    record(
      '/ 高亮「媒体库」',
      navHome.length === 2 && navHome[0].text === '媒体库' && navHome[0].active && !navHome[1].active,
      JSON.stringify(navHome),
    )

    // 4 条路由 + 兜底
    const routes = [
      { path: '/', expect: '媒体库' },
      { path: '/study/1', expect: '学习页' },
      { path: '/vocab', expect: '生词本' },
      { path: '/vocab/practice', expect: '生词练习' },
    ]
    for (const r of routes) {
      await goto(cdp, r.path, 900)
      const probe = await cdp.evaluate(`(() => ({
        title: (document.querySelector('main h2') || {}).textContent || '',
        errs: window.__errs || [],
        url: location.pathname,
      }))()`)
      record(
        `路由 ${r.path} 可渲染「${r.expect}」且无脚本错误`,
        probe.title.includes(r.expect) && probe.errs.length === 0,
        `h2="${probe.title.trim()}" path=${probe.url} errs=${JSON.stringify(probe.errs)}`,
      )
    }

    // 兜底：未知路径重定向到 /
    await goto(cdp, '/no-such-page', 900)
    const fallback = await cdp.evaluate(`(() => ({
      path: location.pathname,
      title: (document.querySelector('main h2') || {}).textContent || '',
    }))()`)
    record(
      '* 兜底重定向到 /',
      fallback.path === '/' && fallback.title.includes('媒体库'),
      `path=${fallback.path} h2="${fallback.title.trim()}"`,
    )

    // /vocab 应高亮「生词本」
    await goto(cdp, '/vocab', 700)
    const navVocab = await cdp.evaluate(`(() => {
      const links = [...document.querySelectorAll('header nav a')];
      return links.map((a) => ({ text: a.textContent.trim(), active: a.classList.contains('bg-slate-900') }));
    })()`)
    record(
      '/vocab 高亮「生词本」',
      navVocab[1] && navVocab[1].active && !navVocab[0].active,
      JSON.stringify(navVocab),
    )

    // ================= 375px 视口：无横向溢出、顶部不被顶出 =================
    await cdp.send('Emulation.setDeviceMetricsOverride', {
      width: 375,
      height: 667,
      deviceScaleFactor: 2,
      mobile: true,
    })
    for (const path of ['/', '/study/1', '/vocab', '/vocab/practice']) {
      await goto(cdp, path, 900)
      const m = await cdp.evaluate(`(() => {
        const inner = window.innerWidth;
        const offenders = [...document.querySelectorAll('body *')]
          .map((el) => ({ el, r: el.getBoundingClientRect() }))
          .filter((x) => x.r.width > 0 && x.r.right > inner + 1)
          .slice(0, 5)
          .map((x) => x.el.tagName.toLowerCase() + (x.el.className ? '.' + String(x.el.className).split(' ')[0] : ''));
        const header = document.querySelector('.h-dvh > header');
        const footer = document.querySelector('.h-dvh > footer');
        return {
          scrollW: document.documentElement.scrollWidth,
          inner,
          offenders,
          headerTop: header ? Math.round(header.getBoundingClientRect().top) : null,
          footerBottom: footer ? Math.round(footer.getBoundingClientRect().bottom) : null,
          innerH: window.innerHeight,
        };
      })()`)
      record(
        `375px ${path} 无横向滚动`,
        m.scrollW <= m.inner + 1,
        `内容 ${m.scrollW}px / 视口 ${m.inner}px${m.offenders.length ? `；越界：${m.offenders.join(', ')}` : ''}`,
      )
      record(
        `375px ${path} 顶部没被顶出`,
        m.headerTop >= -1 && m.footerBottom <= m.innerH + 1,
        `header.top=${m.headerTop} footer.bottom=${m.footerBottom} innerH=${m.innerH}`,
      )
    }

    // ================= 结论 =================
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

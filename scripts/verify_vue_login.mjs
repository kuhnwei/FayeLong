/** Vue 登录门禁验证（P1 Round D / P2-A）。**不碰旧 React 的 verify_v1_12.mjs**。
 *
 * 覆盖「copy」与「fresh」**两种形态**：
 *   —— 公共（backend 级）：
 *     A1 未登录调受保护接口 → 401
 *     A2 `/api/health` 保持公开
 *   —— copy 形态（已有账号的库）：
 *     A3 未登录打开站点 → 出现登录表单、**不出现应用导航**
 *     A4 密码错误 → 提示可读错误且仍停在登录页
 *     A5 密码正确 → 进入应用
 *     A6 账号已存在时重复初始化 → 409
 *     A7 刷新页面仍保持登录（cookie 持久）
 *     A8 退出登录 → 回到登录页；受保护接口重新 401
 *     A9/A9b/A10/A11 改密弹窗：结构 + 保存可用性 + 「密码已更新」+ 新密码可重登
 *   —— fresh 形态（空库）：
 *     S1 setup 形态：有「再输一次」字段 + 初始化文案（首次使用，先设置账号 / 创建并进入）
 *     S2 两次密码不一致 → 提示「两次输入的密码不一致」
 *     S3 建号成功 → 进入应用；之后 needs_setup=false
 *
 * ⚠️ **静默少测护栏**：`--mode` **省略 → 默认 copy + fresh 都跑**（历史失败模式：只跑一种，
 *    工具却「绿」）。`--mode copy|fresh` 才只跑单种；`--mode both` 显式跑两种。
 *    若 `--no-spawn-backend` 且要跑两种（两种要求后端在 copy/fresh 间切换）→ **直接报错退出**，
 *    绝不静默降级成只跑一种。
 *
 * ⚠️ 必须用 `--url http://localhost:5174`：本机 Vite dev 只绑 IPv6 `[::1]`，
 *    用 `127.0.0.1:5174` 会命中代理报 502。
 * ⚠️ Chrome 必须与测试同一条命令内「启动→测试→收尾」；每次换新 --user-data-dir。
 *
 * 默认自带隔离后端（`run_isolated_backend.py`，8010）+ dev（5174），用完收尾。
 * 用法（项目根）：
 *   node scripts/verify_vue_login.mjs                # 两种模式都跑（默认）
 *   node scripts/verify_vue_login.mjs --mode copy    # 只跑 copy
 */

import { execFileSync, spawn } from 'node:child_process'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { TEST_ACCOUNT, installSessionInBrowserByMint } from './lib/session.mjs'

const __dirname = dirname(fileURLToPath(import.meta.url))
const REPO = resolve(__dirname, '..')
const PYTHON = join(REPO, 'backend', '.venv', 'Scripts', 'python.exe')

const argv = process.argv.slice(2)
const hasFlag = (n) => argv.includes(n)
const arg = (name, fallback) => {
  const i = argv.indexOf(name)
  return i >= 0 && argv[i + 1] ? argv[i + 1] : fallback
}

const BASE = arg('--url', 'http://localhost:5174').replace(/\/$/, '')
const API_PORT = Number(arg('--api-port', '8010'))
const CDP_PORT = Number(arg('--cdp-port', '9342'))
const CHROME = arg('--chrome', 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe')
const SPAWN_BACKEND = !hasFlag('--no-spawn-backend')
const SPAWN_DEV = !hasFlag('--no-spawn-dev')
const ISO_BASE = arg('--iso-root', join(tmpdir(), 'fayelong-login-iso'))

// ---- 模式解析（默认 both = 两种都跑，堵住「静默少测」）----
const MODE_ARG = arg('--mode', 'both')
if (!['both', 'copy', 'fresh'].includes(MODE_ARG)) {
  console.error(`[verify_vue_login] 非法 --mode：${MODE_ARG}（可选 both | copy | fresh）`)
  process.exit(2)
}
const MODES = MODE_ARG === 'both' ? ['copy', 'fresh'] : [MODE_ARG]
if (MODES.length > 1 && !SPAWN_BACKEND) {
  console.error(
    '[verify_vue_login] 要跑两种模式需要后端在 copy/fresh 间切换，但指定了 --no-spawn-backend；' +
      '请改用 --mode copy / --mode fresh 明确指定单一模式（拒绝静默只跑一种）。',
  )
  process.exit(2)
}
console.log(`模式：${MODES.join(' + ')}${MODE_ARG === 'both' ? '（默认：两种都跑）' : ''}\n`)

const USER = TEST_ACCOUNT.username
const PASS = TEST_ACCOUNT.password
const NEW_PASS = 'newpassword1'

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
    await new Promise((res, rej) => {
      ws.addEventListener('open', res, { once: true })
      ws.addEventListener('error', rej, { once: true })
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
    return new Promise((res, rej) => {
      const timer = setTimeout(() => {
        if (this.pending.delete(id)) rej(new Error(`CDP 超时：${method}`))
      }, timeout)
      this.pending.set(id, {
        resolve: (v) => {
          clearTimeout(timer)
          res(v)
        },
        reject: (e) => {
          clearTimeout(timer)
          rej(e)
        },
      })
      this.ws.send(JSON.stringify({ id, method, params }))
    })
  }
  async evaluate(expression) {
    const res = await this.send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true })
    if (res.exceptionDetails) {
      throw new Error(res.exceptionDetails.exception?.description || '页面脚本异常')
    }
    return res.result.value
  }
  async waitValue(expression, timeout = 8000, step = 80) {
    const t0 = Date.now()
    for (;;) {
      let v = null
      try {
        v = await this.evaluate(expression)
      } catch {
        v = null
      }
      if (v) return v
      if (Date.now() - t0 > timeout) return null
      await sleep(step)
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

async function waitForJson(url, timeoutMs = 40000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    try {
      const r = await fetch(url)
      if (r.ok) return await r.json()
    } catch {
      /* 还没起来 */
    }
    await sleep(300)
  }
  throw new Error(`等待 ${url} 超时`)
}

function killTree(child) {
  if (!child || child.killed) return
  try {
    execFileSync('taskkill', ['/PID', String(child.pid), '/T', '/F'], { stdio: 'ignore' })
  } catch {
    try {
      child.kill()
    } catch {
      /* 忽略 */
    }
  }
}

const HELPERS = `
(() => {
  window.__setVal = (sel, val) => {
    const el = document.querySelector(sel);
    if (!el) return false;
    const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, val);
    el.dispatchEvent(new Event('input', { bubbles: true }));
    return true;
  };
  window.__submit = () => { const f = document.querySelector('form'); if (f) f.requestSubmit(); };
  window.__probe = () => ({
    hasUsername: !!document.querySelector('#username'),
    hasPassword: !!document.querySelector('#password'),
    hasConfirm: !!document.querySelector('#confirm'),
    submitText: (document.querySelector('form button[type=submit]') || {}).textContent?.trim() || '',
    subtitle: (document.querySelector('h1 + p, p') || {}).textContent?.trim() || '',
    h1: (document.querySelector('h1') || {}).textContent?.trim() || '',
    errorText: (document.querySelector('form .text-red-600') || {}).textContent?.trim() || '',
    hasLayout: !!document.querySelector('.h-dvh'),
    navLinks: [...document.querySelectorAll('header nav a')].map((a) => a.textContent.trim()),
    hasNotice: !!(document.body.innerText || '').includes('\\u8fd9\\u53f0\\u670d\\u52a1\\u5728\\u516c\\u7f51'),
    hasFooter: !!(document.body.innerText || '').includes('\\u5b66\\u4e60\\u6570\\u636e\\u4fdd\\u5b58\\u5728\\u4f60\\u81ea\\u5df1\\u7684\\u670d\\u52a1\\u5668\\u4e0a'),
  });
  window.__openMenu = () => {
    const acc = [...document.querySelectorAll('header button')].find((b) => b.textContent.includes('\\u25be'));
    if (!acc) return false;
    acc.click();
    return true;
  };
  window.__clickByText = (t) => {
    const b = [...document.querySelectorAll('button')].find((x) => x.textContent.trim() === t);
    if (!b) return false;
    b.click();
    return true;
  };
  window.__menuProbe = () => {
    const cur = document.querySelector('input[placeholder="\\u5f53\\u524d\\u5bc6\\u7801"]');
    const nxt = [...document.querySelectorAll('input')].find((i) => i.placeholder && i.placeholder.startsWith('\\u65b0\\u5bc6\\u7801'));
    const save = [...document.querySelectorAll('button')].find((x) => ['\\u4fdd\\u5b58', '\\u4fdd\\u5b58\\u4e2d\\u2026'].includes(x.textContent.trim()));
    const cancel = [...document.querySelectorAll('button')].find((x) => x.textContent.trim() === '\\u53d6\\u6d88');
    const msgEl = document.querySelector('p.bg-slate-50');
    return { hasCur: !!cur, hasNext: !!nxt, hasSave: !!save, saveDisabled: save ? save.disabled : null, hasCancel: !!cancel, msg: msgEl ? msgEl.textContent.trim() : '' };
  };
})();
`

async function goto(cdp, path) {
  await cdp.send('Page.navigate', { url: `${BASE}${path}` })
  // 等待页面渲染出「登录表单」或「应用外壳」之一（谓词等待，不用固定 sleep）
  await cdp.waitValue(`!!(document.querySelector('#username') || document.querySelector('.h-dvh'))`, 12000)
  await cdp.evaluate(HELPERS)
}

/** 跑一种模式的断言。 */
async function runMode(cdp, mode) {
  const say = (name, ok, detail = '') => record(`[${mode}] ${name}`, ok, detail)

  // 公共：backend 级（经 dev 代理）
  const noCookie = await fetch(`${BASE}/api/media`)
  say('A1 未登录调受保护接口 → 401', noCookie.status === 401, `GET /api/media → ${noCookie.status}`)
  const health = await fetch(`${BASE}/api/health`)
  say('A2 /api/health 保持公开', health.status === 200, `GET /api/health → ${health.status}`)

  await cdp.send('Network.clearBrowserCookies')
  await goto(cdp, '/', 1800)

  if (mode === 'fresh') {
    const p = await cdp.evaluate('window.__probe()')
    say(
      'S1 setup 形态：有「再输一次」字段 + 初始化文案',
      p.hasUsername && p.hasPassword && p.hasConfirm && p.submitText === '创建并进入' && p.subtitle.includes('首次使用') && p.hasNotice && p.hasFooter && !p.hasLayout,
      `confirm=${p.hasConfirm} btn="${p.submitText}" subtitle="${p.subtitle}" notice=${p.hasNotice}`,
    )

    await cdp.evaluate(`(() => {
      window.__setVal('#username', 'faye');
      window.__setVal('#password', 'password123');
      window.__setVal('#confirm', 'password999');
      window.__submit();
    })()`)
    await cdp.waitValue(`window.__probe().errorText.length > 0`, 5000)
    const mismatch = await cdp.evaluate('window.__probe()')
    say('S2 两次密码不一致 → 提示一致错误', mismatch.errorText.includes('两次输入的密码不一致') && !mismatch.hasLayout, `error="${mismatch.errorText}"`)

    await cdp.evaluate(`(() => {
      window.__setVal('#password', 'password123');
      window.__setVal('#confirm', 'password123');
      window.__submit();
    })()`)
    const entered = await cdp.waitValue(`window.__probe().hasLayout === true`, 12000)
    const done = await cdp.evaluate('window.__probe()')
    say('S3 建号成功 → 进入应用', !!entered && done.hasLayout === true && done.navLinks.length >= 2, `hasLayout=${done.hasLayout} nav=${JSON.stringify(done.navLinks)}`)
    const st = await (await fetch(`${BASE}/api/auth/status`)).json()
    say('S3 needs_setup 之后为 false', st.needs_setup === false, JSON.stringify(st))
    return
  }

  // ---- copy 模式 ----
  const anon = await cdp.evaluate('window.__probe()')
  say(
    'A3 未登录 → 登录表单出现、无应用导航',
    anon.hasUsername && anon.hasPassword && !anon.hasConfirm && anon.submitText === '登录' && !anon.hasLayout && anon.navLinks.length === 0,
    `btn="${anon.submitText}" hasLayout=${anon.hasLayout} nav=${anon.navLinks.length}`,
  )

  await cdp.evaluate(`(() => {
    window.__setVal('#username', ${JSON.stringify(USER)});
    window.__setVal('#password', 'definitely-wrong');
    window.__submit();
  })()`)
  await cdp.waitValue(`window.__probe().errorText.length > 0`, 6000)
  const bad = await cdp.evaluate('window.__probe()')
  say('A4 密码错误 → 可读错误且仍在登录页', bad.errorText.length > 0 && !bad.hasLayout, `error="${bad.errorText}"`)

  await cdp.evaluate(`(() => {
    window.__setVal('#password', ${JSON.stringify(PASS)});
    window.__submit();
  })()`)
  const okIn = await cdp.waitValue(`window.__probe().hasLayout === true`, 12000)
  const ok = await cdp.evaluate('window.__probe()')
  say('A5 密码正确 → 进入应用', !!okIn && ok.hasLayout === true && ok.navLinks.length >= 2, `hasLayout=${ok.hasLayout} nav=${JSON.stringify(ok.navLinks)}`)

  const dup = await fetch(`${BASE}/api/auth/setup`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: 'intruder', password: 'password123' }),
  })
  say('A6 账号已存在时重复初始化 → 409', dup.status === 409, `POST /api/auth/setup → ${dup.status}`)

  await cdp.send('Page.reload')
  // ⚠️ 刷新会换掉整个文档，脚本注入的 helper（window.__probe）随之消失。
  //    所以「跨导航的等待谓词」必须是**纯 DOM 判定**，不能依赖注入 helper：
  //    旧写法 `window.__probe().hasLayout === true` 在新文档里永远抛异常 → 12s 必然超时，
  //    只能靠「旧文档还没被换掉时抢跑」侥幸通过（flaky by construction）。
  //    `.h-dvh` 与 __probe 里 hasLayout 的判据保持一字不差。
  const afterReload = await cdp.waitValue(`(() => { try { return !!document.querySelector('.h-dvh'); } catch { return false; } })()`, 12000)
  await cdp.evaluate(HELPERS)
  const reloaded = await cdp.evaluate('window.__probe()')
  say('A7 刷新后仍保持登录', !!afterReload && reloaded.hasLayout === true, `hasLayout=${reloaded.hasLayout}`)

  await cdp.evaluate('window.__openMenu()')
  await cdp.waitValue(`!!document.querySelector('p.bg-slate-50, button')`, 2000)
  await cdp.evaluate(`window.__clickByText('退出登录')`)
  const outNow = await cdp.waitValue(`window.__probe().hasLayout === false && window.__probe().hasUsername === true`, 8000)
  const out = await cdp.evaluate('window.__probe()')
  say('A8 退出登录 → 回到登录页', !!outNow && out.hasLayout === false && out.hasUsername, `hasLayout=${out.hasLayout}`)
  const afterLogout = await fetch(`${BASE}/api/media`)
  say('A8 退出后受保护接口重新 401', afterLogout.status === 401, `GET /api/media → ${afterLogout.status}`)

  // A9–A11 改密弹窗
  await cdp.evaluate(`(() => {
    window.__setVal('#username', ${JSON.stringify(USER)});
    window.__setVal('#password', ${JSON.stringify(PASS)});
    window.__submit();
  })()`)
  const backIn = await cdp.waitValue(`window.__probe().hasLayout === true`, 12000)
  await cdp.evaluate(HELPERS)
  await cdp.evaluate('window.__openMenu()')
  await cdp.waitValue(`(() => { const bs = [...document.querySelectorAll('button')].map(b=>b.textContent.trim()); return bs.includes('修改密码'); })()`, 3000)
  await cdp.evaluate(`window.__clickByText('修改密码')`)
  const s1 = await cdp.waitValue(`window.__menuProbe().hasCur ? window.__menuProbe() : null`, 4000)
  say(
    'A9 改密弹窗：两输入 + 保存/取消，空时「保存」禁用',
    !!backIn && !!s1 && s1.hasCur && s1.hasNext && s1.hasSave && s1.hasCancel && s1.saveDisabled === true,
    JSON.stringify(s1),
  )

  await cdp.evaluate(`(() => {
    window.__setVal('input[placeholder="当前密码"]', ${JSON.stringify(PASS)});
    window.__setVal('input[placeholder^="新密码"]', ${JSON.stringify(NEW_PASS)});
  })()`)
  const s2 = await cdp.waitValue(`window.__menuProbe().saveDisabled === false ? window.__menuProbe() : null`, 4000)
  say('A9b 填好后「保存」可用', !!s2 && s2.saveDisabled === false, JSON.stringify(s2))

  await cdp.evaluate(`window.__clickByText('保存')`)
  const s3 = await cdp.waitValue(`window.__menuProbe().msg.includes('密码已更新') ? window.__menuProbe() : null`, 8000)
  say('A10 保存 → 提示「密码已更新」', !!s3 && s3.msg.includes('密码已更新'), `msg="${s3 ? s3.msg : ''}"`)

  await cdp.evaluate(`window.__clickByText('退出登录')`)
  await cdp.waitValue(`window.__probe().hasLayout === false`, 8000)
  await cdp.evaluate(`(() => {
    window.__setVal('#username', ${JSON.stringify(USER)});
    window.__setVal('#password', ${JSON.stringify(NEW_PASS)});
    window.__submit();
  })()`)
  const re = await cdp.waitValue(`window.__probe().hasLayout === true`, 12000)
  say('A11 用新密码重新登录成功', !!re, `hasLayout=${!!re}`)
}

async function startBackend(mode) {
  const root = `${ISO_BASE}-${mode}`
  try {
    rmSync(root, { recursive: true, force: true })
  } catch {
    /* 忽略 */
  }
  const child = spawn(
    PYTHON,
    ['scripts/run_isolated_backend.py', mode === 'fresh' ? '--fresh' : '--copy', '--port', String(API_PORT), '--root', root],
    { cwd: REPO, stdio: 'ignore' },
  )
  await waitForJson(`http://127.0.0.1:${API_PORT}/api/health`)
  return { child, root }
}

async function main() {
  console.log(`目标：${BASE}   API：${API_PORT}\n`)
  let dev = null
  let backend = null
  let backendRoot = null
  let cdp = null
  let chrome = null

  try {
    if (SPAWN_DEV) {
      dev = spawn('npm run dev', {
        cwd: join(REPO, 'frontend-vue'),
        env: { ...process.env, FAYELONG_API_TARGET: `http://127.0.0.1:${API_PORT}` },
        stdio: 'ignore',
        shell: true,
      })
    }

    const profile = mkdtempSync(join(tmpdir(), 'fayelong-login-'))
    chrome = spawn(
      CHROME,
      ['--headless=new', `--remote-debugging-port=${CDP_PORT}`, `--user-data-dir=${profile}`, '--no-first-run', '--no-default-browser-check', '--disable-gpu', 'about:blank'],
      { stdio: 'ignore' },
    )

    try {
      if (SPAWN_DEV) {
        const deadline = Date.now() + 40000
        for (;;) {
          try {
            if ((await fetch(`${BASE}/`)).ok) break
          } catch {
            /* 还没起来 */
          }
          if (Date.now() > deadline) throw new Error('等待 dev 就绪超时')
          await sleep(300)
        }
      }

      await waitForJson(`http://127.0.0.1:${CDP_PORT}/json/version`)
      const targets = await waitForJson(`http://127.0.0.1:${CDP_PORT}/json/list`)
      const page = targets.find((t) => t.type === 'page')
      if (!page) throw new Error('没有找到可用的页面目标')
      cdp = await CDP.connect(page.webSocketDebuggerUrl)
      await cdp.send('Page.enable')
      await cdp.send('Runtime.enable')
      await cdp.send('Network.enable')
      await cdp.send('Emulation.setDeviceMetricsOverride', { width: 1280, height: 800, deviceScaleFactor: 1, mobile: false })

      if (!SPAWN_BACKEND) {
        backendRoot = `${ISO_BASE}-${MODES[0]}`
      }

      for (const mode of MODES) {
        if (SPAWN_BACKEND) {
          const started = await startBackend(mode)
          backend = started.child
          backendRoot = started.root
          console.log(`--- 模式 ${mode}：隔离后端就绪（库 ${join(backendRoot, 'data', 'app.db')}）---`)
        }
        // copy 模式用铸牌建立会话（零写库）；fresh 模式故意保持未登录以测 setup 表单
        if (mode === 'copy') {
          await installSessionInBrowserByMint(cdp, BASE, join(backendRoot, 'data', 'app.db'))
        }
        await runMode(cdp, mode)
        if (SPAWN_BACKEND) {
          killTree(backend)
          backend = null
          await sleep(500)
        }
      }
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
    }
  } finally {
    killTree(dev)
    killTree(backend)
    for (const mode of ['copy', 'fresh']) {
      try {
        rmSync(`${ISO_BASE}-${mode}`, { recursive: true, force: true })
      } catch {
        /* 忽略 */
      }
    }
  }

  const failed = results.filter((r) => !r.ok)
  console.log(`\n===== 结果：${results.length - failed.length}/${results.length} 通过（模式 ${MODES.join(' + ')}）=====`)
  for (const f of failed) console.log(`  - FAIL ${f.name}`)
  process.exitCode = failed.length ? 1 : 0
}

main().catch((err) => {
  console.error('验证脚本异常：', err)
  process.exitCode = 1
})

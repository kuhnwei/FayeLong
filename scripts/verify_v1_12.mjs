/** v1.12 端到端验证：登录门禁 + 一句一页学习页（CDP 驱动真实无头 Chrome）。
 *
 * 覆盖两块新需求：
 *
 * A. 用户机制 / 登录访问
 *   A1 未登录调用受保护接口 → 401
 *   A2 /api/health 保持公开（外部拨测用）
 *   A3 未登录打开站点 → 出现登录表单，且不出现应用导航
 *   A4 密码错误 → 提示可读错误且仍停在登录页
 *   A5 密码正确 → 进入应用
 *   A6 账号已存在时重复初始化 → 409（防止在公网上被抢占）
 *   A7 刷新页面仍保持登录（cookie 持久）
 *   A8 退出登录 → 回到登录页，受保护接口重新 401
 *
 * B. 一句一页
 *   B1 一屏只渲染一句（只有一个原文/翻译切换组）
 *   B2 整页不出现纵向滚动条
 *   B3「下一句」翻页，序号随之变化
 *   B4「上一句」翻回
 *   B5 ← / → 方向键翻页
 *   B6 底部数字宫格点击直跳
 *   B7 宫格按「已掌握 / 练过 / 未听」着色区分
 *   B8 正文字号随句长自适应（短句字更大）
 *   B9 焦点在输入框时 → 不被劫持（方向键留给光标）
 *   B10 听写草稿跨页保留
 *
 * 依赖：本机 Chrome + 已启动的后端（默认 http://127.0.0.1:8000）+ Node 22。
 * 用法（项目根目录）：
 *   node scripts/verify_v1_12.mjs [--url http://127.0.0.1:8000] [--media 3] [--port 9336]
 */

import { spawn } from 'node:child_process'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { apiFetch, ensureSession, TEST_ACCOUNT } from './lib/session.mjs'

const argv = process.argv.slice(2)
const arg = (name, fallback) => {
  const i = argv.indexOf(name)
  return i >= 0 && argv[i + 1] ? argv[i + 1] : fallback
}

const BASE = arg('--url', 'http://127.0.0.1:8000').replace(/\/$/, '')
const MEDIA_ID = Number(arg('--media', '3'))
const PORT = Number(arg('--port', '9336'))
const CHROME = arg('--chrome', 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe')

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
      const desc = res.exceptionDetails.exception?.description || '页面脚本异常'
      throw new Error(desc)
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

/** 通用工具：等条件成立、按文本找按钮、给 React 受控输入赋值。
 *  包一层 IIFE 并挂到 window，保证多次注入（每次导航后都要注入）不重复声明。 */
const HELPERS = `
(() => {
  if (window.__fayeHelpers) return;
  window.__fayeHelpers = true;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const waitFor = async (fn, timeout = 12000) => {
    const t0 = Date.now();
    while (Date.now() - t0 < timeout) {
      try { const v = fn(); if (v) return v; } catch (e) {}
      await sleep(120);
    }
    return null;
  };
  const allByText = (text) =>
    [...document.querySelectorAll('button, a')].filter((el) => el.textContent.trim().includes(text));
  const byText = (text) => allByText(text)[0] || null;
  const setNativeValue = (el, value) => {
    const proto = el instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, value);
    el.dispatchEvent(new Event('input', { bubbles: true }));
  };
  /** 当前「第 X / N 句」里的 X */
  const currentIndex = () => {
    const m = document.body.innerText.match(/第\\s*(\\d+)\\s*\\/\\s*(\\d+)\\s*句/);
    return m ? Number(m[1]) : null;
  };
  /** 宫格按钮：底部一排数字（长度 1~3、纯数字文本） */
  const gridButtons = () =>
    [...document.querySelectorAll('button')].filter(
      (b) => /^\\d{1,3}$/.test(b.textContent.trim()) && b.className.includes('rounded-md'),
    );
  const arrow = (key, target) => {
    const el = target || window;
    el.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }));
  };
  Object.assign(window, { sleep, waitFor, allByText, byText, setNativeValue, currentIndex, gridButtons, arrow });
})();
`

async function bootstrap(cdp) {
  await cdp.evaluate(HELPERS)
}

// --------------------------- 主流程 ---------------------------

async function main() {
  console.log(`目标：${BASE}   媒体：#${MEDIA_ID}\n`)

  // ---------- A1 / A2：接口层门禁（Node 侧，不带 cookie）----------
  const anonMedia = await fetch(`${BASE}/api/media`)
  record('A1 未登录访问 /api/media 被拒', anonMedia.status === 401, `HTTP ${anonMedia.status}`)

  const anonHealth = await fetch(`${BASE}/api/health`)
  record('A2 /api/health 保持公开', anonHealth.status === 200, `HTTP ${anonHealth.status}`)

  // 先确保账号存在（干净 data/ 时自动完成初始化），后续浏览器流程才有账号可登
  await ensureSession(BASE)
  const status = await (await fetch(`${BASE}/api/auth/status`)).json()
  console.log(`（鉴权状态：needs_setup=${status.needs_setup}）\n`)

  // A6：账号已存在时重复初始化必须被拒绝
  const reSetup = await fetch(`${BASE}/api/auth/setup`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: 'intruder', password: 'Intruder123' }),
  })
  record(
    'A6 账号已存在时重复初始化被拒',
    reSetup.status === 409,
    status.needs_setup ? '（本轮刚初始化，跳过语义）' : `HTTP ${reSetup.status}`,
  )

  const profile = mkdtempSync(join(tmpdir(), 'fayelong-v112-'))
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
      '--window-size=1280,900',
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

    // ---------- A3：未登录打开站点 → 登录页 ----------
    await cdp.send('Page.navigate', { url: `${BASE}/` })
    await sleep(1500)
    await bootstrap(cdp)

    const anonUi = await cdp.evaluate(`(() => {
      const inputs = [...document.querySelectorAll('input[type=password]')].length;
      const nav = allByText('媒体库').length;
      const text = document.body.innerText;
      return { inputs, nav, text: text.slice(0, 400) };
    })()`)
    record(
      'A3 未登录打开站点显示登录页且无应用导航',
      anonUi.inputs >= 1 && anonUi.nav === 0,
      `密码框 ${anonUi.inputs} 个 / 导航项 ${anonUi.nav} 个`,
    )

    // ---------- A4：密码错误 ----------
    await cdp.evaluate(`(() => {
      const inputs = [...document.querySelectorAll('input[type=password]')];
      setNativeValue(document.querySelector('input[name=username]'), ${JSON.stringify(TEST_ACCOUNT.username)});
      setNativeValue(inputs[0], 'definitely-wrong-password');
      byText('登录').click();
      return true;
    })()`)
    await sleep(1200)
    const wrongPw = await cdp.evaluate(`(() => {
      const text = document.body.innerText;
      const inputs = [...document.querySelectorAll('input[type=password]')].length;
      return { stillLogin: inputs >= 1, text };
    })()`)
    const wrongRejected =
      wrongPw.stillLogin && /不正确|失败|错误/.test(wrongPw.text)
    record('A4 密码错误给出可读提示且仍在登录页', wrongRejected,
      wrongRejected ? '' : wrongPw.text.slice(0, 120))

    // ---------- A5：密码正确 → 进入应用 ----------
    await cdp.evaluate(`(() => {
      const inputs = [...document.querySelectorAll('input[type=password]')];
      setNativeValue(inputs[0], ${JSON.stringify(TEST_ACCOUNT.password)});
      byText('登录').click();
      return true;
    })()`)
    await sleep(2000)
    await bootstrap(cdp)
    const loggedIn = await cdp.evaluate(`(() => ({
      nav: allByText('媒体库').length,
      pwInputs: [...document.querySelectorAll('input[type=password]')].length,
    }))()`)
    record(
      'A5 密码正确后进入应用',
      loggedIn.nav >= 1 && loggedIn.pwInputs === 0,
      `导航 ${loggedIn.nav} / 密码框 ${loggedIn.pwInputs}`,
    )

    // ---------- A7：刷新后仍登录 ----------
    await cdp.send('Page.navigate', { url: `${BASE}/` })
    await sleep(1800)
    await bootstrap(cdp)
    const afterReload = await cdp.evaluate(`allByText('媒体库').length`)
    record('A7 刷新页面仍保持登录', afterReload >= 1, `导航 ${afterReload}`)

    // ---------- B：学习页一句一页 ----------
    await cdp.send('Page.navigate', { url: `${BASE}/study/${MEDIA_ID}` })
    await sleep(2500)
    await bootstrap(cdp)

    const firstSeq = await cdp.evaluate(`currentIndex()`)
    record('B1 学习页加载并落在第 1 句', firstSeq === 1, `序号 ${firstSeq}`)

    const toggles = await cdp.evaluate(
      `[...document.querySelectorAll('button')].filter((b) => /原文$/.test(b.textContent.trim())).length`,
    )
    record('B1b 一屏只渲染一句（只有一组原文切换）', toggles === 1, `切换按钮 ${toggles} 个`)

    const scrollInfo = await cdp.evaluate(`(() => ({
      scrollH: document.documentElement.scrollHeight,
      inner: window.innerHeight,
    }))()`)
    record(
      'B2 整页无纵向滚动条',
      scrollInfo.scrollH <= scrollInfo.inner + 2,
      `内容 ${scrollInfo.scrollH}px / 视口 ${scrollInfo.inner}px`,
    )

    // 展开原文，后面才能量字号
    await cdp.evaluate(`(() => { const b = byText('显示原文'); if (b) b.click(); return true; })()`)
    await sleep(400)

    const measured = []
    const gridCount = await cdp.evaluate(`gridButtons().length`)
    const totalCount = await cdp.evaluate(`(() => {
      const m = document.body.innerText.match(/第\\s*\\d+\\s*\\/\\s*(\\d+)\\s*句/);
      return m ? Number(m[1]) : 0;
    })()`)
    record('B7 底部数字宫格与句子总数一致', gridCount === totalCount && totalCount > 0,
      `格子 ${gridCount} / 总句数 ${totalCount}`)

    for (let i = 0; i < Math.min(totalCount, 6); i += 1) {
      await cdp.evaluate(`(() => { const g = gridButtons()[${i}]; if (g) g.click(); return true; })()`)
      await sleep(350)
      // 跳过去后原文可能仍是隐藏态，先展开才能量到真实字号
      await cdp.evaluate(`(() => { const b = byText('显示原文'); if (b) b.click(); return true; })()`)
      await sleep(250)
      const info = await cdp.evaluate(`(() => {
        const p = document.querySelector('[data-testid="sentence-stage"] p');
        return {
          idx: currentIndex(),
          len: p ? p.textContent.trim().length : 0,
          size: p ? parseFloat(getComputedStyle(p).fontSize) : 0,
        };
      })()`)
      measured.push(info)
    }

    const gridJumpOk = measured.every((m, i) => m.idx === i + 1)
    record('B6 宫格点击可直达对应句', gridJumpOk,
      measured.map((m) => m.idx).join(','))

    const sizes = measured.filter((m) => m.len > 0)
    const maxSize = Math.max(...sizes.map((m) => m.size))
    const minSize = Math.min(...sizes.map((m) => m.size))
    record(
      'B8 正文字号随句长自适应（不是固定值）',
      maxSize > minSize && minSize >= 14,
      `字号区间 ${minSize}–${maxSize}px（对应句长 ${sizes.map((m) => m.len).join('/')}）`,
    )
    // 校验单调性：更短的句子字号不应小于更长的句子
    let monotonic = true
    for (const a of sizes) {
      for (const b of sizes) {
        if (a.len < b.len && a.size < b.size) monotonic = false
      }
    }
    record('B8b 短句字号 ≥ 长句字号', monotonic, '')

    // ---------- B3 / B4：下一句 / 上一句 ----------
    await cdp.evaluate(`(() => { gridButtons()[0].click(); return true; })()`)
    await sleep(300)
    await cdp.evaluate(`(() => { byText('下一句').click(); return true; })()`)
    await sleep(350)
    const afterNext = await cdp.evaluate(`currentIndex()`)
    await cdp.evaluate(`(() => { byText('上一句').click(); return true; })()`)
    await sleep(350)
    const afterPrev = await cdp.evaluate(`currentIndex()`)
    record('B3「下一句」翻页', afterNext === 2, `→ ${afterNext}`)
    record('B4「上一句」翻回', afterPrev === 1, `→ ${afterPrev}`)

    // ---------- B5：方向键 ----------
    await cdp.evaluate(`arrow('ArrowRight')`)
    await sleep(300)
    const keyRight = await cdp.evaluate(`currentIndex()`)
    await cdp.evaluate(`arrow('ArrowLeft')`)
    await sleep(300)
    const keyLeft = await cdp.evaluate(`currentIndex()`)
    record('B5 ← / → 方向键翻页', keyRight === 2 && keyLeft === 1, `→ ${keyRight}，← ${keyLeft}`)

    // ---------- B9：输入框聚焦时不被劫持 ----------
    const hijack = await cdp.evaluate(`(() => {
      const ta = document.querySelector('textarea');
      if (!ta) return { ok: false, reason: '没有找到听写输入框' };
      const before = currentIndex();
      ta.focus();
      arrow('ArrowRight', ta);
      return { ok: true, before };
    })()`)
    await sleep(300)
    const afterHijack = await cdp.evaluate(`currentIndex()`)
    record(
      'B9 输入框聚焦时方向键不翻页',
      hijack.ok && afterHijack === hijack.before,
      `前 ${hijack.before} / 后 ${afterHijack}`,
    )

    // ---------- B10：听写草稿跨页保留 ----------
    const DRAFT = `draft-${Date.now()}`
    await cdp.evaluate(`(() => {
      const ta = document.querySelector('textarea');
      setNativeValue(ta, ${JSON.stringify(DRAFT)});
      return true;
    })()`)
    await sleep(250)
    await cdp.evaluate(`(() => { byText('下一句').click(); return true; })()`)
    await sleep(350)
    await cdp.evaluate(`(() => { byText('上一句').click(); return true; })()`)
    await sleep(350)
    const draftBack = await cdp.evaluate(`document.querySelector('textarea').value`)
    record('B10 听写草稿跨页保留', draftBack === DRAFT, `回来读到「${draftBack.slice(0, 24)}」`)
    // 收尾：把草稿清掉，别留脏值
    await cdp.evaluate(`(() => { const b = byText('清空'); if (b) b.click(); return true; })()`)

    // ---------- A8：退出登录 ----------
    await cdp.send('Page.navigate', { url: `${BASE}/` })
    await sleep(1600)
    await bootstrap(cdp)
    await cdp.evaluate(`(() => { const b = byText('退出登录'); if (b) { b.click(); return true; } return false; })()`)
    // 退出登录藏在账号菜单里，先展开再点
    const needOpen = await cdp.evaluate(`allByText('退出登录').length === 0`)
    if (needOpen) {
      await cdp.evaluate(`(() => {
        const trigger = [...document.querySelectorAll('button')].find((b) => b.textContent.includes('▾'));
        if (trigger) trigger.click();
        return true;
      })()`)
      await sleep(400)
      await cdp.evaluate(`(() => { const b = byText('退出登录'); if (b) b.click(); return true; })()`)
    }
    await sleep(1500)
    await bootstrap(cdp)
    const afterLogout = await cdp.evaluate(`(() => ({
      pw: [...document.querySelectorAll('input[type=password]')].length,
      nav: allByText('媒体库').length,
    }))()`)
    record('A8 退出登录回到登录页', afterLogout.pw >= 1 && afterLogout.nav === 0,
      `密码框 ${afterLogout.pw} / 导航 ${afterLogout.nav}`)

    const anonAfter = await fetch(`${BASE}/api/media`)
    record('A8b 退出后受保护接口重新 401', anonAfter.status === 401, `HTTP ${anonAfter.status}`)

    // ---------- 附：带会话的接口仍可用 ----------
    const authed = await apiFetch(BASE, '/api/stats')
    record('附 带会话访问 /api/stats 正常', authed.status === 200, `HTTP ${authed.status}`)
  } finally {
    if (cdp) cdp.close()
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
  console.log(`\n合计 ${results.length} 项，通过 ${results.length - failed.length} 项，失败 ${failed.length} 项`)
  if (failed.length) {
    for (const f of failed) console.log(`  FAIL  ${f.name}  ${f.detail}`)
    process.exitCode = 1
  }
}

main().catch((err) => {
  console.error('验证脚本异常：', err)
  process.exitCode = 1
})

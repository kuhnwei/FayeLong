/** P2-B 播放条验证（G2 用）。**P2-D 已落地：Group B 直接驱动真实学习页（不再用假宿主）。**
 *
 * 覆盖两组的**语义最小充分集**：
 *
 * Group A —— 整段播放条（PlayerBar + store）
 *   A1 登录态打开学习页 → 句子舞台与「整段播放」按钮可用
 *   A2 点「整段播放」→ `[data-testid=player-bar]` 出现；**恰好 1 个 `<audio>`，且由 PlayerBar 持有**（src = media.stream_url）
 *   A3 播放 → `audio.paused === false`
 *   A4 倍速：select 有 5 档（0.5/0.75/1/1.25/1.5），选 1.5 → `audio.playbackRate === 1.5`
 *   A5 进度：seek 到 5s → `audio.currentTime ≈ 5`
 *   A6 关闭：player-bar 消失
 *   A7 375px：player-bar 无横向溢出；外壳 `h-dvh` 三段式仍成立（header `shrink-0` / main `flex-1 min-h-0 overflow-y-auto` / 底条 `shrink-0`）
 *
 * Group B —— 句子级（`useClipPlayer`，**经真实学习页的按钮 / 进度条 / 翻页驱动**）
 *   B0 前置：无头下句子音频能播且 currentTime 前进（否则如实报「测不了」，不放宽断言）
 *   B1 单句循环：开循环 → 播到结尾 → 回卷且仍在播放
 *   B2 A-B 生效：设 A/B → 播过 B → 回到 A（且 A-B 仍处激活态）
 *   B3 ⭐ A-B 切句自动失效：切到**另一句** → A/B 被清空（按钮回到未设定态）
 *   B4 ⭐ A-B 同句重播**保留**：重播同一句（「重听本句」）→ A/B 仍在
 *   B5 句子 ↔ 整段 互斥（两个方向，均在真实 UI 上触发）
 *
 * ⏱️ **时序策略**：全部用**事件/状态谓词驱动的等待**（`waitValue(expr, timeout)` 轮询
 *    `currentTime` / `paused` / 按钮文案 / 舞台 `#N` 等**真实状态**），**不用固定 sleep 硬凑**。
 *    超时即判 FAIL（附观察到的实际值），绝不「放宽到必然通过」。
 *
 * ⚠️ **用法前提：8010 与 5174 必须空闲**。本脚本**自己起**隔离后端（8010）与 dev（5174）：
 *   - 若端口被占（例如别的实例还挂着），后端起不来 → 读 `--iso-root` 下的自建库时会报
 *     `unable to open database file`（或 dev 报 strictPort 冲突）。先停掉占用者再跑。
 *   - 想复用已在跑的服务：加 `--no-spawn-backend --no-spawn-dev`（此时由调用方保证
 *     dev 的 `/api` 代理指向 8010 的隔离后端）。
 * ⚠️ 一律用 `http://localhost:5174`（本机 Vite 只绑 IPv6，`127.0.0.1` 会 502）。
 * ⚠️ Chrome 必须与测试同一条命令内「启动→测试→收尾」；每次换新 --user-data-dir。
 *
 * 历史注记：P2-B 时代 Group B 曾靠 DEV 空壳组件 `src/dev/ClipHarness.vue` 暴露的
 * `window.__fayeClip` 驱动（当时学习页未实现）；P2-D 落地后已按 `TODO(P2-D)` 兑现删除，
 * 改为对真实学习页断言。
 *
 * 用法（项目根）：node scripts/verify_vue_player.mjs [--media 4]
 */

import { execFileSync, spawn } from 'node:child_process'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { installSessionInBrowserByMint } from './lib/session.mjs'

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
const CDP_PORT = Number(arg('--cdp-port', '9343'))
const MEDIA_ID = Number(arg('--media', '4'))
const CHROME = arg('--chrome', 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe')
const SPAWN_BACKEND = !hasFlag('--no-spawn-backend')
const SPAWN_DEV = !hasFlag('--no-spawn-dev')
const ISO_ROOT = arg('--iso-root', join(tmpdir(), 'fayelong-player-iso'))

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
  /** 轮询求值直到为真；超时返回 null（不抛），便于记录实际观察值。 */
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

/** 页内辅助：clip 音频选择器 / A-B 三态按钮 / mm:ss 解析 / 受控 range 赋值 / 谓词等待 */
const HELPERS = `
window.__sleep = (ms) => new Promise((r) => setTimeout(r, ms));
window.__CLIP = () => document.querySelector('audio.hidden');
window.__AB = () =>
  document.querySelector('button[title^="清除 A-B 循环"]') ||
  document.querySelector('button[title^="在当前位置设定 B 点"]') ||
  document.querySelector('button[title^="设定 A 点"]');
window.__parseSec = (s) => { const [m, sec] = String(s).split(':').map(Number); return (m || 0) * 60 + (sec || 0); };
window.__setRange = (el, val) => {
  const setS = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  setS.call(el, String(val));
  el.dispatchEvent(new Event('input', { bubbles: true }));
};
window.__stageIdx = () => (document.querySelector('[data-testid="sentence-stage-card"] span') || {}).textContent?.trim() || '';
`

async function main() {
  console.log(
    `目标：${BASE}   API：${API_PORT}   媒体：#${MEDIA_ID}   模式：${SPAWN_BACKEND ? '自起隔离后端 + dev' : '用既有服务'}\n`,
  )

  let backend = null
  let dev = null
  let cdp = null
  let chrome = null

  try {
    if (SPAWN_BACKEND) {
      backend = spawn(
        PYTHON,
        ['scripts/run_isolated_backend.py', '--copy', '--port', String(API_PORT), '--root', ISO_ROOT],
        { cwd: REPO, stdio: 'ignore' },
      )
    }
    await waitForJson(`http://127.0.0.1:${API_PORT}/api/health`)
    console.log(`[iso] 后端就绪：http://127.0.0.1:${API_PORT}（库：${join(ISO_ROOT, 'data', 'app.db')}）`)

    if (SPAWN_DEV) {
      dev = spawn('npm run dev', {
        cwd: join(REPO, 'frontend-vue'),
        env: { ...process.env, FAYELONG_API_TARGET: `http://127.0.0.1:${API_PORT}` },
        stdio: 'ignore',
        shell: true,
      })
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
    console.log(`[dev] 就绪：${BASE}\n`)

    const profile = mkdtempSync(join(tmpdir(), 'fayelong-player-'))
    chrome = spawn(
      CHROME,
      [
        '--headless=new',
        `--remote-debugging-port=${CDP_PORT}`,
        `--user-data-dir=${profile}`,
        '--no-first-run',
        '--no-default-browser-check',
        '--disable-gpu',
        '--autoplay-policy=no-user-gesture-required',
        'about:blank',
      ],
      { stdio: 'ignore' },
    )

    try {
      await waitForJson(`http://127.0.0.1:${CDP_PORT}/json/version`)
      const targets = await waitForJson(`http://127.0.0.1:${CDP_PORT}/json/list`)
      const page = targets.find((t) => t.type === 'page')
      if (!page) throw new Error('没有找到可用的页面目标')
      cdp = await CDP.connect(page.webSocketDebuggerUrl)
      await cdp.send('Page.enable')
      await cdp.send('Runtime.enable')
      await cdp.send('Network.enable')

      await installSessionInBrowserByMint(cdp, BASE, join(ISO_ROOT, 'data', 'app.db'))

      await cdp.send('Emulation.setDeviceMetricsOverride', {
        width: 1280,
        height: 800,
        deviceScaleFactor: 1,
        mobile: false,
      })
      await cdp.send('Page.navigate', { url: `${BASE}/study/${MEDIA_ID}` })

      // A1 登录态 → 学习页可用（谓词等待，不用固定 sleep）
      const ready = await cdp.waitValue(
        `(() => { ${HELPERS}
          const stage = document.querySelector('[data-testid="sentence-stage-card"]');
          const open = document.querySelector('[data-testid="open-player"]');
          return !!(stage && open && !open.disabled);
        })()`,
        15000,
      )
      record('A1 登录态打开学习页 → 句子舞台与「整段播放」可用', !!ready, `ready=${!!ready}`)

      // A2 点「整段播放」→ player-bar
      await cdp.evaluate(`document.querySelector('[data-testid="open-player"]').click()`)
      const barOk = await cdp.waitValue(
        `(() => {
          const el = document.querySelector('[data-testid="player-bar"]');
          const a = el && el.querySelector('audio');
          return !!(el && a && a.getAttribute('src') === '/api/media/${MEDIA_ID}/stream');
        })()`,
        8000,
      )
      const bar = await cdp.evaluate(`(() => {
        const el = document.querySelector('[data-testid="player-bar"]');
        const audios = el ? [...el.querySelectorAll('audio')] : [];
        return { present: !!el, audioCount: audios.length, src: audios[0] ? audios[0].getAttribute('src') : null };
      })()`)
      record(
        'A2 点「整段播放」→ player-bar 出现，且 PlayerBar 持有唯一 <audio>（src = stream_url）',
        !!barOk && bar.present && bar.audioCount === 1,
        `present=${bar.present} audio=${bar.audioCount} src="${bar.src}"`,
      )

      // A3 播放 → 未暂停
      const playing = await cdp.waitValue(
        `(() => { const a = document.querySelector('[data-testid="player-bar"] audio'); return a && !a.paused; })()`,
        8000,
      )
      const playState = await cdp.evaluate(
        `(() => { const a = document.querySelector('[data-testid="player-bar"] audio'); return a ? { paused: a.paused, ct: a.currentTime } : null; })()`,
      )
      record('A3 播放 → audio 未暂停', !!playing, JSON.stringify(playState))

      // A4 倍速
      const rateOpts = await cdp.evaluate(`(() => {
        const s = document.querySelector('[data-testid="player-bar"] select');
        return s ? [...s.options].map((o) => o.value) : [];
      })()`)
      const ratesOk = JSON.stringify(rateOpts) === JSON.stringify(['0.5', '0.75', '1', '1.25', '1.5'])
      await cdp.evaluate(`(() => {
        const s = document.querySelector('[data-testid="player-bar"] select');
        s.value = '1.5'; s.dispatchEvent(new Event('change', { bubbles: true }));
      })()`)
      const rate = await cdp.waitValue(
        `(() => { const a = document.querySelector('[data-testid="player-bar"] audio'); return a && a.playbackRate === 1.5 ? 1.5 : null; })()`,
        4000,
      )
      record('A4 倍速：5 档齐全且选 1.5 → playbackRate=1.5', ratesOk && rate === 1.5, `options=${JSON.stringify(rateOpts)} playbackRate=${rate}`)

      // A5 进度（先暂停避免播放中漂移）
      await cdp.evaluate(`(() => {
        const b = document.querySelector('[data-testid="player-bar"] button[aria-label="暂停"]');
        if (b) b.click();
      })()`)
      await cdp.evaluate(`(() => { ${HELPERS}
        const r = document.querySelector('[data-testid="player-bar"] input[type=range]');
        if (r) window.__setRange(r, 5);
      })()`)
      const seeked = await cdp.waitValue(
        `(() => { const a = document.querySelector('[data-testid="player-bar"] audio'); return a && Math.abs(a.currentTime - 5) < 0.8 ? a.currentTime : null; })()`,
        5000,
      )
      const seekNow = await cdp.evaluate(
        `(() => { const a = document.querySelector('[data-testid="player-bar"] audio'); return a ? a.currentTime : null; })()`,
      )
      record('A5 进度：seek(5) → currentTime ≈ 5', typeof seeked === 'number', `currentTime=${seekNow}`)

      // ---------- Group B（真实学习页驱动）----------
      // 先关掉整段播放，给句子级用例干净状态
      await cdp.evaluate(`(() => {
        const b = document.querySelector('[data-testid="player-bar"] button[aria-label="暂停"]');
        if (b) b.click();
      })()`)

      // B0 前置：无头下句子音频能播且 currentTime 前进
      const b0 = await cdp.evaluate(`(async () => { ${HELPERS}
        const playBtn = await (async () => { const s = Date.now(); for (;;) { const b = document.querySelector('button[title="播放本句"]'); if (b && !b.disabled) return b; if (Date.now() - s > 6000) return null; await __sleep(120); } })();
        if (!playBtn) return { error: '未找到可用的句子播放按钮' };
        playBtn.click();
        const t0 = Date.now();
        let advanced = false;
        while (Date.now() - t0 < 8000) {
          const a = window.__CLIP();
          if (a && a.currentTime > 0.05) { advanced = true; break; }
          await ____sleep(80);
        }
        const a = window.__CLIP();
        const stopBtn = document.querySelector('button[title="播放本句"]');
        if (advanced && stopBtn && a && !a.paused) stopBtn.click();   // 复位
        return { advanced, ct: a ? a.currentTime : null, dur: a ? a.duration : null };
      })()`)
      if (!b0 || !b0.advanced) {
        record('B0 前置：无头下句子音频能播且 currentTime 前进', false, JSON.stringify(b0 ?? null))
        record('B1–B5 句子级断言', false, '跳过：B0 前置不成立；**不把断言放宽为必然通过**')
      } else {
        record('B0 前置：无头下句子音频能播且 currentTime 前进', true, JSON.stringify(b0))
        const dur = b0.dur

        // B1 单句循环：开循环 → 播到结尾 → 回卷且仍在播放
        const b1 = await cdp.evaluate(`(async () => { ${HELPERS}
          const loop = document.querySelector('button[title="单句循环"]');
          if (!loop) return { error: '未找到循环按钮' };
          loop.click();                                        // 开启单句循环
          await ____sleep(200);
          const playBtn = document.querySelector('button[title="播放本句"]');
          playBtn.click();
          const started = await (async () => { const s = Date.now(); for (;;) { const a = window.__CLIP(); if (a && a.currentTime > 0.05) return true; if (Date.now() - s > 6000) return false; await __sleep(80); } })();
          const range = document.querySelector('input[title^="拖动定位"]');
          if (range && ${dur} > 1) window.__setRange(range, ${dur} - 0.25);   // 跳到接近结尾
          const wrapped = await (async () => { const s = Date.now(); for (;;) { const a = window.__CLIP(); if (a && a.currentTime < 1.0) return true; if (Date.now() - s > 6000) return false; await __sleep(80); } })();
          const a = window.__CLIP();
          const out = { started, dur: ${dur}, wrapped, playing: a ? !a.paused : null, ct: a ? a.currentTime : null };
          const off = document.querySelector('button[title="关闭单句循环"]');
          if (off) off.click();
          const stopBtn = document.querySelector('button[title="播放本句"]');
          if (stopBtn && a && !a.paused) stopBtn.click();      // 停掉，给后续用例干净状态
          return out;
        })()`)
        record(
          'B1 单句循环：播到结尾回卷且仍在播放',
          !!b1?.started && !!b1?.wrapped && b1?.playing === true,
          JSON.stringify(b1 ?? null),
        )

        // B2 A-B 生效：设 A → 设 B → 播过 B → 回到 A（且 A-B 仍处激活态）
        const b2 = await cdp.evaluate(`(async () => { ${HELPERS}
          const playBtn = document.querySelector('button[title="播放本句"]');
          playBtn.click();                                     // 播放
          const up = await (async () => { const s = Date.now(); for (;;) { const a = window.__CLIP(); if (a && a.currentTime > 0.6) return a.currentTime; if (Date.now() - s > 8000) return null; await __sleep(80); } })();
          if (up == null) return { error: '音频未前进到 0.6s' };
          let ab = document.querySelector('button[title^="设定 A 点"]');
          ab.click();                                          // 设 A
          const setB = await (async () => { const s = Date.now(); for (;;) { ab = document.querySelector('button[title^="在当前位置设定 B 点"]'); if (ab) return true; if (Date.now() - s > 3000) return false; await __sleep(80); } })();
          const a2 = await (async () => { const s = Date.now(); const start = window.__CLIP().currentTime; for (;;) { const a = window.__CLIP(); if (a && a.currentTime > start + 0.25) return a.currentTime; if (Date.now() - s > 5000) return null; await __sleep(80); } })();
          if (!setB || a2 == null) return { error: '未能进入设 B 状态', up, setB };
          ab = document.querySelector('button[title^="在当前位置设定 B 点"]');
          ab.click();                                          // 设 B
          ab = await (async () => { const s = Date.now(); for (;;) { const b = document.querySelector('button[title^="清除 A-B 循环"]'); if (b) return b; if (Date.now() - s > 3000) return null; await __sleep(80); } })();
          if (!ab) return { error: '未能进入 A-B 循环状态' };
          const label = ab.textContent.trim();                 // 形如 0:01–0:02
          const bPoint = window.__parseSec(label.split('–')[1]);
          const range = document.querySelector('input[title^="拖动定位"]');
          if (range && ${dur} > bPoint + 0.6) window.__setRange(range, ${dur} - 0.1);   // 越过 B
          const wrapped = await (async () => { const s = Date.now(); for (;;) { const a = window.__CLIP(); if (a && a.currentTime < bPoint) return a.currentTime; if (Date.now() - s > 6000) return null; await __sleep(80); } })();
          const still = document.querySelector('button[title^="清除 A-B 循环"]');
          const out = { up, setB, label, bPoint, wrapped, stillActive: !!still, ct: wrapped };
          const clr = document.querySelector('button[title^="清除 A-B 循环"]');
          if (clr) clr.click();
          const stopBtn = document.querySelector('button[title="播放本句"]');
          const a = window.__CLIP();
          if (stopBtn && a && !a.paused) stopBtn.click();
          return out;
        })()`)
        record(
          'B2 A-B 生效：播过 B 回到 A（且 A-B 仍处于激活态）',
          !!b2?.wrapped && b2?.stillActive === true,
          JSON.stringify(b2 ?? null),
        )

        // B3 ⭐ A-B 切句自动失效
        const b3 = await cdp.evaluate(`(async () => { ${HELPERS}
          const playBtn = document.querySelector('button[title="播放本句"]');
          playBtn.click();
          const up = await (async () => { const s = Date.now(); for (;;) { const a = window.__CLIP(); if (a && a.currentTime > 0.6) return true; if (Date.now() - s > 8000) return false; await __sleep(80); } })();
          let ab = document.querySelector('button[title^="设定 A 点"]');
          ab.click();
          await (async () => { const s = Date.now(); for (;;) { if (document.querySelector('button[title^="在当前位置设定 B 点"]')) return true; if (Date.now() - s > 3000) return false; await __sleep(80); } })();
          const a2 = await (async () => { const s = Date.now(); const start = window.__CLIP().currentTime; for (;;) { const a = window.__CLIP(); if (a && a.currentTime > start + 0.25) return true; if (Date.now() - s > 5000) return false; await __sleep(80); } })();
          ab = document.querySelector('button[title^="在当前位置设定 B 点"]');
          ab.click();
          const activeBefore = await (async () => { const s = Date.now(); for (;;) { const b = document.querySelector('button[title^="清除 A-B 循环"]'); if (b) return true; if (Date.now() - s > 3000) return false; await __sleep(80); } })();
          if (!up || !a2 || !activeBefore) return { error: '未能建立 A-B 状态', up, a2, activeBefore };
          const stageBefore = window.__stageIdx();
          const next = [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === '下一句 →');
          if (!next) return { error: '未找到「下一句」按钮' };
          next.click();                                        // 切到另一句
          const changed = await (async () => { const s = Date.now(); for (;;) { const cur = window.__stageIdx(); if (cur && cur !== ${JSON.stringify('')} && cur !== stageBefore) return true; if (Date.now() - s > 6000) return false; await __sleep(80); } })();
          await ____sleep(400);                                    // 等新句子的工具行渲染完
          const abAfter = document.querySelector('button[title^="设定 A 点"]');
          const clipStillSame = (() => { const a = window.__CLIP(); return a ? a.paused : null; })();
          const out = { up, a2, activeBefore, changed, stageBefore, abTitle: abAfter ? abAfter.getAttribute('title') : null, clipPaused: clipStillSame };
          return out;
        })()`)
        record(
          'B3 ⭐ A-B 切句自动失效（按钮回到未设定态）',
          !!b3?.changed && b3?.abTitle != null && b3.abTitle.startsWith('设定 A 点'),
          JSON.stringify(b3 ?? null),
        )

        // B4 ⭐ A-B 同句重播保留（重听 = 同一句，不切句）
        const b4 = await cdp.evaluate(`(async () => { ${HELPERS}
          const a0 = window.__CLIP();
          const stopBtn = document.querySelector('button[title="播放本句"]');
          if (a0 && !a0.paused && stopBtn) stopBtn.click();    // 先停
          const playBtn = document.querySelector('button[title="播放本句"]');
          playBtn.click();
          const up = await (async () => { const s = Date.now(); for (;;) { const a = window.__CLIP(); if (a && a.currentTime > 0.6) return true; if (Date.now() - s > 8000) return false; await __sleep(80); } })();
          let ab = document.querySelector('button[title^="设定 A 点"]');
          ab.click();
          await (async () => { const s = Date.now(); for (;;) { if (document.querySelector('button[title^="在当前位置设定 B 点"]')) return true; if (Date.now() - s > 3000) return false; await __sleep(80); } })();
          const a2 = await (async () => { const s = Date.now(); const start = window.__CLIP().currentTime; for (;;) { const a = window.__CLIP(); if (a && a.currentTime > start + 0.25) return true; if (Date.now() - s > 5000) return false; await __sleep(80); } })();
          ab = document.querySelector('button[title^="在当前位置设定 B 点"]');
          ab.click();
          const activeBefore = await (async () => { const s = Date.now(); for (;;) { const b = document.querySelector('button[title^="清除 A-B 循环"]'); if (b) return b; if (Date.now() - s > 3000) return null; await __sleep(80); } })();
          if (!activeBefore) return { error: '未能建立 A-B 状态' };
          const replay = [...document.querySelectorAll('button')].find((b) => b.getAttribute('title') === '重听本句');
          if (!replay) return { error: '未找到「重听本句」按钮' };
          replay.click();                                      // 同一句重播（seek 0 + play）
          await ____sleep(600);
          const still = document.querySelector('button[title^="清除 A-B 循环"]');
          const out = { up, a2, activeBefore: !!activeBefore, stillActive: !!still, abTitle: still ? still.getAttribute('title') : null };
          const clr = document.querySelector('button[title^="清除 A-B 循环"]');
          if (clr) clr.click();
          const a = window.__CLIP();
          if (a && !a.paused) { const b = document.querySelector('button[title="播放本句"]'); if (b) b.click(); }
          return out;
        })()`)
        record(
          'B4 ⭐ A-B 同句重播保留（重听后 A-B 仍在）',
          !!b4?.activeBefore && b4?.stillActive === true,
          JSON.stringify(b4 ?? null),
        )

        // B5 句子 ↔ 整段 互斥（两个方向，都在真实 UI 上触发）
        const b5 = await cdp.evaluate(`(async () => { ${HELPERS}
          const out = {};
          const barBtn = () => document.querySelector('[data-testid="player-bar"] button[aria-label="暂停"], [data-testid="player-bar"] button[aria-label="播放"]');
          // 方向1：句子在播 → 点「整段播放」→ 句子应被暂停
          const stopBtn = document.querySelector('button[title="播放本句"]');
          const a0 = window.__CLIP();
          if (a0 && !a0.paused && stopBtn) stopBtn.click();
          const playBtn = document.querySelector('button[title="播放本句"]');
          playBtn.click();
          const clipUp = await (async () => { const s = Date.now(); for (;;) { const a = window.__CLIP(); if (a && !a.paused) return true; if (Date.now() - s > 5000) return false; await __sleep(80); } })();
          const open = document.querySelector('[data-testid="open-player"]');
          open.click();                                        // 整段播放（store.isPlaying=true）
          const clipPaused = await (async () => { const s = Date.now(); for (;;) { const a = window.__CLIP(); if (a && a.paused) return true; if (Date.now() - s > 5000) return false; await __sleep(80); } })();
          out.dir1 = { clipUp, clipPaused };
          // 方向2：整段在播 → 点句子播放 → 整段应被暂停
          const storeUp = await (async () => { const s = Date.now(); for (;;) { const b = barBtn(); if (b && b.getAttribute('aria-label') === '暂停') return true; if (Date.now() - s > 5000) return false; await __sleep(80); } })();
          const playBtn2 = document.querySelector('button[title="播放本句"]');
          playBtn2.click();                                    // 句子播放（pauseGlobal）
          const storePaused = await (async () => { const s = Date.now(); for (;;) { const b = barBtn(); if (b && b.getAttribute('aria-label') === '播放') return true; if (Date.now() - s > 5000) return false; await __sleep(80); } })();
          out.dir2 = { storeUp, storePaused };
          const a = window.__CLIP();
          if (a && !a.paused) { const b = document.querySelector('button[title="播放本句"]'); if (b) b.click(); }
          const closeBtn = document.querySelector('[data-testid="player-bar"] button[aria-label="关闭播放器"]');
          if (closeBtn) closeBtn.click();                      // 给后续用例干净状态
          await ____sleep(400);
          return out;
        })()`)
        record(
          'B5 句子↔整段互斥（两方向，均在真实 UI 上触发）',
          !!b5?.dir1?.clipUp && b5.dir1.clipPaused === true && b5?.dir2?.storeUp && b5.dir2.storePaused === true,
          JSON.stringify(b5 ?? null),
        )
      }

      // ---------- A7 375px ----------
      await cdp.send('Emulation.setDeviceMetricsOverride', { width: 375, height: 667, deviceScaleFactor: 2, mobile: true })
      await cdp.evaluate(`document.querySelector('[data-testid="open-player"]').click()`)
      await cdp.waitValue(`!!document.querySelector('[data-testid="player-bar"]')`, 8000)
      const m = await cdp.evaluate(`(() => { ${HELPERS}
        const inner = window.innerWidth;
        const offenders = [...document.querySelectorAll('body *')]
          .map((el) => ({ el, r: el.getBoundingClientRect() }))
          .filter((x) => x.r.width > 0 && x.r.right > inner + 1).slice(0, 5)
          .map((x) => x.el.tagName.toLowerCase() + (x.el.className ? '.' + String(x.el.className).split(' ')[0] : ''));
        const shell = document.querySelector('.h-dvh');
        const header = shell && shell.querySelector(':scope > header');
        const main = shell && shell.querySelector(':scope > main');
        const bar = document.querySelector('[data-testid="player-bar"]');
        const cs = (el) => (el ? getComputedStyle(el) : null);
        return {
          scrollW: document.documentElement.scrollWidth, inner, offenders,
          shellFound: !!shell,
          headerShrink: cs(header)?.flexShrink, mainGrow: cs(main)?.flexGrow,
          mainMinH: cs(main)?.minHeight, mainOverflowY: cs(main)?.overflowY,
          barShrink: cs(bar)?.flexShrink,
          barRight: bar ? Math.round(bar.getBoundingClientRect().right) : null,
        };
      })()`)
      record('A7 375px 无横向滚动', m.scrollW <= m.inner + 1, `内容 ${m.scrollW} / 视口 ${m.inner}${m.offenders.length ? ' 越界:' + m.offenders.join(',') : ''}`)
      record(
        'A7 375px 三段式外壳仍成立（底条 shrink-0）',
        m.shellFound && m.headerShrink === '0' && m.mainGrow === '1' && m.mainMinH === '0px' && m.mainOverflowY === 'auto' && m.barShrink === '0' && m.barRight <= m.inner + 1,
        `headerShrink=${m.headerShrink} mainGrow=${m.mainGrow} mainMinH=${m.mainMinH} barShrink=${m.barShrink} barRight=${m.barRight}`,
      )

      // ---------- A6 关闭 ----------
      await cdp.evaluate(`(() => {
        const b = document.querySelector('[data-testid="player-bar"] button[aria-label="关闭播放器"]');
        if (b) b.click();
      })()`)
      const gone = await cdp.waitValue(`!document.querySelector('[data-testid="player-bar"]')`, 5000)
      record('A6 关闭 → player-bar 消失', !!gone, `gone=${!!gone}`)
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
    try {
      rmSync(ISO_ROOT, { recursive: true, force: true })
    } catch {
      /* 忽略 */
    }
  }

  const failed = results.filter((r) => !r.ok)
  console.log(`\n===== 结果：${results.length - failed.length}/${results.length} 通过 =====`)
  for (const f of failed) console.log(`  - FAIL ${f.name}`)
  process.exitCode = failed.length ? 1 : 0
}

main().catch((err) => {
  console.error('验证脚本异常：', err)
  process.exitCode = 1
})

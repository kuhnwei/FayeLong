/** M5 端到端交互验证（CDP 驱动真实无头 Chrome）。
 *
 * 覆盖 M5 打磨项：
 *   1. 媒体库：学习概览卡片、素材搜索过滤
 *   2. 学习页：A-B 循环按钮的状态机（设 A → 设 B → 清除）
 *   3. 学习页：笔记汇总面板（计数 / 列表 / 导出链接 / 点击定位高亮）
 *   4. 学习页：听写历史正确率趋势条
 *   5. 异常兜底：访问不存在的媒体不白屏，给出可读错误
 *   6. 接口：笔记导出返回 Markdown、全局统计接口可用
 *
 * 依赖：本机 Chrome + 已启动的后端（默认 http://127.0.0.1:8000）。
 * 用法（项目根目录）：
 *   node scripts/verify_m5.mjs [--url http://127.0.0.1:8000] [--media 3] [--port 9333]
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
// v1.12 起站点需要登录：让后续所有 Node 侧 fetch 自动带上会话
patchFetchForSession(BASE)
const MEDIA_ID = Number(arg('--media', '3'))
const PORT = Number(arg('--port', '9334'))
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
`

// --------------------------- 主流程 ---------------------------

async function main() {
  // ---------- 准备：造一条笔记 + 一次听写（供面板与趋势条验证）----------
  const detail = await (await fetch(`${BASE}/api/media/${MEDIA_ID}`)).json()
  const target = detail.sentences?.[1]
  // 目标句在句子数组里的下标（一句一页后用宫格按序号跳）
  const TARGET_INDEX = Math.max(0, (detail.sentences ?? []).findIndex((s) => s.id === target?.id))
  const NOTE_STAMP = `e2e-m5-note-${Date.now()}`
  if (target) {
    await fetch(`${BASE}/api/notes/${target.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: NOTE_STAMP }),
    })
    for (const input of ['And so my fellow', 'And so my fellow Americans ask not']) {
      await fetch(`${BASE}/api/attempts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sentence_id: target.id, input }),
      })
    }
  }

  const profile = mkdtempSync(join(tmpdir(), 'fayelong-m5-'))
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
    // 浏览器侧也要带上会话，否则真实点击会落到登录页
    await installSessionInBrowser(cdp, BASE)

    // ---------- 1. 媒体库：概览卡片 + 搜索 ----------
    await cdp.send('Page.navigate', { url: `${BASE}/` })
    await sleep(1800)
    const libProbe = await cdp.evaluate(`(async () => {
      ${HELPERS}
      const out = { statCards: 0, statText: '', rowsBefore: 0, rowsAfter: 0, hasSearch: false, error: null };
      await waitFor(() => document.body.innerText.includes('已导入素材'));
      // 概览卡片：包含「素材 / 句子 / 生词 / 句子笔记」四个标签
      const labels = [...document.querySelectorAll('p')].map((p) => p.textContent.trim());
      out.statCards = ['素材', '句子', '生词', '句子笔记'].filter((k) => labels.includes(k)).length;
      out.statText = document.body.innerText.replace(/\\n+/g, ' | ').slice(0, 240);
      const input = await waitFor(() => document.querySelector('input[placeholder*="搜索标题"]'));
      out.hasSearch = Boolean(input);
      out.rowsBefore = document.querySelectorAll('a[title="进入学习页"]').length;
      if (input) {
        const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
        setter.call(input, '不存在的关键词zzz');
        input.dispatchEvent(new Event('input', { bubbles: true }));
        await sleep(400);
        out.rowsAfter = document.querySelectorAll('a[title="进入学习页"]').length;
        out.emptyHint = document.body.innerText.includes('没有匹配');
        setter.call(input, '');
        input.dispatchEvent(new Event('input', { bubbles: true }));
        await sleep(300);
      }
      return out;
    })()`)

    record('媒体库显示四项学习概览', (libProbe?.statCards ?? 0) === 4, libProbe?.statText ?? '')
    record(
      '媒体库搜索可过滤素材',
      Boolean(libProbe?.hasSearch) &&
        (libProbe?.rowsBefore ?? 0) > 0 &&
        (libProbe?.rowsAfter ?? 1) === 0 &&
        Boolean(libProbe?.emptyHint),
      `命中前 ${libProbe?.rowsBefore ?? 0} → 命中后 ${libProbe?.rowsAfter ?? 0}`,
    )

    // ---------- 2. 学习页：A-B 循环 ----------
    await cdp.send('Page.navigate', { url: `${BASE}/study/${MEDIA_ID}` })
    await sleep(1800)
    const abProbe = await cdp.evaluate(`(async () => {
      ${HELPERS}
      const out = { step0: null, step1: null, step2: null, step3: null, abActive: false, error: null };
      const ab = await waitFor(() => document.querySelector('button[title^="设定 A 点"]'));
      if (!ab) { out.error = '未找到 A-B 按钮'; return out; }
      out.step0 = ab.getAttribute('title');
      ab.click();
      await sleep(700);                       // 让音频走一点，B 点才会 > A 点
      const b1 = await waitFor(() => document.querySelector('button[title^="在当前位置设定 B 点"]'), 3000);
      out.step1 = b1 ? b1.getAttribute('title') : null;
      if (b1) {
        b1.click();
        await sleep(300);
        const b2 = document.querySelector('button[title^="清除 A-B 循环"]');
        out.step2 = b2 ? b2.getAttribute('title') : null;
        out.abActive = b2 ? /sky/.test(b2.className) : false;
        if (b2) {
          b2.click();
          await sleep(250);
          const b3 = document.querySelector('button[title^="设定 A 点"]');
          out.step3 = b3 ? b3.getAttribute('title') : null;
        }
      }
      return out;
    })()`)

    record('A-B 按钮存在（初始态）', Boolean(abProbe?.step0), abProbe?.step0 ?? abProbe?.error ?? '')
    record('第一次点击设定 A 点', Boolean(abProbe?.step1), abProbe?.step1 ?? '未进入设 B 状态')
    record('第二次点击设定 B 点并进入循环', Boolean(abProbe?.step2) && Boolean(abProbe?.abActive), abProbe?.step2 ?? '')
    record('第三次点击清除 A-B', Boolean(abProbe?.step3), abProbe?.step3 ?? '')

    // ---------- 3. 学习页：笔记汇总面板 ----------
    const panelProbe = await cdp.evaluate(`(async () => {
      ${HELPERS}
      const out = { entry: null, opened: false, hasNote: false, hasExport: false, jumped: false, highlighted: false, error: null };
      const entry = await waitFor(() => {
        const b = [...document.querySelectorAll('button')].find((el) => el.textContent.trim().startsWith('笔记'));
        return b || null;
      });
      if (!entry) { out.error = '未找到「笔记」入口'; return out; }
      out.entry = entry.textContent.trim();
      entry.click();
      const dialog = await waitFor(() => document.querySelector('div[role="dialog"]'));
      if (!dialog) { out.error = '笔记面板未打开'; return out; }
      out.opened = true;
      out.hasNote = dialog.innerText.includes(${JSON.stringify(NOTE_STAMP)});
      const exportLink = dialog.querySelector('a[href*="/notes/export"]');
      out.hasExport = Boolean(exportLink);
      out.exportHref = exportLink ? exportLink.getAttribute('href') : null;
      // 点击条目 → 面板关闭 → 对应句子卡片高亮
      const item = await waitFor(() => {
        const b = [...dialog.querySelectorAll('button')].find((el) => el.innerText.includes(${JSON.stringify(NOTE_STAMP)}));
        return b || null;
      });
      if (item) {
        item.click();
        await sleep(500);
        out.jumped = !document.querySelector('div[role="dialog"]');
        // v1.12 一句一页：目标句不再有固定 id，改看句子舞台是否被高亮环包住
        const card = document.querySelector('[data-testid="sentence-stage-card"]');
        out.highlighted = Boolean(card && card.className.includes('ring-2'));
      }
      return out;
    })()`)

    record('「笔记」入口显示计数', /笔记/.test(panelProbe?.entry ?? ''), panelProbe?.entry ?? panelProbe?.error ?? '')
    record('笔记面板可打开', Boolean(panelProbe?.opened), panelProbe?.error ?? '')
    record('面板列出刚写入的笔记', Boolean(panelProbe?.hasNote))
    record('面板有导出 Markdown 链接', Boolean(panelProbe?.hasExport), panelProbe?.exportHref ?? '')
    record('点击条目关闭面板并高亮定位', Boolean(panelProbe?.jumped) && Boolean(panelProbe?.highlighted))

    // ---------- 4. 听写历史趋势条 ----------
    const trendProbe = await cdp.evaluate(`(async () => {
      ${HELPERS}
      // v1.12 一句一页：没有「句子卡片」了，改用底部宫格跳到目标句
      const card = document.querySelector('[data-testid="sentence-stage-card"]');
      const grid = [...document.querySelectorAll('[data-testid="sentence-grid"] button')];
      if (!card || !grid.length) return { ok: false, error: '未找到句子舞台或句子宫格' };
      const slot = grid[${TARGET_INDEX}] || grid[0];
      slot.click();
      await sleep(450);
      const btn = [...card.querySelectorAll('button')].find((b) => b.textContent.includes('听写历史'));
      if (!btn) return { ok: false, error: '未找到听写历史入口' };
      btn.click();
      const bars = await waitFor(() => {
        const list = card.querySelectorAll('span[title$="%"]');
        return list.length > 1 ? list : null;
      }, 8000);
      return { ok: Boolean(bars), bars: bars ? bars.length : 0 };
    })()`)
    record('听写历史显示正确率趋势条', Boolean(trendProbe?.ok), trendProbe?.error ?? `柱数 ${trendProbe?.bars ?? 0}`)

    // ---------- 5. 异常兜底：不存在的媒体 ----------
    await cdp.send('Page.navigate', { url: `${BASE}/study/999999` })
    await sleep(1800)
    const errProbe = await cdp.evaluate(`(async () => {
      ${HELPERS}
      const txt = await waitFor(() => {
        const t = document.body.innerText;
        return t.includes('媒体不存在') ? t : null;
      }, 8000);
      return { text: txt ? txt.replace(/\\n+/g, ' | ').slice(0, 160) : null,
               blank: document.body.innerText.trim().length < 10 };
    })()`)
    record(
      '访问不存在的媒体给出可读错误（不白屏）',
      Boolean(errProbe?.text) && !errProbe?.blank,
      errProbe?.text ?? '无错误提示',
    )

    // ---------- 6. 接口级：笔记导出 + 全局统计 ----------
    const expRes = await fetch(`${BASE}/api/media/${MEDIA_ID}/notes/export`)
    const expText = await expRes.text()
    record(
      '笔记导出接口返回 Markdown（含笔记内容）',
      expRes.ok && expText.includes('句子笔记') && expText.includes(NOTE_STAMP),
      `HTTP ${expRes.status}，${expText.split('\n').length} 行`,
    )

    const statsRes = await fetch(`${BASE}/api/stats`)
    const stats = await statsRes.json()
    record(
      '全局统计接口可用',
      statsRes.ok && typeof stats?.media?.total === 'number' && typeof stats?.vocab?.total === 'number',
      JSON.stringify(stats).slice(0, 160),
    )

    // ---------- 清理：删除本次造的数据 ----------
    if (target) {
      await fetch(`${BASE}/api/notes/${target.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: '' }),
      })
    }
  } catch (err) {
    record('验证流程', false, String(err?.message ?? err))
  } finally {
    cdp?.close()
    chrome.kill()
    await sleep(300)
    try {
      rmSync(profile, { recursive: true, force: true })
    } catch {
      /* 忽略清理失败 */
    }
  }

  const failed = results.filter((r) => !r.ok)
  console.log('\n' + '='.repeat(56))
  console.log(
    failed.length === 0
      ? `全部通过 ✔（${results.length} 项）`
      : `未通过 ${failed.length}/${results.length} 项 ✘`,
  )
  console.log('='.repeat(56))
  process.exit(failed.length === 0 ? 0 : 1)
}

main()

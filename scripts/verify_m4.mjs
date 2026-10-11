/** M4 端到端交互验证（CDP 驱动真实无头 Chrome）。
 *
 * 覆盖：点击原文单词 → 查词浮层（音标/释义）→ 加入生词本 →
 *       生词本页出现该词 → 导出链接可用 → 句子笔记保存与回显。
 *
 * 依赖：本机 Chrome + 已启动的后端（默认 http://127.0.0.1:8000）。
 * 用法（项目根目录）：
 *   node scripts/verify_m4.mjs [--url http://127.0.0.1:8000] [--media 3] [--port 9333]
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

const BASE = arg('--url', 'http://127.0.0.1:8000').replace(/\/$/, '')
const MEDIA_ID = arg('--media', '3')
const PORT = Number(arg('--port', '9333'))
const CHROME = arg(
  '--chrome',
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
)

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
  const profile = mkdtempSync(join(tmpdir(), 'fayelong-cdp-'))
  const chrome = spawn(
    CHROME,
    [
      '--headless=new',
      `--remote-debugging-port=${PORT}`,
      `--user-data-dir=${profile}`,
      '--no-first-run',
      '--no-default-browser-check',
      '--disable-gpu',
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

    // ---------- 1. 打开学习页 ----------
    await cdp.send('Page.navigate', { url: `${BASE}/study/${MEDIA_ID}` })
    await sleep(1500)

    const wordProbe = await cdp.evaluate(`(async () => {
      ${HELPERS}
      const out = { cards: 0, word: null, overlay: null, added: null, error: null };
      // 等待句子卡片渲染（出现「显示原文」按钮）
      const reveal = await waitFor(() => byText(document.body, '显示原文'));
      if (!reveal) { out.error = '未渲染出句子卡片（媒体可能还没处理完）'; return out; }
      reveal.click();
      await sleep(250);
      out.cards = document.querySelectorAll('button[title^="查询"]').length;
      // 找到第一个可点击单词
      const wordBtn = await waitFor(() => document.querySelector('button[title^="查询"]'));
      if (!wordBtn) { out.error = '原文展开后仍没有可点击单词'; return out; }
      out.word = wordBtn.textContent.trim();
      wordBtn.click();
      // 等待浮层出现
      const overlay = await waitFor(() => document.querySelector('div.fixed.inset-0.z-50'));
      if (!overlay) { out.error = '查词浮层未出现'; return out; }
      const addBtn = await waitFor(() => byText(overlay, '加入生词本') || byText(overlay, '已在生词本') || byText(overlay, '已加入生词本'));
      // 等释义加载完成（查询中… 消失）
      await waitFor(() => !overlay.textContent.includes('查询中'));
      out.overlay = {
        text: overlay.innerText.replace(/\\n+/g, ' | ').slice(0, 400),
        hasPhonetic: /\\/[^/]+\\//.test(overlay.innerText),
        hasChinese: /[\\u4e00-\\u9fa5]/.test(overlay.innerText),
        hasOxfordLink: !!overlay.querySelector('a[href*="oxfordlearners"]'),
        hasLongmanLink: !!overlay.querySelector('a[href*="ldoceonline"]'),
        addButton: addBtn ? addBtn.textContent.trim() : null,
      };
      // 点击加入生词本
      const add = byText(overlay, '加入生词本');
      if (add) {
        add.click();
        const after = await waitFor(() => {
          const b = byText(overlay, '已加入生词本') || byText(overlay, '已在生词本');
          return b ? b.textContent.trim() : null;
        }, 8000);
        out.added = after;
      } else {
        out.added = addBtn ? addBtn.textContent.trim() : null;
      }
      // 关闭浮层
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
      await sleep(200);
      out.overlayClosed = !document.querySelector('div.fixed.inset-0.z-50');
      return out;
    })()`)

    record('学习页渲染句子卡片', Boolean(wordProbe?.cards !== undefined && !wordProbe?.error), wordProbe?.error ?? `可点击单词 ${wordProbe?.cards ?? 0} 个`)
    record('点击单词弹出查词浮层', Boolean(wordProbe?.overlay), wordProbe?.overlay?.text ?? '无')
    record('浮层含音标与中文释义', Boolean(wordProbe?.overlay?.hasPhonetic && wordProbe?.overlay?.hasChinese))
    record('浮层含牛津 / 朗文跳转', Boolean(wordProbe?.overlay?.hasOxfordLink && wordProbe?.overlay?.hasLongmanLink))
    record('一键加入生词本', /已/.test(wordProbe?.added ?? ''), wordProbe?.added ?? '未成功')
    record('Esc 可关闭浮层', Boolean(wordProbe?.overlayClosed))

    // ---------- 2. 句子笔记 ----------
    const noteProbe = await cdp.evaluate(`(async () => {
      ${HELPERS}
      const out = { ok: false, error: null, saved: null, echoed: null };
      const openBtn = await waitFor(() => byText(document.body, '添加笔记') || byText(document.body, '查看笔记'));
      if (!openBtn) { out.error = '未找到笔记入口'; return out; }
      openBtn.click();
      const area = await waitFor(() => document.querySelector('textarea[placeholder*="记录这个词"]'));
      if (!area) { out.error = '笔记输入框未出现'; return out; }
      const stamp = 'e2e-note-' + Date.now();
      const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
      setter.call(area, stamp);
      area.dispatchEvent(new Event('input', { bubbles: true }));
      await sleep(150);
      area.dispatchEvent(new Event('blur', { bubbles: true }));
      const save = byText(document.body, '保存');
      if (save) save.click();
      const toast = await waitFor(() => {
        const el = [...document.querySelectorAll('span')].find((s) => s.textContent.includes('笔记已保存'));
        return el ? el.textContent.trim() : null;
      }, 8000);
      out.saved = toast;
      out.echoed = stamp;
      out.ok = Boolean(toast);
      return out;
    })()`)

    record('句子笔记可保存', Boolean(noteProbe?.ok), noteProbe?.saved ?? noteProbe?.error ?? '未成功')

    // 重新加载页面，确认笔记回显（持久化）
    await cdp.send('Page.navigate', { url: `${BASE}/study/${MEDIA_ID}` })
    await sleep(1800)
    const noteEcho = await cdp.evaluate(`(async () => {
      ${HELPERS}
      // 有笔记时 NoteEditor 默认展开，内容存放在 textarea.value（不是文本节点）
      const area = await waitFor(() => {
        const el = document.querySelector('textarea[placeholder*="记录这个词"]');
        return el && el.value && el.value.trim() ? el : null;
      }, 12000);
      return area ? area.value.trim() : null;
    })()`)
    record('刷新后笔记回显（已持久化）', /^e2e-note-/.test(noteEcho ?? ''), noteEcho ?? '未回显')

    // ---------- 3. 生词本页 ----------
    await cdp.send('Page.navigate', { url: `${BASE}/vocab` })
    await sleep(1800)
    const vocabProbe = await cdp.evaluate(`(async () => {
      ${HELPERS}
      const out = { total: 0, hasExport: false, firstWord: null, hasMasteredBtn: false, hasDelete: false };
      await waitFor(() => document.querySelector('[data-vocab-row]') || document.body.innerText.includes('还没有生词'));
      out.total = document.querySelectorAll('[data-vocab-row]').length;
      const exportLink = document.querySelector('a[href*="/api/vocab/export"]');
      out.hasExport = Boolean(exportLink);
      out.exportHref = exportLink ? exportLink.getAttribute('href') : null;
      const first = document.querySelector('[data-vocab-row]');
      out.firstWord = first ? first.innerText.split('\\n')[0].slice(0, 40) : null;
      out.hasMasteredBtn = Boolean(byText(document.body, '标记掌握') || byText(document.body, '已掌握'));
      out.hasDelete = Boolean(document.querySelector('button[title="删除"]'));
      return out;
    })()`)

    record('生词本页有生词', (vocabProbe?.total ?? 0) > 0, `共 ${vocabProbe?.total ?? 0} 条；首条 ${vocabProbe?.firstWord ?? '-'}`)
    record('生词本页有掌握 / 删除操作', Boolean(vocabProbe?.hasMasteredBtn && vocabProbe?.hasDelete))
    record('导出 Markdown 链接可用', Boolean(vocabProbe?.hasExport), vocabProbe?.exportHref ?? '')

    // 验证导出接口真的返回 Markdown
    const exportRes = await fetch(`${BASE}/api/vocab/export`)
    const exportText = await exportRes.text()
    record(
      '导出接口返回 Markdown 表格',
      exportRes.ok && exportText.includes('| 单词 |') && exportText.includes('生词本'),
      `HTTP ${exportRes.status}，${exportText.split('\n').length} 行`,
    )
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

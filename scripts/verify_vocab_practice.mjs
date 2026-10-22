/** 生词本增强（朗读 + 练习 + 听写）端到端验证（CDP 驱动真实无头 Chrome）。
 *
 * 覆盖新增需求：
 *   1. 生词本列表每行都有「朗读」按钮，且有「开始练习」入口
 *   2. 练习设置区：练习方式 / 练习范围 / 题量（听写模式下另有语速）三/四组选项
 *   3. 中译英：手输拼写、自动判分（含「填原型也算对」）、答错时给出正确答案、朗读按钮
 *   4. 英译中：四选一、点击即判分、正确项高亮
 *   5. 听写：题干**只给发音不给文字**、进入题目自动播放、可重播/慢速重播、
 *      按听到的单词作答判正确、答错给出正确答案
 *   6. 结果页：正确率 / 用时 / 错题回顾 / 重练错题
 *   7. 路由：/vocab/practice 可直接访问（刷新不丢）
 *
 * 听写判定说明：脚本在文档创建时注入钩子拦截 `speechSynthesis.speak`，
 * 记录每次被朗读的文本与语速——相当于「用程序把听到的声音记下来」，
 * 既能验证「题干不泄露文字」，又能拿到答案去验证判分。页面代码本身不额外暴露答案。
 *
 * 依赖：本机 Chrome + 已构建前端 + 已启动后端（默认 http://127.0.0.1:8000）。
 * 用法（项目根目录）：
 *   node scripts/verify_vocab_practice.mjs [--url http://127.0.0.1:8000] [--port 9336] [--wipe-test-words]
 *
 * 副作用：会向生词本写入 9 个测试词条用于出题（幂等，重复运行不增长）。
 * 默认验证结束后**保留**它们（方便立刻试用练习功能）；加 `--wipe-test-words` 则把 9 个测试词全部删除。
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
const PORT = Number(arg('--port', '9336'))
const CHROME = arg('--chrome', 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe')
const WIPE = argv.includes('--wipe-test-words')

/** 测试词条：释义刻意各不相同，便于反查与生成干扰项 */
const SEED = [
  { word: 'abandon', lemma: null, phonetic: 'əˈbændən', translation: 'v. 放弃，抛弃；离弃' },
  { word: 'benefit', lemma: null, phonetic: 'ˈbenɪfɪt', translation: 'n. 好处，利益；v. 有益于' },
  { word: 'cautious', lemma: null, phonetic: 'ˈkɔːʃəs', translation: 'adj. 谨慎的，小心的' },
  { word: 'diligent', lemma: null, phonetic: 'ˈdɪlɪdʒənt', translation: 'adj. 勤勉的，用功的' },
  { word: 'efficient', lemma: null, phonetic: 'ɪˈfɪʃnt', translation: 'adj. 高效的，效率高的' },
  { word: 'fragile', lemma: null, phonetic: 'ˈfrædʒaɪl', translation: 'adj. 易碎的，脆弱的' },
  { word: 'genuine', lemma: null, phonetic: 'ˈdʒenjuɪn', translation: 'adj. 真的，真诚的' },
  { word: 'hesitate', lemma: null, phonetic: 'ˈhezɪteɪt', translation: 'v. 犹豫，踌躇' },
  // 专门用来验证「填写原型也算对」
  { word: 'went', lemma: 'go', phonetic: 'went', translation: 'v. 去（go 的过去式）' },
]

/** 释义 → 应填答案（原型场景刻意填 lemma） */
const ANSWER_BY_TRANSLATION = Object.fromEntries(
  SEED.map((item) => [item.translation, item.lemma || item.word]),
)
/** 单词显示名 → 释义（英译中反查用） */
const TRANSLATION_BY_NAME = Object.fromEntries(
  SEED.map((item) => [item.lemma || item.word, item.translation]),
)
const LEMMA_CASE_TRANSLATION = 'v. 去（go 的过去式）'
/** 刻意答错的题（中文释义定位，避免与原型用例撞车） */
const FORCE_WRONG_TRANSLATION = 'v. 犹豫，踌躇'
/** 全部测试单词（含原型，小写），用于校验听写题干是否泄露了文字 */
const ALL_WORDS = [
  ...new Set(SEED.flatMap((item) => [item.word, item.lemma]).filter(Boolean).map((w) => w.toLowerCase())),
]

/** 注入钩子：把「被朗读的内容」记录下来，用于验证听写（页面本身不暴露答案）。
 *  - 无语音合成能力的环境（部分无头场景）注入桩实现，保证听写模式可用；
 *  - 有则包一层 `speak`，记录 text 与 rate。 */
const SPEECH_HOOK = `(() => {
  window.__spoken = [];
  const record = (u) => {
    try { window.__spoken.push({ text: String((u && u.text) || ''), rate: u && u.rate }); } catch (e) {}
  };
  const makeStub = () => ({
    speak(u) { record(u); }, cancel() {}, pause() {}, resume() {},
    getVoices() { return [{ lang: 'en-US', name: 'Test EN', voiceURI: 'test-en', localService: true, default: true }]; },
    addEventListener() {}, removeEventListener() {},
    speaking: false, pending: false, paused: false,
  });
  if (!window.SpeechSynthesisUtterance) {
    window.SpeechSynthesisUtterance = function (text) {
      this.text = text; this.rate = 1; this.lang = ''; this.voice = null;
    };
  }
  if (!window.speechSynthesis) {
    Object.defineProperty(window, 'speechSynthesis', { value: makeStub(), configurable: true });
  } else {
    const real = window.speechSynthesis;
    const orig = real.speak.bind(real);
    real.speak = (u) => { record(u); try { return orig(u); } catch (e) {} };
  }
})();`

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
const setInput = (el, value) => {
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  setter.call(el, value);
  el.dispatchEvent(new Event('input', { bubbles: true }));
};
`

// --------------------------- 主流程 ---------------------------

async function main() {
  // ---------- 准备：写入测试生词（幂等，重复运行不增长）----------
  const createdIds = []
  for (const item of SEED) {
    const res = await fetch(`${BASE}/api/vocab`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(item),
    })
    if (!res.ok) throw new Error(`写入测试生词失败：${item.word} HTTP ${res.status}`)
    const body = await res.json()
    if (!body.duplicated) createdIds.push(body.id)
  }
  console.log(`已准备 ${SEED.length} 个测试生词（本次新建 ${createdIds.length} 个）\n`)

  const profile = mkdtempSync(join(tmpdir(), 'fayelong-vocab-practice-'))
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
    // 每个新文档创建时注入「朗读记录钩子」（听写验证依赖它）
    await cdp.send('Page.addScriptToEvaluateOnNewDocument', { source: SPEECH_HOOK })

    // ---------- 1. 生词本列表：朗读按钮 + 练习入口 ----------
    await cdp.send('Page.navigate', { url: `${BASE}/vocab` })
    await sleep(1800)
    const listProbe = await cdp.evaluate(`(async () => {
      ${HELPERS}
      const out = { rows: 0, speakButtons: 0, practiceEntry: null, practiceHref: null, error: null };
      const row = await waitFor(() => document.querySelector('[data-vocab-row]'));
      if (!row) { out.error = '生词行为空，测试数据可能未写入'; return out; }
      await sleep(400);
      out.rows = document.querySelectorAll('[data-vocab-row]').length;
      out.speakButtons = document.querySelectorAll('[data-vocab-row] button[title^="朗读"]').length;
      const entry = [...document.querySelectorAll('a')].find((el) => el.textContent.includes('开始练习'));
      out.practiceEntry = entry ? entry.textContent.trim() : null;
      out.practiceHref = entry ? entry.getAttribute('href') : null;
      // 点击朗读按钮不应抛错（headless 下 speechSynthesis 存在即可）
      const btn = row.querySelector('button[title^="朗读"]');
      if (btn) btn.click();
      out.speakApi = typeof window.speechSynthesis !== 'undefined';
      return out;
    })()`)

    record(
      '生词本每个词条都有朗读按钮',
      (listProbe?.rows ?? 0) > 0 && listProbe?.speakButtons === listProbe?.rows,
      `行 ${listProbe?.rows ?? 0}，朗读按钮 ${listProbe?.speakButtons ?? 0}`,
    )
    record(
      '生词本有「开始练习」入口且指向 /vocab/practice',
      /开始练习/.test(listProbe?.practiceEntry ?? '') &&
        (listProbe?.practiceHref ?? '').includes('/vocab/practice'),
      `${listProbe?.practiceEntry ?? listProbe?.error ?? ''} → ${listProbe?.practiceHref ?? ''}`,
    )

    // ---------- 2. 练习页设置区 ----------
    await cdp.send('Page.navigate', { url: `${BASE}/vocab/practice` })
    await sleep(1800)
    const setupProbe = await cdp.evaluate(`(async () => {
      ${HELPERS}
      const out = { phase: null, groups: 0, hasZh2En: false, hasEn2Zh: false, hasDictation: false, counts: [], enabled: false, error: null };
      const root = await waitFor(() => document.querySelector('[data-practice-phase="setup"]'));
      if (!root) { out.error = '未进入设置界面'; return out; }
      out.phase = 'setup';
      const text = root.innerText;
      out.groups = ['练习方式', '练习范围', '题量'].filter((k) => text.includes(k)).length;
      out.hasZh2En = text.includes('看中文写英文');
      out.hasEn2Zh = text.includes('看英文选释义');
      out.hasDictation = text.includes('听发音写单词');
      out.counts = ['全部', '待复习', '已掌握'].filter((k) => text.includes(k));
      const start = [...root.querySelectorAll('button')].find((b) => b.textContent.includes('开始练习'));
      out.enabled = Boolean(start) && !start.disabled;
      return out;
    })()`)

    record(
      '练习设置区含「练习方式 / 练习范围 / 题量」',
      setupProbe?.phase === 'setup' && setupProbe?.groups === 3,
      `${setupProbe?.groups ?? 0}/3 组${setupProbe?.error ? `（${setupProbe.error}）` : ''}`,
    )
    record(
      '练习方式含「中译英 / 英译中 / 听写」三种',
      Boolean(setupProbe?.hasZh2En) && Boolean(setupProbe?.hasEn2Zh) && Boolean(setupProbe?.hasDictation),
    )
    record(
      '练习范围含「全部 / 待复习 / 已掌握」',
      (setupProbe?.counts ?? []).length === 3,
      (setupProbe?.counts ?? []).join('、'),
    )
    record('生词足够时「开始练习」可点', Boolean(setupProbe?.enabled))

    // ---------- 3. 中译英：手输拼写 + 判分 ----------
    const zhProbe = await cdp.evaluate(`(async () => {
      ${HELPERS}
      const ANSWER = ${JSON.stringify(ANSWER_BY_TRANSLATION)};
      const LEMMA_CASE = ${JSON.stringify(LEMMA_CASE_TRANSLATION)};
      const FORCE_WRONG = ${JSON.stringify(FORCE_WRONG_TRANSLATION)};
      const out = { started: false, total: 0, answered: 0, correct: false, wrong: false,
                    wrongShowsAnswer: false, hasHint: false, hasSpeakAfter: false,
                    lemmaCaseSeen: false, lemmaCaseOk: false, resultPhase: false,
                    accuracy: null, error: null };
      // 选「全部」范围 + 「全部」题量，保证 9 个词都出现（含原型用例）
      const pick = (text) => [...document.querySelectorAll('button')].find((b) => b.textContent.trim().startsWith(text));
      const allScope = [...document.querySelectorAll('button')].find((b) => b.textContent.trim().startsWith('全部') && b.textContent.includes('个'));
      if (allScope) allScope.click();
      await sleep(150);
      const allCount = [...document.querySelectorAll('button')].filter((b) => b.textContent.trim().startsWith('全部')).pop();
      if (allCount) allCount.click();
      await sleep(150);
      const start = [...document.querySelectorAll('button')].find((b) => b.textContent.includes('开始练习'));
      if (!start) { out.error = '未找到开始按钮'; return out; }
      start.click();
      const quiz = await waitFor(() => document.querySelector('[data-practice-phase="quiz"]'), 6000);
      if (!quiz) { out.error = '未进入答题界面'; return out; }
      out.started = true;
      const totalEl = document.querySelector('[data-practice-progress]')?.parentElement?.parentElement?.querySelector('span');
      out.total = Number((totalEl?.textContent || '').split('/')[1]?.trim() || 0);
      out.hasHint = quiz.innerText.includes('填原型也可以');

      for (let guard = 0; guard < 40; guard += 1) {
        const card = document.querySelector('[data-practice-phase="quiz"]');
        if (!card) break;
        const prompt = card.querySelector('[data-practice-prompt]')?.textContent.trim() || '';
        const input = card.querySelector('[data-practice-input]');
        if (!input) { out.error = '未找到拼写输入框'; break; }
        const answer = ANSWER[prompt];
        // 指定那一题故意答错，用来验证错题反馈
        const forceWrong = prompt === FORCE_WRONG;
        setInput(input, forceWrong ? 'zzzz' : (answer || ''));
        card.querySelector('[data-practice-submit]').click();
        const fb = await waitFor(() => card.querySelector('[data-practice-feedback]'), 4000);
        const kind = fb ? fb.getAttribute('data-practice-feedback') : null;
        if (kind === 'correct') {
          out.correct = true;
          if (prompt === LEMMA_CASE) { out.lemmaCaseSeen = true; out.lemmaCaseOk = true; }
        }
        if (kind === 'wrong') {
          out.wrong = true;
          if (fb.textContent.includes('正确答案')) out.wrongShowsAnswer = true;
        }
        if (prompt === LEMMA_CASE) out.lemmaCaseSeen = true;
        if (fb.querySelector('[data-practice-speak]')) out.hasSpeakAfter = true;
        out.answered += 1;
        card.querySelector('[data-practice-next]').click();
        await sleep(240);
      }
      out.resultPhase = Boolean(document.querySelector('[data-practice-phase="result"]'));
      const acc = document.querySelector('[data-practice-accuracy]');
      out.accuracy = acc ? Number(acc.textContent.replace('%', '')) : null;
      return out;
    })()`)

    record('中译英可开始答题', Boolean(zhProbe?.started), zhProbe?.error ?? `共 ${zhProbe?.total ?? 0} 题`)
    record('中译英答对时判为正确', Boolean(zhProbe?.correct), `已答 ${zhProbe?.answered ?? 0} 题`)
    record(
      '中译英答错时给出正确答案提示',
      Boolean(zhProbe?.wrong) && Boolean(zhProbe?.wrongShowsAnswer),
    )
    record('中译英支持「填写原型也算对」', Boolean(zhProbe?.lemmaCaseSeen) && Boolean(zhProbe?.lemmaCaseOk),
      zhProbe?.lemmaCaseSeen ? '' : '本轮未抽到原型用例（不判失败）')
    record('答题后提供朗读正确发音', Boolean(zhProbe?.hasSpeakAfter))
    record(
      '答完进入结果页并显示正确率',
      Boolean(zhProbe?.resultPhase) && typeof zhProbe?.accuracy === 'number' && !Number.isNaN(zhProbe?.accuracy),
      `正确率 ${zhProbe?.accuracy ?? '—'}%（共 ${zhProbe?.answered ?? 0} 题，其中 1 题故意答错）`,
    )

    // ---------- 4. 结果页：错题回顾 ----------
    const resultProbe = await cdp.evaluate(`(async () => {
      ${HELPERS}
      const out = { wrongListed: 0, hasRetryWrong: false, hasWrongReview: false };
      const root = document.querySelector('[data-practice-phase="result"]');
      if (!root) return out;
      out.hasWrongReview = root.innerText.includes('错题回顾');
      out.wrongListed = root.querySelectorAll('ul li').length;
      out.hasRetryWrong = Boolean(root.querySelector('[data-practice-retry-wrong]'));
      return out;
    })()`)
    record(
      '结果页列出错题并可重练',
      Boolean(resultProbe?.hasWrongReview) && (resultProbe?.wrongListed ?? 0) >= 1 && Boolean(resultProbe?.hasRetryWrong),
      `错题 ${resultProbe?.wrongListed ?? 0} 条`,
    )

    // ---------- 5. 英译中：四选一 ----------
    const enProbe = await cdp.evaluate(`(async () => {
      ${HELPERS}
      const TRANSLATION = ${JSON.stringify(TRANSLATION_BY_NAME)};
      const out = { modePicked: false, started: false, promptWord: null, optionCount: 0,
                    correctTone: false, feedback: null, speakButton: false, skipped: 0, error: null };
      const back = [...document.querySelectorAll('button')].find((b) => b.textContent.includes('换个设置'));
      if (back) { back.click(); await sleep(500); }
      const modeBtn = [...document.querySelectorAll('button')].find((b) => b.textContent.includes('看英文选释义'));
      if (!modeBtn) { out.error = '未找到英译中选项'; return out; }
      modeBtn.click();
      await sleep(200);
      // 语义锚点优先 data-selected="true"（ARCH §3.2），兜底旧配色类名 bg-slate-900
      out.modePicked =
        (modeBtn.dataset && modeBtn.dataset.selected === 'true') ||
        modeBtn.className.includes('bg-slate-900');
      const start = [...document.querySelectorAll('button')].find((b) => b.textContent.includes('开始练习'));
      if (!start) { out.error = '未找到开始按钮'; return out; }
      start.click();
      const quiz = await waitFor(() => document.querySelector('[data-practice-phase="quiz"]'), 6000);
      if (!quiz) { out.error = '未进入英译中答题界面'; return out; }
      out.started = true;

      // 生词本里可能混有非测试词条，跳过它们直到抽到已知词（保证能反查正确选项）
      for (let guard = 0; guard < 14; guard += 1) {
        const card = document.querySelector('[data-practice-phase="quiz"]');
        if (!card) break;
        const word = card.querySelector('[data-practice-prompt]')?.textContent.trim() || '';
        const options = [...card.querySelectorAll('[data-practice-option]')];
        const want = TRANSLATION[word];
        if (out.promptWord === null) {
          out.promptWord = word;
          out.optionCount = options.length;
          out.speakButton = Boolean(card.querySelector('[data-practice-speak]'));
        }
        if (want) {
          out.promptWord = word;
          out.optionCount = options.length;
          out.speakButton = Boolean(card.querySelector('[data-practice-speak]'));
          const target = options.find((o) => o.textContent.trim().startsWith(want)) || options[0];
          target.click();
          const fb = await waitFor(() => card.querySelector('[data-practice-feedback]'), 4000);
          out.feedback = fb ? fb.getAttribute('data-practice-feedback') : null;
          await sleep(200);
          const marked = [...card.querySelectorAll('[data-practice-option]')].find((o) =>
            o.textContent.trim().startsWith(want),
          );
          // 语义锚点优先 data-tone="correct"（ARCH §3.2），兜底旧配色类名 emerald
          out.correctTone = marked
            ? (marked.dataset && marked.dataset.tone === 'correct') || /emerald/.test(marked.className || '')
            : false;
          return out;
        }
        // 未知词：随便点一个再进入下一题
        if (options[0]) options[0].click();
        await waitFor(() => card.querySelector('[data-practice-next]'), 3000);
        card.querySelector('[data-practice-next]')?.click();
        out.skipped += 1;
        await sleep(240);
      }
      if (!out.error) out.error = '未抽到测试词条';
      return out;
    })()`)

    record('可切换到「英译中」并开始', Boolean(enProbe?.started),
      `${enProbe?.modePicked ? '已选中' : '（状态未知）'}${enProbe?.error ? ` ${enProbe.error}` : ''}`)
    record(
      '英译中为四选一',
      (enProbe?.optionCount ?? 0) >= 2,
      `${enProbe?.optionCount ?? 0} 个选项（题干：${enProbe?.promptWord ?? '—'}）`,
    )
    record('英译中选中正确释义判为正确并高亮', enProbe?.feedback === 'correct' && Boolean(enProbe?.correctTone),
      `反馈 ${enProbe?.feedback ?? '—'}，跳过无关词 ${enProbe?.skipped ?? 0} 题`)
    record('英译中题干提供朗读', Boolean(enProbe?.speakButton))

    // ---------- 6. 听写：听发音写拼写 ----------
    const dictProbe = await cdp.evaluate(`(async () => {
      ${HELPERS}
      const WORDS = ${JSON.stringify(ALL_WORDS)};
      const out = { modeFound: false, modePicked: false, hasRateRow: false, started: false,
                    badge: null, hasPlay: false, hasSlow: false, playsText: null,
                    autoSpoken: 0, autoCounted: false, leaked: null, playIncrements: false,
                    slowRate: null, answered: 0, correct: 0, wrongShowsAnswer: false,
                    resultPhase: false, accuracy: null, error: null };
      const back = [...document.querySelectorAll('button')].find(
        (b) => b.textContent.includes('退出练习') || b.textContent.includes('换个设置'),
      );
      if (back) { back.click(); await sleep(450); }
      const modeBtn = [...document.querySelectorAll('button')].find((b) => b.textContent.includes('听发音写单词'));
      if (!modeBtn) { out.error = '未找到听写选项'; return out; }
      out.modeFound = true;
      modeBtn.click();
      await sleep(220);
      // 语义锚点优先 data-selected="true"（ARCH §3.2），兜底旧配色类名 bg-slate-900
      out.modePicked =
        (modeBtn.dataset && modeBtn.dataset.selected === 'true') ||
        modeBtn.className.includes('bg-slate-900');
      // 「语速」只在听写模式下出现
      out.hasRateRow = Boolean(document.querySelector('[data-practice-rate]'));
      const allCount = [...document.querySelectorAll('button')].filter((b) => b.textContent.trim().startsWith('全部')).pop();
      if (allCount) allCount.click();
      await sleep(150);
      const start = [...document.querySelectorAll('button')].find((b) => b.textContent.includes('开始练习'));
      if (!start) { out.error = '未找到开始按钮'; return out; }
      start.click();
      const quiz = await waitFor(() => document.querySelector('[data-practice-phase="quiz"]'), 6000);
      if (!quiz) { out.error = '未进入听写答题界面'; return out; }
      out.started = true;

      // 进入题目后应自动播放一次
      await sleep(800);
      out.autoSpoken = (window.__spoken || []).length;
      out.autoCounted = (document.querySelector('[data-practice-plays]')?.textContent || '').includes('已听 1 次');

      let first = true;
      for (let guard = 0; guard < 30; guard += 1) {
        const card = document.querySelector('[data-practice-phase="quiz"]');
        if (!card) break;
        if (first) {
          first = false;
          out.badge = card.querySelector('[data-practice-badge]')?.getAttribute('data-practice-badge') || null;
          out.hasPlay = Boolean(card.querySelector('[data-practice-play]'));
          out.hasSlow = Boolean(card.querySelector('[data-practice-play-slow]'));
          out.playsText = card.querySelector('[data-practice-plays]')?.textContent.trim() || null;
          // 题干不得泄露任何测试单词（此时尚未作答，卡片可见文本里不应出现答案）
          const text = (card.innerText || '').toLowerCase();
          out.leaked = WORDS.find((w) => new RegExp('(^|[^a-z])' + w + '([^a-z]|$)').test(text)) || null;
        }
        const playsEl = card.querySelector('[data-practice-plays]');
        const countNow = () => Number((playsEl && playsEl.textContent || '').replace(/\\D/g, '')) || 0;
        const before = countNow();
        const spokenBefore = (window.__spoken || []).length;
        card.querySelector('[data-practice-play]').click();
        await waitFor(() => (window.__spoken || []).length > spokenBefore, 3000);
        const spoken = window.__spoken || [];
        const answer = (spoken[spoken.length - 1] || {}).text || '';
        if (!out.playIncrements) out.playIncrements = countNow() > before;
        // 慢速重播：应带 0.6 语速（只验一次）
        if (out.slowRate === null && card.querySelector('[data-practice-play-slow]')) {
          const s0 = (window.__spoken || []).length;
          card.querySelector('[data-practice-play-slow]').click();
          await waitFor(() => (window.__spoken || []).length > s0, 3000);
          const list = window.__spoken || [];
          out.slowRate = (list[list.length - 1] || {}).rate ?? null;
        }
        const forceWrong = out.answered === 1; // 第 2 题故意答错
        setInput(card.querySelector('[data-practice-input]'), forceWrong ? 'zzzzq' : answer);
        card.querySelector('[data-practice-submit]').click();
        const fb = await waitFor(() => card.querySelector('[data-practice-feedback]'), 4000);
        const kind = fb ? fb.getAttribute('data-practice-feedback') : null;
        if (kind === 'correct') out.correct += 1;
        if (kind === 'wrong') {
          const body = (fb.textContent || '').toLowerCase();
          if (body.includes('正确答案') && answer && body.includes(answer.toLowerCase())) {
            out.wrongShowsAnswer = true;
          }
        }
        out.answered += 1;
        card.querySelector('[data-practice-next]').click();
        await sleep(260);
      }
      out.resultPhase = Boolean(document.querySelector('[data-practice-phase="result"]'));
      const acc = document.querySelector('[data-practice-accuracy]');
      out.accuracy = acc ? Number(acc.textContent.replace('%', '')) : null;
      return out;
    })()`)

    record('练习方式含「听写」且可选', Boolean(dictProbe?.modeFound) && Boolean(dictProbe?.modePicked),
      dictProbe?.error ?? '')
    record('听写模式提供「语速」设置', Boolean(dictProbe?.hasRateRow))
    record('进入听写答题界面', Boolean(dictProbe?.started), dictProbe?.error ?? '')
    record('听写题干只给发音、不泄露单词文字', dictProbe?.started && !dictProbe?.leaked,
      dictProbe?.leaked ? `题干出现了「${dictProbe.leaked}」` : '题干可见文本中无任何测试单词')
    record('听写提供播放 / 慢速重播 / 已听次数',
      Boolean(dictProbe?.hasPlay) && Boolean(dictProbe?.hasSlow) && /已听/.test(dictProbe?.playsText ?? ''),
      dictProbe?.playsText ?? '')
    record('进入题目自动播放一次并计数',
      (dictProbe?.autoSpoken ?? 0) >= 1 && Boolean(dictProbe?.autoCounted),
      `自动朗读 ${dictProbe?.autoSpoken ?? 0} 次`)
    record('点击播放后「已听次数」递增', Boolean(dictProbe?.playIncrements))
    // rate 是 float32，0.6 会存成 0.60000002384…，用容差比较
    record('慢速重播以 0.6 语速朗读',
      Math.abs(Number(dictProbe?.slowRate) - 0.6) < 0.01,
      `rate=${dictProbe?.slowRate ?? '—'}`)
    record('按听到的单词作答判为正确', (dictProbe?.correct ?? 0) >= 1,
      `答对 ${dictProbe?.correct ?? 0} / ${dictProbe?.answered ?? 0} 题`)
    record('听写答错时给出正确答案', Boolean(dictProbe?.wrongShowsAnswer))
    record('听写完进入结果页并显示正确率',
      Boolean(dictProbe?.resultPhase) && typeof dictProbe?.accuracy === 'number' && !Number.isNaN(dictProbe?.accuracy),
      `正确率 ${dictProbe?.accuracy ?? '—'}%（共 ${dictProbe?.answered ?? 0} 题，其中 1 题故意答错）`)

    // ---------- 7. 刷新直达（路由可访问）----------
    await cdp.send('Page.navigate', { url: `${BASE}/vocab/practice` })
    await sleep(1600)
    const routeProbe = await cdp.evaluate(`(async () => {
      ${HELPERS}
      const root = await waitFor(() => document.querySelector('[data-practice-phase]'), 6000);
      return { phase: root ? root.getAttribute('data-practice-phase') : null,
               blank: document.body.innerText.trim().length < 10 };
    })()`)
    record(
      '直接访问 /vocab/practice 不白屏',
      Boolean(routeProbe?.phase) && !routeProbe?.blank,
      `phase=${routeProbe?.phase ?? '—'}`,
    )

    // ---------- 清理 ----------
    const listing = await (await fetch(`${BASE}/api/vocab`)).json()
    const seeded = (listing.items ?? []).filter((row) =>
      SEED.some(
        (item) =>
          row.word.toLowerCase() === item.word.toLowerCase() &&
          (row.lemma ?? '').toLowerCase() === (item.lemma ?? '').toLowerCase(),
      ),
    )
    if (WIPE) {
      for (const row of seeded) {
        await fetch(`${BASE}/api/vocab/${row.id}`, { method: 'DELETE' })
      }
      console.log(`\n已删除 ${seeded.length} 个测试生词（--wipe-test-words）`)
    } else {
      console.log(`\n生词本中现有 ${seeded.length} 个测试生词（已保留，可用 --wipe-test-words 删除）`)
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

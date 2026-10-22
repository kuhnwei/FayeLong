/** 端到端验证脚本的登录辅助（v1.12 起站点需要登录）。
 *
 * 验证脚本有两条通道，都要带会话：
 * 1. **Node 侧**：造数据、断言接口。这里用「给 `globalThis.fetch` 打补丁」的方式，
 *    让脚本里已有的 `fetch(...)` 调用自动带上 Cookie —— 否则要逐个改成 `api()`，
 *    改动面大且容易漏。
 * 2. **浏览器侧**：真实点击必须落在已登录会话里，用 CDP `Network.setCookie` 注入，
 *    必须在 `Page.navigate` 之前调用。
 *
 * 账号来源：环境变量 `FAYELONG_TEST_USER` / `FAYELONG_TEST_PASS`
 * （默认 `faye` / `FayeLong2026`）。站点尚未初始化时脚本会自动完成首次初始化，
 * 所以「干净 data/」与「已建号」两种环境都能跑。
 *
 * 用法（每个脚本 3 行）：
 *   import { installSessionInBrowser, patchFetchForSession } from './lib/session.mjs'
 *   patchFetchForSession(BASE)                       // 定义 BASE 之后
 *   await installSessionInBrowser(cdp, BASE)         // Runtime.enable 之后、navigate 之前
 */

const USER = process.env.FAYELONG_TEST_USER || 'faye'
const PASS = process.env.FAYELONG_TEST_PASS || 'FayeLong2026'
const COOKIE_NAME = 'fayelong_session'

/** 模块加载时就抓住原生 fetch，避免打补丁后递归调用自己 */
const rawFetch = globalThis.fetch.bind(globalThis)

let cookieValue = null
let patched = false

/** 登录（或首次初始化）并拿到会话 cookie 值。 */
export async function ensureSession(base) {
  if (cookieValue) return cookieValue

  const statusRes = await rawFetch(`${base}/api/auth/status`)
  if (!statusRes.ok) {
    throw new Error(`无法读取鉴权状态（HTTP ${statusRes.status}），后端启动了吗？`)
  }
  const status = await statusRes.json()
  const path = status.needs_setup ? 'setup' : 'login'

  const res = await rawFetch(`${base}/api/auth/${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: USER, password: PASS }),
  })
  if (!res.ok) {
    const detail = await res.text().catch(() => '')
    throw new Error(
      `${status.needs_setup ? '初始化' : '登录'}失败（HTTP ${res.status}）：${detail}\n` +
        '若站点已有账号，请用 FAYELONG_TEST_USER / FAYELONG_TEST_PASS 传入正确账号。',
    )
  }

  const raw = res.headers.getSetCookie().find((c) => c.startsWith(`${COOKIE_NAME}=`))
  if (!raw) throw new Error('登录响应里没有会话 cookie')
  cookieValue = raw.split(';')[0].slice(COOKIE_NAME.length + 1)
  return cookieValue
}

/** 给 Node 侧 fetch 打补丁：访问本站的请求自动带会话。 */
export function patchFetchForSession(base) {
  if (patched) return
  patched = true
  globalThis.fetch = async (input, init = {}) => {
    const url = typeof input === 'string' ? input : (input?.url ?? '')
    if (url.startsWith(base)) {
      const value = await ensureSession(base)
      const headers = new Headers(init.headers)
      if (!headers.has('Cookie')) headers.set('Cookie', `${COOKIE_NAME}=${value}`)
      return rawFetch(url, { ...init, headers })
    }
    return rawFetch(input, init)
  }
}

/** 把会话 cookie 注入无头浏览器（须在 Page.navigate 之前调用）。 */
export async function installSessionInBrowser(cdp, base) {
  const value = await ensureSession(base)
  const { hostname } = new URL(base)
  await cdp.send('Network.enable')
  await cdp.send('Network.setCookie', {
    name: COOKIE_NAME,
    value,
    domain: hostname,
    path: '/',
    httpOnly: true,
  })
}

/** 带会话的 Node 侧请求（不想给全局 fetch 打补丁时用这个）。 */
export async function apiFetch(base, path, init = {}) {
  const value = await ensureSession(base)
  const headers = new Headers(init.headers)
  headers.set('Cookie', `${COOKIE_NAME}=${value}`)
  if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  return rawFetch(`${base}${path}`, { ...init, headers })
}

export const TEST_ACCOUNT = { password: PASS, username: USER }

// ---------------------------------------------------------------------------
// 免登录「铸牌」（P1 Round C 新增；**不影响上面的既有导出**）
//
// 为什么需要：`ensureSession()` 走的是 `POST /api/auth/login`，而后端登录成功会
// 写 `users.last_login_at` —— 对「只读验证」来说是多余的数据变更。这里改为
// **只读**读出签名密钥后、在 Node 侧用内置 crypto 现签一个等价的会话 cookie，
// 全程**零写库**。
//
// 与 `backend/app/services/auth.py` 对齐的要点（照实现抄，未猜）：
//   cookie 名 : `fayelong_session`（= 本文件既有的 COOKIE_NAME）
//   secret    : `settings` 表 `auth.secret` 的 hex → bytes（32 字节）
//   token     : `base64url(JSON.stringify({uid, exp}))` + "." + `base64url(HMAC-SHA256(secret, body))`
//               —— JSON 无空格（对应 Python `separators=(",", ":")`）、base64 **无填充**、
//                  HMAC 输入是 body 字符串的 **ascii** 字节
//   payload   : `{ "uid": <int>, "exp": <int 秒级时间戳> }`（键序 uid → exp）
//   校验      : 签名 compare_digest 相等 且 exp > now 且 uid / exp 均为 int
// ---------------------------------------------------------------------------

/** 默认的库路径：`<repo>/data/app.db`（可用环境变量 FAYELONG_DB_PATH 覆盖）。 */
async function defaultDbPath() {
  const { fileURLToPath } = await import('node:url')
  const { dirname, resolve, join } = await import('node:path')
  if (process.env.FAYELONG_DB_PATH) return resolve(process.env.FAYELONG_DB_PATH)
  const here = dirname(fileURLToPath(import.meta.url)) // scripts/lib
  return join(resolve(here, '..', '..'), 'data', 'app.db')
}

/**
 * 从真实库**只读**读出签名密钥与站点账号 id（Node 内置 `node:sqlite`，只读连接）。
 * @returns {Promise<{ secret: Buffer, uid: number }>}
 */
export async function readAuthSecret(dbPath) {
  const { DatabaseSync } = await import('node:sqlite')
  const db = new DatabaseSync(dbPath ?? (await defaultDbPath()), { readOnly: true })
  try {
    const secretRow = db.prepare("SELECT value FROM settings WHERE key = 'auth.secret'").get()
    if (!secretRow || !secretRow.value) {
      throw new Error('库中缺少 settings.auth.secret（站点可能从未登录过，无法铸牌）')
    }
    const userRow = db.prepare('SELECT id FROM users ORDER BY id LIMIT 1').get()
    if (!userRow) throw new Error('users 表为空（站点尚未初始化账号）')
    return { secret: Buffer.from(String(secretRow.value), 'hex'), uid: Number(userRow.id) }
  } finally {
    db.close()
  }
}

/**
 * 现签一个后端认可的 `fayelong_session` token（**零写库**）。
 * @returns {Promise<string>} token 值
 */
export async function mintSessionToken(dbPath, ttlSeconds = 30 * 86400) {
  const { createHmac } = await import('node:crypto')
  const { secret, uid } = await readAuthSecret(dbPath)
  const payload = JSON.stringify({ uid, exp: Math.floor(Date.now() / 1000) + ttlSeconds })
  const body = Buffer.from(payload, 'utf8').toString('base64url')
  const signature = createHmac('sha256', secret).update(body, 'ascii').digest('base64url')
  return `${body}.${signature}`
}

/**
 * 「铸牌」版会话注入：与 `installSessionInBrowser` 语义相同，但**不登录、零写库**
 * （不写 `users.last_login_at`）。须在 `Page.navigate` 之前调用。
 * @returns {Promise<string>} 注入的 token（便于调用方断言）
 */
export async function installSessionInBrowserByMint(cdp, base, dbPath) {
  const value = await mintSessionToken(dbPath)
  const { hostname } = new URL(base)
  await cdp.send('Network.enable')
  await cdp.send('Network.setCookie', {
    name: COOKIE_NAME,
    value,
    domain: hostname,
    path: '/',
    httpOnly: true,
  })
  return value
}

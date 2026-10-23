/**
 * 请求基础设施：接口前缀、超时、统一错误、401 广播、`request()` / `readError()`。
 *
 * 开发期由 Vite 代理 `/api` 到 `127.0.0.1:8000`（见 `vite.config.ts`）；
 * 生产由后端同源托管（单端口），所以 `BASE` **保持相对路径**，不要改成绝对 URL。
 */

/** 后端接口前缀（相对路径）。 */
export const BASE = '/api'

/** 单次请求超时（毫秒）。后端全本地，超过基本意味着进程卡住或未启动。 */
const REQUEST_TIMEOUT = 30_000

/** 网络层错误的统一文案（连接失败 / 超时 / 中断）。 */
class NetworkError extends Error {}

/** 带 HTTP 状态码的错误（业务/权限错误，前端可按 status 区分处理）。 */
export class HttpError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.name = 'HttpError'
    this.status = status
  }
}

/** 收到 401 时广播的事件名：App 监听它把界面切回登录页。 */
export const UNAUTHORIZED_EVENT = 'fayelong:unauthorized'

/** 统一请求封装：超时、同源 cookie、401 广播、错误解析。 */
export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  if (init.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT)

  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, {
      ...init,
      headers,
      // 会话是 HttpOnly cookie，必须显式带上（同源请求）
      credentials: 'same-origin',
      signal: init.signal ?? controller.signal,
    })
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new NetworkError('请求超时：后端可能正忙或未启动，请稍后重试')
    }
    throw new NetworkError('无法连接后端服务，请确认它已启动')
  } finally {
    window.clearTimeout(timer)
  }

  if (res.status === 401) {
    window.dispatchEvent(new Event(UNAUTHORIZED_EVENT))
    throw new HttpError(await readError(res), 401)
  }
  if (res.status === 403) {
    // 403 = 已登录但无权限：**不**广播 unauthorized（否则会把管理员误踢回登录页）。
    throw new HttpError(await readError(res), 403)
  }
  if (!res.ok) {
    throw new HttpError(await readError(res), res.status)
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

/** 从错误响应里解析出可读文案。 */
export async function readError(res: Response): Promise<string> {
  try {
    const data = await res.json()
    const detail = (data as { detail?: unknown }).detail
    if (typeof detail === 'string') return detail
    if (detail) return JSON.stringify(detail)
  } catch {
    /* 忽略解析失败 */
  }
  return `请求失败（HTTP ${res.status}）`
}

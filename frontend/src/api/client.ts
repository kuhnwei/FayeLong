/** 后端 API 封装。开发期由 Vite 代理 /api 到 127.0.0.1:8000。 */

const BASE = '/api'

export const MEDIA_STATUS = {
  PENDING: 'pending',
  TRANSCODING: 'transcoding',
  READY: 'ready',
  ASR: 'asr',
  TRANSLATING: 'translating',
  CLIPPING: 'clipping',
  DONE: 'done',
  FAILED: 'failed',
} as const

/** 处理中（前端需要轮询刷新）的状态 */
export const PROCESSING_STATUSES: string[] = [
  MEDIA_STATUS.PENDING,
  MEDIA_STATUS.TRANSCODING,
  MEDIA_STATUS.ASR,
  MEDIA_STATUS.TRANSLATING,
  MEDIA_STATUS.CLIPPING,
]

/** 可播放的状态 */
export const PLAYABLE_STATUSES: string[] = [
  MEDIA_STATUS.READY,
  MEDIA_STATUS.ASR,
  MEDIA_STATUS.TRANSLATING,
  MEDIA_STATUS.CLIPPING,
  MEDIA_STATUS.DONE,
]

export const STATUS_LABEL: Record<string, string> = {
  pending: '排队中',
  transcoding: '转码中',
  ready: '可播放',
  asr: '识别中',
  translating: '翻译中',
  clipping: '切片中',
  done: '已完成',
  failed: '处理失败',
}

// --------------------------- 请求基础设施 ---------------------------

/** 单次请求超时（毫秒）。后端全本地，超过基本意味着进程卡住或未启动。 */
const REQUEST_TIMEOUT = 30_000

/** 网络层错误的统一文案（连接失败 / 超时 / 中断）。 */
class NetworkError extends Error {}

/** 收到 401 时广播的事件名：App 监听它把界面切回登录页。 */
export const UNAUTHORIZED_EVENT = 'fayelong:unauthorized'

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
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
    throw new Error(await readError(res))
  }
  if (!res.ok) {
    throw new Error(await readError(res))
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

async function readError(res: Response): Promise<string> {
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

// --------------------------- 类型 ---------------------------

export interface HealthResponse {
  status: string
  app: string
  version: string
  checks: {
    database: boolean
    ffmpeg: boolean
    ffprobe: boolean
    asr: boolean
    asr_model: boolean
    dict: boolean
  }
  config: { whisper_model: string; translate_engines: string[] }
  asr: { installed: boolean; ready: boolean; model: string; dir: string; endpoint: string }
  dict: { installed: boolean; path: string; size_bytes: number; entries: number }
  paths: { data_dir: string; inbox_dir: string; db: string }
  media: { total: number; ready: number }
}

export interface MediaItem {
  id: number
  title: string
  type: 'audio' | 'video'
  original_name: string
  duration_ms: number
  size_bytes: number
  status: string
  progress: number
  error: string | null
  origin: 'upload' | 'inbox'
  created_at: string
  has_audio: boolean
  stream_url: string
  sentence_count: number
}

export interface SentenceItem {
  id: number
  idx: number
  start_ms: number
  end_ms: number
  text_en: string
  text_zh: string
  is_edited: boolean
  clip_url: string | null
  /** 听写统计（M3） */
  attempt_count: number
  best_accuracy: number
  last_accuracy: number | null
  last_input: string
  mastered: boolean
  /** 原文易听错标记（v1.14）：闭区间 [起始词序, 结束词序]，0 基 */
  marks: number[][]
}

/** 媒体级听写进度汇总 */
export interface DictationSummary {
  sentences: number
  attempted: number
  mastered: number
  total_attempts: number
  avg_best_accuracy: number
}

export interface MediaDetail extends MediaItem {
  sentences: SentenceItem[]
  dictation: DictationSummary | null
}

export interface MediaListResponse {
  items: MediaItem[]
  total: number
}

export interface InboxItem {
  name: string
  path: string
  ext: string
  supported: boolean
  size_bytes: number
  imported: boolean
}

export interface InboxResponse {
  inbox_dir: string
  items: InboxItem[]
}

/** 处理进度事件（SSE / 轮询共用） */
export interface ProgressEventData {
  media_id: number
  status: string
  progress: number
  stage: string
  error: string | null
  sentence_count: number
  done: boolean
}

/** 句子编辑载荷（只传要改的字段） */
export interface SentencePatch {
  text_en?: string
  text_zh?: string
  start_ms?: number
  end_ms?: number
  /** 易听错标记：传了就整体替换（空数组 = 清空） */
  marks?: number[][]
}

// --------------------------- M3：听写 ---------------------------

export type DiffTokenType = 'correct' | 'wrong' | 'missing' | 'extra'

/** 词级对齐结果中的一个位置 */
export interface DiffToken {
  type: DiffTokenType
  expected: string | null
  actual: string | null
}

/** 一次听写的校验结果 + 该句累计统计 */
export interface AttemptResult {
  sentence_id: number
  attempt_id: number
  input: string
  accuracy: number
  is_correct: boolean
  tokens: DiffToken[]
  total_words: number
  correct: number
  wrong: number
  missing: number
  extra: number
  attempt_count: number
  best_accuracy: number
  mastered: boolean
  created_at: string
}

export interface AttemptRecord {
  id: number
  input: string
  accuracy: number
  is_correct: boolean
  created_at: string
}

// --------------------------- 接口 ---------------------------

export const getHealth = () => request<HealthResponse>('/health')

export const listMedia = () => request<MediaListResponse>('/media')

export const getMedia = (id: number) => request<MediaDetail>(`/media/${id}`)

export const listInbox = () => request<InboxResponse>('/media/inbox')

export const importFromInbox = (files?: string[]) =>
  request<MediaListResponse>('/media/import', {
    method: 'POST',
    body: JSON.stringify({ files: files ?? null }),
  })

export const updateMedia = (id: number, title: string) =>
  request<MediaItem>(`/media/${id}`, {
    method: 'PATCH',
    body: JSON.stringify({ title }),
  })

export const retryMedia = (id: number) =>
  request<MediaItem>(`/media/${id}/retry`, { method: 'POST' })

/** 重新识别（保留已转码音频）：会重建句表 */
export const retranscribeMedia = (id: number) =>
  request<MediaItem>(`/media/${id}/retranscribe`, { method: 'POST' })

export const deleteMedia = (id: number) =>
  request<void>(`/media/${id}`, { method: 'DELETE' })

// --------------------------- M2：句子编辑 ---------------------------

export const updateSentence = (id: number, patch: SentencePatch) =>
  request<MediaDetail>(`/sentences/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  })

export const splitSentence = (
  id: number,
  payload: { at_ms: number; text_left?: string; text_right?: string },
) =>
  request<MediaDetail>(`/sentences/${id}/split`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })

export const mergeSentence = (id: number, direction: 'next' | 'prev' = 'next') =>
  request<MediaDetail>(`/sentences/${id}/merge`, {
    method: 'POST',
    body: JSON.stringify({ direction }),
  })

export const retranslateSentence = (id: number) =>
  request<MediaDetail>(`/sentences/${id}/retranslate`, { method: 'POST' })

export const clearClips = (mediaId: number) =>
  request<{ media_id: number; cleared: boolean; clips_dir: string }>(
    `/media/${mediaId}/clips`,
    { method: 'DELETE' },
  )

// --------------------------- M3：听写 ---------------------------

/** 提交一次听写：由服务端做词级比对（唯一判定源）并落库 */
export const submitAttempt = (sentenceId: number, input: string) =>
  request<AttemptResult>('/attempts', {
    method: 'POST',
    body: JSON.stringify({ sentence_id: sentenceId, input }),
  })

/** 某句的听写历史（倒序） */
export const listAttempts = (sentenceId: number, limit = 20) =>
  request<{ items: AttemptRecord[]; total: number }>(
    `/sentences/${sentenceId}/attempts?limit=${limit}`,
  )

/**
 * 订阅处理进度（SSE）。返回取消函数。
 * 若浏览器/代理不支持 SSE，调用方应保留轮询兜底。
 */
export function openProgressStream(
  mediaId: number,
  onEvent: (event: ProgressEventData) => void,
  onError?: () => void,
): () => void {
  if (typeof EventSource === 'undefined') {
    onError?.()
    return () => {}
  }
  const source = new EventSource(`${BASE}/media/${mediaId}/progress`)
  source.onmessage = (message) => {
    try {
      onEvent(JSON.parse(message.data) as ProgressEventData)
    } catch {
      /* 忽略无法解析的帧 */
    }
  }
  source.onerror = () => {
    source.close()
    onError?.()
  }
  return () => source.close()
}

/** 上传单个文件（带进度回调）。用 XHR 是因为 fetch 不支持上传进度。 */
export function uploadMedia(
  file: File,
  onProgress?: (percent: number) => void,
): Promise<MediaItem> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `${BASE}/media`)
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && onProgress) {
        onProgress(Math.round((event.loaded / event.total) * 100))
      }
    }
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText) as MediaItem)
        } catch {
          reject(new Error('服务端返回内容解析失败'))
        }
      } else {
        let message = `上传失败（HTTP ${xhr.status}）`
        try {
          const data = JSON.parse(xhr.responseText) as { detail?: string }
          if (data.detail) message = data.detail
        } catch {
          /* 忽略 */
        }
        reject(new Error(message))
      }
    }
    xhr.onerror = () => reject(new Error('网络错误，上传失败'))
    xhr.onabort = () => reject(new Error('上传已取消'))
    const form = new FormData()
    form.append('file', file)
    xhr.send(form)
  })
}

// --------------------------- M4：词典 / 生词本 / 笔记 ---------------------------

/** 词形变化的一项 */
export interface DictFormItem {
  label: string
  value: string
}

/** 一次查词结果 */
export interface DictResult {
  query: string
  word: string
  found: boolean
  notice: string | null
  lemma: string | null
  via: string
  phonetic: string
  translation: string[]
  definition: string[]
  pos: string
  tags: string[]
  collins: number
  oxford: number
  exchange: Record<string, string>
  forms: DictFormItem[]
  source: string
  oxford_url: string
  longman_url: string
}

/** 一条生词 */
export interface VocabItem {
  id: number
  word: string
  lemma: string | null
  phonetic: string | null
  translation: string | null
  media_id: number | null
  sentence_id: number | null
  context: string | null
  mastered: boolean
  created_at: string
  media_title: string | null
  duplicated: boolean
}

export interface VocabListResponse {
  items: VocabItem[]
  total: number
  mastered: number
}

export interface VocabCreatePayload {
  word: string
  lemma?: string | null
  phonetic?: string | null
  translation?: string | null
  media_id?: number | null
  sentence_id?: number | null
  context?: string | null
}

/** 一句的笔记 */
export interface NoteItem {
  sentence_id: number
  content: string
  updated_at: string | null
  exists: boolean
}

/** 查词（含词形还原） */
export const lookupWord = (word: string) =>
  request<DictResult>(`/dict/${encodeURIComponent(word)}`)

/** 生词本列表 */
export const listVocab = (params: { mastered?: boolean; q?: string } = {}) => {
  const search = new URLSearchParams()
  if (params.mastered !== undefined) search.set('mastered', String(params.mastered))
  if (params.q) search.set('q', params.q)
  const qs = search.toString()
  return request<VocabListResponse>(`/vocab${qs ? `?${qs}` : ''}`)
}

/** 加入生词本（同词重复添加不会产生重复记录） */
export const addVocab = (payload: VocabCreatePayload) =>
  request<VocabItem>('/vocab', { method: 'POST', body: JSON.stringify(payload) })

/** 修改生词（释义 / 上下文 / 是否已掌握） */
export const updateVocab = (
  id: number,
  patch: { translation?: string; context?: string; mastered?: boolean },
) => request<VocabItem>(`/vocab/${id}`, { method: 'PATCH', body: JSON.stringify(patch) })

/** 删除生词 */
export const deleteVocab = (id: number) => request<void>(`/vocab/${id}`, { method: 'DELETE' })

/** 生词本导出 Markdown 的下载地址（浏览器直接打开即可下载） */
export const vocabExportUrl = (mastered?: boolean) =>
  `${BASE}/vocab/export${mastered !== undefined ? `?mastered=${mastered}` : ''}`

/** 读取句子笔记 */
export const getNote = (sentenceId: number) => request<NoteItem>(`/notes/${sentenceId}`)

/** 保存句子笔记（内容为空即删除） */
export const saveNote = (sentenceId: number, content: string) =>
  request<NoteItem>(`/notes/${sentenceId}`, {
    method: 'PUT',
    body: JSON.stringify({ content }),
  })

// --------------------------- M5：笔记汇总 / 全局统计 ---------------------------

/** 笔记汇总里的一条：句子 + 笔记 + 听写概要 */
export interface MediaNoteItem {
  sentence_id: number
  idx: number
  text_en: string
  text_zh: string
  content: string
  updated_at: string | null
  attempt_count: number
  best_accuracy: number
  mastered: boolean
}

export interface MediaNotesResponse {
  media_id: number
  title: string
  total: number
  sentence_count: number
  items: MediaNoteItem[]
}

/** 全局学习概览 */
export interface StatsResponse {
  media: { total: number; done: number; processing: number; failed: number }
  sentences: number
  notes: number
  vocab: { total: number; mastered: number }
  attempts: { total: number; attempted_sentences: number; mastered_sentences: number }
}

/** 某媒体的句子笔记汇总 */
export const getMediaNotes = (mediaId: number) =>
  request<MediaNotesResponse>(`/media/${mediaId}/notes`)

/** 笔记导出 Markdown 的下载地址 */
export const mediaNotesExportUrl = (mediaId: number) => `${BASE}/media/${mediaId}/notes/export`

/** 全局学习概览 */
export const getStats = () => request<StatsResponse>('/stats')

// --------------------------- 鉴权（v1.12） ---------------------------

/** 站点鉴权状态：决定渲染「首次设置」「登录页」还是应用本体 */
export interface AuthStatus {
  needs_setup: boolean
  authenticated: boolean
  username: string | null
  min_password_length: number
}

/** 问后端：要初始化吗 / 我登录了吗。公开接口，未登录也能调。 */
export const getAuthStatus = () => request<AuthStatus>('/auth/status')

/** 首次创建账号（仅在还没有账号时可用，建完即锁定） */
export const setupAccount = (username: string, password: string) =>
  request<AuthStatus>('/auth/setup', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  })

export const login = (username: string, password: string) =>
  request<AuthStatus>('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  })

export const logout = () => request<AuthStatus>('/auth/logout', { method: 'POST' })

export const changePassword = (currentPassword: string, newPassword: string) =>
  request<AuthStatus>('/auth/password', {
    method: 'POST',
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  })

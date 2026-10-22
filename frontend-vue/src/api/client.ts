/**
 * 后端 API 封装。开发期由 Vite 代理 `/api` 到 `127.0.0.1:8000`。
 *
 * - 请求基础设施（`request` / `readError` / `UNAUTHORIZED_EVENT`）在 `./request`。
 * - 类型**不再手写**：全部取自后端契约 `contracts/api-types.d.ts`
 *   （见 `./schema`），旧的手写类型名保留为**别名**，让 P2 迁移无需改名。
 * - 少数「契约里没有对应物」的类型（SSE 帧 / 内联匿名返回 / 纯前端概念）就地定义，
 *   理由逐条写在定义处。
 */

import { BASE, request } from './request'
import type { Schemas } from './schema'

export { UNAUTHORIZED_EVENT } from './request'

// --------------------------- 状态常量（运行时值，非类型） ---------------------------

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

// --------------------------- 类型 ---------------------------
// 旧手写名 → 后端 schema（`contracts/api-types.d.ts`）别名。保留旧名，P2 无需改名。

export type MediaItem = Schemas['MediaOut']
export type SentenceItem = Schemas['SentenceOut']
export type DictationSummary = Schemas['DictationSummary']
export type MediaDetail = Schemas['MediaDetailOut']
export type MediaListResponse = Schemas['MediaListResponse']
export type CategoryItem = Schemas['CategoryOut']
export type CategoryListResponse = Schemas['CategoryListResponse']
export type MediaPatch = Schemas['MediaUpdate']
export type InboxItem = Schemas['InboxItem']
export type InboxResponse = Schemas['InboxResponse']
export type SentencePatch = Schemas['SentenceUpdate']
export type AttemptResult = Schemas['AttemptResult']
export type AttemptRecord = Schemas['AttemptRecord']
export type DictFormItem = Schemas['DictForm']
export type DictResult = Schemas['DictResult']
export type VocabItem = Schemas['VocabOut']
export type VocabListResponse = Schemas['VocabListResponse']
export type VocabCreatePayload = Schemas['VocabCreate']
export type NoteItem = Schemas['NoteOut']
export type MediaNoteItem = Schemas['MediaNoteItem']
export type MediaNotesResponse = Schemas['MediaNotesResponse']
export type StatsResponse = Schemas['StatsOut']
export type AuthStatus = Schemas['AuthStatus']

/** 听写比对展示类型（DiffToken / DiffTokenType / DiffResultData）——见 `../types/diff`。 */
export type { DiffToken, DiffResultData, DiffTokenType } from '../types/diff'

/**
 * ⚠️ 本地类型（契约里**没有**对应 schema，理由如下）：
 */
/** ① `/api/health` 后端返回的是**内联匿名 dict**（无 schema）→ 本地定义。 */
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

/** ② 删除分类的返回：后端返回**内联匿名 dict**（released = 被移入「未分类」的素材数）。 */
export interface CategoryDeleteResponse {
  id: number
  name: string
  released: number
}

/** ③ 批量移动的返回：后端返回**内联匿名 dict**（missing = ids 中不存在/已失效的媒体 id）。 */
export interface BatchCategoryResponse {
  updated: number
  category_id: number | null
  missing: number[]
}

/**
 * ⑤ 题型注册表（P4-1 新增端点 `GET /api/question-types`）。
 *
 * ⚠️ **本地类型**（不是来自 `contracts/api-types.d.ts`）：P4 是「第一次合法改变
 * 契约」（34 path / 42 op → 35/43），新 schema 要等基线重置并重跑
 * `scripts/gen-api-types.mjs` 之后才会出现在生成文件里。在那之前先在此处手写，
 * 字段与后端 `app/schemas/question_type.py` **逐字对应**；基线重置后应改为
 * `Schemas['QuestionTypeOut']` 别名（留一条 TODO 记录在 §八 报告里）。
 */
export interface QuestionTypeInfo {
  code: string
  label: string
  /** `sync` = 纯函数就地判分；`async` = 入 jobs 表由 IO 池判分（ADR-001 §7.1） */
  grade_mode: 'sync' | 'async'
  /** 判分是否依赖外部服务（为真时前端应展示降级提示） */
  requires_external: boolean
}

/** ⑤ 题型注册表响应（`{"types": [...]}`，注册表为空时 `types == []`）。 */
export interface QuestionTypeListResponse {
  types: QuestionTypeInfo[]
}

/** ④ 处理进度事件：**SSE 帧**（`/media/{id}/progress` 的 EventSource 数据），不是 REST schema。 */
export interface ProgressEventData {
  media_id: number
  status: string
  progress: number
  stage: string
  error: string | null
  sentence_count: number
  done: boolean
}

// --------------------------- 接口 ---------------------------

export const getHealth = () => request<HealthResponse>('/health')

/**
 * 题型注册表（P4-1）。
 *
 * 用途：让前端「有哪些题型」以后端为唯一真相，避免前后端两份清单漂移。
 * 调用方（`StudyPage.vue`）在**拉取失败**时必须降级到内置 `dictation`，
 * 不能因为这一个请求失败就白屏（见 `question-types/index.ts::resolve`）。
 */
export const listQuestionTypes = () => request<QuestionTypeListResponse>('/question-types')

/**
 * 素材列表。
 * @param categoryId 不传 = 全部；数字 = 该分类；`'none'` = 未分类（服务端字面量 `category_id=none`）
 */
export const listMedia = (categoryId?: number | 'none') =>
  request<MediaListResponse>(
    categoryId === undefined ? '/media' : `/media?category_id=${categoryId}`,
  )

export const getMedia = (id: number) => request<MediaDetail>(`/media/${id}`)

export const listInbox = () => request<InboxResponse>('/media/inbox')

/** 从素材目录导入；categoryId 为 null / 不传 = 导入到「未分类」 */
export const importFromInbox = (files?: string[], categoryId?: number | null) =>
  request<MediaListResponse>('/media/import', {
    method: 'POST',
    body: JSON.stringify({ files: files ?? null, category_id: categoryId ?? null }),
  })

/**
 * 改素材属性（标题 / 分类）。
 * 注意：`category_id: null` 会被真的写进请求体 —— 这是「移到未分类」的唯一表达方式，
 * 不能靠省略字段实现（后端用 `model_fields_set` 区分「未传」与「传了 null」）。
 */
export const updateMedia = (id: number, patch: MediaPatch) =>
  request<MediaItem>(`/media/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  })

export const retryMedia = (id: number) =>
  request<MediaItem>(`/media/${id}/retry`, { method: 'POST' })

/** 重新识别（保留已转码音频）：会重建句表 */
export const retranscribeMedia = (id: number) =>
  request<MediaItem>(`/media/${id}/retranscribe`, { method: 'POST' })

export const deleteMedia = (id: number) =>
  request<void>(`/media/${id}`, { method: 'DELETE' })

/** 批量移动素材到某分类（categoryId 为 null = 移到「未分类」） */
export const batchMoveCategory = (ids: number[], categoryId: number | null) =>
  request<BatchCategoryResponse>('/media/batch-category', {
    method: 'POST',
    body: JSON.stringify({ ids, category_id: categoryId }),
  })

// --------------------------- 媒体库分类 CRUD ---------------------------

/** 分类列表（含每个分类的素材数与未分类数） */
export const listCategories = () => request<CategoryListResponse>('/categories')

/** 新建分类（同名 409 / 空名或超 32 字 400） */
export const createCategory = (name: string) =>
  request<CategoryItem>('/categories', {
    method: 'POST',
    body: JSON.stringify({ name }),
  })

/** 重命名分类 */
export const updateCategory = (id: number, name: string) =>
  request<CategoryItem>(`/categories/${id}`, {
    method: 'PATCH',
    body: JSON.stringify({ name }),
  })

/** 删除分类（旗下素材回落「未分类」，不删素材） */
export const deleteCategory = (id: number) =>
  request<CategoryDeleteResponse>(`/categories/${id}`, { method: 'DELETE' })

/** 重排分类：ids 必须是当前全部分类 id 的完整有序集合（服务端按下标重写 sort_order） */
export const reorderCategories = (ids: number[]) =>
  request<CategoryListResponse>('/categories/order', {
    method: 'PATCH',
    body: JSON.stringify({ ids }),
  })

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
  request<Schemas['AttemptListResponse']>(`/sentences/${sentenceId}/attempts?limit=${limit}`)

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

/**
 * 上传单个文件（带进度回调）。用 XHR 是因为 fetch 不支持上传进度。
 * @param categoryId 选中分类时把 `category_id` 拼进 FormData；null / 不传 = 归入「未分类」
 */
export function uploadMedia(
  file: File,
  onProgress?: (percent: number) => void,
  categoryId?: number | null,
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
    // 只在真的选了分类时附加：multipart 里所有值都是字符串，
    // 传 "null" 会让后端的 int 校验炸掉，所以「未分类」就是不传该字段。
    if (categoryId !== undefined && categoryId !== null) {
      form.append('category_id', String(categoryId))
    }
    xhr.send(form)
  })
}

// --------------------------- M4：词典 / 生词本 / 笔记 ---------------------------

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

/** 某媒体的句子笔记汇总 */
export const getMediaNotes = (mediaId: number) =>
  request<MediaNotesResponse>(`/media/${mediaId}/notes`)

/** 笔记导出 Markdown 的下载地址 */
export const mediaNotesExportUrl = (mediaId: number) => `${BASE}/media/${mediaId}/notes/export`

/** 全局学习概览 */
export const getStats = () => request<StatsResponse>('/stats')

// --------------------------- 鉴权（v1.12） ---------------------------

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

// --------------------------- 开发期调试探针 ---------------------------

/** 全部 API 的聚合对象（仅供 DEV 探针使用）。 */
export const api = {
  getHealth,
  listMedia,
  getMedia,
  listInbox,
  importFromInbox,
  updateMedia,
  retryMedia,
  retranscribeMedia,
  deleteMedia,
  batchMoveCategory,
  listCategories,
  createCategory,
  updateCategory,
  deleteCategory,
  reorderCategories,
  updateSentence,
  splitSentence,
  mergeSentence,
  retranslateSentence,
  clearClips,
  submitAttempt,
  listAttempts,
  openProgressStream,
  uploadMedia,
  lookupWord,
  listVocab,
  addVocab,
  updateVocab,
  deleteVocab,
  vocabExportUrl,
  getNote,
  saveNote,
  getMediaNotes,
  mediaNotesExportUrl,
  getStats,
  getAuthStatus,
  setupAccount,
  login,
  logout,
  changePassword,
}

declare global {
  interface Window {
    /** 仅 DEV 下挂载的调试探针；生产构建里不存在。 */
    __fayeApi?: typeof api
  }
}

// `import.meta.env.DEV` 在生产构建里被替换为 `false`，整个分支随之被摇树删除，
// 产物 js 里不会留下 `__fayeApi`。
if (import.meta.env.DEV) {
  window.__fayeApi = api
}

import { useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'
import {
  PLAYABLE_STATUSES,
  PROCESSING_STATUSES,
  batchMoveCategory,
  deleteMedia,
  getHealth,
  getStats,
  importFromInbox,
  listCategories,
  listInbox,
  listMedia,
  retryMedia,
  updateMedia,
  uploadMedia,
  type CategoryItem,
  type InboxItem,
  type MediaItem,
} from '../api/client'
import { usePlayer } from '../store/player'
import { formatBytes, formatDuration, formatRelative } from '../utils/format'
import CategoryChips, { CategorySelect, type CategoryFilter } from '../components/CategoryChips'
import CategoryManager from '../components/CategoryManager'
import {
  AlertIcon,
  BookIcon,
  CloseIcon,
  FolderIcon,
  ListIcon,
  PencilIcon,
  PlayIcon,
  RefreshIcon,
  SearchIcon,
  SortIcon,
  TrashIcon,
  UploadIcon,
} from '../components/icons'

const ACCEPT =
  '.mp3,.wav,.m4a,.flac,.aac,.ogg,.opus,.wma,.mp4,.mkv,.mov,.webm,.avi,.flv,.m4v,.ts'

interface UploadTask {
  id: string
  name: string
  percent: number
  status: 'uploading' | 'done' | 'error'
  error?: string
}

const canPlay = (media: MediaItem) =>
  PLAYABLE_STATUSES.includes(media.status) || media.has_audio

// --------------------------- 小组件 ---------------------------

function TypeBadge({ media }: { media: MediaItem }) {
  const isVideo = media.type === 'video'
  return (
    <span
      className={[
        'shrink-0 rounded px-1.5 py-0.5 text-[10px]',
        isVideo ? 'bg-purple-50 text-purple-600' : 'bg-sky-50 text-sky-600',
      ].join(' ')}
    >
      {isVideo ? '视频·仅音轨' : '音频'}
    </span>
  )
}

function StatusLine({ media }: { media: MediaItem }) {
  if (media.status === 'failed') {
    return (
      <div className="mt-1.5 flex items-start gap-1.5 text-[12px] text-red-600">
        <AlertIcon className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <span>{media.error || '处理失败'}</span>
      </div>
    )
  }

  if (PROCESSING_STATUSES.includes(media.status)) {
    const label =
      media.status === 'transcoding' || media.status === 'pending'
        ? '正在转码为标准音频'
        : media.status === 'asr'
          ? '正在识别语音（faster-whisper）'
          : media.status === 'translating'
            ? '正在逐句翻译'
            : media.status === 'clipping'
              ? '正在生成句子切片'
              : '正在处理'
    return (
      <div className="mt-2">
        <div className="flex items-center justify-between text-[11px] text-slate-400">
          <span>{label}</span>
          <span className="tabular-nums">{media.progress}%</span>
        </div>
        <div className="mt-1 h-1 w-full overflow-hidden rounded-full bg-slate-100">
          <div
            className="h-full rounded-full bg-slate-900 transition-[width] duration-300"
            style={{ width: `${Math.max(2, media.progress)}%` }}
          />
        </div>
      </div>
    )
  }

  return (
    <div className="mt-1.5 flex items-center gap-1.5 text-[12px] text-emerald-600">
      <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
      <span>
        已就绪，可播放
        {media.sentence_count > 0 && `（${media.sentence_count} 句已转录）`}
      </span>
    </div>
  )
}

// --------------------------- 概览卡片（M5） ---------------------------

function StatCard({ label, value, sub }: { label: string; value: number; sub?: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white px-4 py-3">
      <p className="text-[11px] text-slate-400">{label}</p>
      <p className="mt-0.5 text-[20px] font-medium tabular-nums leading-tight text-slate-900">
        {value}
      </p>
      {sub && <p className="mt-0.5 text-[11px] text-slate-400">{sub}</p>}
    </div>
  )
}

/** 列表加载骨架屏（M5：替代干巴巴的「加载中…」） */
function ListSkeleton() {
  return (
    <div className="space-y-3 px-3 py-4 sm:px-5 sm:py-5">
      {[0, 1, 2].map((i) => (
        <div key={i} className="flex animate-pulse items-center gap-4">
          <div className="h-9 w-9 shrink-0 rounded-full bg-slate-100" />
          <div className="flex-1 space-y-2">
            <div className="h-3.5 w-1/3 rounded bg-slate-100" />
            <div className="h-3 w-2/3 rounded bg-slate-100" />
          </div>
        </div>
      ))}
    </div>
  )
}

// --------------------------- 媒体行 ---------------------------

interface MediaRowProps {
  media: MediaItem
  /** 所属分类名（父级用 ['categories'] 结果本地映射）；null = 未分类 */
  categoryName: string | null
  selectable: boolean
  checked: boolean
  onToggleSelect: (checked: boolean) => void
  onPlay: (media: MediaItem) => void
  onDelete: (media: MediaItem) => void
  onRetry: (media: MediaItem) => void
  onRename: (media: MediaItem, title: string) => void
  busy: boolean
}

/** 素材行的分类 badge：由父级传进来的分类名渲染，未分类是灰字 */
function CategoryBadge({ name }: { name: string | null }) {
  if (!name) {
    return <span className="shrink-0 text-[10px] text-slate-300">未分类</span>
  }
  return (
    <span className="inline-block max-w-[7rem] shrink-0 truncate rounded bg-slate-100 px-1.5 py-0.5 align-middle text-[10px] text-slate-600">
      {name}
    </span>
  )
}

function MediaRow({
  media,
  categoryName,
  selectable,
  checked,
  onToggleSelect,
  onPlay,
  onDelete,
  onRetry,
  onRename,
  busy,
}: MediaRowProps) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(media.title)
  const playable = canPlay(media)

  const commit = () => {
    const value = draft.trim()
    setEditing(false)
    if (value && value !== media.title) onRename(media, value)
    else setDraft(media.title)
  }

  return (
    <div className="flex items-start gap-3 px-3 py-4 sm:gap-4 sm:px-5">
      {/* 多选态：左侧 checkbox，点击热区 32×32 */}
      {selectable && (
        <label
          className="flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-lg hover:bg-slate-50"
          title="选择此素材"
        >
          <input
            type="checkbox"
            checked={checked}
            onChange={(e) => onToggleSelect(e.target.checked)}
            aria-label={`选择「${media.title}」`}
            className="h-4 w-4 accent-slate-900"
          />
        </label>
      )}

      <button
        type="button"
        disabled={!playable}
        onClick={() => onPlay(media)}
        title={playable ? '播放' : '转码完成后可播放'}
        className={[
          'mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full transition-colors',
          playable
            ? 'bg-slate-900 text-white hover:bg-slate-700'
            : 'cursor-not-allowed bg-slate-100 text-slate-300',
        ].join(' ')}
      >
        <PlayIcon className="ml-0.5 h-3.5 w-3.5" />
      </button>

      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          {editing ? (
            <input
              autoFocus
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onBlur={commit}
              onKeyDown={(e) => {
                if (e.key === 'Enter') commit()
                if (e.key === 'Escape') {
                  setDraft(media.title)
                  setEditing(false)
                }
              }}
              className="min-w-0 flex-1 rounded border border-slate-300 px-2 py-0.5 text-[14px] outline-none focus:border-slate-500"
            />
          ) : (
            <span className="truncate text-[14px] font-medium text-slate-900">
              {media.title}
            </span>
          )}
          <CategoryBadge name={categoryName} />
          <TypeBadge media={media} />
        </div>

        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-slate-400">
          <span className="tabular-nums">{formatDuration(media.duration_ms)}</span>
          <span>{formatBytes(media.size_bytes)}</span>
          <span>{media.origin === 'inbox' ? '素材目录导入' : '本地上传'}</span>
          <span>{formatRelative(media.created_at)}</span>
          <span className="truncate">{media.original_name}</span>
        </div>

        <StatusLine media={media} />
      </div>

      <div className="flex shrink-0 items-center gap-1">
        <Link
          to={`/study/${media.id}`}
          className={[
            'flex items-center gap-1 rounded-lg border px-2.5 py-1.5 text-xs transition-colors',
            playable
              ? 'border-slate-200 text-slate-600 hover:bg-slate-50'
              : 'pointer-events-none border-slate-100 text-slate-300',
          ].join(' ')}
          title="进入学习页"
        >
          <BookIcon className="h-3.5 w-3.5" />
          学习
        </Link>

        {media.status === 'failed' && (
          <button
            type="button"
            onClick={() => onRetry(media)}
            disabled={busy}
            title="重新处理"
            className="rounded-lg p-2 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700 disabled:opacity-40"
          >
            <RefreshIcon className="h-4 w-4" />
          </button>
        )}

        <button
          type="button"
          onClick={() => {
            setDraft(media.title)
            setEditing(true)
          }}
          title="重命名"
          className="rounded-lg p-2 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700"
        >
          <PencilIcon className="h-4 w-4" />
        </button>

        <button
          type="button"
          onClick={() => onDelete(media)}
          disabled={busy}
          title="删除"
          className="rounded-lg p-2 text-slate-400 transition-colors hover:bg-red-50 hover:text-red-600 disabled:opacity-40"
        >
          <TrashIcon className="h-4 w-4" />
        </button>
      </div>
    </div>
  )
}

// --------------------------- 页面 ---------------------------

export default function MediaLibraryPage() {
  const queryClient = useQueryClient()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const openPlayer = usePlayer((s) => s.open)

  const [uploads, setUploads] = useState<UploadTask[]>([])
  const [dragging, setDragging] = useState(false)
  const [notice, setNotice] = useState<{ text: string; tone: 'info' | 'error' } | null>(null)
  const [inboxOpen, setInboxOpen] = useState(false)
  const [selected, setSelected] = useState<string[]>([])
  const [keyword, setKeyword] = useState('')
  const [sort, setSort] = useState<'recent' | 'title' | 'duration'>('recent')

  // --- 分类相关状态 ---
  /** 列表筛选：null = 全部；'none' = 未分类；数字 = 某分类 */
  const [categoryFilter, setCategoryFilter] = useState<CategoryFilter>(null)
  /** 上传 / 收件箱导入的目标分类（'' = 未分类，数字串 = 分类 id） */
  const [uploadCategory, setUploadCategory] = useState('')
  const [inboxCategory, setInboxCategory] = useState('')
  const [managerOpen, setManagerOpen] = useState(false)
  /** 批量管理态 */
  const [batchMode, setBatchMode] = useState(false)
  const [batchIds, setBatchIds] = useState<number[]>([])
  const [moveMenuOpen, setMoveMenuOpen] = useState(false)

  const showNotice = (text: string, tone: 'info' | 'error' = 'info') => setNotice({ text, tone })

  const healthQuery = useQuery({ queryKey: ['health'], queryFn: getHealth })
  const statsQuery = useQuery({
    queryKey: ['stats'],
    queryFn: getStats,
    refetchInterval: 15000,
  })

  /** 分类列表：既是 chips 的计数来源，也是素材行分类名的本地映射来源 */
  const categoriesQuery = useQuery({
    queryKey: ['categories'],
    queryFn: listCategories,
  })

  const mediaQuery = useQuery({
    queryKey: ['media', categoryFilter ?? 'all'],
    queryFn: () => listMedia(categoryFilter ?? undefined),
    // 换分类时先显示上一份数据，避免列表闪一下骨架屏
    placeholderData: keepPreviousData,
    refetchInterval: (query) => {
      const items = query.state.data?.items ?? []
      const busy = items.some((m) => PROCESSING_STATUSES.includes(m.status))
      return busy ? 1500 : false
    },
  })

  const inboxQuery = useQuery({
    queryKey: ['inbox'],
    queryFn: listInbox,
    enabled: inboxOpen,
  })

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['media'] })
    void queryClient.invalidateQueries({ queryKey: ['categories'] })
    void queryClient.invalidateQueries({ queryKey: ['health'] })
  }

  const deleteMutation = useMutation({
    mutationFn: (id: number) => deleteMedia(id),
    onSuccess: refresh,
  })

  const renameMutation = useMutation({
    mutationFn: ({ id, title }: { id: number; title: string }) => updateMedia(id, { title }),
    onSuccess: refresh,
  })

  const retryMutation = useMutation({
    mutationFn: (id: number) => retryMedia(id),
    onSuccess: refresh,
  })

  const moveMutation = useMutation({
    mutationFn: ({ ids, categoryId }: { ids: number[]; categoryId: number | null }) =>
      batchMoveCategory(ids, categoryId),
    onSuccess: (result, variables) => {
      const target = categoryNameOf(variables.categoryId)
      const skipped = result.missing.length > 0 ? `，${result.missing.length} 个已失效被跳过` : ''
      showNotice(`已移动 ${result.updated} 个素材到「${target}」${skipped}`)
      setBatchMode(false)
      setBatchIds([])
      setMoveMenuOpen(false)
      refresh()
    },
    onError: (error: Error) => showNotice(`移动失败：${error.message}`, 'error'),
  })

  const importMutation = useMutation({
    mutationFn: ({ files, categoryId }: { files?: string[]; categoryId: number | null }) =>
      importFromInbox(files, categoryId),
    onSuccess: (result, variables) => {
      setInboxOpen(false)
      setSelected([])
      const target = categoryNameOf(variables.categoryId)
      setNotice({
        tone: 'info',
        text:
          result.total > 0
            ? `已导入 ${result.total} 个素材到「${target}」，正在后台转码`
            : '没有可导入的新素材',
      })
      refresh()
      void queryClient.invalidateQueries({ queryKey: ['inbox'] })
    },
    onError: (error: Error) => showNotice(`导入失败：${error.message}`, 'error'),
  })

  /**
   * 分类列表。必须 memo 出稳定的数组引用：
   * 直接写 `data?.items ?? []` 会在「数据未到」时每次渲染都产生新数组，
   * 而 CategoryManager 用它当 effect 依赖做本地排序副本同步 —— 引用一直变会让它无限重渲染。
   */
  const categories: CategoryItem[] = useMemo(
    () => categoriesQuery.data?.items ?? [],
    [categoriesQuery.data],
  )
  /** id → name 的本地映射：素材行 badge 用，不让后端 JOIN */
  const categoryNames = useMemo(
    () => new Map(categories.map((c) => [c.id, c.name] as const)),
    [categories],
  )
  const categoryNameOf = (id: CategoryFilter) =>
    id === null || id === 'none' ? '未分类' : (categoryNames.get(id) ?? '所选分类')

  const items = mediaQuery.data?.items ?? []
  const processingCount = useMemo(
    () => items.filter((m) => PROCESSING_STATUSES.includes(m.status)).length,
    [items],
  )

  const scopeLabel = categoryFilter === null ? '全部' : categoryNameOf(categoryFilter)

  /** 批量移动的目标选项：「未分类」+ 各分类 */
  const moveOptions: { id: number | null; name: string }[] = [
    { id: null, name: '未分类' },
    ...categories.map((c) => ({ id: c.id, name: c.name })),
  ]

  // 搜索 + 排序（M5 打磨：素材变多后仍能快速找到）
  const visible = useMemo(() => {
    const kw = keyword.trim().toLowerCase()
    const filtered = kw
      ? items.filter(
          (m) =>
            m.title.toLowerCase().includes(kw) ||
            m.original_name.toLowerCase().includes(kw),
        )
      : items
    const sorted = [...filtered]
    if (sort === 'title') sorted.sort((a, b) => a.title.localeCompare(b.title, 'zh'))
    else if (sort === 'duration') sorted.sort((a, b) => b.duration_ms - a.duration_ms)
    return sorted
  }, [items, keyword, sort])

  const stats = statsQuery.data

  async function handleFiles(files: FileList | File[]) {
    const list = Array.from(files)
    if (list.length === 0) return
    setNotice(null)

    // 本轮所选文件统一归入同一分类（上传是逐文件循环，逐个改选会让结果不可预期）
    const categoryId = uploadCategory === '' ? null : Number(uploadCategory)
    const target = categoryNameOf(categoryId)
    let ok = 0

    for (const file of list) {
      const task: UploadTask = {
        id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
        name: file.name,
        percent: 0,
        status: 'uploading',
      }
      setUploads((prev) => [...prev, task])
      try {
        await uploadMedia(
          file,
          (percent) =>
            setUploads((prev) => prev.map((t) => (t.id === task.id ? { ...t, percent } : t))),
          categoryId,
        )
        ok += 1
        setUploads((prev) =>
          prev.map((t) => (t.id === task.id ? { ...t, percent: 100, status: 'done' } : t)),
        )
      } catch (error) {
        setUploads((prev) =>
          prev.map((t) =>
            t.id === task.id
              ? { ...t, status: 'error', error: (error as Error).message }
              : t,
          ),
        )
      }
    }

    if (ok > 0 && categoryId !== null) {
      showNotice(`已上传 ${ok} 个素材到「${target}」，正在后台转码`)
    }
    refresh()
    window.setTimeout(() => {
      setUploads((prev) => prev.filter((t) => t.status === 'error'))
    }, 4000)
  }

  function handleDelete(media: MediaItem) {
    const confirmed = window.confirm(
      `确定删除「${media.title}」吗？\n音频文件与相关的句子、笔记都会被一并删除，且无法恢复。`,
    )
    if (confirmed) deleteMutation.mutate(media.id)
  }

  const inboxItems: InboxItem[] = inboxQuery.data?.items ?? []

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-[15px] font-medium text-slate-900">媒体库</h2>
          <p className="mt-1 text-[13px] text-slate-500">
            导入英语音频（视频仅取音轨），系统自动转码为标准音频，后续将自动识别原文并翻译。
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <button
            type="button"
            onClick={() => setInboxOpen((v) => !v)}
            className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-2 text-[13px] text-slate-600 transition-colors hover:bg-slate-50"
          >
            <FolderIcon className="h-4 w-4" />
            从素材目录导入
          </button>
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="flex items-center gap-1.5 rounded-lg bg-slate-900 px-3.5 py-2 text-[13px] text-white transition-colors hover:bg-slate-700"
          >
            <UploadIcon className="h-4 w-4" />
            上传文件
          </button>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept={ACCEPT}
            className="hidden"
            onChange={(e) => {
              if (e.target.files) void handleFiles(e.target.files)
              e.target.value = ''
            }}
          />
        </div>
      </div>

      {/* 学习概览（M5） */}
      {stats && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <StatCard
            label="素材 · 全库"
            value={stats.media.total}
            sub={`${stats.media.done} 个已就绪`}
          />
          <StatCard
            label="句子"
            value={stats.sentences}
            sub={`已听写 ${stats.attempts.attempted_sentences} 句`}
          />
          <StatCard
            label="生词"
            value={stats.vocab.total}
            sub={`已掌握 ${stats.vocab.mastered} 个`}
          />
          <StatCard
            label="句子笔记"
            value={stats.notes}
            sub={`听写提交 ${stats.attempts.total} 次`}
          />
        </div>
      )}

      {/* 拖拽上传区 + 按类导入 */}
      <div className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="text-[12px] text-slate-500">
            上传时可指定分类：本轮所选文件统一归入该分类
          </span>
          <CategorySelect
            items={categories}
            value={uploadCategory}
            onChange={setUploadCategory}
            label="导入到分类"
          />
        </div>

        <div
          onDragOver={(e) => {
            e.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragging(false)
            if (e.dataTransfer.files?.length) void handleFiles(e.dataTransfer.files)
          }}
          className={[
            'cursor-pointer rounded-xl border border-dashed px-3 py-5 text-center transition-colors sm:px-5 sm:py-6',
            dragging
              ? 'border-slate-900 bg-slate-50'
              : 'border-slate-300 bg-white hover:border-slate-400',
          ].join(' ')}
          onClick={() => fileInputRef.current?.click()}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') fileInputRef.current?.click()
          }}
          role="button"
          tabIndex={0}
        >
          <p className="text-[13px] text-slate-500">
            {/* 手机上没有拖拽，改成「点一下选文件」；桌面保留原提示 */}
            <span className="hidden sm:inline">把音频 / 视频文件拖到这里，或点右上角「上传文件」</span>
            <span className="sm:hidden">点这里选择手机里的音频 / 视频</span>
          </p>
          <p className="mt-1 text-[12px] text-slate-400">
            支持 mp3 / wav / m4a / flac / aac / ogg 与 mp4 / mkv / mov / webm 等（视频仅提取音轨）
          </p>
        </div>
      </div>

      {notice && (
        <div
          role="status"
          className={[
            'rounded-lg border px-4 py-2.5 text-[13px]',
            notice.tone === 'error'
              ? 'border-red-100 bg-red-50 text-red-700'
              : 'border-sky-100 bg-sky-50 text-sky-700',
          ].join(' ')}
        >
          {notice.text}
        </div>
      )}

      {/* 上传进度 */}
      {uploads.length > 0 && (
        <div className="space-y-2 rounded-xl border border-slate-200 bg-white p-4">
          {uploads.map((task) => (
            <div key={task.id}>
              <div className="flex items-center justify-between text-[12px]">
                <span className="truncate text-slate-600">{task.name}</span>
                <span
                  className={[
                    'shrink-0 tabular-nums',
                    task.status === 'error' ? 'text-red-600' : 'text-slate-400',
                  ].join(' ')}
                >
                  {task.status === 'error'
                    ? task.error ?? '失败'
                    : task.status === 'done'
                      ? '上传完成'
                      : `${task.percent}%`}
                </span>
              </div>
              <div className="mt-1 h-1 w-full overflow-hidden rounded-full bg-slate-100">
                <div
                  className={[
                    'h-full rounded-full transition-[width]',
                    task.status === 'error' ? 'bg-red-400' : 'bg-slate-900',
                  ].join(' ')}
                  style={{ width: `${task.status === 'error' ? 100 : task.percent}%` }}
                />
              </div>
            </div>
          ))}
        </div>
      )}

      {/* 素材目录导入面板 */}
      {inboxOpen && (
        <div className="rounded-xl border border-slate-200 bg-white p-5">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <h3 className="text-sm font-medium text-slate-900">从素材目录导入</h3>
              <p className="mt-1 text-[12px] leading-relaxed text-slate-500">
                把音频 / 视频文件放进下面这个目录，然后点「重新扫描」即可批量导入（原文件保留在目录里）。
              </p>
              <code className="mt-2 block break-all rounded bg-slate-50 px-2 py-1.5 text-[11px] text-slate-600">
                {healthQuery.data?.paths.inbox_dir ?? '读取中…'}
              </code>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <button
                type="button"
                onClick={() => void inboxQuery.refetch()}
                className="flex items-center gap-1.5 rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs text-slate-600 hover:bg-slate-50"
              >
                <RefreshIcon className="h-3.5 w-3.5" />
                重新扫描
              </button>
              <button
                type="button"
                onClick={() => setInboxOpen(false)}
                className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100"
              >
                <CloseIcon className="h-4 w-4" />
              </button>
            </div>
          </div>

          <div className="mt-3 max-h-64 overflow-auto rounded-lg border border-slate-100">
            {inboxQuery.isLoading && (
              <p className="px-3 py-4 text-[13px] text-slate-400">扫描中…</p>
            )}
            {!inboxQuery.isLoading && inboxItems.length === 0 && (
              <p className="px-3 py-4 text-[13px] text-slate-400">
                目录里还没有文件。把素材拷进去后点「重新扫描」。
              </p>
            )}
            {inboxItems.map((item) => {
              const disabled = item.imported || !item.supported
              const checked = selected.includes(item.path)
              return (
                <label
                  key={item.path}
                  className={[
                    'flex cursor-pointer items-center gap-3 border-b border-slate-50 px-3 py-2 last:border-0',
                    disabled ? 'cursor-not-allowed opacity-50' : 'hover:bg-slate-50',
                  ].join(' ')}
                >
                  <input
                    type="checkbox"
                    disabled={disabled}
                    checked={checked}
                    onChange={(e) =>
                      setSelected((prev) =>
                        e.target.checked
                          ? [...prev, item.path]
                          : prev.filter((p) => p !== item.path),
                      )
                    }
                    className="accent-slate-900"
                  />
                  <span className="min-w-0 flex-1 truncate text-[13px] text-slate-700">
                    {item.name}
                  </span>
                  <span className="shrink-0 text-[11px] text-slate-400">
                    {formatBytes(item.size_bytes)}
                  </span>
                  {item.imported && (
                    <span className="shrink-0 text-[11px] text-emerald-600">已导入</span>
                  )}
                  {!item.supported && !item.imported && (
                    <span className="shrink-0 text-[11px] text-amber-600">格式不支持</span>
                  )}
                </label>
              )
            })}
          </div>

          <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
            <span className="text-[12px] text-slate-400">
              共 {inboxItems.length} 个文件，已选 {selected.length} 个
            </span>
            <div className="flex flex-wrap items-center gap-2">
              <CategorySelect
                items={categories}
                value={inboxCategory}
                onChange={setInboxCategory}
                label="导入到分类"
              />
              <button
                type="button"
                disabled={selected.length === 0 || importMutation.isPending}
                onClick={() =>
                  importMutation.mutate({
                    files: selected,
                    categoryId: inboxCategory === '' ? null : Number(inboxCategory),
                  })
                }
                className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-40"
              >
                导入选中
              </button>
              <button
                type="button"
                disabled={importMutation.isPending}
                onClick={() =>
                  importMutation.mutate({
                    files: undefined,
                    categoryId: inboxCategory === '' ? null : Number(inboxCategory),
                  })
                }
                className="rounded-lg bg-slate-900 px-3 py-1.5 text-xs text-white hover:bg-slate-700 disabled:opacity-40"
              >
                {importMutation.isPending ? '导入中…' : '全部导入'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 列表 */}
      <div className="rounded-xl border border-slate-200 bg-white">
        <div className="border-b border-slate-100 px-3 py-3 sm:px-5">
          <div className="flex flex-wrap items-center gap-2 sm:gap-3">
            <h3 className="text-sm font-medium text-slate-900">
              已导入素材
              <span className="ml-1 text-[12px] font-normal text-slate-400">· {scopeLabel}</span>
              <span className="ml-2 text-[12px] font-normal text-slate-400">
                共 {items.length} 个
              </span>
            </h3>
            {processingCount > 0 && (
              <span className="text-[12px] text-slate-500">
                {processingCount} 个正在处理…
              </span>
            )}

            {/* 窄屏整组换行并允许内部折行，避免搜索框 + 排序 + 批量管理把卡片顶出横向滚动 */}
            <div className="ml-auto flex w-full flex-wrap items-center gap-2 sm:w-auto">
              <div className="relative">
                <SearchIcon className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" />
                <input
                  value={keyword}
                  onChange={(e) => setKeyword(e.target.value)}
                  placeholder="搜索标题 / 文件名…"
                  className="w-[180px] rounded-lg border border-slate-200 py-1.5 pl-8 pr-3 text-[12px] text-slate-700 outline-none transition-colors focus:border-slate-400"
                />
              </div>
              <div className="flex items-center gap-1 rounded-lg border border-slate-200 px-2 py-1.5">
                <SortIcon className="h-3.5 w-3.5 text-slate-400" />
                <select
                  value={sort}
                  onChange={(e) => setSort(e.target.value as typeof sort)}
                  title="排序方式"
                  className="bg-transparent text-[12px] text-slate-600 outline-none"
                >
                  <option value="recent">最近导入</option>
                  <option value="title">按标题</option>
                  <option value="duration">按时长</option>
                </select>
              </div>
              <button
                type="button"
                onClick={() => {
                  setNotice(null)
                  setBatchMode((v) => !v)
                  setBatchIds([])
                  setMoveMenuOpen(false)
                }}
                aria-pressed={batchMode}
                className={[
                  'flex h-8 items-center gap-1.5 rounded-lg border px-3 text-[12px] transition-colors',
                  batchMode
                    ? 'border-slate-900 bg-slate-900 text-white'
                    : 'border-slate-200 text-slate-600 hover:bg-slate-50',
                ].join(' ')}
              >
                <ListIcon className="h-3.5 w-3.5" />
                {batchMode ? '退出批量' : '批量管理'}
              </button>
            </div>
          </div>

          {/* 分类 chips：计数来自 /api/categories 的分类子集计数 */}
          <div className="mt-2.5">
            <CategoryChips
              items={categories}
              uncategorizedCount={categoriesQuery.data?.uncategorized_count ?? 0}
              loading={categoriesQuery.isLoading}
              selected={categoryFilter}
              onSelect={(value) => {
                setCategoryFilter(value)
                // 换筛选口径时清空多选，避免选中了看不到的行
                setBatchIds([])
                setMoveMenuOpen(false)
              }}
              onManage={() => setManagerOpen(true)}
            />
          </div>
        </div>

        {/* 批量操作条 */}
        {batchMode && (
          <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 bg-slate-50 px-3 py-2 sm:px-5">
            <span className="text-[12px] text-slate-600">
              已选 <span className="tabular-nums">{batchIds.length}</span> 项
            </span>

            <div className="relative">
              <button
                type="button"
                disabled={batchIds.length === 0}
                onClick={() => setMoveMenuOpen((v) => !v)}
                aria-haspopup="menu"
                aria-expanded={moveMenuOpen}
                className="flex h-8 items-center gap-1.5 rounded-lg bg-slate-900 px-3 text-[12px] text-white transition-colors hover:bg-slate-700 disabled:opacity-40"
              >
                移动到分类
                <span aria-hidden="true">▾</span>
              </button>

              {moveMenuOpen && (
                <>
                  {/* 桌面：锚定下拉 */}
                  <div
                    className="fixed inset-0 z-20 hidden sm:block"
                    onClick={() => setMoveMenuOpen(false)}
                  />
                  <div
                    role="menu"
                    className="absolute left-0 z-30 mt-1 hidden max-h-72 w-56 overflow-y-auto rounded-xl border border-slate-200 bg-white py-1 shadow-lg sm:block"
                  >
                    {moveOptions.map((option) => (
                      <button
                        key={option.id ?? 'none'}
                        type="button"
                        role="menuitem"
                        onClick={() =>
                          moveMutation.mutate({ ids: batchIds, categoryId: option.id })
                        }
                        className="flex h-8 w-full items-center px-3 text-left text-[12px] text-slate-600 transition-colors hover:bg-slate-50"
                      >
                        <span className="truncate">{option.name}</span>
                      </button>
                    ))}
                  </div>

                  {/* 移动端：底部弹层（触摸目标 ≥32px） */}
                  <div
                    className="fixed inset-0 z-50 flex items-end justify-center bg-slate-900/40 sm:hidden"
                    onClick={() => setMoveMenuOpen(false)}
                  >
                    <div
                      className="w-full rounded-t-2xl bg-white pb-[env(safe-area-inset-bottom)]"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <p className="px-4 py-3 text-[13px] font-medium text-slate-900">
                        把 {batchIds.length} 个素材移动到…
                      </p>
                      <div className="max-h-[55dvh] overflow-y-auto border-t border-slate-100">
                        {moveOptions.map((option) => (
                          <button
                            key={option.id ?? 'none'}
                            type="button"
                            onClick={() =>
                              moveMutation.mutate({ ids: batchIds, categoryId: option.id })
                            }
                            className="flex w-full items-center px-4 py-3 text-left text-[14px] text-slate-700 active:bg-slate-50"
                          >
                            <span className="truncate">{option.name}</span>
                          </button>
                        ))}
                      </div>
                      <button
                        type="button"
                        onClick={() => setMoveMenuOpen(false)}
                        className="w-full border-t border-slate-100 px-4 py-3 text-[14px] text-slate-500"
                      >
                        取消
                      </button>
                    </div>
                  </div>
                </>
              )}
            </div>

            <button
              type="button"
              onClick={() => {
                setBatchMode(false)
                setBatchIds([])
                setMoveMenuOpen(false)
              }}
              className="flex h-8 items-center rounded-lg border border-slate-200 bg-white px-3 text-[12px] text-slate-600 transition-colors hover:bg-slate-50"
            >
              取消
            </button>

            {moveMutation.isPending && (
              <span className="text-[12px] text-slate-500">移动中…</span>
            )}
          </div>
        )}

        {mediaQuery.isLoading && <ListSkeleton />}
        {mediaQuery.isError && (
          <p className="px-3 py-8 text-center text-[13px] text-red-600 sm:px-5">
            读取失败：{(mediaQuery.error as Error).message}
          </p>
        )}
        {!mediaQuery.isLoading && items.length === 0 && (
          <div className="px-3 py-12 text-center sm:px-5">
            <p className="text-[13px] text-slate-400">
              {categoryFilter === null
                ? '还没有素材。上传一个英语音频，开始你的第一课。'
                : `「${scopeLabel}」下还没有素材。`}
            </p>
          </div>
        )}
        {!mediaQuery.isLoading && items.length > 0 && visible.length === 0 && (
          <p className="px-3 py-12 text-center text-[13px] text-slate-400 sm:px-5">
            没有匹配「{keyword}」的素材。
          </p>
        )}

        {visible.map((media) => (
          <div key={media.id} className="border-b border-slate-50 last:border-0">
            <MediaRow
              media={media}
              categoryName={
                media.category_id === null ? null : (categoryNames.get(media.category_id) ?? null)
              }
              selectable={batchMode}
              checked={batchIds.includes(media.id)}
              onToggleSelect={(checked) =>
                setBatchIds((prev) =>
                  checked ? [...prev, media.id] : prev.filter((id) => id !== media.id),
                )
              }
              busy={
                deleteMutation.isPending || renameMutation.isPending || retryMutation.isPending
              }
              onPlay={(m) => openPlayer(m, true)}
              onDelete={handleDelete}
              onRetry={(m) => retryMutation.mutate(m.id)}
              onRename={(m, title) => renameMutation.mutate({ id: m.id, title })}
            />
          </div>
        ))}
      </div>

      {/* 管理分类面板 */}
      {managerOpen && (
        <CategoryManager
          items={categories}
          onClose={() => setManagerOpen(false)}
          onChanged={refresh}
          onNotify={showNotice}
        />
      )}

      {/* 环境自检 */}
      <details className="rounded-xl border border-slate-200 bg-white px-3 py-4 sm:px-5">
        <summary className="cursor-pointer text-sm font-medium text-slate-900">
          环境自检
        </summary>
        <ul className="mt-3 space-y-2 text-[13px]">
          <li className="flex items-center gap-2">
            <span className={healthQuery.data?.checks.database ? 'text-green-600' : 'text-slate-400'}>
              {healthQuery.data?.checks.database ? '✓' : '○'}
            </span>
            <span className="text-slate-600">SQLite 数据库已就绪</span>
          </li>
          <li className="flex items-center gap-2">
            <span
              className={
                healthQuery.data?.checks.ffmpeg && healthQuery.data?.checks.ffprobe
                  ? 'text-green-600'
                  : 'text-amber-500'
              }
            >
              {healthQuery.data?.checks.ffmpeg && healthQuery.data?.checks.ffprobe ? '✓' : '!'}
            </span>
            <span className="text-slate-600">
              ffmpeg / ffprobe
              {healthQuery.data &&
                !(healthQuery.data.checks.ffmpeg && healthQuery.data.checks.ffprobe) &&
                '（未检测到，转码与音频切片需要）'}
            </span>
          </li>
          <li className="flex items-start gap-2">
            <span
              className={
                healthQuery.data?.checks.asr && healthQuery.data?.checks.asr_model
                  ? 'text-green-600'
                  : healthQuery.data?.checks.asr
                    ? 'text-amber-500'
                    : 'text-amber-500'
              }
            >
              {healthQuery.data?.checks.asr && healthQuery.data?.checks.asr_model ? '✓' : '!'}
            </span>
            <span className="text-slate-600">
              语音识别 faster-whisper
              {healthQuery.data?.asr.model && `（${healthQuery.data.asr.model}）`}
              {healthQuery.data &&
                !healthQuery.data.checks.asr &&
                '（未安装 ML 依赖：pip install -r backend/requirements-ml.txt）'}
              {healthQuery.data &&
                healthQuery.data.checks.asr &&
                !healthQuery.data.checks.asr_model &&
                '（模型未就绪，处理时自动下载）'}
            </span>
          </li>
          <li className="flex items-start gap-2">
            <span className={healthQuery.data?.checks.dict ? 'text-green-600' : 'text-amber-500'}>
              {healthQuery.data?.checks.dict ? '✓' : '!'}
            </span>
            <span className="text-slate-600">
              离线词典 ECDICT
              {healthQuery.data?.dict.entries
                ? `（${healthQuery.data.dict.entries.toLocaleString('en-US')} 词条）`
                : healthQuery.data && !healthQuery.data.checks.dict
                  ? '（未安装，查词将无法给出站内释义）'
                  : ''}
            </span>
          </li>
          <li className="flex items-start gap-2">
            <span className="text-slate-400">○</span>
            <span className="text-slate-600">
              在线翻译引擎：{healthQuery.data?.config.translate_engines.join(' → ') ?? '—'}
            </span>
          </li>
          <li className="flex items-start gap-2">
            <span className="text-slate-400">○</span>
            <span className="break-all text-slate-600">
              数据目录：{healthQuery.data?.paths.data_dir ?? '—'}
            </span>
          </li>
        </ul>
      </details>
    </div>
  )
}

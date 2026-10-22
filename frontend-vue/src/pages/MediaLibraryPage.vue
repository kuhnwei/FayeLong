<script setup lang="ts">
/**
 * 媒体库页（照搬旧 `frontend/src/pages/MediaLibraryPage.tsx`，1162 行）。
 *
 * 覆盖：列表 / 分类筛选与 ↑↓ 排序（旧实现有意不做拖拽）/ 批量移动分类 /
 * 收件箱扫描导入 / 上传进度 / 处理中自动轮询 / 删除确认 / 学习概览 / 环境自检。
 *
 * 与旧版的等价性说明：
 * - 旧版内联的 MediaRow / StatCard / ListSkeleton 拆成独立 SFC；
 *   MediaRow 内联的 TypeBadge / CategoryBadge / StatusLine 收进 MediaRow.vue。
 * - 排序、搜索、分类映射等派生值改用 computed（旧版 useMemo），语义一致。
 * - 收件箱/导入/改密等流程一律跑在隔离后端上（scripts/run_isolated_backend.py）。
 */
import { computed, ref } from 'vue'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import {
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
} from '../api/client'
import type { CategoryItem, InboxItem, MediaItem } from '../api/client'
import { usePlayer } from '../stores/player'
import { formatBytes } from '../utils/format'
import CategoryChips from '../components/CategoryChips.vue'
import CategorySelect from '../components/CategorySelect.vue'
import CategoryManager from '../components/CategoryManager.vue'
import type { CategoryFilter } from '../components/category'
import ListSkeleton from '../components/ListSkeleton.vue'
import MediaRow from '../components/MediaRow.vue'
import StatCard from '../components/StatCard.vue'
import {
  CloseIcon,
  FolderIcon,
  ListIcon,
  RefreshIcon,
  SearchIcon,
  SortIcon,
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

const queryClient = useQueryClient()
const fileInputRef = ref<HTMLInputElement | null>(null)
const player = usePlayer()

const uploads = ref<UploadTask[]>([])
const dragging = ref(false)
const notice = ref<{ text: string; tone: 'info' | 'error' } | null>(null)
const inboxOpen = ref(false)
const selected = ref<string[]>([])
const keyword = ref('')
const sort = ref<'recent' | 'title' | 'duration'>('recent')

// --- 分类相关状态 ---
/** 列表筛选：null = 全部；'none' = 未分类；数字 = 某分类 */
const categoryFilter = ref<CategoryFilter>(null)
/** 上传 / 收件箱导入的目标分类（'' = 未分类，数字串 = 分类 id） */
const uploadCategory = ref('')
const inboxCategory = ref('')
const managerOpen = ref(false)
/** 批量管理态 */
const batchMode = ref(false)
const batchIds = ref<number[]>([])
const moveMenuOpen = ref(false)

const showNotice = (text: string, tone: 'info' | 'error' = 'info') => {
  notice.value = { text, tone }
}

const { data: healthData } = useQuery({ queryKey: ['health'], queryFn: getHealth })
const { data: statsData } = useQuery({
  queryKey: ['stats'],
  queryFn: getStats,
  refetchInterval: 15000,
})

/** 分类列表：既是 chips 的计数来源，也是素材行分类名的本地映射来源 */
const { data: categoriesData, isLoading: categoriesLoading } = useQuery({
  queryKey: ['categories'],
  queryFn: listCategories,
})

const mediaKey = computed(() => ['media', categoryFilter.value ?? 'all'])
const {
  data: mediaData,
  isLoading: mediaLoading,
  isError: mediaIsError,
  error: mediaError,
} = useQuery({
  queryKey: mediaKey,
  queryFn: () => listMedia(categoryFilter.value ?? undefined),
  // 换分类时先显示上一份数据，避免列表闪一下骨架屏
  placeholderData: keepPreviousData,
  refetchInterval: (query) => {
    const data = query.state.data as { items?: MediaItem[] } | undefined
    const items = data?.items ?? []
    const busy = items.some((m) => PROCESSING_STATUSES.includes(m.status))
    return busy ? 1500 : false
  },
})

const inboxEnabled = computed(() => inboxOpen.value)
const {
  data: inboxData,
  isLoading: inboxLoading,
  refetch: refetchInbox,
} = useQuery({
  queryKey: ['inbox'],
  queryFn: listInbox,
  enabled: inboxEnabled,
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
    batchMode.value = false
    batchIds.value = []
    moveMenuOpen.value = false
    refresh()
  },
  onError: (error: Error) => showNotice(`移动失败：${error.message}`, 'error'),
})

const importMutation = useMutation({
  mutationFn: ({ files, categoryId }: { files?: string[]; categoryId: number | null }) =>
    importFromInbox(files, categoryId),
  onSuccess: (result, variables) => {
    inboxOpen.value = false
    selected.value = []
    const target = categoryNameOf(variables.categoryId)
    notice.value = {
      tone: 'info',
      text:
        result.total > 0
          ? `已导入 ${result.total} 个素材到「${target}」，正在后台转码`
          : '没有可导入的新素材',
    }
    refresh()
    void queryClient.invalidateQueries({ queryKey: ['inbox'] })
  },
  onError: (error: Error) => showNotice(`导入失败：${error.message}`, 'error'),
})

/**
 * 分类列表。必须是**内容稳定**的派生值：
 * 旧版注释指出 CategoryManager 以它为依赖做本地排序副本同步，
 * 若每次都是新数组会引发无限重渲染 —— 这里用 computed + 内容比较（见 CategoryManager 的 sameCategories）。
 */
const categories = computed<CategoryItem[]>(() => categoriesData.value?.items ?? [])
/** id → name 的本地映射：素材行 badge 用，不让后端 JOIN */
const categoryNames = computed(() => new Map(categories.value.map((c) => [c.id, c.name] as const)))
const categoryNameOf = (id: CategoryFilter) =>
  id === null || id === 'none' ? '未分类' : (categoryNames.value.get(id) ?? '所选分类')

const items = computed(() => mediaData.value?.items ?? [])
const processingCount = computed(
  () => items.value.filter((m) => PROCESSING_STATUSES.includes(m.status)).length,
)

const scopeLabel = computed(() =>
  categoryFilter.value === null ? '全部' : categoryNameOf(categoryFilter.value),
)

/** 批量移动的目标选项：「未分类」+ 各分类 */
const moveOptions = computed<{ id: number | null; name: string }[]>(() => [
  { id: null, name: '未分类' },
  ...categories.value.map((c) => ({ id: c.id, name: c.name })),
])

// 搜索 + 排序（M5 打磨：素材变多后仍能快速找到）
const visible = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  const filtered = kw
    ? items.value.filter(
        (m) => m.title.toLowerCase().includes(kw) || m.original_name.toLowerCase().includes(kw),
      )
    : items.value
  const sorted = [...filtered]
  if (sort.value === 'title') sorted.sort((a, b) => a.title.localeCompare(b.title, 'zh'))
  else if (sort.value === 'duration') sorted.sort((a, b) => b.duration_ms - a.duration_ms)
  return sorted
})

const inboxItems = computed<InboxItem[]>(() => inboxData.value?.items ?? [])

async function handleFiles(files: FileList | File[]) {
  const list = Array.from(files)
  if (list.length === 0) return
  notice.value = null

  // 本轮所选文件统一归入同一分类（上传是逐文件循环，逐个改选会让结果不可预期）
  const categoryId = uploadCategory.value === '' ? null : Number(uploadCategory.value)
  const target = categoryNameOf(categoryId)
  let ok = 0

  for (const file of list) {
    const task: UploadTask = {
      id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
      name: file.name,
      percent: 0,
      status: 'uploading',
    }
    uploads.value = [...uploads.value, task]
    try {
      await uploadMedia(
        file,
        (percent) => {
          uploads.value = uploads.value.map((t) => (t.id === task.id ? { ...t, percent } : t))
        },
        categoryId,
      )
      ok += 1
      uploads.value = uploads.value.map((t): UploadTask =>
        t.id === task.id ? { ...t, percent: 100, status: 'done' } : t,
      )
    } catch (error) {
      uploads.value = uploads.value.map((t): UploadTask =>
        t.id === task.id ? { ...t, status: 'error', error: (error as Error).message } : t,
      )
    }
  }

  if (ok > 0 && categoryId !== null) {
    showNotice(`已上传 ${ok} 个素材到「${target}」，正在后台转码`)
  }
  refresh()
  window.setTimeout(() => {
    uploads.value = uploads.value.filter((t) => t.status === 'error')
  }, 4000)
}

function handleDelete(media: MediaItem) {
  const confirmed = window.confirm(
    `确定删除「${media.title}」吗？\n音频文件与相关的句子、笔记都会被一并删除，且无法恢复。`,
  )
  if (confirmed) deleteMutation.mutate(media.id)
}

function onDrop(event: DragEvent) {
  dragging.value = false
  if (event.dataTransfer?.files?.length) void handleFiles(event.dataTransfer.files)
}

function onSortChange(event: Event) {
  sort.value = (event.target as HTMLSelectElement).value as typeof sort.value
}

function onFileInput(event: Event) {
  const target = event.target as HTMLInputElement | null
  if (target?.files) void handleFiles(target.files)
  // 清空选择，让再次选择同一文件也能触发 change
  if (target) target.value = ''
}

/** 素材行的分类名：未分类（null/undefined）返回 null，其余走本地 id→name 映射 */
function categoryNameFor(media: MediaItem): string | null {
  // 注意：生成的 schema 里 category_id 是可选的（number | null | undefined），用 `== null` 兜住两种
  return media.category_id == null ? null : (categoryNames.value.get(media.category_id) ?? null)
}

function toggleBatch(id: number, checked: boolean) {
  batchIds.value = checked
    ? [...batchIds.value, id]
    : batchIds.value.filter((existing) => existing !== id)
}

function enterBatchMode() {
  notice.value = null
  batchMode.value = !batchMode.value
  batchIds.value = []
  moveMenuOpen.value = false
}

function exitBatchMode() {
  batchMode.value = false
  batchIds.value = []
  moveMenuOpen.value = false
}
</script>

<template>
  <div class="space-y-5">
    <div class="flex flex-wrap items-end justify-between gap-3">
      <div>
        <h2 class="text-[15px] font-medium text-slate-900">媒体库</h2>
        <p class="mt-1 text-[13px] text-slate-500">
          导入英语音频（视频仅取音轨），系统自动转码为标准音频，后续将自动识别原文并翻译。
        </p>
      </div>
      <div class="flex shrink-0 items-center gap-2">
        <button
          type="button"
          class="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-2 text-[13px] text-slate-600 transition-colors hover:bg-slate-50"
          @click="inboxOpen = !inboxOpen"
        >
          <FolderIcon class-name="h-4 w-4" />
          从素材目录导入
        </button>
        <button
          type="button"
          class="flex items-center gap-1.5 rounded-lg bg-slate-900 px-3.5 py-2 text-[13px] text-white transition-colors hover:bg-slate-700"
          @click="fileInputRef?.click()"
        >
          <UploadIcon class-name="h-4 w-4" />
          上传文件
        </button>
        <input
          ref="fileInputRef"
          type="file"
          multiple
          :accept="ACCEPT"
          class="hidden"
          @change="onFileInput"
        />
      </div>
    </div>

    <!-- 学习概览（M5） -->
    <div v-if="statsData" class="grid grid-cols-2 gap-3 sm:grid-cols-4">
      <StatCard
        label="素材 · 全库"
        :value="statsData.media.total"
        :sub="`${statsData.media.done} 个已就绪`"
      />
      <StatCard
        label="句子"
        :value="statsData.sentences"
        :sub="`已听写 ${statsData.attempts.attempted_sentences} 句`"
      />
      <StatCard label="生词" :value="statsData.vocab.total" :sub="`已掌握 ${statsData.vocab.mastered} 个`" />
      <StatCard label="句子笔记" :value="statsData.notes" :sub="`听写提交 ${statsData.attempts.total} 次`" />
    </div>

    <!-- 拖拽上传区 + 按类导入 -->
    <div class="space-y-2">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <span class="text-[12px] text-slate-500">
          上传时可指定分类：本轮所选文件统一归入该分类
        </span>
        <CategorySelect v-model="uploadCategory" :items="categories" label="导入到分类" />
      </div>

      <div
        role="button"
        tabindex="0"
        :class="[
          'cursor-pointer rounded-xl border border-dashed px-3 py-5 text-center transition-colors sm:px-5 sm:py-6',
          dragging ? 'border-slate-900 bg-slate-50' : 'border-slate-300 bg-white hover:border-slate-400',
        ]"
        @click="fileInputRef?.click()"
        @keydown.enter="fileInputRef?.click()"
        @keydown.space="fileInputRef?.click()"
        @dragover.prevent="dragging = true"
        @dragleave="dragging = false"
        @drop="onDrop"
      >
        <p class="text-[13px] text-slate-500">
          <!-- 手机上没有拖拽，改成「点一下选文件」；桌面保留原提示 -->
          <span class="hidden sm:inline">把音频 / 视频文件拖到这里，或点右上角「上传文件」</span>
          <span class="sm:hidden">点这里选择手机里的音频 / 视频</span>
        </p>
        <p class="mt-1 text-[12px] text-slate-400">
          支持 mp3 / wav / m4a / flac / aac / ogg 与 mp4 / mkv / mov / webm 等（视频仅提取音轨）
        </p>
      </div>
    </div>

    <div
      v-if="notice"
      role="status"
      :class="[
        'rounded-lg border px-4 py-2.5 text-[13px]',
        notice.tone === 'error'
          ? 'border-red-100 bg-red-50 text-red-700'
          : 'border-sky-100 bg-sky-50 text-sky-700',
      ]"
    >
      {{ notice.text }}
    </div>

    <!-- 上传进度 -->
    <div v-if="uploads.length > 0" class="space-y-2 rounded-xl border border-slate-200 bg-white p-4">
      <div v-for="task in uploads" :key="task.id">
        <div class="flex items-center justify-between text-[12px]">
          <span class="truncate text-slate-600">{{ task.name }}</span>
          <span
            :class="[
              'shrink-0 tabular-nums',
              task.status === 'error' ? 'text-red-600' : 'text-slate-400',
            ]"
          >
            {{
              task.status === 'error'
                ? task.error ?? '失败'
                : task.status === 'done'
                  ? '上传完成'
                  : `${task.percent}%`
            }}
          </span>
        </div>
        <div class="mt-1 h-1 w-full overflow-hidden rounded-full bg-slate-100">
          <div
            :class="[
              'h-full rounded-full transition-[width]',
              task.status === 'error' ? 'bg-red-400' : 'bg-slate-900',
            ]"
            :style="{ width: (task.status === 'error' ? 100 : task.percent) + '%' }"
          />
        </div>
      </div>
    </div>

    <!-- 素材目录导入面板 -->
    <div v-if="inboxOpen" class="rounded-xl border border-slate-200 bg-white p-5">
      <div class="flex items-start justify-between gap-4">
        <div class="min-w-0">
          <h3 class="text-sm font-medium text-slate-900">从素材目录导入</h3>
          <p class="mt-1 text-[12px] leading-relaxed text-slate-500">
            把音频 / 视频文件放进下面这个目录，然后点「重新扫描」即可批量导入（原文件保留在目录里）。
          </p>
          <code class="mt-2 block break-all rounded bg-slate-50 px-2 py-1.5 text-[11px] text-slate-600">
            {{ healthData?.paths.inbox_dir ?? '读取中…' }}
          </code>
        </div>
        <div class="flex shrink-0 items-center gap-2">
          <button
            type="button"
            class="flex items-center gap-1.5 rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs text-slate-600 hover:bg-slate-50"
            @click="void refetchInbox()"
          >
            <RefreshIcon class-name="h-3.5 w-3.5" />
            重新扫描
          </button>
          <button
            type="button"
            class="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100"
            @click="inboxOpen = false"
          >
            <CloseIcon class-name="h-4 w-4" />
          </button>
        </div>
      </div>

      <div class="mt-3 max-h-64 overflow-auto rounded-lg border border-slate-100">
        <p v-if="inboxLoading" class="px-3 py-4 text-[13px] text-slate-400">扫描中…</p>
        <p
          v-if="!inboxLoading && inboxItems.length === 0"
          class="px-3 py-4 text-[13px] text-slate-400"
        >
          目录里还没有文件。把素材拷进去后点「重新扫描」。
        </p>
        <label
          v-for="item in inboxItems"
          :key="item.path"
          :class="[
            'flex cursor-pointer items-center gap-3 border-b border-slate-50 px-3 py-2 last:border-0',
            item.imported || !item.supported ? 'cursor-not-allowed opacity-50' : 'hover:bg-slate-50',
          ]"
        >
          <input
            type="checkbox"
            :disabled="item.imported || !item.supported"
            :checked="selected.includes(item.path)"
            class="accent-slate-900"
            @change="
              (event) => {
                const checked = (event.target as HTMLInputElement).checked
                selected = checked
                  ? [...selected, item.path]
                  : selected.filter((p) => p !== item.path)
              }
            "
          />
          <span class="min-w-0 flex-1 truncate text-[13px] text-slate-700">{{ item.name }}</span>
          <span class="shrink-0 text-[11px] text-slate-400">{{ formatBytes(item.size_bytes) }}</span>
          <span v-if="item.imported" class="shrink-0 text-[11px] text-emerald-600">已导入</span>
          <span v-if="!item.supported && !item.imported" class="shrink-0 text-[11px] text-amber-600">
            格式不支持
          </span>
        </label>
      </div>

      <div class="mt-3 flex flex-wrap items-center justify-between gap-2">
        <span class="text-[12px] text-slate-400">
          共 {{ inboxItems.length }} 个文件，已选 {{ selected.length }} 个
        </span>
        <div class="flex flex-wrap items-center gap-2">
          <CategorySelect v-model="inboxCategory" :items="categories" label="导入到分类" />
          <button
            type="button"
            :disabled="selected.length === 0 || importMutation.isPending.value"
            class="rounded-lg border border-slate-200 px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-40"
            @click="
              importMutation.mutate({
                files: selected,
                categoryId: inboxCategory === '' ? null : Number(inboxCategory),
              })
            "
          >
            导入选中
          </button>
          <button
            type="button"
            :disabled="importMutation.isPending.value"
            class="rounded-lg bg-slate-900 px-3 py-1.5 text-xs text-white hover:bg-slate-700 disabled:opacity-40"
            @click="
              importMutation.mutate({
                files: undefined,
                categoryId: inboxCategory === '' ? null : Number(inboxCategory),
              })
            "
          >
            {{ importMutation.isPending.value ? '导入中…' : '全部导入' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 列表 -->
    <div class="rounded-xl border border-slate-200 bg-white">
      <div class="border-b border-slate-100 px-3 py-3 sm:px-5">
        <div class="flex flex-wrap items-center gap-2 sm:gap-3">
          <h3 class="text-sm font-medium text-slate-900">
            已导入素材
            <span class="ml-1 text-[12px] font-normal text-slate-400">· {{ scopeLabel }}</span>
            <span class="ml-2 text-[12px] font-normal text-slate-400">共 {{ items.length }} 个</span>
          </h3>
          <span v-if="processingCount > 0" class="text-[12px] text-slate-500">
            {{ processingCount }} 个正在处理…
          </span>

          <!-- 窄屏整组换行并允许内部折行，避免搜索框 + 排序 + 批量管理把卡片顶出横向滚动 -->
          <div class="ml-auto flex w-full flex-wrap items-center gap-2 sm:w-auto">
            <div class="relative">
              <SearchIcon
                class-name="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400"
              />
              <input
                v-model="keyword"
                placeholder="搜索标题 / 文件名…"
                class="w-[180px] rounded-lg border border-slate-200 py-1.5 pl-8 pr-3 text-[12px] text-slate-700 outline-none transition-colors focus:border-slate-400"
              />
            </div>
            <div class="flex items-center gap-1 rounded-lg border border-slate-200 px-2 py-1.5">
              <SortIcon class-name="h-3.5 w-3.5 text-slate-400" />
              <select
                :value="sort"
                title="排序方式"
                class="bg-transparent text-[12px] text-slate-600 outline-none"
                @change="onSortChange"
              >
                <option value="recent">最近导入</option>
                <option value="title">按标题</option>
                <option value="duration">按时长</option>
              </select>
            </div>
            <button
              type="button"
              :aria-pressed="batchMode"
              :class="[
                'flex h-8 items-center gap-1.5 rounded-lg border px-3 text-[12px] transition-colors',
                batchMode
                  ? 'border-slate-900 bg-slate-900 text-white'
                  : 'border-slate-200 text-slate-600 hover:bg-slate-50',
              ]"
              @click="enterBatchMode"
            >
              <ListIcon class-name="h-3.5 w-3.5" />
              {{ batchMode ? '退出批量' : '批量管理' }}
            </button>
          </div>
        </div>

        <!-- 分类 chips：计数来自 /api/categories 的分类子集计数 -->
        <div class="mt-2.5">
          <CategoryChips
            :items="categories"
            :uncategorized-count="categoriesData?.uncategorized_count ?? 0"
            :loading="categoriesLoading"
            :selected="categoryFilter"
            @select="
              (value) => {
                categoryFilter = value
                // 换筛选口径时清空多选，避免选中了看不到的行
                batchIds = []
                moveMenuOpen = false
              }
            "
            @manage="managerOpen = true"
          />
        </div>
      </div>

      <!-- 批量操作条 -->
      <div
        v-if="batchMode"
        class="flex flex-wrap items-center gap-2 border-b border-slate-100 bg-slate-50 px-3 py-2 sm:px-5"
      >
        <span class="text-[12px] text-slate-600">
          已选 <span class="tabular-nums">{{ batchIds.length }}</span> 项
        </span>

        <div class="relative">
          <button
            type="button"
            :disabled="batchIds.length === 0"
            aria-haspopup="menu"
            :aria-expanded="moveMenuOpen"
            class="flex h-8 items-center gap-1.5 rounded-lg bg-slate-900 px-3 text-[12px] text-white transition-colors hover:bg-slate-700 disabled:opacity-40"
            @click="moveMenuOpen = !moveMenuOpen"
          >
            移动到分类
            <span aria-hidden="true">▾</span>
          </button>

          <template v-if="moveMenuOpen">
            <!-- 桌面：锚定下拉 -->
            <div class="fixed inset-0 z-20 hidden sm:block" @click="moveMenuOpen = false" />
            <div
              role="menu"
              class="absolute left-0 z-30 mt-1 hidden max-h-72 w-56 overflow-y-auto rounded-xl border border-slate-200 bg-white py-1 shadow-lg sm:block"
            >
              <button
                v-for="option in moveOptions"
                :key="option.id ?? 'none'"
                type="button"
                role="menuitem"
                class="flex h-8 w-full items-center px-3 text-left text-[12px] text-slate-600 transition-colors hover:bg-slate-50"
                @click="moveMutation.mutate({ ids: batchIds, categoryId: option.id })"
              >
                <span class="truncate">{{ option.name }}</span>
              </button>
            </div>

            <!-- 移动端：底部弹层（触摸目标 ≥32px） -->
            <div
              class="fixed inset-0 z-50 flex items-end justify-center bg-slate-900/40 sm:hidden"
              @click="moveMenuOpen = false"
            >
              <div class="w-full rounded-t-2xl bg-white pb-[env(safe-area-inset-bottom)]" @click.stop>
                <p class="px-4 py-3 text-[13px] font-medium text-slate-900">
                  把 {{ batchIds.length }} 个素材移动到…
                </p>
                <div class="max-h-[55dvh] overflow-y-auto border-t border-slate-100">
                  <button
                    v-for="option in moveOptions"
                    :key="option.id ?? 'none'"
                    type="button"
                    class="flex w-full items-center px-4 py-3 text-left text-[14px] text-slate-700 active:bg-slate-50"
                    @click="moveMutation.mutate({ ids: batchIds, categoryId: option.id })"
                  >
                    <span class="truncate">{{ option.name }}</span>
                  </button>
                </div>
                <button
                  type="button"
                  class="w-full border-t border-slate-100 px-4 py-3 text-[14px] text-slate-500"
                  @click="moveMenuOpen = false"
                >
                  取消
                </button>
              </div>
            </div>
          </template>
        </div>

        <button
          type="button"
          class="flex h-8 items-center rounded-lg border border-slate-200 bg-white px-3 text-[12px] text-slate-600 transition-colors hover:bg-slate-50"
          @click="exitBatchMode"
        >
          取消
        </button>

        <span v-if="moveMutation.isPending.value" class="text-[12px] text-slate-500">移动中…</span>
      </div>

      <ListSkeleton v-if="mediaLoading" />
      <p v-if="mediaIsError" class="px-3 py-8 text-center text-[13px] text-red-600 sm:px-5">
        读取失败：{{ (mediaError as Error).message }}
      </p>
      <div v-if="!mediaLoading && items.length === 0" class="px-3 py-12 text-center sm:px-5">
        <p class="text-[13px] text-slate-400">
          {{
            categoryFilter === null
              ? '还没有素材。上传一个英语音频，开始你的第一课。'
              : `「${scopeLabel}」下还没有素材。`
          }}
        </p>
      </div>
      <p
        v-if="!mediaLoading && items.length > 0 && visible.length === 0"
        class="px-3 py-12 text-center text-[13px] text-slate-400 sm:px-5"
      >
        没有匹配「{{ keyword }}」的素材。
      </p>

      <div v-for="media in visible" :key="media.id" class="border-b border-slate-50 last:border-0">
        <MediaRow
          :media="media"
          :category-name="categoryNameFor(media)"
          :selectable="batchMode"
          :checked="batchIds.includes(media.id)"
          :busy="
            deleteMutation.isPending.value || renameMutation.isPending.value || retryMutation.isPending.value
          "
          @toggle-select="(checked) => toggleBatch(media.id, checked)"
          @play="(m) => player.open(m, true)"
          @delete="handleDelete"
          @retry="(m) => retryMutation.mutate(m.id)"
          @rename="(m, title) => renameMutation.mutate({ id: m.id, title })"
        />
      </div>
    </div>

    <!-- 管理分类面板 -->
    <CategoryManager
      v-if="managerOpen"
      :items="categories"
      @close="managerOpen = false"
      @changed="refresh"
      @notify="(text, tone) => showNotice(text, tone ?? 'info')"
    />

    <!-- 环境自检 -->
    <details class="rounded-xl border border-slate-200 bg-white px-3 py-4 sm:px-5">
      <summary class="cursor-pointer text-sm font-medium text-slate-900">环境自检</summary>
      <ul class="mt-3 space-y-2 text-[13px]">
        <li class="flex items-center gap-2">
          <span :class="healthData?.checks.database ? 'text-green-600' : 'text-slate-400'">
            {{ healthData?.checks.database ? '✓' : '○' }}
          </span>
          <span class="text-slate-600">SQLite 数据库已就绪</span>
        </li>
        <li class="flex items-center gap-2">
          <span
            :class="
              healthData?.checks.ffmpeg && healthData?.checks.ffprobe
                ? 'text-green-600'
                : 'text-amber-500'
            "
          >
            {{ healthData?.checks.ffmpeg && healthData?.checks.ffprobe ? '✓' : '!' }}
          </span>
          <span class="text-slate-600">
            ffmpeg / ffprobe
            {{
              healthData && !(healthData.checks.ffmpeg && healthData.checks.ffprobe)
                ? '（未检测到，转码与音频切片需要）'
                : ''
            }}
          </span>
        </li>
        <li class="flex items-start gap-2">
          <span
            :class="
              healthData?.checks.asr && healthData?.checks.asr_model
                ? 'text-green-600'
                : 'text-amber-500'
            "
          >
            {{ healthData?.checks.asr && healthData?.checks.asr_model ? '✓' : '!' }}
          </span>
          <span class="text-slate-600">
            语音识别 faster-whisper
            {{ healthData?.asr.model ? `（${healthData.asr.model}）` : '' }}
            {{
              healthData && !healthData.checks.asr
                ? '（未安装 ML 依赖：pip install -r backend/requirements-ml.txt）'
                : ''
            }}
            {{
              healthData && healthData.checks.asr && !healthData.checks.asr_model
                ? '（模型未就绪，处理时自动下载）'
                : ''
            }}
          </span>
        </li>
        <li class="flex items-start gap-2">
          <span :class="healthData?.checks.dict ? 'text-green-600' : 'text-amber-500'">
            {{ healthData?.checks.dict ? '✓' : '!' }}
          </span>
          <span class="text-slate-600">
            离线词典 ECDICT
            {{
              healthData?.dict.entries
                ? `（${healthData.dict.entries.toLocaleString('en-US')} 词条）`
                : healthData && !healthData.checks.dict
                  ? '（未安装，查词将无法给出站内释义）'
                  : ''
            }}
          </span>
        </li>
        <li class="flex items-start gap-2">
          <span class="text-slate-400">○</span>
          <span class="text-slate-600">
            在线翻译引擎：{{ healthData?.config.translate_engines.join(' → ') ?? '—' }}
          </span>
        </li>
        <li class="flex items-start gap-2">
          <span class="text-slate-400">○</span>
          <span class="break-all text-slate-600">
            数据目录：{{ healthData?.paths.data_dir ?? '—' }}
          </span>
        </li>
      </ul>
    </details>
  </div>
</template>

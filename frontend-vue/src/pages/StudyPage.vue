<script setup lang="ts">
/**
 * 学习页：一句一页的听写工作台（v1.12 改版）。逐行照搬旧 `StudyPage.tsx` 1–760 行主体。
 *
 * 三段式布局（高度锁定在视口内）：
 *   顶部条（媒体信息 + 整体操作）
 *   ├─ 句子舞台（flex-1，正文大字自适应）  → `components/SentenceStage.vue`
 *   └─ 底部（上一句 / 序号 / 下一句 + 句子索引宫格）
 *
 * 原有能力全部保留：单句播放 / 单句循环 / A-B 循环、听写输入与词级标红、
 * 查词浮层、笔记、拆分 / 合并 / 重译 / 编辑。
 *
 * P4-2 起练习区改为**题型动态挂载**：本页只按 `code` 解析出 `Answer` 组件
 * （`question-types/index.ts::resolve`）并交给 `SentenceStage` 用 `<component :is>`
 * 渲染。因此「加一个题型」不再需要改这一页（见 ADR-001 §5.5.1）。
 *
 * ⭐⭐ **「下一句」按钮绝不加 `autoFocus` / `v-focus`** —— Enter 双触发坑（v1.12）：
 * 焦点在按钮上时按 Enter 会先命中按钮 → 提交后立刻翻页，校验结果根本看不到。
 * 详见 `types/study.ts:79-86`。
 */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import {
  PROCESSING_STATUSES,
  STATUS_LABEL,
  clearClips,
  getMedia,
  getMediaNotes,
  listQuestionTypes,
  mergeSentence,
  openProgressStream,
  retranslateSentence,
  retranscribeMedia,
  splitSentence,
  updateSentence,
  type MediaDetail,
  type ProgressEventData,
  type SentenceItem,
} from '../api/client'
import NotesPanel from '../components/NotesPanel.vue'
import SentenceStage from '../components/SentenceStage.vue'
import WordPopover from '../components/WordPopover.vue'
import { useClipPlayer } from '../composables/useClipPlayer'
import { FALLBACK_CODE, resolve } from '../question-types'
import { usePlayer } from '../stores/player'
import { formatBytes, formatDuration, formatSeconds } from '../utils/format'
import { gridClass, type Draft, type StatOverride, type WordPopoverTarget, type WordRect } from '../types/study'
import { AlertIcon, NoteIcon, RefreshIcon, TargetIcon } from '../components/icons'

/** 逐句的听写草稿：翻页回来时输入的内容与上次校验结果都还在 */
const EMPTY_DRAFT: Draft = { result: null, text: '' }

const route = useRoute()
const id = computed(() => Number(route.params.mediaId))

const queryClient = useQueryClient()
const player = usePlayer()
const clip = useClipPlayer()

const live = ref<ProgressEventData | null>(null)
const revealEn = ref<Record<number, boolean>>({})
const revealZh = ref<Record<number, boolean>>({})
const editingId = ref<number | null>(null)
const notice = ref<string | null>(null)
const autoReveal = ref(true)
const stats = ref<Record<number, StatOverride>>({})
const wordTarget = ref<WordPopoverTarget | null>(null)
const notesOpen = ref(false)
const toolsOpen = ref(false)
const correctOpen = ref(false)
const noteOpen = ref(false)
const drafts = ref<Record<number, Draft>>({})
const highlightId = ref<number | null>(null)

//: 当前句在句子数组里的下标（注意与 sentence.idx 不同：后者是切分序号）
const index = ref(0)

const { data, isLoading, isError, error } = useQuery({
  queryKey: ['media', id],
  queryFn: () => getMedia(id.value),
  enabled: Number.isFinite(id.value),
  // SSE 为主，轮询兜底（SSE 不可用时仍能推进）
  refetchInterval: (query) => {
    const detail = query.state.data as MediaDetail | undefined
    return detail && PROCESSING_STATUSES.includes(detail.status) ? 2500 : false
  },
})

// 笔记汇总（用于顶部入口的计数与面板）
const notesQuery = useQuery({
  queryKey: ['media-notes', id],
  queryFn: () => getMediaNotes(id.value),
  enabled: Number.isFinite(id.value),
})
const noteCount = computed(() => notesQuery.data.value?.total ?? 0)

// ---- 题型清单（P4-2）：以后端注册表为唯一真相 ----
// 拉取失败不重试、不阻塞页面：`activeTypeCode` 会降级到内置 dictation，
// 用户看到的仍是可用界面（不是白屏，也不是错误提示）。
const questionTypesQuery = useQuery({
  queryKey: ['question-types'],
  queryFn: listQuestionTypes,
  retry: false,
  staleTime: 10 * 60_000,
})
const backendTypeCodes = computed(() =>
  (questionTypesQuery.data.value?.types ?? []).map((item) => item.code),
)

//: 当前句的题型 code。P4-3 之前站点只有听写一种形态（没有 `questions` 表），
//: 因此恒为兜底题型；P4-3 起改成 `current.value?.question_type ?? FALLBACK_CODE` 即可，
//: **挂载链路不用再动**。
const preferredTypeCode = computed<string>(() => FALLBACK_CODE)

//: 实际挂载的题型：后端清单里没有它（拉取失败 / 清单为空 / 没有该 code）→ 降级。
const activeTypeCode = computed<string>(() =>
  backendTypeCodes.value.includes(preferredTypeCode.value)
    ? preferredTypeCode.value
    : FALLBACK_CODE,
)

//: 题型组件（Answer + Result）。`resolve()` 自带二次降级：即便 `code` 在清单里、
//: 前端却没有对应组件（后端先上线），也不会白屏。
const answerType = computed(() => resolve(activeTypeCode.value))

const status = computed(() => live.value?.status ?? data.value?.status ?? '')
const progress = computed(() => live.value?.progress ?? data.value?.progress ?? 0)
const processing = computed(() => PROCESSING_STATUSES.includes(status.value))

// ---- SSE 进度订阅（处理中才连；清理函数在 watch 的 onCleanup 里，卸载也会跑）----
watch(
  [id, () => data.value?.status],
  (_v, _o, onCleanup) => {
    const detail = data.value
    if (!detail || !PROCESSING_STATUSES.includes(detail.status)) {
      live.value = null
      return
    }
    const close = openProgressStream(id.value, (event) => {
      live.value = event
      if (event.done) {
        void queryClient.invalidateQueries({ queryKey: ['media', id.value] })
        void queryClient.invalidateQueries({ queryKey: ['media'] })
      }
    })
    onCleanup(() => close())
  },
  { immediate: true },
)

function applyDetail(detail: MediaDetail) {
  queryClient.setQueryData(['media', id.value], detail)
}

const editMutation = useMutation({
  mutationFn: (vars: { sid: number; patch: { text_en?: string; text_zh?: string } }) =>
    updateSentence(vars.sid, vars.patch),
  onSuccess: (detail) => {
    applyDetail(detail)
    editingId.value = null
    notice.value = '已保存修改'
  },
  onError: (e) => {
    notice.value = `保存失败：${(e as Error).message}`
  },
})

const retranslateMutation = useMutation({
  mutationFn: (sid: number) => retranslateSentence(sid),
  onSuccess: (detail) => applyDetail(detail),
  onError: (e) => {
    notice.value = `重新翻译失败：${(e as Error).message}`
  },
})

// 原文「易听错」标记（v1.14）：整组覆盖保存，服务端归并区间后回传完整详情。
// ⚠️ 只改 text_en 的 PATCH **不带 marks** → 后端按 `model_fields_set` 视为「未传」，
//    不会动 marks（「改原文清空 marks」由后端在校对分支里显式处理，见 api/sentences.py）。
const marksMutation = useMutation({
  mutationFn: (vars: { sid: number; marks: number[][] }) =>
    updateSentence(vars.sid, { marks: vars.marks }),
  onSuccess: (detail) => applyDetail(detail),
  onError: (e) => {
    notice.value = `标记保存失败：${(e as Error).message}`
  },
})

const splitMutation = useMutation({
  mutationFn: (vars: { sid: number; atMs: number }) => splitSentence(vars.sid, { at_ms: vars.atMs }),
  onSuccess: (detail) => {
    applyDetail(detail)
    notice.value = '已拆分'
  },
  onError: (e) => {
    notice.value = `拆分失败：${(e as Error).message}`
  },
})

const mergeMutation = useMutation({
  mutationFn: (sid: number) => mergeSentence(sid, 'next'),
  onSuccess: (detail) => {
    applyDetail(detail)
    notice.value = '已与下一句合并'
  },
  onError: (e) => {
    notice.value = `合并失败：${(e as Error).message}`
  },
})

const rebuildMutation = useMutation({
  mutationFn: () => retranscribeMedia(id.value),
  onSuccess: () => {
    notice.value = '已开始重新识别，完成后自动刷新'
    stats.value = {}
    drafts.value = {}
    void queryClient.invalidateQueries({ queryKey: ['media', id.value] })
  },
  onError: (e) => {
    notice.value = `重新识别失败：${(e as Error).message}`
  },
})

const clearClipsMutation = useMutation({
  mutationFn: () => clearClips(id.value),
  onSuccess: () => {
    notice.value = '切片已清理，释放磁盘空间（逐句播放暂不可用）'
    clip.stop()
    void queryClient.invalidateQueries({ queryKey: ['media', id.value] })
  },
  onError: (e) => {
    notice.value = `清理失败：${(e as Error).message}`
  },
})

const sentences = computed<SentenceItem[]>(() => data.value?.sentences ?? [])

// 把「本次会话刚提交的统计」叠加到服务端数据之上
const effective = computed<SentenceItem[]>(() =>
  sentences.value.map((s) => {
    const patch = stats.value[s.id]
    return patch ? { ...s, ...patch } : s
  }),
)

const total = computed(() => effective.value.length)
const current = computed<SentenceItem | null>(() =>
  total.value > 0 ? (effective.value[Math.min(index.value, total.value - 1)] ?? null) : null,
)

// 句子数变化（拆分 / 合并 / 重新识别）后把下标收回合法范围
watch(
  () => sentences.value.length,
  (count) => {
    index.value = Math.min(index.value, Math.max(count - 1, 0))
  },
)

/** 跳到第 next 句（越界自动收敛）；切句时停掉上一句的音频。
 *  Vue 里闭包读 ref 永远是最新值，不需要 React 的 navRef 技巧。 */
function goTo(next: number) {
  const last = Math.max(total.value - 1, 0)
  index.value = Math.min(Math.max(next, 0), last)
  clip.stop()
}

// ← / → 翻页。⭐ 焦点在输入框里时**不劫持**方向键（那时方向键是移动光标）——
// `verify_m5` 的 B9 断言的就是这条。
function onArrowKey(event: KeyboardEvent) {
  if (event.metaKey || event.ctrlKey || event.altKey) return
  if (editingId.value !== null) return
  const el = event.target as HTMLElement | null
  if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable)) {
    return
  }
  if (event.key === 'ArrowRight') {
    event.preventDefault()
    goTo(index.value + 1)
  } else if (event.key === 'ArrowLeft') {
    event.preventDefault()
    goTo(index.value - 1)
  }
}
onMounted(() => window.addEventListener('keydown', onArrowKey))
onUnmounted(() => window.removeEventListener('keydown', onArrowKey))

const summary = computed(() => {
  const attempted = effective.value.filter((s) => s.attempt_count > 0)
  const avg = attempted.length
    ? Math.round((attempted.reduce((n, s) => n + s.best_accuracy, 0) / attempted.length) * 10) / 10
    : 0
  return {
    total: effective.value.length,
    attempted: attempted.length,
    mastered: effective.value.filter((s) => s.mastered).length,
    attempts: effective.value.reduce((n, s) => n + s.attempt_count, 0),
    avg,
  }
})

const playable = computed(() => Boolean(data.value && (data.value.has_audio || status.value === 'done')))
const clipsReady = computed(
  () => sentences.value.length > 0 && sentences.value.every((s) => s.clip_url),
)

// notice 自动消失
let noticeTimer: number | null = null
watch(notice, (value) => {
  if (!value) return
  if (noticeTimer !== null) window.clearTimeout(noticeTimer)
  noticeTimer = window.setTimeout(() => {
    notice.value = null
    noticeTimer = null
  }, 3200)
})
onUnmounted(() => {
  if (noticeTimer !== null) window.clearTimeout(noticeTimer)
})

function revealAll(kind: 'en' | 'zh' | 'none') {
  if (kind === 'none') {
    revealEn.value = {}
    revealZh.value = {}
    return
  }
  const map = Object.fromEntries(sentences.value.map((s) => [s.id, true]))
  if (kind === 'en') revealEn.value = map
  else revealZh.value = map
}

/** 从笔记面板跳到某句：直接翻到那一页 + 展开原文 + 短暂高亮 */
function jumpToSentence(sid: number) {
  const target = effective.value.findIndex((s) => s.id === sid)
  if (target < 0) return
  revealEn.value = { ...revealEn.value, [sid]: true }
  highlightId.value = sid
  goTo(target)
  window.setTimeout(() => {
    highlightId.value = highlightId.value === sid ? null : highlightId.value
  }, 2400)
}

function patchDraft(sid: number, patch: Partial<Draft>) {
  drafts.value = { ...drafts.value, [sid]: { ...(drafts.value[sid] ?? EMPTY_DRAFT), ...patch } }
}

function setStat(sid: number, stat: StatOverride) {
  stats.value = { ...stats.value, [sid]: stat }
}

function onWordClick(word: string, rect: WordRect) {
  const cur = current.value
  if (!cur) return
  wordTarget.value = {
    word,
    sentenceId: cur.id,
    mediaId: id.value,
    context: cur.text_en,
    rect,
  }
}

function saveMarksFor(marks: number[][]): Promise<void> {
  const sid = current.value?.id
  if (sid == null) return Promise.resolve()
  return marksMutation.mutateAsync({ sid, marks }).then(() => undefined)
}

// —— 面向当前句的回调（在 script 里取 `current.value?.id`，避免模板箭头函数里
//    `current` 的类型窄化失效；这些函数只在 SentenceStage 的 props 上使用）——
function toggleEnCurrent() {
  const sid = current.value?.id
  if (sid == null) return
  revealEn.value = { ...revealEn.value, [sid]: !(revealEn.value[sid] ?? false) }
}
function toggleZhCurrent() {
  const sid = current.value?.id
  if (sid == null) return
  revealZh.value = { ...revealZh.value, [sid]: !(revealZh.value[sid] ?? false) }
}
function draftForCurrent(patch: Partial<Draft>) {
  const sid = current.value?.id
  if (sid == null) return
  patchDraft(sid, patch)
}
function recordCurrent(stat: StatOverride) {
  const sid = current.value?.id
  if (sid == null) return
  setStat(sid, stat)
}
function startEdit() {
  const sid = current.value?.id
  if (sid == null) return
  editingId.value = sid
}
function cancelEdit() {
  editingId.value = null
}
function setCorrectOpenV(next: boolean) {
  correctOpen.value = next
}
function setNoteOpenV(next: boolean) {
  noteOpen.value = next
}

function saveEdit(patch: { text_en?: string; text_zh?: string }) {
  const sid = current.value?.id
  if (sid == null) return
  editMutation.mutate({ sid, patch })
}

function retranslateCurrent() {
  const sid = current.value?.id
  if (sid == null) return
  retranslateMutation.mutate(sid)
}

function mergeCurrentWithNext() {
  const sid = current.value?.id
  if (sid == null) return
  mergeMutation.mutate(sid)
}

function splitCurrentAt(atMs: number) {
  const sid = current.value?.id
  if (sid == null) return
  splitMutation.mutate({ sid, atMs })
}

const busy = computed(
  () =>
    editMutation.isPending.value ||
    retranslateMutation.isPending.value ||
    splitMutation.isPending.value ||
    mergeMutation.isPending.value,
)

function openPlayer() {
  if (data.value) player.open(data.value, true)
}
function playerActive(): boolean {
  return player.current?.id === data.value?.id
}
</script>

<template>
  <div class="flex h-full min-h-0 flex-col gap-2 overflow-hidden sm:gap-3">
    <!-- 隐藏的句子音频元素 -->
    <audio :ref="clip.bind" preload="auto" class="hidden" />

    <!-- 单词浮层（M4：查词 + 加入生词本） -->
    <WordPopover
      v-if="wordTarget"
      :key="`${wordTarget.word}-${wordTarget.sentenceId ?? 0}`"
      :target="wordTarget"
      @close="wordTarget = null"
    />

    <!-- 笔记汇总面板（M5：FR-A6） -->
    <NotesPanel v-if="notesOpen" :media-id="id" @close="notesOpen = false" @jump="jumpToSentence" />

    <!-- --------------------------- 顶部条 --------------------------- -->
    <div class="shrink-0 rounded-xl border border-slate-200 bg-white px-3 py-2 sm:px-4 sm:py-2.5">
      <!--
        窄屏允许换行：右侧按钮组（播放 / 笔记 / 工具）是 shrink-0，单行时会把
        中间栏压到 ~90px —— 标题被截断，下面那行「已听写 / 已掌握 / 平均最佳」
        还会被压成竖排单字。手机上让按钮组独占一行（见下方 w-full sm:w-auto），
        中间栏就能拿回整宽。
      -->
      <div class="flex flex-wrap items-center gap-2 sm:gap-3">
        <RouterLink
          to="/"
          title="返回媒体库"
          class="shrink-0 rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs text-slate-600 transition-colors hover:bg-slate-50"
        >
          ←
        </RouterLink>

        <div class="min-w-0 flex-1">
          <div class="flex items-baseline gap-2">
            <h2 class="truncate text-[14px] font-medium text-slate-900">
              {{ data?.title ?? '加载中…' }}
            </h2>
            <span v-if="total > 0" class="shrink-0 text-[12px] tabular-nums text-slate-400">
              第 {{ Math.min(index + 1, total) }} / {{ total }} 句
            </span>
          </div>
          <div class="mt-0.5 flex flex-wrap items-center gap-x-3 text-[11px] text-slate-400">
            <span
              :class="[
                'rounded-full px-2 py-0.5',
                status === 'failed'
                  ? 'bg-red-50 text-red-600'
                  : processing
                    ? 'bg-amber-50 text-amber-600'
                    : 'bg-emerald-50 text-emerald-600',
              ].join(' ')"
            >
              {{ STATUS_LABEL[status] ?? status }}
              <template v-if="processing"> {{ progress }}%</template>
            </span>
            <span v-if="data" class="tabular-nums">{{ formatDuration(data.duration_ms) }}</span>
            <span v-if="data" class="hidden sm:inline">{{ formatBytes(data.size_bytes) }}</span>
            <span v-if="data" class="hidden sm:inline">
              {{ data.type === 'video' ? '视频（仅音轨）' : '音频' }}
            </span>
            <span v-if="total > 0" class="flex flex-wrap items-center gap-x-1.5 gap-y-0.5">
              <!-- 这一组是「图标 + 三段文字」。**绝不能**做成不换行的 flex ——
                   里面的裸文本会各自成为 flex item，被压到 min-content（= 一个汉字宽），
                   于是「已听写」竖排成三行单字。现在每段 whitespace-nowrap 保持完整，
                   整组按「段」换行，最窄也只会掉到下一行，不会拆字。 -->
              <span class="flex items-center gap-1 whitespace-nowrap">
                <TargetIcon class-name="h-3 w-3 shrink-0" />
                已听写
                <span class="tabular-nums text-slate-600">
                  {{ summary.attempted }}/{{ summary.total }}
                </span>
              </span>
              <span class="whitespace-nowrap">
                · 已掌握 <span class="tabular-nums text-emerald-600">{{ summary.mastered }}</span>
              </span>
              <span v-if="summary.attempted > 0" class="whitespace-nowrap">
                · 平均最佳 <span class="tabular-nums text-slate-600">{{ summary.avg }}%</span>
              </span>
            </span>
          </div>
        </div>

        <!-- 手机（<sm）上 w-full 让它换到第二行并右对齐，把第一行整宽让给标题；
             sm 起恢复 w-auto，回到原来的单行布局 -->
        <div class="flex w-full shrink-0 items-center justify-end gap-1 sm:w-auto sm:gap-1.5">
          <button
            type="button"
            data-testid="open-player"
            :disabled="!playable"
            :class="[
              'rounded-lg px-2 py-1.5 text-[11px] transition-colors sm:px-2.5 sm:text-xs',
              playable
                ? 'bg-slate-900 text-white hover:bg-slate-700'
                : 'cursor-not-allowed bg-slate-100 text-slate-400',
            ].join(' ')"
            @click="openPlayer"
          >
            <!-- 窄屏上标题已经要截断了，按钮文案收缩成「播放 / 播放中」 -->
            <span class="sm:hidden">{{ playerActive() ? '播放中' : '播放' }}</span>
            <span class="hidden sm:inline">{{ playerActive() ? '整段播放中' : '整段播放' }}</span>
          </button>
          <button
            v-if="total > 0"
            type="button"
            title="查看本媒体全部句子笔记"
            class="flex items-center gap-1 rounded-lg border border-slate-200 px-2 py-1.5 text-[11px] text-slate-600 transition-colors hover:bg-slate-50 sm:px-2.5 sm:text-xs"
            @click="notesOpen = true"
          >
            <NoteIcon class-name="h-3.5 w-3.5" />
            笔记{{ noteCount > 0 ? `（${noteCount}）` : '' }}
          </button>
          <button
            type="button"
            title="更多操作"
            :class="[
              'rounded-lg border px-2 py-1.5 text-[11px] transition-colors sm:px-2.5 sm:text-xs',
              toolsOpen
                ? 'border-slate-900 bg-slate-900 text-white'
                : 'border-slate-200 text-slate-600 hover:bg-slate-50',
            ].join(' ')"
            @click="toolsOpen = !toolsOpen"
          >
            工具 {{ toolsOpen ? '▴' : '▾' }}
          </button>
        </div>
      </div>

      <!-- 工具面板（低频操作收在这里，避免顶部条变高） -->
      <div
        v-if="toolsOpen"
        class="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-slate-100 pt-2.5 text-[11px]"
      >
        <label class="flex cursor-pointer items-center gap-1.5 text-slate-500">
          <input v-model="autoReveal" type="checkbox" class="h-3.5 w-3.5 accent-slate-900" />
          答错后自动显示原文
        </label>
        <div class="flex items-center gap-2">
          <button type="button" class="text-slate-500 hover:text-slate-900" @click="revealAll('en')">
            展开全部原文
          </button>
          <span class="text-slate-200">·</span>
          <button type="button" class="text-slate-500 hover:text-slate-900" @click="revealAll('zh')">
            展开全部翻译
          </button>
          <span class="text-slate-200">·</span>
          <button type="button" class="text-slate-500 hover:text-slate-900" @click="revealAll('none')">
            全部折叠
          </button>
        </div>
        <div class="ml-auto flex items-center gap-2">
          <button
            type="button"
            :disabled="rebuildMutation.isPending.value || processing || !data?.has_audio"
            title="用当前模型重新识别（会重建句子，原笔记与听写记录将清除）"
            class="flex items-center gap-1 rounded-lg border border-slate-200 px-2 py-1 text-[11px] text-slate-600 transition-colors hover:bg-slate-50 disabled:opacity-40"
            @click="rebuildMutation.mutate()"
          >
            <RefreshIcon class-name="h-3.5 w-3.5" />
            重新识别
          </button>
          <button
            v-if="clipsReady"
            type="button"
            :disabled="clearClipsMutation.isPending.value"
            title="删除句子切片以回收磁盘空间"
            class="rounded-lg border border-slate-200 px-2 py-1 text-[11px] text-slate-500 transition-colors hover:bg-slate-50 disabled:opacity-40"
            @click="clearClipsMutation.mutate()"
          >
            清理切片
          </button>
        </div>
      </div>

      <div
        v-if="status === 'failed' && data?.error"
        class="mt-2 flex items-start gap-1.5 rounded-lg bg-red-50 px-3 py-2 text-[12px] text-red-600"
      >
        <AlertIcon class-name="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <span>{{ data.error }}</span>
      </div>

      <div v-if="processing" class="mt-2.5">
        <div class="flex items-center justify-between text-[11px] text-slate-400">
          <span>正在处理：解码 → 识别 → 翻译 → 切片</span>
          <span class="tabular-nums">
            {{ live?.stage ?? STATUS_LABEL[status] ?? status }} {{ progress }}%
          </span>
        </div>
        <div class="mt-1 h-1 w-full overflow-hidden rounded-full bg-slate-100">
          <div
            class="h-full rounded-full bg-slate-900 transition-[width] duration-500"
            :style="{ width: `${Math.max(2, progress)}%` }"
          />
        </div>
      </div>

      <p v-if="isLoading" class="py-3 text-center text-[13px] text-slate-400">加载中…</p>
      <p v-if="isError" class="py-3 text-center text-[13px] text-red-600">
        {{ (error as Error).message }}
      </p>
      <p v-if="notice" class="pt-2 text-[12px] text-sky-700">{{ notice }}</p>
    </div>

    <!-- --------------------------- 句子舞台 --------------------------- -->
    <SentenceStage
      v-if="current"
      :key="current.id"
      :sentence="current"
      :clip="clip"
      :answer-component="answerType.Answer"
      :highlight="highlightId === current.id"
      :show-en="revealEn[current.id] ?? false"
      :show-zh="revealZh[current.id] ?? false"
      :on-toggle-en="toggleEnCurrent"
      :on-toggle-zh="toggleZhCurrent"
      :auto-reveal="autoReveal"
      :draft="drafts[current.id] ?? EMPTY_DRAFT"
      :on-draft="draftForCurrent"
      :on-recorded="recordCurrent"
      :editing="editingId === current.id"
      :on-start-edit="startEdit"
      :on-cancel-edit="cancelEdit"
      :on-save="saveEdit"
      :on-retranslate="retranslateCurrent"
      :on-merge-next="mergeCurrentWithNext"
      :on-split-at-playhead="splitCurrentAt"
      :on-save-marks="saveMarksFor"
      :on-word-click="onWordClick"
      :correct-open="correctOpen"
      :set-correct-open="setCorrectOpenV"
      :note-open="noteOpen"
      :set-note-open="setNoteOpenV"
      :busy="busy"
    />
    <div
      v-else
      class="flex min-h-0 flex-1 items-center justify-center rounded-xl border border-slate-200 bg-white px-5 text-center"
    >
      <p class="text-[13px] text-slate-400">
        <template v-if="!data">加载中…</template>
        <template v-else-if="processing">正在处理，完成后会自动出现句子</template>
        <template v-else-if="status === 'failed'">处理失败，请查看上方错误信息后在「工具」里重试</template>
        <template v-else>还没有句子。</template>
      </p>
    </div>

    <!-- --------------------------- 底部：翻页 + 宫格 --------------------------- -->
    <div
      v-if="total > 0"
      class="shrink-0 rounded-xl border border-slate-200 bg-white px-3 py-2 sm:px-4 sm:py-2.5"
    >
      <div class="flex items-center gap-2 sm:gap-3">
        <button
          type="button"
          :disabled="index <= 0"
          class="rounded-lg border border-slate-200 px-3.5 py-2 text-[13px] text-slate-600 transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40 sm:px-4 sm:py-2.5 sm:text-sm"
          @click="goTo(index - 1)"
        >
          ← 上一句
        </button>

        <div class="flex min-w-0 flex-1 items-center gap-2">
          <span class="shrink-0 text-[11px] tabular-nums text-slate-400">
            {{ current ? `${formatSeconds(current.start_ms / 1000)} – ${formatSeconds(current.end_ms / 1000)}` : '' }}
          </span>
          <div class="ml-auto flex shrink-0 items-center gap-2 text-[10px] text-slate-400">
            <span class="flex items-center gap-1">
              <span class="h-2.5 w-2.5 rounded-sm bg-emerald-200" />已掌握
            </span>
            <span class="flex items-center gap-1">
              <span class="h-2.5 w-2.5 rounded-sm bg-amber-200" />练过
            </span>
            <span class="flex items-center gap-1">
              <span class="h-2.5 w-2.5 rounded-sm bg-slate-200" />未听
            </span>
            <span class="hidden sm:inline">· ← → 翻页</span>
          </div>
        </div>

        <!-- ⭐⭐ 「下一句」按钮：**绝不加 `autoFocus` / `v-focus`**（Enter 双触发坑，
             见 types/study.ts:79-86 与本文件顶部注释） -->
        <button
          type="button"
          :disabled="index >= total - 1"
          class="shrink-0 rounded-lg bg-slate-900 px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-40 sm:px-6 sm:py-3 sm:text-base"
          @click="goTo(index + 1)"
        >
          下一句 →
        </button>
      </div>

      <!-- 句子索引宫格：点击直跳。手机上加高格子到 32px 以满足触摸目标 -->
      <div
        data-testid="sentence-grid"
        class="mt-2 flex max-h-24 flex-wrap gap-1 overflow-y-auto sm:max-h-[7.5rem]"
      >
        <button
          v-for="(sentence, i) in effective"
          :key="sentence.id"
          type="button"
          :title="
            `第 ${i + 1} 句` +
            (sentence.attempt_count > 0
              ? ` · 练过 ${sentence.attempt_count} 次 · 最佳 ${sentence.best_accuracy}%`
              : ' · 还没听写')
          "
          :class="[
            // 触摸目标统一 32px：手机和 iPad 都是手指操作，按屏宽分档是错的
            'h-8 min-w-[2rem] rounded-md px-1 text-[11px] tabular-nums transition-colors',
            gridClass(sentence, i === index),
          ].join(' ')"
          @click="goTo(i)"
        >
          {{ i + 1 }}
        </button>
      </div>
    </div>
  </div>
</template>

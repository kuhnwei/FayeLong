<script setup lang="ts">
/**
 * 句子舞台（一句一页的正文区）：单句播放 / 循环 / A-B 循环、易听错标记、
 * 校对（改原文 / 翻译 / 拆分 / 合并 / 重译）、笔记、听写练习区。
 *
 * 从 `StudyPage.tsx` 内联组件拆出（旧 761–1286 行），**props 接口原样保留** ——
 * 所有 `on*` 回调都保持为**函数 props**（不是 emits），因为 `onSaveMarks` 需要返回
 * Promise（乐观更新要等结果），emits 做不到。
 *
 * P4-2 起多了一个 `answerComponent`（题型作答组件，由宿主按 `code` 解析后传入）：
 * 练习区不再是写死的听写框，而是 `<component :is>` 挂载 —— 本组件因此对题型无感知。
 */
import { computed, ref, watch } from 'vue'
import type { Component } from 'vue'
import type { SentenceItem } from '../api/client'
import ClickableText from './ClickableText.vue'
import NoteEditor from './NoteEditor.vue'
import type { ClipPlayer } from '../composables/useClipPlayer'
import { formatSeconds } from '../utils/format'
import {
  CLIP_PAD_MS,
  rangesToWords,
  stageFontSize,
  translationFontSize,
  wordsToRanges,
  type Draft,
  type StatOverride,
  type WordRect,
} from '../types/study'
import {
  ABLoopIcon,
  CheckIcon,
  EyeIcon,
  EyeOffIcon,
  HighlightIcon,
  LoopIcon,
  MergeIcon,
  NoteIcon,
  PencilIcon,
  PlayIcon,
  PauseIcon,
  ScissorsIcon,
  TranslateIcon,
} from './icons'

const props = defineProps<{
  sentence: SentenceItem
  clip: ClipPlayer
  highlight: boolean
  showEn: boolean
  showZh: boolean
  onToggleEn: () => void
  onToggleZh: () => void
  autoReveal: boolean
  draft: Draft
  onDraft: (patch: Partial<Draft>) => void
  onRecorded: (stat: StatOverride) => void
  /**
   * 本题型的**作答组件**（P4-2 题型动态挂载）。
   *
   * 由宿主页面从 `question-types` 注册表按 `code` 解析后传下来 —— 本组件因此
   * **不认识任何具体题型**。契约（与 `QuestionTypeComponents.Answer` 一致）：
   * 接收 `sentence` / `disabled` / `auto-reveal` / `draft` / `on-draft` /
   * `on-replay` / `on-reveal-en` / `on-recorded` 这八个 props。
   */
  answerComponent: Component
  editing: boolean
  onStartEdit: () => void
  onCancelEdit: () => void
  onSave: (patch: { text_en?: string; text_zh?: string }) => void
  onRetranslate: () => void
  onMergeNext: () => void
  onSplitAtPlayhead: (atMs: number) => void
  onSaveMarks: (marks: number[][]) => Promise<void>
  onWordClick: (word: string, rect: WordRect) => void
  correctOpen: boolean
  setCorrectOpen: (next: boolean) => void
  noteOpen: boolean
  setNoteOpen: (next: boolean) => void
  busy: boolean
}>()

const draftEn = ref(props.sentence.text_en)
const draftZh = ref(props.sentence.text_zh)

watch(
  [() => props.sentence.text_en, () => props.sentence.text_zh, () => props.editing],
  () => {
    draftEn.value = props.sentence.text_en
    draftZh.value = props.sentence.text_zh
  },
)

// ---- 原文「易听错」标记（v1.14）----
const markMode = ref(false)
const markAnchor = ref<number | null>(null)
const markHover = ref<number | null>(null)
// 乐观值：点完立刻高亮，不等一个来回；服务端回传的标记一到就丢掉它
const pendingMarks = ref<number[][] | null>(null)

watch(
  () => props.sentence.marks,
  () => {
    pendingMarks.value = null
  },
)

const marks = computed<number[][]>(() => pendingMarks.value ?? props.sentence.marks ?? [])
const markedWords = computed(() => rangesToWords(marks.value))
const previewRange = computed<readonly [number, number] | null>(() =>
  markAnchor.value !== null && markHover.value !== null
    ? ([Math.min(markAnchor.value, markHover.value), Math.max(markAnchor.value, markHover.value)] as const)
    : null,
)

function saveMarks(next: number[][]) {
  pendingMarks.value = next
  void props.onSaveMarks(next).catch(() => {
    pendingMarks.value = null
  })
}

/** 区间内要么全被标记（→ 取消），要么整体补上（→ 标记） */
function toggleWordRange(from: number, to: number) {
  const lo = Math.min(from, to)
  const hi = Math.max(from, to)
  const next = new Set(markedWords.value)
  let allMarked = true
  for (let i = lo; i <= hi; i += 1) {
    if (!next.has(i)) {
      allMarked = false
      break
    }
  }
  for (let i = lo; i <= hi; i += 1) {
    if (allMarked) next.delete(i)
    else next.add(i)
  }
  saveMarks(wordsToRanges([...next]))
}

// 拖选落点：按下 → 划到哪算到哪 → 松手提交（单击即长度为 1 的区间）
watch(
  [markAnchor, markedWords],
  (_v, _o, onCleanup) => {
    if (markAnchor.value === null) return
    const commit = () => {
      const anchor = markAnchor.value
      if (anchor === null) return
      toggleWordRange(anchor, markHover.value ?? anchor)
      markAnchor.value = null
      markHover.value = null
    }
    window.addEventListener('pointerup', commit)
    window.addEventListener('pointercancel', commit)
    onCleanup(() => {
      window.removeEventListener('pointerup', commit)
      window.removeEventListener('pointercancel', commit)
    })
  },
)

const isActive = computed(() => props.clip.activeId.value === props.sentence.id)
const isPlaying = computed(() => isActive.value && props.clip.playing.value)
const canSplit = computed(() => isActive.value && props.clip.currentTime.value > 0.4)

// 播放位置 → 绝对时间（切片带 120ms 首部留白，这里回算）
const playheadMs = computed(
  () => Math.round(props.sentence.start_ms - CLIP_PAD_MS + props.clip.currentTime.value * 1000),
)
const spanMs = computed(() => props.sentence.end_ms - props.sentence.start_ms)

// A-B 循环：A 未设 → 设 A；A 已设 B 未设 → 设 B；都已设 → 清除
const abActive = computed(
  () => isActive.value && props.clip.abStart.value !== null && props.clip.abEnd.value !== null,
)

function cycleAB() {
  const clip = props.clip
  if (!props.sentence.clip_url) return
  if (clip.abStart.value === null) {
    if (isActive.value) {
      clip.setAB(props.sentence.id, Math.max(0, clip.currentTime.value), null)
    } else {
      clip.play(props.sentence.id, props.sentence.clip_url)
      clip.setAB(props.sentence.id, 0, null)
    }
    return
  }
  if (clip.abEnd.value === null) {
    const t = clip.currentTime.value
    if (t > clip.abStart.value + 0.2) clip.setAB(props.sentence.id, clip.abStart.value, t)
    else clip.setAB(props.sentence.id, t, null) // 与 A 太近，视为重设 A
    return
  }
  clip.clearAB()
}

function togglePlay() {
  const url = props.sentence.clip_url
  if (url) props.clip.toggle(props.sentence.id, url)
}
function toggleLoop() {
  props.clip.setLoop(!props.clip.loop.value)
}
function replay() {
  const url = props.sentence.clip_url
  if (!url) return
  props.clip.seek(0)
  props.clip.play(props.sentence.id, url)
}
function toggleNote() {
  props.setNoteOpen(!props.noteOpen)
}
function toggleCorrect() {
  props.setCorrectOpen(!props.correctOpen)
}
function toggleMarkMode() {
  const next = !markMode.value
  markMode.value = next
  markAnchor.value = null
  markHover.value = null
  if (next && !props.showEn) props.onToggleEn() // 标记对象是原文，先把原文亮出来
}
function finishMark() {
  markMode.value = false
  markAnchor.value = null
  markHover.value = null
}
function onMarkStart(wordIndex: number) {
  markAnchor.value = wordIndex
  markHover.value = wordIndex
}
function onMarkHover(wordIndex: number) {
  if (markAnchor.value !== null) markHover.value = wordIndex
}
function onWordClick(word: string, rect: WordRect) {
  props.onWordClick(word, rect)
}
function saveEdit() {
  props.onSave({ text_en: draftEn.value, text_zh: draftZh.value })
}
function splitAtPlayhead() {
  props.onSplitAtPlayhead(playheadMs.value)
}

const iconBtn =
  'flex h-8 w-8 items-center justify-center rounded-full transition-colors disabled:cursor-not-allowed'
const chipBtn = 'flex h-8 items-center gap-1 rounded-lg border px-2 text-[11px] transition-colors'

function abTitle(): string {
  if (!props.sentence.clip_url) return '该句切片不可用'
  if (props.clip.abStart.value === null) return '设定 A 点（开始片段循环）'
  if (props.clip.abEnd.value === null) return '在当前位置设定 B 点'
  return '清除 A-B 循环'
}
function abLabel(): string {
  const clip = props.clip
  if (clip.abStart.value === null) return 'A-B'
  if (clip.abEnd.value === null) return `A ${formatSeconds(clip.abStart.value)}`
  return `${formatSeconds(clip.abStart.value)}–${formatSeconds(clip.abEnd.value)}`
}

/** A-B 状态机语义锚点（ARCH §3.2：ab-idle / ab-a / ab-active），verify_m5 优先读 data-state。 */
function abState(): 'ab-idle' | 'ab-a' | 'ab-active' {
  if (abActive.value) return 'ab-active'
  if (props.clip.abStart.value !== null) return 'ab-a'
  return 'ab-idle'
}
</script>

<template>
  <div
    data-testid="sentence-stage-card"
    :data-highlight="highlight ? 'true' : 'false'"
    :class="[
      'flex min-h-0 flex-1 flex-col gap-2 rounded-xl border bg-white p-3 transition-colors sm:gap-3 sm:p-4',
      highlight ? 'border-amber-400 ring-2 ring-amber-200' : 'border-ink',
    ].join(' ')"
  >
    <!-- 句子工具行 -->
    <div class="flex flex-wrap items-center gap-2">
      <span class="shrink-0 text-[11px] tabular-nums text-ink-3">#{{ sentence.idx + 1 }}</span>

      <button
        type="button"
        :disabled="!sentence.clip_url"
        :title="sentence.clip_url ? '播放本句' : '该句切片不可用'"
        :class="[
          iconBtn,
          sentence.clip_url ? 'bg-lemon-400 text-ink hover:bg-lemon-300' : 'bg-cream-2 text-ink-3',
        ].join(' ')"
        @click="togglePlay"
      >
        <PauseIcon v-if="isPlaying" class-name="h-3 w-3" />
        <PlayIcon v-else class-name="ml-0.5 h-3 w-3" />
      </button>

      <button
        type="button"
        :disabled="!sentence.clip_url"
        :title="clip.loop.value ? '关闭单句循环' : '单句循环'"
        :class="[
          chipBtn,
          clip.loop.value
            ? 'border-ink bg-lemon-400 text-ink'
            : 'border-ink text-ink-2 hover:bg-lemon-100',
          sentence.clip_url ? '' : 'cursor-not-allowed opacity-40',
        ].join(' ')"
        @click="toggleLoop"
      >
        <LoopIcon class-name="h-3.5 w-3.5" />
        循环
      </button>

      <!-- A-B 循环（FR-A1）：点一下设 A、再点设 B、再点清除 -->
      <button
        type="button"
        :disabled="!sentence.clip_url"
        :data-state="abState()"
        :title="abTitle()"
        :class="[
          chipBtn,
          'tabular-nums',
          abActive
            ? 'border-sky-600 bg-sky-600 text-ink'
            : clip.abStart.value !== null
              ? 'border-sky-300 bg-sky-50 text-sky-700'
              : 'border-ink text-ink-2 hover:bg-lemon-100',
          sentence.clip_url ? '' : 'cursor-not-allowed opacity-40',
        ].join(' ')"
        @click="cycleAB"
      >
        <ABLoopIcon class-name="h-3.5 w-3.5" />
        {{ abLabel() }}
      </button>

      <!-- 标记易听错（v1.14）：点词标记 / 拖选标整段 -->
      <button
        type="button"
        data-testid="toggle-mark"
        :disabled="!sentence.text_en"
        :aria-pressed="markMode"
        title="标出原文里自己容易听错的部分：点单词标记/取消，按住从左拖到右可标一整段"
        :class="[
          chipBtn,
          'tabular-nums',
          markMode ? 'border-amber-500 bg-amber-500 text-ink' : 'border-ink text-ink-2 hover:bg-lemon-100',
          sentence.text_en ? '' : 'cursor-not-allowed opacity-40',
        ].join(' ')"
        @click="toggleMarkMode"
      >
        <HighlightIcon class-name="h-3.5 w-3.5" />
        {{ markMode ? '标记中' : '标记难点' }}
        <template v-if="marks.length > 0"> {{ marks.length }}</template>
      </button>

      <span class="text-[11px] tabular-nums text-ink-3">
        {{ formatSeconds(sentence.start_ms / 1000) }} – {{ formatSeconds(sentence.end_ms / 1000) }}
        <span class="ml-1 text-ink-3">({{ (spanMs / 1000).toFixed(1) }}s)</span>
      </span>

      <span v-if="isActive && clip.duration.value > 0" class="text-[11px] tabular-nums text-ink-2">
        {{ formatSeconds(clip.currentTime.value) }} / {{ formatSeconds(clip.duration.value) }}
      </span>

      <span
        v-if="sentence.attempt_count > 0"
        :class="[
          'rounded-full px-2 py-0.5 text-[10px] tabular-nums',
          sentence.mastered ? 'bg-emerald-50 text-emerald-600' : 'bg-amber-50 text-amber-600',
        ].join(' ')"
        :title="`练过 ${sentence.attempt_count} 次，最佳 ${sentence.best_accuracy}%`"
      >
        {{ sentence.mastered ? '已掌握' : `最佳 ${sentence.best_accuracy}%` }}
      </span>

      <div class="ml-auto flex items-center gap-1">
        <button
          type="button"
          data-testid="toggle-note"
          title="本句笔记"
          :class="[
            chipBtn,
            noteOpen ? 'border-ink bg-lemon-400 text-ink' : 'border-ink text-ink-2 hover:bg-lemon-100',
          ].join(' ')"
          @click="toggleNote"
        >
          <NoteIcon class-name="h-3.5 w-3.5" />
          笔记
        </button>
        <button
          type="button"
          data-testid="toggle-correct"
          title="校对：改原文 / 改时间 / 拆分 / 合并 / 重译"
          :class="[
            chipBtn,
            correctOpen ? 'border-ink bg-lemon-400 text-ink' : 'border-ink text-ink-2 hover:bg-lemon-100',
          ].join(' ')"
          @click="toggleCorrect"
        >
          <PencilIcon class-name="h-3.5 w-3.5" />
          校对
        </button>
      </div>
    </div>

    <!-- 句子级进度条（拖动定位，便于精确设定 A-B 点） -->
    <div v-if="isActive && clip.duration.value > 0" class="flex shrink-0 items-center gap-2">
      <input
        type="range"
        :min="0"
        :max="clip.duration.value"
        :step="0.05"
        :value="Math.min(clip.currentTime.value, clip.duration.value)"
        title="拖动定位（配合 A-B 循环精抠片段）"
        class="h-1 w-full cursor-pointer accent-sky-600"
        @input="clip.seek(Number(($event.target as HTMLInputElement).value))"
      />
      <span class="shrink-0 text-[10px] tabular-nums text-ink-3">
        {{ formatSeconds(clip.currentTime.value) }}/{{ formatSeconds(clip.duration.value) }}
      </span>
    </div>

    <!-- 标记模式提示条（低频，仅开启时出现） -->
    <div
      v-if="markMode"
      data-testid="mark-hint"
      class="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-amber-200 bg-amber-50/70 px-3 py-2 text-[11px] text-amber-700"
    >
      <span class="font-medium">标记模式</span>
      <span>点单词标记/取消 · 按住从左拖到右可标一整段</span>
      <div class="ml-auto flex items-center gap-2">
        <button
          v-if="markedWords.size > 0"
          type="button"
          class="rounded border border-amber-300 bg-white px-2 py-0.5 transition-colors hover:bg-amber-100"
          @click="saveMarks([])"
        >
          清除全部（{{ marks.length }} 段 / {{ markedWords.size }} 词）
        </button>
        <button
          type="button"
          class="rounded border border-amber-300 bg-white px-2 py-0.5 transition-colors hover:bg-amber-100"
          @click="finishMark"
        >
          完成
        </button>
      </div>
    </div>

    <div v-if="editing" class="flex min-h-0 flex-1 flex-col gap-2">
      <textarea
        v-model="draftEn"
        class="min-h-0 flex-1 resize-none rounded-lg border border-ink-3 px-3 py-2 text-[15px] leading-relaxed text-ink outline-none focus:border-ink"
      />
      <textarea
        v-model="draftZh"
        rows="2"
        class="shrink-0 resize-none rounded-lg border border-ink-3 px-3 py-2 text-[13px] leading-relaxed text-ink-2 outline-none focus:border-ink"
      />
      <div class="flex shrink-0 items-center justify-end gap-2">
        <button
          type="button"
          class="rounded-lg border border-ink px-3 py-1.5 text-xs text-ink-2 hover:bg-lemon-100"
          @click="onCancelEdit"
        >
          取消
        </button>
        <button
          type="button"
          :disabled="busy"
          class="flex items-center gap-1.5 rounded-lg bg-lemon-400 px-3 py-1.5 text-xs text-ink hover:bg-lemon-300 disabled:opacity-40"
          @click="saveEdit"
        >
          <CheckIcon class-name="h-3.5 w-3.5" />
          保存
        </button>
      </div>
    </div>

    <template v-else>
      <!-- 正文舞台：一句一屏，字号随句长自适应 -->
      <div class="min-h-0 flex-1 overflow-y-auto" data-testid="sentence-stage">
        <div class="flex min-h-full flex-col items-center justify-center py-1 text-center">
          <ClickableText
            v-if="showEn"
            :text="sentence.text_en"
            :font-size="stageFontSize(sentence.text_en.length)"
            :marks="markedWords"
            :mark-mode="markMode"
            :preview-range="previewRange"
            @mark-start="onMarkStart"
            @mark-hover="onMarkHover"
            @word-click="onWordClick"
          >
            <template #trailing>
              <span
                v-if="sentence.is_edited"
                class="ml-2 rounded bg-amber-50 px-1.5 py-0.5 align-middle text-[10px] text-amber-600"
              >
                已校对
              </span>
            </template>
          </ClickableText>
          <div v-else class="my-4 flex items-center gap-2 rounded-lg bg-cream px-4 py-2.5 text-[13px] text-ink-3">
            <EyeOffIcon class-name="h-4 w-4" />
            原文已隐藏 —— 先听，再写下来
          </div>

          <!-- 翻译 -->
          <div class="mt-3">
            <p
              v-if="showZh"
              data-testid="sentence-zh"
              class="leading-relaxed text-ink-2"
              :style="{ fontSize: translationFontSize(sentence.text_zh.length) }"
            >
              <template v-if="sentence.text_zh">{{ sentence.text_zh }}</template>
              <span v-else class="text-amber-600">翻译缺失，可用「校对」重译或手改</span>
            </p>
            <span v-else class="text-[12px] text-ink-3">翻译已隐藏</span>
          </div>

          <div class="mt-2 flex items-center gap-3">
            <button
              type="button"
              class="flex items-center gap-1 text-[11px] text-ink-2 transition-colors hover:text-ink"
              @click="onToggleEn"
            >
              <EyeOffIcon v-if="showEn" class-name="h-3.5 w-3.5" />
              <EyeIcon v-else class-name="h-3.5 w-3.5" />
              {{ showEn ? '隐藏原文' : '显示原文' }}
            </button>
            <button
              type="button"
              class="flex items-center gap-1 text-[11px] text-ink-2 transition-colors hover:text-ink"
              @click="onToggleZh"
            >
              <EyeOffIcon v-if="showZh" class-name="h-3.5 w-3.5" />
              <EyeIcon v-else class-name="h-3.5 w-3.5" />
              {{ showZh ? '隐藏翻译' : '显示翻译' }}
            </button>
          </div>
        </div>
      </div>

      <!-- 校对面板（低频，默认收起） -->
      <div
        v-if="correctOpen"
        class="flex shrink-0 flex-wrap items-center gap-2 rounded-lg border border-ink bg-cream-2 px-3 py-2"
      >
        <span class="text-[11px] text-ink-3">校对：</span>
        <button
          v-if="canSplit"
          type="button"
          :disabled="busy"
          :title="`在播放位置（${formatSeconds(playheadMs / 1000)}）拆分`"
          class="flex items-center gap-1 rounded-lg border border-ink bg-white px-2 py-1 text-[11px] text-ink-2 transition-colors hover:bg-lemon-100 disabled:opacity-40"
          @click="splitAtPlayhead"
        >
          <ScissorsIcon class-name="h-3.5 w-3.5" />
          在 {{ formatSeconds(playheadMs / 1000) }} 拆分
        </button>
        <button
          type="button"
          :disabled="busy"
          title="与下一句合并"
          class="flex items-center gap-1 rounded-lg border border-ink bg-white px-2 py-1 text-[11px] text-ink-2 transition-colors hover:bg-lemon-100 disabled:opacity-40"
          @click="onMergeNext"
        >
          <MergeIcon class-name="h-3.5 w-3.5" />
          合并下句
        </button>
        <button
          type="button"
          :disabled="busy || !sentence.text_en"
          title="重新翻译本句"
          class="flex items-center gap-1 rounded-lg border border-ink bg-white px-2 py-1 text-[11px] text-ink-2 transition-colors hover:bg-lemon-100 disabled:opacity-40"
          @click="onRetranslate"
        >
          <TranslateIcon class-name="h-3.5 w-3.5" />
          重译
        </button>
        <button
          type="button"
          :disabled="busy"
          title="编辑原文 / 翻译"
          class="flex items-center gap-1 rounded-lg border border-ink bg-white px-2 py-1 text-[11px] text-ink-2 transition-colors hover:bg-lemon-100 disabled:opacity-40"
          @click="onStartEdit"
        >
          <PencilIcon class-name="h-3.5 w-3.5" />
          编辑原文
        </button>
      </div>

      <!-- 句子笔记（M4 / FR-S8） -->
      <div v-if="noteOpen" class="shrink-0">
        <NoteEditor :sentence-id="sentence.id" />
      </div>

      <!-- 听写练习区（FR-S2 / FR-S3）→ **题型动态挂载**（P4-2）。
           `<component :is>` 不产生额外的包裹元素，因此 DOM 结构与 P4-2 之前
           逐字一致（验收脚本靠 `data-testid` 与 className 定位）。 -->
      <component
        :is="answerComponent"
        :sentence="sentence"
        :disabled="!sentence.text_en"
        :auto-reveal="autoReveal"
        :draft="draft"
        :on-draft="onDraft"
        :on-replay="replay"
        :on-reveal-en="onToggleEn"
        :on-recorded="onRecorded"
      />
    </template>
  </div>
</template>

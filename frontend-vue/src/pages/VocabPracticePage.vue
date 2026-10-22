<script setup lang="ts">
/**
 * 生词本练习页（照搬旧 `frontend/src/pages/VocabPracticePage.tsx`，861 行）。
 *
 * 中译英（手输拼写） / 英译中（四选一） / 听写（听发音手输拼写）。
 * 题目全部来自生词本（`GET /api/vocab`），**纯前端出题与判分**，后端无需改动。
 *
 * ⚠️ 三个历史上最容易改坏的行为（本文件逐条保留）：
 * 1. **回车键**：`window` 上监听 keydown，条件是 `key === 'Enter' && !isComposing`，
 *    并 `preventDefault()`；未作答→提交，已作答→下一题。`isComposing` 判断不能丢
 *    （中文 / 日文输入法组词中按回车不能提交）。
 * 2. **听写自动播放**：进入每一题自动播一次（setTimeout 300ms）并重置 `plays`；
 *    `rate` 变化**不能**触发重播（只能靠「慢速重播」按钮）——所以 watch 的依赖里没有 rate。
 * 3. **听写题干不得泄露任何文字**：不显示单词、不显示音标，只显示播放按钮（旧版刻意如此）。
 *
 * 其它等价性说明：
 * - 出题 / 判分 / 文案全部搬到 `types/vocab.ts`（纯函数不放在 `<script setup>` 顶层）。
 * - 旧版 `useMemo` → `computed`；`useRef` → 模板 ref + `let`（`startedAt` 无需响应式）。
 * - 旧版内联的 `PageHeader` / `Field` / `Choice` 拆成三个小组件（DOM 逐字保留）。
 */
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { useQuery } from '@tanstack/vue-query'
import { listVocab } from '../api/client'
import type { VocabItem } from '../api/client'
import { speakEnglish, speechAvailable } from '../utils/speech'
import VocabPracticeChoice from '../components/VocabPracticeChoice.vue'
import VocabPracticeField from '../components/VocabPracticeField.vue'
import VocabPracticeHeader from '../components/VocabPracticeHeader.vue'
import {
  AlertIcon,
  BookIcon,
  CheckIcon,
  CloseIcon,
  LightbulbIcon,
  RefreshIcon,
  ShuffleIcon,
  SpeakerIcon,
  TargetIcon,
  TrophyIcon,
} from '../components/icons'
import {
  COUNT_OPTIONS,
  DISPLAY_NAME,
  MODE_META,
  buildQuestions,
  formatDuration,
  normEn,
  shuffle,
} from '../types/vocab'
import type { CountOption, Mode, Phase, Question, RateOption, Scope } from '../types/vocab'

const { data, isLoading, isError, error } = useQuery({
  queryKey: ['vocab', 'practice-pool'],
  queryFn: () => listVocab({}),
})

const allItems = computed<VocabItem[]>(() => data.value?.items ?? [])
/** 带释义的生词才能出题 */
const withMeaning = computed(() => allItems.value.filter((item) => (item.translation ?? '').trim()))
const errorText = computed(() => (error.value as Error | null)?.message ?? '')

/** 环境是否支持语音合成（旧版 `useMemo(() => speechAvailable(), [])`） */
const canSpeak = ref(speechAvailable())

const phase = ref<Phase>('setup')
const mode = ref<Mode>('zh2en')
const scope = ref<Scope>('all')
const count = ref<CountOption>(10)
/** 听写语速 */
const rate = ref<RateOption>(0.9)

const questions = ref<Question[]>([])
const index = ref(0)
const input = ref('')
const picked = ref<string | null>(null)
const revealed = ref(false)
const results = ref<boolean[]>([])
const elapsed = ref(0)
/** 听写：当前题已听次数 */
const plays = ref(0)

/** 开始时间戳：不需要响应式，用普通变量即可（旧版是 ref，仅因为 React 要跨渲染保留） */
let startedAt = 0

const inputRef = ref<HTMLInputElement | null>(null)
/** 自动播放定时器句柄（切题 / 卸载时清掉） */
let autoplayTimer: number | null = null

const scoped = computed<VocabItem[]>(() => {
  if (scope.value === 'todo') return withMeaning.value.filter((item) => !item.mastered)
  if (scope.value === 'mastered') return withMeaning.value.filter((item) => item.mastered)
  return withMeaning.value
})
const todoCount = computed(() => withMeaning.value.filter((item) => !item.mastered).length)
const masteredCount = computed(() => withMeaning.value.filter((item) => item.mastered).length)

const en2zhReady = computed(() => withMeaning.value.length >= 2)
// 选择类（英译中）需要至少 2 个词才能生成选项；拼写类 1 个即可
const enough = computed(() =>
  mode.value === 'en2zh' ? scoped.value.length >= 2 : scoped.value.length >= 1,
)

const current = computed<Question | undefined>(() => questions.value[index.value])
const answered = computed<boolean | null>(() =>
  results.value.length > index.value ? (results.value[index.value] ?? null) : null,
)
/** 拼写类：中译英 + 听写（需要打字）—— 注意是 `!== 'en2zh'`，听写也走拼写路径 */
const isSpelling = computed(() => mode.value !== 'en2zh')
const isDictation = computed(() => mode.value === 'dictation')
/** 听写依赖浏览器语音合成；不支持时禁用该模式 */
const canDictate = computed(() => canSpeak.value)

const correctCount = computed(() => results.value.filter(Boolean).length)
const accuracy = computed(() =>
  results.value.length ? Math.round((correctCount.value / results.value.length) * 100) : 0,
)
const accuracyTone = computed(() =>
  accuracy.value >= 80
    ? 'text-amber-500'
    : accuracy.value >= 60
      ? 'text-ink-3'
      : 'text-ink-3',
)
const wrongItems = computed<VocabItem[]>(() =>
  questions.value.filter((_, i) => results.value[i] === false).map((q) => q.item),
)
/** 当前连对（从最近一次作答往前数，纯展示用，不参与判分） */
const streak = computed(() => {
  let n = 0
  for (let i = results.value.length - 1; i >= 0; i -= 1) {
    if (results.value[i]) n += 1
    else break
  }
  return n
})
const progress = computed(() =>
  questions.value.length
    ? ((index.value + (revealed.value ? 1 : 0)) / questions.value.length) * 100
    : 0,
)
const correctText = computed(() => {
  const question = current.value
  if (!question) return ''
  return isSpelling.value ? DISPLAY_NAME(question.item) : (question.correctOption ?? '')
})

// 作答区自动聚焦（拼写类需要打字）：旧版 useEffect 的依赖是 [phase, isSpelling, revealed, index]
watch(
  [phase, isSpelling, revealed, index],
  async () => {
    if (phase.value !== 'quiz' || !isSpelling.value || revealed.value) return
    await nextTick()
    inputRef.value?.focus()
  },
  { immediate: true },
)

/** 听写：进入每一题都自动播一次发音（并重置计数）。
 *  依赖刻意不含 `rate` —— 换语速不重播，否则设置页刚改完语速就会重复朗读。 */
watch(
  [phase, index, mode, canSpeak],
  () => {
    if (autoplayTimer !== null) {
      window.clearTimeout(autoplayTimer)
      autoplayTimer = null
    }
    if (phase.value !== 'quiz' || mode.value !== 'dictation' || !canSpeak.value) return
    plays.value = 0
    autoplayTimer = window.setTimeout(() => {
      autoplayTimer = null
      const item = questions.value[index.value]?.item
      if (item && speakEnglish(DISPLAY_NAME(item), rate.value)) plays.value = 1
    }, 300)
  },
  { immediate: true },
)

onUnmounted(() => {
  if (autoplayTimer !== null) window.clearTimeout(autoplayTimer)
  autoplayTimer = null
})

function backToSetup() {
  phase.value = 'setup'
}

function begin(source: readonly VocabItem[]) {
  const built = buildQuestions(source, mode.value)
  const usable = mode.value === 'en2zh' ? built.filter((q) => (q.options?.length ?? 0) >= 2) : built
  if (!usable.length) return
  questions.value = usable
  index.value = 0
  input.value = ''
  picked.value = null
  revealed.value = false
  results.value = []
  elapsed.value = 0
  plays.value = 0
  startedAt = Date.now()
  phase.value = 'quiz'
}

function start() {
  const limited =
    count.value > 0 ? shuffle(scoped.value).slice(0, count.value) : shuffle(scoped.value)
  begin(limited)
}

function submitSpelling() {
  const question = current.value
  if (!question || revealed.value) return
  const value = normEn(input.value)
  const ok = value.length > 0 && question.accept.includes(value)
  results.value = [...results.value, ok]
  revealed.value = true
}

function giveUp() {
  const question = current.value
  if (!question || revealed.value) return
  results.value = [...results.value, false]
  revealed.value = true
}

function choose(option: string) {
  const question = current.value
  if (!question || revealed.value) return
  picked.value = option
  results.value = [...results.value, option === question.correctOption]
  revealed.value = true
}

/** 听写：播放当前题发音（`useRate` 可覆盖，用于「慢速重播」） */
function listen(useRate: number = rate.value) {
  const question = current.value
  if (!question) return
  if (speakEnglish(DISPLAY_NAME(question.item), useRate)) plays.value += 1
}

function next() {
  if (index.value + 1 >= questions.value.length) {
    elapsed.value = Math.max(1, Math.round((Date.now() - startedAt) / 1000))
    phase.value = 'result'
    return
  }
  index.value += 1
  input.value = ''
  picked.value = null
  revealed.value = false
  plays.value = 0
}

// 回车：未作答则提交，已作答则下一题（`isComposing` 判断不能丢：输入法组词中不能提交）
function onEnter(event: KeyboardEvent) {
  if (phase.value !== 'quiz') return
  if (event.key !== 'Enter' || event.isComposing) return
  event.preventDefault()
  if (revealed.value) next()
  else if (isSpelling.value) submitSpelling()
}

onMounted(() => window.addEventListener('keydown', onEnter))
onUnmounted(() => window.removeEventListener('keydown', onEnter))

/** 题量选项的标题 / 说明（旧版是内联三元，抽成函数避免模板里出现 `<=`） */
function countTitle(value: CountOption): string {
  return value === 0 ? '全部' : `${value} 题`
}

function countDesc(value: CountOption): string {
  if (value === 0) return `${scoped.value.length} 个`
  return value <= scoped.value.length ? '随机抽题' : '不足则用全部'
}

/** 英译中选项的配色（旧版内联 if/else，抽成函数保持可读性，产出字符串完全一致） */
function optionTone(option: string): string {
  const isCorrectOption = option === current.value?.correctOption
  const isPickedOption = option === picked.value
  if (revealed.value && isCorrectOption) return 'border-emerald-300 bg-emerald-50 text-emerald-800'
  if (revealed.value && isPickedOption) return 'border-red-300 bg-red-50 text-red-700'
  return 'border-ink hover:border-ink-3 hover:bg-lemon-100'
}

/** 选项的语义态（T03 解耦锚点：verify_vocab_practice 优先读 data-tone，class fallback 是 emerald）。 */
/** 选项左侧字母圆的配色（纯视觉，不参与判分） */
function optionKeyClass(option: string): string {
  if (revealed.value && option === current.value?.correctOption) {
    return 'border-emerald-300 bg-emerald-600 text-white'
  }
  if (revealed.value && option === picked.value) return 'border-red-300 bg-red-500 text-white'
  return 'border-ink/30 bg-white text-ink-2'
}

function optionDataTone(option: string): 'correct' | 'wrong' | 'neutral' {
  if (revealed.value && option === current.value?.correctOption) return 'correct'
  if (revealed.value && option === picked.value) return 'wrong'
  return 'neutral'
}
</script>

<template>
  <!-- 加载 -->
  <div
    v-if="isLoading"
    class="mx-auto w-full max-w-[680px] rounded-xl border border-ink bg-white px-3 py-10 text-center text-[13px] text-ink-3 sm:px-5"
  >
    加载生词本…
  </div>

  <!-- 错误 -->
  <div
    v-else-if="isError"
    class="mx-auto w-full max-w-[680px] rounded-xl border border-red-100 bg-red-50 px-3 py-10 text-center text-[13px] text-red-600 sm:px-5"
  >
    {{ errorText }}
  </div>

  <!-- 生词不足 -->
  <div v-else-if="!withMeaning.length" data-practice-phase="empty" class="mx-auto w-full max-w-[680px] space-y-4">
    <VocabPracticeHeader :can-back="false" />
    <div class="rounded-xl border border-ink bg-white px-3 py-12 text-center sm:px-5">
      <BookIcon class-name="mx-auto h-8 w-8 text-ink-3" />
      <p class="mt-3 text-[13px] text-ink-2">
        生词本里还没有「带释义」的生词，暂时无法出题。
      </p>
      <p class="mt-1 text-[12px] text-ink-3">
        到学习页点击原文里的单词，查词后加入生词本，这里就能开始练习了。
      </p>
      <RouterLink
        to="/vocab"
        class="mt-4 inline-flex items-center gap-1.5 rounded-lg bg-lemon-400 px-3.5 py-2 text-[13px] text-ink transition-colors hover:bg-lemon-300"
      >
        返回生词本
      </RouterLink>
    </div>
  </div>

  <!-- 设置 -->
  <div v-else-if="phase === 'setup'" data-practice-phase="setup" class="mx-auto w-full max-w-[680px] space-y-5">
    <VocabPracticeHeader :can-back="false" />

    <div class="space-y-5 rounded-xl border border-ink bg-white p-5">
      <VocabPracticeField label="练习方式">
        <VocabPracticeChoice
          :active="mode === 'zh2en'"
          :title="MODE_META.zh2en.title"
          :desc="MODE_META.zh2en.desc"
          @select="mode = 'zh2en'"
        />
        <VocabPracticeChoice
          :active="mode === 'en2zh'"
          :disabled="!en2zhReady"
          :title="MODE_META.en2zh.title"
          :desc="en2zhReady ? MODE_META.en2zh.desc : '需要至少 2 个带释义的生词'"
          @select="mode = 'en2zh'"
        />
        <VocabPracticeChoice
          :active="mode === 'dictation'"
          :disabled="!canDictate"
          :title="MODE_META.dictation.title"
          :desc="canDictate ? MODE_META.dictation.desc : '当前浏览器不支持语音合成'"
          @select="mode = 'dictation'"
        />
      </VocabPracticeField>

      <VocabPracticeField v-if="isDictation" label="语速">
        <VocabPracticeChoice
          :active="rate === 0.9"
          title="正常"
          desc="默认语速"
          @select="rate = 0.9"
        />
        <VocabPracticeChoice
          :active="rate === 0.6"
          title="慢速"
          desc="便于听清发音"
          @select="rate = 0.6"
        />
        <span :data-practice-rate="String(rate)" />
      </VocabPracticeField>

      <VocabPracticeField label="练习范围">
        <VocabPracticeChoice
          :active="scope === 'all'"
          title="全部"
          :desc="`${withMeaning.length} 个`"
          @select="scope = 'all'"
        />
        <VocabPracticeChoice
          :active="scope === 'todo'"
          title="待复习"
          :desc="`${todoCount} 个`"
          @select="scope = 'todo'"
        />
        <VocabPracticeChoice
          :active="scope === 'mastered'"
          title="已掌握"
          :desc="`${masteredCount} 个`"
          @select="scope = 'mastered'"
        />
      </VocabPracticeField>

      <VocabPracticeField label="题量">
        <VocabPracticeChoice
          v-for="value in COUNT_OPTIONS"
          :key="value"
          :active="count === value"
          :title="countTitle(value)"
          :desc="countDesc(value)"
          @select="count = value"
        />
      </VocabPracticeField>

      <div class="flex flex-wrap items-center gap-3 border-t border-cream-2 pt-4">
        <button
          type="button"
          :disabled="!enough"
          class="flex items-center gap-1.5 rounded-lg bg-lemon-400 px-4 py-2 text-[13px] text-ink transition-colors hover:bg-lemon-300 disabled:cursor-not-allowed disabled:bg-cream-2 disabled:text-ink-3"
          @click="start"
        >
          <TargetIcon class-name="h-4 w-4" />
          开始练习
        </button>
        <span
          v-if="!enough"
          data-practice-hint
          class="flex items-center gap-1 text-[12px] text-amber-600"
        >
          <AlertIcon class-name="h-3.5 w-3.5" />
          {{
            mode === 'en2zh'
              ? '当前范围内带释义的生词不足 2 个，换个范围或改用「中译英 / 听写」'
              : '当前范围内没有带释义的生词，换个范围试试'
          }}
        </span>
        <span class="ml-auto flex items-center gap-1 text-[11px] text-ink-3">
          <kbd class="rounded border border-ink px-1.5 py-0.5">Enter</kbd>
          提交 / 下一题
        </span>
      </div>
    </div>
  </div>

  <!-- 结果 -->
  <div v-else-if="phase === 'result'" data-practice-phase="result" class="mx-auto w-full max-w-[680px] space-y-5">
    <VocabPracticeHeader :can-back="true" @back="backToSetup" />

    <div class="rounded-xl border border-ink bg-white p-6 text-center">
      <TrophyIcon :class-name="`mx-auto h-9 w-9 ${accuracyTone}`" />
      <p
        data-practice-accuracy
        class="mt-3 text-[28px] font-medium tabular-nums text-ink"
      >
        {{ accuracy }}%
      </p>
      <p class="mt-1 text-[13px] text-ink-2">答对 <span class="tabular-nums text-emerald-600">{{ correctCount }}</span> / <span class="tabular-nums">{{ questions.length }}</span> 题　·　用时 {{ formatDuration(elapsed) }}</p>
      <p class="mt-2 text-[12px] text-ink-3">{{ MODE_META[mode].result }}</p>

      <div class="mt-5 flex flex-wrap items-center justify-center gap-2">
        <button
          type="button"
          class="flex items-center gap-1.5 rounded-lg border border-ink px-3.5 py-2 text-[13px] text-ink transition-colors hover:bg-lemon-100"
          @click="backToSetup"
        >
          <ShuffleIcon class-name="h-3.5 w-3.5" />
          换个设置
        </button>
        <button
          v-if="wrongItems.length > 0"
          type="button"
          data-practice-retry-wrong
          class="flex items-center gap-1.5 rounded-lg border border-ink px-3.5 py-2 text-[13px] text-ink transition-colors hover:bg-lemon-100"
          @click="begin(wrongItems)"
        >
          <RefreshIcon class-name="h-3.5 w-3.5" />
          重练错题（{{ wrongItems.length }}）
        </button>
        <button
          type="button"
          class="flex items-center gap-1.5 rounded-lg bg-lemon-400 px-3.5 py-2 text-[13px] text-ink transition-colors hover:bg-lemon-300"
          @click="start"
        >
          <TargetIcon class-name="h-3.5 w-3.5" />
          再练一次
        </button>
        <RouterLink
          to="/vocab"
          class="flex items-center gap-1.5 rounded-lg border border-ink px-3.5 py-2 text-[13px] text-ink transition-colors hover:bg-lemon-100"
        >
          返回生词本
        </RouterLink>
      </div>
    </div>

    <div v-if="wrongItems.length > 0" class="rounded-xl border border-ink bg-white p-5">
      <h3 class="text-[13px] font-medium text-ink">错题回顾（{{ wrongItems.length }}）</h3>
      <ul class="mt-3 space-y-2.5">
        <li
          v-for="item in wrongItems"
          :key="item.id"
          class="flex flex-wrap items-baseline gap-x-2 gap-y-1 border-t border-cream-2 pt-2.5 first:border-0 first:pt-0"
        >
          <span class="text-[14px] font-medium text-ink">{{ DISPLAY_NAME(item) }}</span>
          <button
            v-if="canSpeak"
            type="button"
            :title="`朗读 ${DISPLAY_NAME(item)}`"
            class="rounded p-0.5 text-ink-3 transition-colors hover:bg-lemon-100 hover:text-ink"
            @click="speakEnglish(DISPLAY_NAME(item))"
          >
            <SpeakerIcon class-name="h-3.5 w-3.5" />
          </button>
          <span v-if="item.phonetic" class="text-[11px] text-ink-3">/{{ item.phonetic }}/</span>
          <span class="w-full text-[12px] leading-relaxed text-ink-2">{{ item.translation }}</span>
        </li>
      </ul>
    </div>
  </div>

  <!-- 没有可用题目 -->
  <div
    v-else-if="!current"
    class="mx-auto w-full max-w-[680px] rounded-xl border border-ink bg-white px-3 py-10 text-center text-[13px] text-ink-3 sm:px-5"
  >
    没有可用题目。
  </div>

  <!-- 答题 -->
  <div v-else-if="current" data-practice-phase="quiz" class="mx-auto w-full max-w-[680px] space-y-5">
    <VocabPracticeHeader :can-back="true" @back="backToSetup" />

    <!-- 进度 -->
    <div class="flex items-center gap-3">
      <div class="h-1.5 flex-1 overflow-hidden rounded-full bg-cream-2">
        <div
          data-practice-progress
          class="h-full rounded-full bg-lemon-400 transition-all duration-300"
          :style="{ width: `${progress}%` }"
        />
      </div>
      <span class="shrink-0 text-[12px] tabular-nums text-ink-2">
        {{ index + 1 }} / {{ questions.length }}
      </span>
    </div>

    <div class="rounded-xl border border-ink bg-white p-6">
      <!-- 题干 -->
      <div class="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span
          :data-practice-badge="mode"
          class="rounded bg-cream-2 px-1.5 py-0.5 text-[10px] text-ink-2"
        >
          {{ MODE_META[mode].badge }}
        </span>
        <span v-if="current.item.media_title" class="text-[10px] text-ink-3">
          来自《{{ current.item.media_title }}》
        </span>
      </div>

      <!-- 听写：只给发音，不给任何文字（单词 / 音标都不显示） -->
      <div v-if="isDictation" class="mt-3">
        <button
          type="button"
          data-practice-play
          class="flex items-center gap-2.5 rounded-xl border border-ink bg-cream px-4 py-3 text-[14px] text-ink transition-colors hover:border-ink-3 hover:bg-lemon-100 sm:px-5 sm:py-3.5"
          @click="listen()"
        >
          <SpeakerIcon class-name="h-5 w-5 text-ink-2" />
          {{ plays === 0 ? '点击播放发音' : '再听一次' }}
        </button>
        <div class="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1.5">
          <button
            type="button"
            data-practice-play-slow
            class="rounded-lg border border-ink px-2.5 py-1 text-[11px] text-ink-2 transition-colors hover:bg-lemon-100"
            @click="listen(0.6)"
          >
            慢速重播
          </button>
          <span data-practice-plays class="text-[11px] text-ink-3">已听 {{ plays }} 次</span>
        </div>
      </div>

      <!-- 中译英：中文释义当题干 -->
      <p
        v-else-if="isSpelling"
        data-practice-prompt
        class="mt-3 text-[26px] font-extrabold leading-[1.45] tracking-[0.2px] text-ink"
      >
        {{ current.item.translation }}
      </p>

      <!-- 英译中：英文单词当题干 -->
      <div v-else class="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1">
        <span data-practice-prompt class="text-[26px] font-medium text-ink">
          {{ DISPLAY_NAME(current.item) }}
        </span>
        <span v-if="current.item.phonetic" class="text-[12px] text-ink-3">
          /{{ current.item.phonetic }}/
        </span>
        <button
          v-if="canSpeak"
          type="button"
          data-practice-speak
          title="朗读"
          class="flex items-center gap-1 rounded-lg border border-ink px-2 py-1 text-[11px] text-ink-2 transition-colors hover:bg-lemon-100"
          @click="speakEnglish(DISPLAY_NAME(current.item))"
        >
          <SpeakerIcon class-name="h-3.5 w-3.5" />
          朗读
        </button>
      </div>

      <p
        v-if="isSpelling && mode === 'zh2en' && current.item.context"
        class="mt-2 text-[11px] leading-relaxed text-ink-3"
      >
        上下文：{{ current.item.context }}
      </p>

      <!-- 作答区 -->
      <div class="mt-5 border-t border-cream-2 pt-5">
        <div v-if="isSpelling" class="flex flex-wrap items-center gap-2">
          <input
            ref="inputRef"
            v-model="input"
            data-practice-input
            :disabled="revealed"
            :placeholder="isDictation ? '写下你听到的单词，回车提交' : '输入英文单词，回车提交'"
            autocomplete="off"
            autocapitalize="off"
            :spellcheck="false"
            :class="[
              'w-full max-w-[320px] rounded-lg border px-3 py-2 text-[15px] text-ink outline-none transition-colors disabled:bg-cream',
              revealed
                ? answered
                  ? 'border-emerald-300 bg-emerald-50/40'
                  : 'border-red-300 bg-red-50/40'
                : 'border-ink-3 focus:border-ink',
            ]"
          />
          <template v-if="!revealed">
            <button
              type="button"
              data-practice-submit
              class="rounded-lg bg-lemon-400 px-4 py-2 text-[13px] text-ink transition-colors hover:bg-lemon-300"
              @click="submitSpelling"
            >
              提交
            </button>
            <button
              type="button"
              class="flex items-center gap-1 rounded-lg border border-ink px-3 py-2 text-[12px] text-ink-2 transition-colors hover:bg-lemon-100"
              @click="giveUp"
            >
              <LightbulbIcon class-name="h-3.5 w-3.5" />
              不会，看答案
            </button>
          </template>
        </div>

        <div v-else class="grid gap-2.5 sm:grid-cols-2">
          <button
            v-for="(option, oi) in (current.options ?? [])"
            :key="option"
            type="button"
            data-practice-option
            :data-tone="optionDataTone(option)"
            :disabled="revealed"
            :class="`flex items-center gap-3 rounded-[14px] border-2 px-4 py-3.5 text-left transition-colors disabled:cursor-default ${optionTone(option)}`"
            @click="choose(option)"
          >
            <span
              class="opt-key grid h-7 w-7 shrink-0 place-items-center rounded-full border-2 text-[12px] font-extrabold"
              :class="optionKeyClass(option)"
              :data-key="String.fromCharCode(65 + oi)"
              aria-hidden="true"
            />
            <span class="min-w-0 flex-1 text-[15px] font-semibold leading-snug text-ink">{{ option }}</span>
            <CheckIcon v-if="revealed && option === current.correctOption" class-name="h-4 w-4 shrink-0 text-emerald-600" />
            <CloseIcon v-if="revealed && option === picked && option !== current.correctOption" class-name="h-4 w-4 shrink-0 text-red-500" />
          </button>
        </div>

        <!-- 反馈 -->
        <div
          v-if="revealed"
          :data-practice-feedback="answered ? 'correct' : 'wrong'"
          :class="[
            'mt-4 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-[18px] border-2 px-4 py-3 text-[12px]',
            answered ? 'border-emerald-300 bg-emerald-50 text-emerald-800' : 'border-red-300 bg-red-50 text-red-700',
          ]"
        >
          <span class="flex items-center gap-1 font-medium">
            <CheckIcon v-if="answered" class-name="h-3.5 w-3.5" />
            <CloseIcon v-else class-name="h-3.5 w-3.5" />
            {{ answered ? '回答正确' : '回答错误' }}
          </span>
          <span v-if="!answered" class="text-ink">
            正确答案：<span class="font-medium text-ink">{{ correctText }}</span><span v-if="isSpelling && current.item.phonetic" class="ml-1.5 text-ink-3">/{{ current.item.phonetic }}/</span>
          </span>
          <button
            v-if="canSpeak"
            type="button"
            data-practice-speak
            title="朗读正确发音"
            class="flex items-center gap-1 rounded border border-ink bg-white px-2 py-0.5 text-[11px] text-ink-2 transition-colors hover:bg-lemon-100"
            @click="speakEnglish(DISPLAY_NAME(current.item))"
          >
            <SpeakerIcon class-name="h-3 w-3" />
            朗读
          </button>
          <button
            type="button"
            data-practice-next
            class="ml-auto rounded-lg bg-lemon-400 px-3.5 py-1.5 text-[12px] text-ink transition-colors hover:bg-lemon-300"
            @click="next"
          >
            {{ index + 1 >= questions.length ? '看结果' : '下一题' }}
          </button>
        </div>

        <p
          v-if="isSpelling && !revealed && current.accept.length > 0"
          class="mt-2 text-[11px] text-ink-3"
        >
          {{
            isDictation
              ? '大小写与标点不计；没听清可以多点几次播放，或试试「慢速重播」。'
              : '大小写与标点不计；填原型也可以（如 went → go）。'
          }}
        </p>

        <p
          v-if="isDictation && revealed && (current.item.translation ?? '').trim()"
          class="mt-2 text-[11px] leading-relaxed text-ink-3"
        >
          释义：{{ current.item.translation }}
        </p>
      </div>
    </div>

    <!-- 本轮统计（纯展示，不参与判分） -->
    <div class="flex items-stretch gap-2">
      <div class="flex-1 rounded-xl border-2 border-ink/20 bg-white py-2 text-center">
        <b class="block text-[16px] font-extrabold leading-tight tabular-nums text-ink">{{ results.length }}</b>
        <span class="text-[10.5px] text-ink-3">已答</span>
      </div>
      <div class="flex-1 rounded-xl border-2 border-ink/20 bg-white py-2 text-center">
        <b class="block text-[16px] font-extrabold leading-tight tabular-nums text-emerald-600">{{ correctCount }}</b>
        <span class="text-[10.5px] text-ink-3">答对</span>
      </div>
      <div class="flex-1 rounded-xl border-2 border-ink/20 bg-white py-2 text-center">
        <b class="block text-[16px] font-extrabold leading-tight tabular-nums text-ink">{{ accuracy }}%</b>
        <span class="text-[10.5px] text-ink-3">正确率</span>
      </div>
      <div class="flex-1 rounded-xl border-2 border-ink/20 bg-lemon-100 py-2 text-center">
        <b class="block text-[16px] font-extrabold leading-tight tabular-nums text-ink">{{ streak }}</b>
        <span class="text-[10.5px] text-ink-3">连对</span>
      </div>
    </div>
  </div>
</template>

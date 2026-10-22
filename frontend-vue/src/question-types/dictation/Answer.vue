<script setup lang="ts">
/**
 * `dictation` 题型的**作答**组件（原 `components/DictationBox.vue`，DOM 逐字搬迁）。
 *
 * 听写输入与校验（FR-S2 / FR-S3）。
 *
 * - 输入内容与校验结果存放在父级（按句 id 归档），翻页回来不会丢。
 * - Enter 提交、Shift+Enter 换行；**输入法组合中（isComposing）不提交**。
 * - 历史记录默认折叠，同时只展开一条；高频错误词由历史记录统计而来。
 *
 * Vue 版：`e.nativeEvent.isComposing` → Vue 里 `@keydown` 拿到的就是原生事件，
 * 直接读 `e.isComposing`。
 *
 * ⚠️ **P4-2 搬迁纪律**：本文件是原 `components/DictationBox.vue` 的**逐字搬迁**，
 * 差异仅两处：① import 相对路径下移一层；② 结果组件改为**本题型自己的** `Result.vue`
 * （原先是 `components/DiffResult.vue`，两者内容逐字相同）。
 * `data-testid`（`dictation-input` / `dictation-meta` / `dictation-error-words` /
 * `dictation-history-item-*` / `dictation-history-input-*`）、className、交互行为
 * **一个字都没改** —— `verify_m4` / `verify_mobile` / `verify_m5` / `verify_marks` /
 * `verify_attempt_history` 全靠它们定位。
 */
import { computed, ref } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { listAttempts, submitAttempt, type SentenceItem } from '../../api/client'
import DiffResult from './Result.vue'
import { formatRelative } from '../../utils/format'
import {
  HistoryIcon,
  SendIcon,
} from '../../components/icons'
import type { Draft, StatOverride } from '../../types/study'

const props = defineProps<{
  sentence: SentenceItem
  disabled: boolean
  autoReveal: boolean
  draft: Draft
  /** 更新该句的听写草稿（存放在父级，翻页不丢） */
  onDraft: (patch: Partial<Draft>) => void
  onReplay: () => void
  onRevealEn: () => void
  onRecorded: (stat: StatOverride) => void
}>()

const queryClient = useQueryClient()
const showHistory = ref(false)
// 历史记录默认折叠；同时只展开一条，避免明细堆叠把面板撑爆
const expandedId = ref<number | null>(null)

const submit = useMutation({
  mutationFn: (input: string) => submitAttempt(props.sentence.id, input),
  onSuccess: (data) => {
    props.onDraft({ result: data })
    props.onRecorded({
      attempt_count: data.attempt_count,
      best_accuracy: data.best_accuracy,
      mastered: data.mastered,
    })
    if (props.autoReveal && !data.is_correct) props.onRevealEn()
    void queryClient.invalidateQueries({ queryKey: ['attempts', props.sentence.id] })
  },
})

const {
  data: historyData,
  isLoading: historyLoading,
  isError: historyIsError,
  error: historyError,
} = useQuery({
  queryKey: ['attempts', props.sentence.id],
  queryFn: () => listAttempts(props.sentence.id, 20),
  enabled: showHistory,
  staleTime: 0,
})

// 高频错误词：遍历已加载的历史记录，统计「反复听错」的词。
// 口径：wrong / missing 取 expected，extra 取 actual；先在单条记录内用 Set 去重，
// 再跨记录累加（同一次提交里同一个词出现多次只算一次）。
const errorWords = computed(() => {
  const items = historyData.value?.items ?? []
  const counts = new Map<string, number>()
  for (const item of items) {
    const seen = new Set<string>()
    for (const token of item.tokens ?? []) {
      const word =
        token.type === 'extra'
          ? token.actual
          : token.type === 'wrong' || token.type === 'missing'
            ? token.expected
            : null
      const key = word?.trim()
      if (key) seen.add(key)
    }
    for (const key of seen) counts.set(key, (counts.get(key) ?? 0) + 1)
  }
  return [...counts.entries()]
    .map(([word, count]) => ({ word, count }))
    .sort((a, b) => b.count - a.count || a.word.localeCompare(b.word))
    .slice(0, 8)
})

const trimmed = computed(() => props.draft.text.trim())
const canSubmit = computed(
  () => !props.disabled && trimmed.value.length > 0 && !submit.isPending.value,
)

function handleSubmit() {
  if (!canSubmit.value) return
  submit.mutate(trimmed.value)
}

function onInput(e: Event) {
  props.onDraft({ text: (e.target as HTMLTextAreaElement).value })
}

function onKeydown(e: KeyboardEvent) {
  // 输入法组合中（拼音候选窗开着）不触发提交
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault()
    handleSubmit()
  }
}

function clearInput() {
  props.onDraft({ text: '', result: null })
  submit.reset()
}

const bars = computed(() => (historyData.value ? [...historyData.value.items].reverse() : []))
</script>

<template>
  <div class="shrink-0 rounded-lg border border-ink/20 bg-cream-2 p-3">
    <div class="flex items-start gap-2">
      <textarea
        data-testid="dictation-input"
        rows="3"
        :value="draft.text"
        :disabled="disabled"
        :placeholder="
          disabled
            ? '该句没有标准答案，无法听写'
            : '听音频，写下你听到的内容…（Enter 提交，Shift+Enter 换行）'
        "
        class="min-h-[88px] flex-1 resize-y rounded-lg border border-ink/30 bg-white px-3 py-3 text-[17px] leading-relaxed text-ink outline-none transition-colors focus:border-ink disabled:bg-cream-2 sm:min-h-[124px] sm:px-4 sm:py-3.5 sm:text-2xl"
        @input="onInput"
        @keydown="onKeydown"
      />
      <div class="flex shrink-0 flex-col gap-1.5">
        <button
          type="button"
          :disabled="!canSubmit"
          class="flex items-center justify-center gap-1.5 rounded-lg bg-lemon-400 px-4 py-2.5 text-[13px] font-bold text-ink transition-colors hover:bg-lemon-300 disabled:cursor-not-allowed disabled:opacity-40 sm:px-5 sm:text-sm"
          @click="handleSubmit"
        >
          <SendIcon class-name="h-4 w-4" />
          {{ submit.isPending.value ? '校验中' : '提交' }}
        </button>
        <div class="flex gap-1.5">
          <button
            type="button"
            :disabled="!sentence.clip_url"
            title="重听本句"
            class="flex-1 rounded-lg border border-ink/20 bg-white px-2 py-1.5 text-xs text-ink-2 transition-colors hover:bg-lemon-100 disabled:opacity-40"
            @click="onReplay"
          >
            重听
          </button>
          <button
            type="button"
            :disabled="!draft.text"
            title="清空输入并收起校验结果"
            class="flex-1 rounded-lg border border-ink/20 bg-white px-2 py-1.5 text-xs text-ink-2 transition-colors hover:bg-lemon-100 disabled:opacity-40"
            @click="clearInput"
          >
            清空
          </button>
        </div>
      </div>
    </div>

    <p v-if="submit.isError.value" class="mt-2 text-[12px] text-red-600">
      提交失败：{{ (submit.error.value as Error).message }}
    </p>

    <DiffResult v-if="draft.result" :result="draft.result" />

    <div
      data-testid="dictation-meta"
      class="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-ink-3"
    >
      <button
        type="button"
        class="flex items-center gap-1 text-ink-3 transition-colors hover:text-ink"
        @click="showHistory = !showHistory"
      >
        <HistoryIcon class-name="h-3.5 w-3.5" />
        {{ showHistory ? '收起历史' : '听写历史' }}
        <template v-if="sentence.attempt_count > 0">（{{ sentence.attempt_count }}）</template>
      </button>
      <!-- ⚠️ schema 可选字段判空必须用 `!= null`（生成的类型是 `number | null | undefined`，
           `!== null` 窄化不掉 undefined，会渲染出 `上次 undefined%`） -->
      <span v-if="sentence.last_accuracy != null && sentence.attempt_count > 0">
        上次 {{ sentence.last_accuracy }}%
      </span>
    </div>

    <div v-if="showHistory" class="mt-2 rounded-lg border border-ink/20 bg-white p-2">
      <p v-if="historyLoading" class="px-1 py-1 text-[12px] text-ink-3">加载中…</p>
      <p v-if="historyIsError" class="px-1 py-1 text-[12px] text-red-500">
        {{ (historyError as Error).message }}
      </p>
      <p v-if="historyData && historyData.items.length === 0" class="px-1 py-1 text-[12px] text-ink-3">
        还没有听写记录
      </p>
      <div
        v-if="historyData && historyData.items.length > 1"
        class="mb-2 flex items-end gap-[2px] px-1"
        title="按时间顺序的正确率（左旧右新）"
      >
        <span
          v-for="item in bars"
          :key="item.id"
          :title="`${item.accuracy}%`"
          :class="[
            'w-full max-w-[16px] rounded-sm',
            item.is_correct ? 'bg-emerald-400' : item.accuracy >= 60 ? 'bg-amber-400' : 'bg-rose-400',
          ].join(' ')"
          :style="{ height: `${Math.max(6, Math.round(item.accuracy * 0.32))}px` }"
        />
      </div>
      <div
        v-if="historyData && errorWords.length > 0"
        data-testid="dictation-error-words"
        class="mb-2 flex flex-wrap items-center gap-1.5 px-1"
      >
        <span class="text-[11px] text-ink-3">高频错误词</span>
        <span
          v-for="{ word, count } in errorWords"
          :key="word"
          :title="`在最近 ${historyData.items.length} 次听写中出错 ${count} 次`"
          class="rounded bg-red-50 px-1.5 py-0.5 text-[11px] text-red-600"
        >
          {{ word }} ×{{ count }}
        </span>
        <span v-if="historyData.total > historyData.items.length" class="text-[11px] text-ink-3">
          （基于最近 {{ historyData.items.length }} 次）
        </span>
      </div>
      <div v-for="item in historyData?.items ?? []" :key="item.id" class="border-b border-cream-2 last:border-0">
        <!-- 整行可点击展开/收起；aria-expanded + button 语义保证键盘可达 -->
        <button
          type="button"
          :data-testid="`dictation-history-item-${item.id}`"
          :aria-expanded="expandedId === item.id"
          class="flex min-h-[32px] w-full min-w-0 items-center justify-between gap-3 px-1 py-1.5 text-left text-[12px] transition-colors hover:bg-lemon-100"
          @click="expandedId = expandedId === item.id ? null : item.id"
        >
          <span class="shrink-0 text-ink-3" aria-hidden="true">
            {{ expandedId === item.id ? '▾' : '▸' }}
          </span>
          <span class="min-w-0 flex-1 truncate text-ink-2" :title="item.input">
            <template v-if="item.input">{{ item.input }}</template>
            <span v-else class="text-ink-3">（空）</span>
          </span>
          <span :class="`shrink-0 tabular-nums ${item.is_correct ? 'text-emerald-600' : 'text-ink-3'}`">
            {{ item.accuracy }}%
          </span>
          <span class="shrink-0 text-[11px] text-ink-3">
            {{ formatRelative(item.created_at) }}
          </span>
        </button>
        <div v-if="expandedId === item.id" class="mb-1.5 min-w-0 space-y-1.5 rounded-md bg-cream-2 px-2 py-2">
          <p class="text-[11px] text-ink-3">
            对照基准为当前原文；原文若被校对修改，明细按最新原文重算。
          </p>
          <div class="min-w-0">
            <span class="text-[11px] text-ink-3">当时提交</span>
            <p
              :data-testid="`dictation-history-input-${item.id}`"
              class="mt-0.5 whitespace-pre-wrap break-words text-[13px] leading-relaxed text-ink-2"
            >
              <template v-if="item.input">{{ item.input }}</template>
              <span v-else class="text-ink-3">（空）</span>
            </p>
          </div>
          <!-- 词级标注复用本题型的结果组件，不在前端重算 diff -->
          <DiffResult :result="item" compact />
        </div>
      </div>
    </div>
  </div>
</template>

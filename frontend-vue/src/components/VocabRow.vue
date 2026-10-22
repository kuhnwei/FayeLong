<script setup lang="ts">
/**
 * 单条生词行（照搬旧 `frontend/src/pages/VocabPage.tsx` 内联的 `VocabRow`）。
 *
 * 为什么独立成 SFC：旧版是同一文件里的内联子组件，Vue 没有等价写法，
 * 沿用 MediaRow.vue 的 props / emits 风格抽出来，DOM 结构逐字保留
 * （`data-vocab-row` 是 `scripts/verify_m4.mjs` 的选择器，不能动）。
 *
 * `editing` + `draft` 两个本地状态对应旧版 useState；
 * 旧版 `useEffect(() => setDraft(item.translation ?? ''), [item.translation])`
 * → `watch(() => props.item.translation, ...)`（列表刷新后草稿跟着服务端值走）。
 */
import { computed, nextTick, ref, watch } from 'vue'
import type { VocabItem } from '../api/client'
import { speakEnglish } from '../utils/speech'
import {
  CheckIcon,
  CloseIcon,
  PencilIcon,
  SpeakerIcon,
  StarFilledIcon,
  StarIcon,
  TrashIcon,
} from './icons'

interface Props {
  item: VocabItem
  /** 任一 mutation 进行中：按钮统一置灰，避免重复提交 */
  busy: boolean
}

const props = defineProps<Props>()

const emit = defineEmits<{
  (e: 'toggle-mastered'): void
  (e: 'save-translation', translation: string): void
  (e: 'delete'): void
}>()

const editing = ref(false)
const draft = ref(props.item.translation ?? '')
/** 编辑态的 textarea：旧版用 `autoFocus`，Vue 里需显式 focus（DOM 更新后） */
const textareaRef = ref<HTMLTextAreaElement | null>(null)

watch(
  () => props.item.translation,
  (value) => {
    draft.value = value ?? ''
  },
)

/** 展示名：有原型时显示原型，并在下方补一行「原文 xxx」 */
const display = computed(() =>
  props.item.lemma && props.item.lemma !== props.item.word ? `${props.item.lemma}` : props.item.word,
)

async function startEdit() {
  editing.value = true
  await nextTick()
  textareaRef.value?.focus()
}

function save() {
  emit('save-translation', draft.value)
  editing.value = false
}

function cancel() {
  draft.value = props.item.translation ?? ''
  editing.value = false
}
</script>

<template>
  <div data-vocab-row class="rounded-xl border border-slate-200 bg-white px-4 py-3">
    <div class="flex flex-wrap items-start gap-x-4 gap-y-2">
      <!-- 单词 -->
      <div class="min-w-[150px] shrink-0">
        <div class="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span class="text-[15px] font-medium text-slate-900">{{ display }}</span>
          <button
            type="button"
            :title="`朗读 ${display}`"
            :aria-label="`朗读 ${display}`"
            class="rounded p-0.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700"
            @click="speakEnglish(display)"
          >
            <SpeakerIcon class-name="h-3.5 w-3.5" />
          </button>
          <span v-if="item.phonetic" class="text-[11px] text-slate-400">/{{ item.phonetic }}/</span>
        </div>
        <p v-if="item.lemma && item.lemma !== item.word" class="mt-0.5 text-[10px] text-slate-400">
          原文 {{ item.word }}
        </p>
      </div>

      <!-- 释义 -->
      <div class="min-w-[220px] flex-1">
        <textarea
          v-if="editing"
          ref="textareaRef"
          v-model="draft"
          rows="2"
          class="w-full resize-y rounded-lg border border-slate-300 px-2.5 py-1.5 text-[13px] leading-relaxed text-slate-700 outline-none focus:border-slate-500"
        />
        <p v-else class="text-[13px] leading-relaxed text-slate-700">
          <template v-if="item.translation">{{ item.translation }}</template>
          <span v-else class="text-slate-400">（暂无释义）</span>
        </p>
        <p v-if="item.context" class="mt-1 text-[11px] leading-relaxed text-slate-400">
          上下文：{{ item.context }}
        </p>
      </div>

      <!-- 来源 -->
      <div class="shrink-0 text-right text-[11px] text-slate-400">
        <span
          v-if="item.media_title"
          :title="item.media_title"
          class="inline-block max-w-[140px] truncate"
        >
          {{ item.media_title }}
        </span>
        <span v-else class="text-slate-300">—</span>
      </div>

      <!-- 操作 -->
      <div class="flex shrink-0 items-center gap-1.5">
        <template v-if="editing">
          <button
            type="button"
            :disabled="busy"
            class="flex items-center gap-1 rounded-lg bg-slate-900 px-2.5 py-1.5 text-[12px] text-white transition-colors hover:bg-slate-700 disabled:opacity-40"
            @click="save"
          >
            <CheckIcon class-name="h-3.5 w-3.5" />
            保存
          </button>
          <button
            type="button"
            title="取消"
            class="rounded-lg border border-slate-200 p-1.5 text-slate-500 transition-colors hover:bg-slate-50"
            @click="cancel"
          >
            <CloseIcon class-name="h-3.5 w-3.5" />
          </button>
        </template>
        <template v-else>
          <button
            type="button"
            :disabled="busy"
            :title="item.mastered ? '标记为待复习' : '标记为已掌握'"
            :class="[
              'flex items-center gap-1 rounded-lg border px-2.5 py-1.5 text-[12px] transition-colors disabled:opacity-40',
              item.mastered
                ? 'border-emerald-200 bg-emerald-50 text-emerald-600'
                : 'border-slate-200 text-slate-500 hover:bg-slate-50',
            ]"
            @click="emit('toggle-mastered')"
          >
            <StarFilledIcon v-if="item.mastered" class-name="h-3.5 w-3.5" />
            <StarIcon v-else class-name="h-3.5 w-3.5" />
            {{ item.mastered ? '已掌握' : '标记掌握' }}
          </button>
          <button
            type="button"
            title="编辑释义"
            class="rounded-lg border border-slate-200 p-1.5 text-slate-500 transition-colors hover:bg-slate-50"
            @click="startEdit"
          >
            <PencilIcon class-name="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            :disabled="busy"
            title="删除"
            class="rounded-lg border border-slate-200 p-1.5 text-slate-400 transition-colors hover:bg-red-50 hover:text-red-600 disabled:opacity-40"
            @click="emit('delete')"
          >
            <TrashIcon class-name="h-3.5 w-3.5" />
          </button>
        </template>
      </div>
    </div>
  </div>
</template>

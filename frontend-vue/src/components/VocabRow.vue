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
  <!-- D3 二次打磨：卡片行 -> 表格行（PC 5 列 grid，移动塌成卡片） -->
  <div
    data-vocab-row
    class="grid grid-cols-1 gap-x-3 gap-y-1.5 border-b border-dashed border-ink/15 px-3 py-3 transition-colors last:border-0 hover:bg-lemon-100/60 sm:grid-cols-[minmax(0,1.05fr)_minmax(0,1.45fr)_minmax(0,.95fr)_88px_96px] sm:items-center sm:px-4"
  >
    <!-- 单词 -->
    <div class="flex min-w-0 items-center gap-1.5">
      <span class="truncate text-[14.5px] font-bold text-ink">{{ display }}</span>
      <button
        type="button"
        :title="`朗读 ${display}`"
        :aria-label="`朗读 ${display}`"
        class="shrink-0 rounded p-0.5 text-ink-3 transition-colors hover:bg-lemon-200 hover:text-ink"
        @click="speakEnglish(display)"
      >
        <SpeakerIcon class-name="h-3.5 w-3.5" />
      </button>
      <span v-if="item.phonetic" class="shrink-0 truncate text-[11px] text-ink-3">/{{ item.phonetic }}/</span>
    </div>

    <!-- 释义 -->
    <div class="min-w-0">
      <textarea
        v-if="editing"
        ref="textareaRef"
        v-model="draft"
        rows="2"
        class="w-full resize-y rounded-lg border-2 border-ink px-2 py-1 text-[12.5px] leading-relaxed text-ink outline-none"
      />
      <template v-else>
        <p class="line-clamp-2 text-[12.5px] leading-relaxed text-ink-2">
          <template v-if="item.translation">{{ item.translation }}</template>
          <span v-else class="text-ink-3">（暂无释义）</span>
        </p>
        <p
          v-if="item.context"
          :title="item.context"
          class="mt-0.5 line-clamp-1 text-[10.5px] leading-relaxed text-ink-3"
        >
          {{ item.context }}
        </p>
      </template>
    </div>

    <!-- 出处 -->
    <div class="hidden min-w-0 sm:block">
      <span
        v-if="item.media_title"
        :title="item.media_title"
        class="block truncate text-[11.5px] text-ink-3"
      >{{ item.media_title }}</span>
      <span v-else class="text-[11.5px] text-ink-3">—</span>
      <p v-if="item.lemma && item.lemma !== item.word" class="mt-0.5 text-[10px] text-ink-3">
        原文 {{ item.word }}
      </p>
    </div>

    <!-- 状态（可点切换） -->
    <div class="sm:text-center">
      <button
        v-if="!editing"
        type="button"
        :disabled="busy"
        :title="item.mastered ? '标记为待复习' : '标记为已掌握'"
        :class="[
          'inline-flex items-center gap-1 rounded-full border-2 px-2.5 py-1 text-[11px] font-bold transition-colors disabled:opacity-40',
          item.mastered
            ? 'border-emerald-300 bg-emerald-50 text-emerald-700'
            : 'border-ink bg-lemon-200 text-ink hover:bg-lemon-300',
        ]"
        @click="emit('toggle-mastered')"
      >
        <StarFilledIcon v-if="item.mastered" class-name="h-3 w-3" />
        <StarIcon v-else class-name="h-3 w-3" />
        {{ item.mastered ? '已掌握' : '待复习' }}
      </button>
    </div>

    <!-- 操作 -->
    <div class="flex items-center gap-1 sm:justify-end">
      <template v-if="editing">
        <button
          type="button"
          :disabled="busy"
          class="flex items-center gap-1 rounded-lg border-2 border-ink bg-lemon-400 px-2 py-1 text-[11.5px] font-bold text-ink transition-colors hover:bg-lemon-300 disabled:opacity-40"
          @click="save"
        >
          <CheckIcon class-name="h-3.5 w-3.5" />
          保存
        </button>
        <button
          type="button"
          title="取消"
          class="rounded-lg border-2 border-ink p-1 text-ink-2 transition-colors hover:bg-lemon-100"
          @click="cancel"
        >
          <CloseIcon class-name="h-3.5 w-3.5" />
        </button>
      </template>
      <template v-else>
        <button
          type="button"
          title="编辑释义"
          class="rounded-lg p-1.5 text-ink-3 transition-colors hover:bg-lemon-200 hover:text-ink"
          @click="startEdit"
        >
          <PencilIcon class-name="h-3.5 w-3.5" />
        </button>
        <button
          type="button"
          :disabled="busy"
          title="删除"
          class="rounded-lg p-1.5 text-ink-3 transition-colors hover:bg-red-50 hover:text-red-600 disabled:opacity-40"
          @click="emit('delete')"
        >
          <TrashIcon class-name="h-3.5 w-3.5" />
        </button>
      </template>
    </div>
  </div>
</template>

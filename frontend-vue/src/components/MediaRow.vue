<script setup lang="ts">
/**
 * 素材行（照搬旧 `MediaLibraryPage.tsx` 内联的 MediaRow / TypeBadge / StatusLine / CategoryBadge）。
 *
 * 旧版把这四个小组件内联在同一文件里；它们只被 MediaRow 使用，为避免文件碎片化
 * 把 TypeBadge / CategoryBadge / StatusLine 内联进模板（StatusLine 的分支用 computed 表达）。
 */
import { computed, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { PLAYABLE_STATUSES, PROCESSING_STATUSES } from '../api/client'
import type { MediaItem } from '../api/client'
import { formatBytes, formatDuration, formatRelative } from '../utils/format'
import { AlertIcon, BookIcon, PencilIcon, PlayIcon, RefreshIcon, TrashIcon } from './icons'

interface Props {
  media: MediaItem
  /** 所属分类名（父级用 ['categories'] 结果本地映射）；null = 未分类 */
  categoryName: string | null
  selectable: boolean
  checked: boolean
  busy: boolean
}

const props = defineProps<Props>()

const emit = defineEmits<{
  (e: 'toggle-select', checked: boolean): void
  (e: 'play', media: MediaItem): void
  (e: 'delete', media: MediaItem): void
  (e: 'retry', media: MediaItem): void
  (e: 'rename', media: MediaItem, title: string): void
}>()

const editing = ref(false)
const draft = ref(props.media.title)

const playable = computed(
  () => PLAYABLE_STATUSES.includes(props.media.status) || props.media.has_audio,
)
const isVideo = computed(() => props.media.type === 'video')

/** StatusLine 的处理中文案（旧版是嵌套三元，展开成映射，结果一致） */
const processingLabel = computed(() => {
  const s = props.media.status
  if (s === 'transcoding' || s === 'pending') return '正在转码为标准音频'
  if (s === 'asr') return '正在识别语音（faster-whisper）'
  if (s === 'translating') return '正在逐句翻译'
  if (s === 'clipping') return '正在生成句子切片'
  return '正在处理'
})

// 重命名输入框是动态渲染的：浏览器不会因 `autofocus` 属性自动聚焦 DOM API 插入的元素，
// 必须显式调用 focus()（与 React 的 autoFocus 语义对齐）。
const vFocus = { mounted: (el: HTMLElement) => el.focus() }

function commit() {
  const value = draft.value.trim()
  editing.value = false
  if (value && value !== props.media.title) emit('rename', props.media, value)
  else draft.value = props.media.title
}

function startRename() {
  draft.value = props.media.title
  editing.value = true
}

function cancelEdit() {
  draft.value = props.media.title
  editing.value = false
}

function onToggle(event: Event) {
  emit('toggle-select', (event.target as HTMLInputElement).checked)
}
</script>

<template>
  <div class="flex items-start gap-3 px-3 py-4 sm:gap-4 sm:px-5">
    <!-- 多选态：左侧 checkbox，点击热区 32×32 -->
    <label
      v-if="selectable"
      class="flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-lg hover:bg-lemon-100"
      title="选择此素材"
    >
      <input
        type="checkbox"
        :checked="checked"
        :aria-label="`选择「${media.title}」`"
        class="h-4 w-4 accent-[var(--lemon-500)]"
        @change="onToggle"
      />
    </label>

    <button
      type="button"
      :disabled="!playable"
      :title="playable ? '播放' : '转码完成后可播放'"
      :class="[
        'mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full transition-colors',
        playable
          ? 'bg-lemon-400 text-ink hover:bg-lemon-300'
          : 'cursor-not-allowed bg-cream-2 text-ink-3',
      ]"
      @click="emit('play', media)"
    >
      <PlayIcon class-name="ml-0.5 h-3.5 w-3.5" />
    </button>

    <div class="min-w-0 flex-1">
      <div class="flex items-center gap-2">
        <input
          v-if="editing"
          v-focus
          v-model="draft"
          class="min-w-0 flex-1 rounded border border-ink-3 px-2 py-0.5 text-[14px] outline-none focus:border-ink"
          @blur="commit"
          @keydown.enter="commit"
          @keydown.esc="cancelEdit"
        />
        <span v-else data-media-title class="truncate text-[14px] font-medium text-ink">{{ media.title }}</span>

        <!-- CategoryBadge：由父级传进来的分类名渲染，未分类是灰字 -->
        <span v-if="!categoryName" class="shrink-0 text-[10px] text-ink-3">未分类</span>
        <span
          v-else
          class="inline-block max-w-[7rem] shrink-0 truncate rounded bg-cream-2 px-1.5 py-0.5 align-middle text-[10px] text-ink-2"
        >{{ categoryName }}</span>

        <!-- TypeBadge -->
        <span
          :class="[
            'shrink-0 rounded px-1.5 py-0.5 text-[10px]',
            isVideo ? 'bg-purple-50 text-purple-600' : 'bg-sky-50 text-sky-600',
          ]"
        >{{ isVideo ? '视频·仅音轨' : '音频' }}</span>
      </div>

      <div class="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-ink-3">
        <span class="tabular-nums">{{ formatDuration(media.duration_ms) }}</span>
        <span>{{ formatBytes(media.size_bytes) }}</span>
        <span>{{ media.origin === 'inbox' ? '素材目录导入' : '本地上传' }}</span>
        <span>{{ formatRelative(media.created_at) }}</span>
        <span class="truncate">{{ media.original_name }}</span>
      </div>

      <!-- StatusLine -->
      <div
        v-if="media.status === 'failed'"
        class="mt-1.5 flex items-start gap-1.5 text-[12px] text-red-600"
      >
        <AlertIcon class-name="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <span>{{ media.error || '处理失败' }}</span>
      </div>

      <div
        v-else-if="PROCESSING_STATUSES.includes(media.status)"
        class="mt-2"
      >
        <div class="flex items-center justify-between text-[11px] text-ink-3">
          <span>{{ processingLabel }}</span>
          <span class="tabular-nums">{{ media.progress }}%</span>
        </div>
        <div class="mt-1 h-1 w-full overflow-hidden rounded-full bg-cream-2">
          <div
            class="h-full rounded-full bg-lemon-400 transition-[width] duration-300"
            :style="{ width: Math.max(2, media.progress) + '%' }"
          />
        </div>
      </div>

      <div v-else class="mt-1.5 flex items-center gap-1.5 text-[12px] text-emerald-600">
        <span class="h-1.5 w-1.5 rounded-full bg-emerald-500" />
        <span>
          已就绪，可播放{{ media.sentence_count > 0 ? `（${media.sentence_count} 句已转录）` : '' }}
        </span>
      </div>
    </div>

    <div class="flex shrink-0 items-center gap-1">
      <RouterLink
        :to="`/study/${media.id}`"
        :class="[
          'flex items-center gap-1 rounded-lg border px-2.5 py-1.5 text-xs transition-colors',
          playable
            ? 'border-ink text-ink-2 hover:bg-lemon-100'
            : 'pointer-events-none border-cream-2 text-ink-3',
        ]"
        title="进入学习页"
      >
        <BookIcon class-name="h-3.5 w-3.5" />
        学习
      </RouterLink>

      <button
        v-if="media.status === 'failed'"
        type="button"
        :disabled="busy"
        title="重新处理"
        class="rounded-lg p-2 text-ink-3 transition-colors hover:bg-lemon-100 hover:text-ink disabled:opacity-40"
        @click="emit('retry', media)"
      >
        <RefreshIcon class-name="h-4 w-4" />
      </button>

      <button
        type="button"
        title="重命名"
        class="rounded-lg p-2 text-ink-3 transition-colors hover:bg-lemon-100 hover:text-ink"
        @click="startRename"
      >
        <PencilIcon class-name="h-4 w-4" />
      </button>

      <button
        type="button"
        :disabled="busy"
        title="删除"
        class="rounded-lg p-2 text-ink-3 transition-colors hover:bg-red-50 hover:text-red-600 disabled:opacity-40"
        @click="emit('delete', media)"
      >
        <TrashIcon class-name="h-4 w-4" />
      </button>
    </div>
  </div>
</template>

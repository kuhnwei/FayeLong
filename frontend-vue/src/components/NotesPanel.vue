<script setup lang="ts">
/**
 * 笔记汇总面板（M5 / FR-A6）。
 *
 * 学习页顶部「笔记」入口打开：列出本媒体所有句子笔记（含原文 / 翻译 / 听写概要），
 * 点击条目可定位到对应句子卡片，右上角可一键导出为 Markdown。
 *
 * Vue 版：React 的 `createPortal` 用 `<Teleport to="body">` 等价替换。
 */
import { computed, onMounted, onUnmounted } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import { getMediaNotes, mediaNotesExportUrl } from '../api/client'
import { CloseIcon, DownloadIcon, NoteIcon } from './icons'

const props = defineProps<{ mediaId: number }>()
const emit = defineEmits<{ close: []; jump: [sentenceId: number] }>()

const { data, isLoading, isError, error } = useQuery({
  queryKey: ['media-notes', props.mediaId],
  queryFn: () => getMediaNotes(props.mediaId),
})

// Esc 关闭
function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape') emit('close')
}
onMounted(() => window.addEventListener('keydown', onKey))
onUnmounted(() => window.removeEventListener('keydown', onKey))

const items = computed(() => data.value?.items ?? [])

function onMaskClick() {
  emit('close')
}
function stopPropagation(e: MouseEvent) {
  e.stopPropagation()
}
function onItem(itemSentenceId: number) {
  emit('jump', itemSentenceId)
  emit('close')
}
function exportUrl() {
  return mediaNotesExportUrl(props.mediaId)
}
function messageOf(e: unknown) {
  return (e as Error).message
}
</script>

<template>
  <Teleport to="body">
    <div
      class="fixed inset-0 z-50 flex items-start justify-center bg-slate-900/30 p-3 backdrop-blur-sm sm:p-6"
      @click="onMaskClick"
    >
      <div
        class="mt-3 flex max-h-[85vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-xl sm:mt-8 sm:max-h-[80vh]"
        role="dialog"
        aria-label="句子笔记汇总"
        @click="stopPropagation"
      >
        <div class="flex flex-wrap items-center gap-2 border-b border-slate-100 px-3 py-3 sm:px-5 sm:py-3.5">
          <NoteIcon class-name="h-4 w-4 text-slate-400" />
          <h3 class="text-[14px] font-medium text-slate-900">句子笔记</h3>
          <span v-if="data" class="text-[12px] text-slate-400">
            {{ data.total }} 条 / 全篇 {{ data.sentence_count }} 句
          </span>
          <div class="ml-auto flex items-center gap-2">
            <a
              :href="exportUrl()"
              :class="[
                'flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[12px] transition-colors',
                items.length ? 'bg-slate-900 text-white hover:bg-slate-700' : 'pointer-events-none bg-slate-200 text-slate-500',
              ].join(' ')"
            >
              <DownloadIcon class-name="h-3.5 w-3.5" />
              导出 Markdown
            </a>
            <button
              type="button"
              title="关闭"
              class="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700"
              @click="emit('close')"
            >
              <CloseIcon class-name="h-4 w-4" />
            </button>
          </div>
        </div>

        <div class="min-h-0 flex-1 overflow-auto px-3 py-3 sm:px-5 sm:py-4">
          <p v-if="isLoading" class="py-6 text-center text-[13px] text-slate-400">加载中…</p>
          <p v-if="isError" class="py-6 text-center text-[13px] text-red-600">
            {{ messageOf(error) }}
          </p>
          <div
            v-if="!isLoading && !isError && items.length === 0"
            class="py-10 text-center"
          >
            <NoteIcon class-name="mx-auto h-7 w-7 text-slate-300" />
            <p class="mt-3 text-[13px] text-slate-400">
              还没有句子笔记。在句子卡片下方点「添加笔记」记录心得，这里会汇总展示。
            </p>
          </div>

          <div class="space-y-2.5">
            <button
              v-for="item in items"
              :key="item.sentence_id"
              type="button"
              class="block w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-left transition-colors hover:border-slate-300 hover:bg-slate-50 sm:px-4"
              @click="onItem(item.sentence_id)"
            >
              <div class="flex items-center gap-2">
                <span class="shrink-0 text-[11px] tabular-nums text-slate-400">#{{ item.idx + 1 }}</span>
                <span
                  v-if="item.attempt_count > 0"
                  :class="[
                    'rounded-full px-2 py-0.5 text-[10px] tabular-nums',
                    item.mastered ? 'bg-emerald-50 text-emerald-600' : 'bg-amber-50 text-amber-600',
                  ].join(' ')"
                >
                  {{ item.mastered ? '已掌握' : `最佳 ${item.best_accuracy}%` }}
                </span>
                <span class="ml-auto hidden shrink-0 text-[11px] text-slate-300 sm:inline">点击定位 →</span>
              </div>
              <p v-if="item.text_en" class="mt-1.5 text-[13px] leading-relaxed text-slate-700">
                {{ item.text_en }}
              </p>
              <p v-if="item.text_zh" class="mt-0.5 text-[12px] leading-relaxed text-slate-400">
                {{ item.text_zh }}
              </p>
              <p class="mt-1.5 whitespace-pre-wrap rounded-lg bg-amber-50/60 px-2.5 py-1.5 text-[12px] leading-relaxed text-slate-700">
                {{ item.content }}
              </p>
            </button>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

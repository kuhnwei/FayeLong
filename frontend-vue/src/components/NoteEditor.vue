<script setup lang="ts">
/**
 * 句子笔记编辑器（M4 / FR-S8）。
 *
 * - 每句至多一条笔记；折叠态显示预览，展开后编辑。
 * - 失焦或点击「保存」时写入后端；内容清空即删除该笔记。
 */
import { computed, onUnmounted, ref, watch } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'
import { getNote, saveNote, type NoteItem } from '../api/client'
import { CheckIcon, NoteIcon, TrashIcon } from './icons'

const props = defineProps<{ sentenceId: number }>()

const queryClient = useQueryClient()
const open = ref(false)
const text = ref('')
const original = ref('')
const status = ref<'idle' | 'saving' | 'saved' | 'error'>('idle')
const message = ref<string | null>(null)
const loading = ref(true)
const loaded = ref(false)

// 首次加载该句笔记（切句时重新加载；取消标记防止过期响应覆盖）
watch(
  () => props.sentenceId,
  (sentenceId, _old, onCleanup) => {
    let cancelled = false
    loaded.value = false
    loading.value = true
    getNote(sentenceId)
      .then((note: NoteItem) => {
        if (cancelled) return
        text.value = note.content
        original.value = note.content
        open.value = Boolean(note.content) // 已有笔记默认展开
      })
      .catch((err: Error) => {
        if (!cancelled) message.value = `读取笔记失败：${err.message}`
      })
      .finally(() => {
        if (!cancelled) {
          loading.value = false
          loaded.value = true
        }
      })
    onCleanup(() => {
      cancelled = true
    })
  },
  { immediate: true },
)

onUnmounted(() => {
  if (statusTimer !== null) window.clearTimeout(statusTimer)
})

let statusTimer: number | null = null

const dirty = computed(() => text.value.trim() !== original.value.trim())

async function persist(value: string) {
  if (value.trim() === original.value.trim()) return
  status.value = 'saving'
  message.value = null
  try {
    const result = await saveNote(props.sentenceId, value)
    const content = result?.content ?? ''
    text.value = content
    original.value = content
    queryClient.setQueryData(['note', props.sentenceId], result)
    // 笔记有变化 → 让学习页的「笔记」汇总与计数同步刷新（M5）
    void queryClient.invalidateQueries({ queryKey: ['media-notes'] })
    status.value = 'saved'
    message.value = result?.exists ? '笔记已保存' : '笔记已清空'
    if (statusTimer !== null) window.clearTimeout(statusTimer)
    statusTimer = window.setTimeout(() => {
      status.value = 'idle'
      statusTimer = null
    }, 1800)
  } catch (err) {
    status.value = 'error'
    message.value = `保存失败：${(err as Error).message}`
  }
}

function toggleOpen() {
  open.value = !open.value
}
function onBlur() {
  void persist(text.value)
}
function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
    e.preventDefault()
    void persist(text.value)
  }
  if (e.key === 'Escape') open.value = false
}
function save() {
  void persist(text.value)
}
function remove() {
  text.value = ''
  void persist('')
}
</script>

<template>
  <div class="mt-2 border-t border-slate-100 pt-2">
    <div class="flex items-center gap-2">
      <button
        type="button"
        class="flex items-center gap-1 text-[11px] text-slate-500 transition-colors hover:text-slate-800"
        @click="toggleOpen"
      >
        <NoteIcon class-name="h-3.5 w-3.5" />
        {{ open ? '收起笔记' : original ? '查看笔记' : '添加笔记' }}
      </button>

      <span
        v-if="!open && original"
        class="min-w-0 flex-1 truncate text-[11px] text-slate-400"
        :title="original"
      >
        {{ original }}
      </span>

      <span
        v-if="message"
        :class="['ml-auto shrink-0 text-[11px]', status === 'error' ? 'text-red-600' : 'text-emerald-600'].join(' ')"
      >
        {{ message }}
      </span>
    </div>

    <div v-if="open" class="mt-2">
      <textarea
        v-model="text"
        rows="3"
        :disabled="loading"
        placeholder="记录这个词的用法、搭配、易错点…（失焦自动保存，Ctrl/Cmd+Enter 立即保存）"
        class="w-full resize-y rounded-lg border border-slate-200 bg-slate-50/60 px-3 py-2 text-[13px] leading-relaxed text-slate-700 outline-none transition-colors focus:border-slate-400 focus:bg-white disabled:bg-slate-100"
        @blur="onBlur"
        @keydown="onKeydown"
      />
      <div class="mt-1.5 flex items-center gap-2">
        <button
          type="button"
          :disabled="!dirty || status === 'saving'"
          class="flex items-center gap-1 rounded-lg bg-slate-900 px-2.5 py-1 text-[11px] text-white transition-colors hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-40"
          @click="save"
        >
          <CheckIcon class-name="h-3.5 w-3.5" />
          {{ status === 'saving' ? '保存中' : '保存' }}
        </button>
        <button
          v-if="original"
          type="button"
          :disabled="status === 'saving'"
          class="flex items-center gap-1 rounded-lg border border-slate-200 px-2.5 py-1 text-[11px] text-slate-500 transition-colors hover:bg-slate-50 disabled:opacity-40"
          @click="remove"
        >
          <TrashIcon class-name="h-3.5 w-3.5" />
          删除笔记
        </button>
        <span v-if="dirty && status !== 'saving'" class="text-[11px] text-amber-600">未保存</span>
      </div>
    </div>
  </div>
</template>

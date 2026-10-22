<script setup lang="ts">
/**
 * 把英文原文按单词拆开渲染，单词可点击以唤起查词浮层（FR-S6）。
 *
 * 开启标记模式后，单词的点击含义改为「标记/取消易听错」，并支持按住拖选一整段。
 *
 * ⭐ 分词正则见 `../types/study.ts::WORD_SPLIT` —— 必须与
 * `backend/app/services/marks.py::word_count` 一字不差（词序下标契约）。
 */
import { computed } from 'vue'
import { WORD_SPLIT, type WordRect } from '../types/study'

const props = withDefaults(
  defineProps<{
    text: string
    fontSize: string
    /** 已标记的词下标 */
    marks?: Set<number>
    markMode?: boolean
    /** 拖选中正在划过的区间（闭区间） */
    previewRange?: readonly [number, number] | null
  }>(),
  { marks: undefined, markMode: false, previewRange: null },
)

const emit = defineEmits<{
  'word-click': [word: string, rect: WordRect]
  'mark-start': [wordIndex: number]
  'mark-hover': [wordIndex: number]
}>()

const parts = computed(() => (props.text || '').split(WORD_SPLIT))

/**
 * WORD_SPLIT 有一个捕获组 → split 结果里**奇数索引**是单词本身。
 * 因此第 i 个（奇数）部分的词序下标恒为 (i-1)/2，无需可变计数器。
 */
function wordIndexOf(index: number): number {
  return (index - 1) / 2
}

function isMarked(wordIndex: number): boolean {
  return props.marks?.has(wordIndex) ?? false
}

function inPreview(wordIndex: number): boolean {
  const range = props.previewRange
  return range !== null && range !== undefined && wordIndex >= range[0] && wordIndex <= range[1]
}

function btnClass(wordIndex: number): string {
  const marked = isMarked(wordIndex)
  return [
    'rounded px-0.5 transition-colors',
    props.markMode
      ? 'cursor-pointer'
      : 'hover:bg-sky-100 hover:text-sky-800 focus:bg-sky-100 focus:outline-none',
    marked
      ? 'bg-amber-100 text-amber-900 underline decoration-amber-400 decoration-wavy decoration-2 underline-offset-4'
      : props.markMode
        ? 'hover:bg-amber-100'
        : '',
    inPreview(wordIndex) && !marked ? 'bg-amber-200/70 text-amber-900' : '',
  ].join(' ')
}

function onMarkDown(event: MouseEvent, wordIndex: number) {
  // 仅标记模式：阻止默认选词，交给 pointerup 统一提交
  if (!props.markMode) return
  event.preventDefault()
  emit('mark-start', wordIndex)
}

function onWordClickHandler(event: MouseEvent, part: string) {
  if (props.markMode) return // 标记模式下由 pointerup 统一提交，避免重复切换
  const rect = (event.currentTarget as HTMLElement).getBoundingClientRect()
  emit('word-click', part, {
    top: rect.top,
    left: rect.left,
    bottom: rect.bottom,
    width: rect.width,
  })
}

function onWordButtonEnter(wordIndex: number) {
  if (!props.markMode) return
  emit('mark-hover', wordIndex)
}

function titleOf(part: string): string {
  return props.markMode ? '点一下标记 / 取消这个词' : `查询「${part}」`
}

function ariaPressedOf(wordIndex: number): boolean | undefined {
  return props.markMode ? isMarked(wordIndex) : undefined
}
</script>

<template>
  <p v-if="text" data-testid="sentence-text" :class="['font-medium leading-[1.4] text-slate-800', markMode ? 'select-none' : ''].join(' ')" :style="{ fontSize }">
    <template v-for="(part, index) in parts" :key="index">
      <span v-if="index % 2 !== 1">{{ part }}</span>
      <button
        v-else
        type="button"
        :data-word-index="wordIndexOf(index)"
        :data-marked="isMarked(wordIndexOf(index)) ? '1' : undefined"
        :title="titleOf(part)"
        :aria-pressed="ariaPressedOf(wordIndexOf(index))"
        :class="btnClass(wordIndexOf(index))"
        @pointerdown="onMarkDown($event, wordIndexOf(index))"
        @pointerenter="onWordButtonEnter(wordIndexOf(index))"
        @click="onWordClickHandler($event, part)"
      >
        {{ part }}
      </button>
    </template>
    <slot name="trailing" />
  </p>
  <p v-else class="text-[15px] leading-relaxed text-slate-400">（空）</p>
</template>

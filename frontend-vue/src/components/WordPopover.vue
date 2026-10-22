<script setup lang="ts">
/**
 * 单词浮层：站内释义 + 词形还原 + 跳牛津/朗文 + 一键加入生词本（M4 / FR-S6 · FR-S7）。
 *
 * 交互要点：
 * - 点击原文中的单词弹出；点击遮罩、Esc、关闭按钮均可关闭。
 * - 释义来自本地 ECDICT 词库（离线）；词库未收录时后端可能返回在线翻译兜底。
 * - 「加入生词本」会带上当前句子作为上下文（便于日后复习与导出）。
 *
 * Vue 版：React 的 `createPortal` 用 `<Teleport to="body">` 等价替换。
 */
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useMutation } from '@tanstack/vue-query'
import { addVocab, lookupWord, type DictResult, type VocabItem } from '../api/client'
import { speakEnglish } from '../utils/speech'
import type { WordPopoverTarget } from '../types/study'
import {
  BookmarkPlusIcon,
  CheckIcon,
  CloseIcon,
  ExternalLinkIcon,
  RefreshIcon,
} from './icons'

const props = defineProps<{ target: WordPopoverTarget }>()
const emit = defineEmits<{ close: [] }>()

const CARD_W = 344
const MARGIN = 8

/** 卡片宽度：桌面上固定 344px；窄屏（手机）收缩到「视口宽 − 两侧留白」，避免横向溢出。 */
function cardWidth(): number {
  if (typeof window === 'undefined') return CARD_W
  return Math.min(CARD_W, window.innerWidth - MARGIN * 2)
}

const cardRef = ref<HTMLDivElement | null>(null)
const pos = ref({ top: props.target.rect.bottom + MARGIN, left: props.target.rect.left })

const loading = ref(true)
const data = ref<DictResult | null>(null)
const error = ref<string | null>(null)
const added = ref<'added' | 'exists' | null>(null)

/** 查词（点击即查，避免依赖缓存 key 的复杂度） */
function reload() {
  loading.value = true
  error.value = null
  lookupWord(props.target.word)
    .then((result) => {
      data.value = result
    })
    .catch((err: Error) => {
      error.value = err.message
    })
    .finally(() => {
      loading.value = false
    })
}

// 首次挂载与切换单词时查询，并重置「已加入」状态
watch(
  () => props.target.word,
  () => {
    added.value = null
    reload()
  },
  { immediate: true },
)

// 定位：优先显示在词下方，空间不足则上移；左右夹在视口内
watch([() => props.target, loading, data, error], () => {
  void nextTick(relayout)
})

function relayout() {
  const el = cardRef.value
  if (!el) return
  const height = el.offsetHeight
  const width = el.offsetWidth || CARD_W
  const rect = props.target.rect
  let top = rect.bottom + MARGIN
  if (top + height > window.innerHeight - MARGIN) {
    const above = rect.top - MARGIN - height
    top = above > MARGIN ? above : Math.max(MARGIN, window.innerHeight - MARGIN - height)
  }
  const left = Math.min(Math.max(MARGIN, rect.left), window.innerWidth - MARGIN - width)
  if (pos.value.top !== top || pos.value.left !== left) pos.value = { top, left }
}

// Esc 关闭
function onKey(event: KeyboardEvent) {
  if (event.key === 'Escape') emit('close')
}
onMounted(() => window.addEventListener('keydown', onKey))
onUnmounted(() => window.removeEventListener('keydown', onKey))

const addMutation = useMutation({
  mutationFn: () => {
    const entry = data.value
    return addVocab({
      word: entry?.word || props.target.word,
      lemma: entry?.lemma ?? null,
      phonetic: entry?.phonetic || null,
      translation: entry?.translation?.length ? entry.translation.join('；') : null,
      media_id: props.target.mediaId ?? null,
      sentence_id: props.target.sentenceId ?? null,
      context: props.target.context ?? null,
    })
  },
  onSuccess: (item: VocabItem) => {
    added.value = item.duplicated ? 'exists' : 'added'
  },
})

// ⚠️ schema 里 tags / translation / definition / forms 均为**可选**（`?`），模板不能直接
// 读子字段 —— 这里统一兜底成空数组（与旧手写类型的「必有」语义对齐）。
const tags = computed(() => data.value?.tags ?? [])
const translation = computed(() => data.value?.translation ?? [])
const definition = computed(() => data.value?.definition ?? [])
const forms = computed(() => data.value?.forms ?? [])

const hasMeta = computed(
  () =>
    tags.value.length > 0 ||
    (data.value?.collins ?? 0) > 0 ||
    data.value?.oxford === 1 ||
    data.value?.source === 'online',
)

function onMaskMouseDown() {
  emit('close')
}
function stopPropagation(event: MouseEvent) {
  event.stopPropagation()
}
function speak() {
  speakEnglish(data.value?.word || props.target.word)
}
</script>

<template>
  <Teleport to="body">
    <div class="fixed inset-0 z-50" @mousedown="onMaskMouseDown">
      <div
        ref="cardRef"
        class="absolute max-h-[70vh] overflow-y-auto rounded-xl border border-slate-200 bg-white p-4 shadow-xl"
        :style="{ top: pos.top, left: pos.left, width: cardWidth() }"
        @mousedown="stopPropagation"
      >
        <!-- 头部 -->
        <div class="flex items-start justify-between gap-3">
          <div class="min-w-0">
            <div class="flex flex-wrap items-baseline gap-x-2 gap-y-1">
              <span class="text-[17px] font-medium text-slate-900">{{ target.word }}</span>
              <span v-if="data?.phonetic" class="text-[12px] text-slate-400">/{{ data.phonetic }}/</span>
              <button
                type="button"
                title="朗读"
                class="rounded border border-slate-200 px-1.5 py-0.5 text-[10px] text-slate-500 transition-colors hover:bg-slate-50"
                @click="speak"
              >
                朗读
              </button>
            </div>
            <p v-if="data?.lemma && data.lemma !== data.query" class="mt-1 text-[11px] text-slate-400">
              已还原原型：<span class="text-slate-600">{{ data.lemma }}</span>
            </p>
          </div>
          <button
            type="button"
            title="关闭"
            class="shrink-0 rounded p-1 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600"
            @click="emit('close')"
          >
            <CloseIcon class-name="h-4 w-4" />
          </button>
        </div>

        <!-- 主体 -->
        <div class="mt-3 border-t border-slate-100 pt-3">
          <p v-if="loading" class="flex items-center gap-2 py-3 text-[12px] text-slate-400">
            <RefreshIcon class-name="h-3.5 w-3.5 animate-spin" />
            查询中…
          </p>

          <p v-if="!loading && error" class="py-2 text-[12px] text-red-600">查询失败：{{ error }}</p>

          <div v-if="!loading && !error && data" class="space-y-2.5">
            <!-- 标签行 -->
            <div v-if="hasMeta" class="flex flex-wrap items-center gap-1.5">
              <span v-if="data.oxford === 1" class="rounded bg-sky-50 px-1.5 py-0.5 text-[10px] text-sky-600">
                牛津核心
              </span>
              <span v-if="data.collins > 0" class="rounded bg-amber-50 px-1.5 py-0.5 text-[10px] text-amber-600">
                柯林斯 {{ '★'.repeat(Math.min(5, data.collins)) }}
              </span>
              <span
                v-for="tag in tags"
                :key="tag"
                class="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-500"
              >
                {{ tag }}
              </span>
              <span v-if="data.source === 'online'" class="rounded bg-violet-50 px-1.5 py-0.5 text-[10px] text-violet-600">
                在线参考
              </span>
            </div>

            <!-- 中文释义 -->
            <ul v-if="translation.length > 0" class="space-y-1">
              <li
                v-for="(line, index) in translation.slice(0, 6)"
                :key="index"
                class="text-[13px] leading-relaxed text-slate-800"
              >
                {{ line }}
              </li>
            </ul>
            <p v-else class="text-[13px] text-slate-400">（暂无中文释义）</p>

            <!-- 英文释义 -->
            <details v-if="definition.length > 0" class="text-[12px]">
              <summary class="cursor-pointer select-none text-slate-400 hover:text-slate-600">
                英文释义（{{ definition.length }}）
              </summary>
              <ul class="mt-1.5 space-y-1">
                <li
                  v-for="(line, index) in definition.slice(0, 4)"
                  :key="index"
                  class="leading-relaxed text-slate-500"
                >
                  {{ line }}
                </li>
              </ul>
            </details>

            <!-- 词形变化 -->
            <div
              v-if="forms.length > 0"
              class="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-slate-400"
            >
              <span v-for="(form, index) in forms.slice(0, 6)" :key="`${form.label}-${index}`">
                {{ form.label }}
                <span class="ml-1 text-slate-600">{{ form.value }}</span>
              </span>
            </div>

            <p
              v-if="data.notice"
              class="rounded bg-amber-50 px-2 py-1.5 text-[11px] leading-relaxed text-amber-700"
            >
              {{ data.notice }}
            </p>
          </div>
        </div>

        <!-- 底部操作 -->
        <div class="mt-3 flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3">
          <button
            type="button"
            :disabled="addMutation.isPending.value || added !== null"
            :class="[
              'flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[12px] transition-colors',
              added ? 'bg-emerald-50 text-emerald-600' : 'bg-slate-900 text-white hover:bg-slate-700',
              addMutation.isPending.value ? 'opacity-60' : '',
            ].join(' ')"
            @click="addMutation.mutate()"
          >
            <CheckIcon v-if="added" class-name="h-3.5 w-3.5" />
            <BookmarkPlusIcon v-else class-name="h-3.5 w-3.5" />
            {{ added === 'added' ? '已加入生词本' : added === 'exists' ? '已在生词本' : '加入生词本' }}
          </button>

          <span v-if="addMutation.isError.value" class="text-[11px] text-red-600">
            {{ (addMutation.error.value as Error).message }}
          </span>

          <div class="ml-auto flex items-center gap-2 text-[11px]">
            <a
              :href="data?.oxford_url || '#'"
              target="_blank"
              rel="noreferrer"
              class="flex items-center gap-0.5 text-slate-500 transition-colors hover:text-slate-900"
            >
              牛津
              <ExternalLinkIcon class-name="h-3 w-3" />
            </a>
            <span class="text-slate-200">·</span>
            <a
              :href="data?.longman_url || '#'"
              target="_blank"
              rel="noreferrer"
              class="flex items-center gap-0.5 text-slate-500 transition-colors hover:text-slate-900"
            >
              朗文
              <ExternalLinkIcon class-name="h-3 w-3" />
            </a>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

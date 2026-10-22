<script setup lang="ts">
/**
 * 分类筛选 chips 条（照搬旧 `CategoryChips.tsx`）。
 *
 * 布局：窄屏单行横向滚动（`overflow-x-auto` + `shrink-0`），`sm` 起换行。
 * 计数口径：这里的数字都是**分类子集计数**（来自 `GET /api/categories`），
 * 与顶部 StatCard 的全局计数不同 —— 所以文案用「名称 N」而不是「共 N 个」。
 */
import { computed } from 'vue'
import type { CategoryItem } from '../api/client'
import { TagIcon } from './icons'
import type { CategoryFilter } from './category'

interface Props {
  items: CategoryItem[]
  uncategorizedCount: number
  /** 服务端分类列表是否还在加载（首帧给占位，避免 chip 跳动） */
  loading?: boolean
  selected: CategoryFilter
}

const props = withDefaults(defineProps<Props>(), { loading: false })

const emit = defineEmits<{
  (e: 'select', value: CategoryFilter): void
  (e: 'manage'): void
}>()

// 「全部」的自洽计数 = 各分类之和 + 未分类（同一个来源，避免与 StatCard 口径打架）
const allCount = computed(
  () => props.items.reduce((sum, c) => sum + c.media_count, 0) + props.uncategorizedCount,
)

const chipClass = (active: boolean, muted = false) =>
  [
    'flex h-8 shrink-0 items-center gap-1.5 rounded-full border px-3 text-[12px] transition-colors',
    active
      ? 'border-ink bg-lemon-400 text-ink'
      : muted
        ? 'border-ink bg-white text-ink-3'
        : 'border-ink bg-white text-ink-2 hover:border-ink-3 hover:text-ink',
  ].join(' ')

const countClass = (active: boolean) =>
  ['tabular-nums', active ? 'text-ink-3' : 'text-ink-3'].join(' ')

const entries = computed<{ key: string; label: string; count: number; value: CategoryFilter }[]>(
  () => [
    { key: 'all', label: '全部', count: allCount.value, value: null },
    { key: 'none', label: '未分类', count: props.uncategorizedCount, value: 'none' },
    ...props.items.map((c) => ({ key: `c${c.id}`, label: c.name, count: c.media_count, value: c.id })),
  ],
)
</script>

<template>
  <div
    class="-mx-1 flex items-center gap-1.5 overflow-x-auto px-1 pb-1 sm:flex-wrap sm:overflow-x-visible sm:pb-0"
    role="group"
    aria-label="按分类筛选素材"
  >
    <span
      v-if="loading && items.length === 0"
      class="h-8 w-24 shrink-0 animate-pulse rounded-full bg-cream-2"
    />

    <button
      v-for="entry in entries"
      :key="entry.key"
      type="button"
      :aria-pressed="selected === entry.value"
      :data-selected="selected === entry.value ? 'true' : 'false'"
      :class="chipClass(selected === entry.value, entry.count === 0 && selected !== entry.value)"
      :title="entry.label === '全部' ? '显示全部素材' : `只看「${entry.label}」`"
      @click="emit('select', entry.value)"
    >
      <span class="max-w-[8rem] truncate">{{ entry.label }}</span>
      <span :class="countClass(selected === entry.value)">{{ entry.count }}</span>
    </button>

    <button
      type="button"
      class="flex h-8 shrink-0 items-center gap-1 rounded-full border border-dashed border-ink-3 px-3 text-[12px] text-ink-2 transition-colors hover:border-ink hover:text-ink"
      @click="emit('manage')"
    >
      <TagIcon class-name="h-3.5 w-3.5" />
      管理分类
    </button>
  </div>
</template>

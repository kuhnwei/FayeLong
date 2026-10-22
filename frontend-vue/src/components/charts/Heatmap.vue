<script setup lang="ts">
/**
 * 12 周听写活跃度热力图（P2 · 契约 §6.3）。
 *
 * 列 = 周（`weeks` 列，默认 12），行 = 周内 7 天；格子 rx 3.5；
 * 按 value（听写次数）分 5 档明度（lemon 100→500，0 = 奶油灰）。
 * 移动端由父级 `overflow-x-auto` 横向滚动，不缩格。
 */
import { computed } from 'vue'
import { CHART } from './theme'

interface Props {
  data: { date: string; value: number }[]
  weeks?: number
  cell?: number
  colors?: string[]
}

const props = withDefaults(defineProps<Props>(), {
  weeks: 12,
  cell: CHART.cellSize,
  colors: () => [
    'var(--cream-2)',
    'var(--lemon-100)',
    'var(--lemon-200)',
    'var(--lemon-300)',
    'var(--lemon-400)',
  ],
})

const byDate = computed(() => {
  const map = new Map<string, number>()
  for (const d of props.data) map.set(d.date, d.value)
  return map
})

/** 从今天向前 `weeks*7` 天的日期序列（本地日，YYYY-MM-DD），旧 → 新。 */
const days = computed<string[]>(() => {
  const out: string[] = []
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const start = new Date(today)
  start.setDate(start.getDate() - (props.weeks * 7 - 1))
  for (let i = 0; i < props.weeks * 7; i += 1) {
    const d = new Date(start)
    d.setDate(start.getDate() + i)
    out.push(d.toISOString().slice(0, 10))
  }
  return out
})

const grid = computed(() => {
  // 列优先：columns = weeks，每列 7 天（行）。index = col*7 + row
  const rows: { col: number; row: number; date: string; tier: number }[] = []
  for (let col = 0; col < props.weeks; col += 1) {
    for (let row = 0; row < 7; row += 1) {
      const date = days.value[col * 7 + row]
      const v = byDate.value.get(date) ?? 0
      const tier = v <= 0 ? 0 : v === 1 ? 1 : v === 2 ? 2 : v === 3 ? 3 : 4
      rows.push({ col, row, date, tier })
    }
  }
  return rows
})

const width = computed(() => props.weeks * (props.cell + CHART.cellGap) + 4)
const height = computed(() => 7 * (props.cell + CHART.cellGap) + 4)

function titleOf(cell: { date: string; tier: number }): string {
  const v = byDate.value.get(cell.date) ?? 0
  return `${cell.date} · 听写 ${v} 次`
}
</script>

<template>
  <svg
    :viewBox="`0 0 ${width} ${height}`"
    :style="{ minWidth: `${width}px` }"
    class="block w-full"
    role="img"
    aria-label="近 12 周听写热力图"
  >
    <rect
      v-for="c in grid"
      :key="`${c.col}-${c.row}`"
      :x="2 + c.col * (cell + CHART.cellGap)"
      :y="2 + c.row * (cell + CHART.cellGap)"
      :width="cell"
      :height="cell"
      :rx="3.5"
      :fill="colors[c.tier]"
    >
      <title>{{ titleOf(c) }}</title>
    </rect>
  </svg>
</template>

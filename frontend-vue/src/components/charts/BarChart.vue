<script setup lang="ts">
/**
 * 每日听写量柱状图（P2 · 契约 §6.3）。
 *
 * 柱宽 22 / 圆角 6，柱顶标数值，x 轴隔日标注；全 0 时渲染空态卡（`emptyText`）。
 * 移动端由父级 `overflow-x-auto` 横向滚动，本组件不缩格（SVG 按真实宽度铺开）。
 */
import { computed } from 'vue'
import { CHART } from './theme'

interface Props {
  data: { label: string; value: number }[]
  height?: number
  color?: string
  emptyText?: string
}

const props = withDefaults(defineProps<Props>(), {
  height: 180,
  color: 'var(--lemon-400)',
  emptyText: '先去媒体库上传一段音频',
})

const GAP = 8
const LABEL_BAND = 20 // 底部日期标签 + 顶部数值标签各留的空间

const layout = computed(() => {
  const width = props.data.length * (CHART.barWidth + GAP) + GAP
  const max = Math.max(1, ...props.data.map((d) => d.value))
  const plotH = props.height - LABEL_BAND * 2
  return { width, max, plotH }
})

const allZero = computed(() => props.data.every((d) => d.value === 0))

function barY(value: number): number {
  const h = (value / layout.value.max) * layout.value.plotH
  return LABEL_BAND + layout.value.plotH - h
}

function barHeight(value: number): number {
  return (value / layout.value.max) * layout.value.plotH
}
</script>

<template>
  <div v-if="allZero" class="flex h-[180px] flex-col items-center justify-center gap-2 text-center">
    <p class="text-[13px] text-ink-3">{{ emptyText }}</p>
  </div>
  <svg
    v-else
    :viewBox="`0 0 ${layout.width} ${height}`"
    :style="{ minWidth: `${layout.width}px` }"
    class="block w-full"
    role="img"
    aria-label="每日听写柱状图"
  >
    <g v-for="(d, i) in data" :key="d.label">
      <rect
        :x="GAP + i * (CHART.barWidth + GAP)"
        :y="barY(d.value)"
        :width="CHART.barWidth"
        :height="Math.max(barHeight(d.value), 2)"
        :rx="CHART.barRadius"
        :fill="color"
      />
      <text
        v-if="d.value > 0"
        :x="GAP + i * (CHART.barWidth + GAP) + CHART.barWidth / 2"
        :y="barY(d.value) - 4"
        text-anchor="middle"
        class="fill-ink"
        font-size="9"
        font-weight="700"
      >
        {{ d.value }}
      </text>
      <text
        v-if="i % 2 === 0"
        :x="GAP + i * (CHART.barWidth + GAP) + CHART.barWidth / 2"
        :y="height - 4"
        text-anchor="middle"
        class="fill-ink-3"
        font-size="8.5"
      >
        {{ d.label }}
      </text>
    </g>
  </svg>
</template>

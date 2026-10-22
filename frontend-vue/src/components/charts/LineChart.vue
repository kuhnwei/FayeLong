<script setup lang="ts">
/**
 * 正确率折线图（P2 · 契约 §6.3）。
 *
 * value 取值 0–1；3px 圆头折线；`target`（默认 80%）画 `--peach` 虚线；
 * 0 值日贴底（休息日，不造假）。移动端父级横向滚动，不缩格。
 */
import { computed } from 'vue'
import { CHART } from './theme'

interface Props {
  points: { label: string; value: number }[]
  target?: number
  height?: number
  color?: string
  targetColor?: string
}

const props = withDefaults(defineProps<Props>(), {
  target: 0.8,
  height: 180,
  color: 'var(--leaf)',
  targetColor: 'var(--peach)',
})

const STEP = 40
const PAD = 14

const layout = computed(() => {
  const width = props.points.length * STEP
  return { width }
})

const allZero = computed(() => props.points.every((p) => p.value === 0))

function x(i: number): number {
  return PAD + i * STEP
}

function y(v: number): number {
  const clamped = Math.max(0, Math.min(1, v))
  return PAD + (1 - clamped) * (props.height - PAD * 2)
}

const path = computed(() =>
  props.points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${x(i)} ${y(p.value)}`).join(' '),
)

const targetY = computed(() => y(props.target))
</script>

<template>
  <svg
    :viewBox="`0 0 ${layout.width + PAD} ${height}`"
    :style="{ minWidth: `${layout.width + PAD}px` }"
    class="block w-full"
    role="img"
    aria-label="正确率趋势折线图"
  >
    <!-- 80% 目标虚线 -->
    <line
      v-if="!allZero"
      :x1="PAD"
      :x2="layout.width"
      :y1="targetY"
      :y2="targetY"
      :stroke="targetColor"
      stroke-width="1.5"
      stroke-dasharray="4 4"
    />
    <text :x="2" :y="targetY - 3" class="fill-ink-3" font-size="8.5">目标 {{ Math.round(target * 100) }}%</text>

    <path
      :d="path"
      fill="none"
      :stroke="color"
      :stroke-width="CHART.lineWidth"
      stroke-linecap="round"
      stroke-linejoin="round"
    />
    <g v-for="(p, i) in points" :key="p.label">
      <circle :cx="x(i)" :cy="y(p.value)" :r="p.value > 0 ? 3 : 0" :fill="color" />
      <text
        v-if="i % 2 === 0"
        :x="x(i)"
        :y="height - 3"
        text-anchor="middle"
        class="fill-ink-3"
        font-size="8.5"
      >
        {{ p.label }}
      </text>
    </g>
  </svg>
</template>

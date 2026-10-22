<script setup lang="ts">
/**
 * 生词构成环形图（P2 · 契约 §6.3）。
 *
 * 第一版两态（已掌握/未掌握）。空库（total=0）渲染**单灰环**；中心显示总数。
 * 纯 SVG（circle stroke-dasharray 扇形），零第三方库。
 */
import { computed } from 'vue'

interface Props {
  segments: { label: string; value: number; color: string }[]
  size?: number
  thickness?: number
}

const props = withDefaults(defineProps<Props>(), {
  size: 140,
  thickness: 16,
})

const total = computed(() => props.segments.reduce((n, s) => n + s.value, 0))
const radius = computed(() => (props.size - props.thickness) / 2)
const circumference = computed(() => 2 * Math.PI * radius.value)

/** 每段 {offset, len, ...seg}，len 为 dasharray 长度。 */
const arcs = computed(() => {
  if (total.value === 0) {
    return [
      {
        label: '暂无生词',
        color: 'var(--cream-2)',
        len: circumference.value,
        offset: 0,
      },
    ]
  }
  let acc = 0
  return props.segments.map((s) => {
    const len = (s.value / total.value) * circumference.value
    const arc = { ...s, len, offset: acc }
    acc += len
    return arc
  })
})
</script>

<template>
  <div class="flex items-center justify-center gap-4">
    <svg :width="size" :height="size" :viewBox="`0 0 ${size} ${size}`" role="img" aria-label="生词构成环形图">
      <circle
        v-for="a in arcs"
        :key="a.label"
        :cx="size / 2"
        :cy="size / 2"
        :r="radius"
        fill="none"
        :stroke="a.color"
        :stroke-width="thickness"
        :stroke-dasharray="`${a.len} ${circumference - a.len}`"
        :stroke-dashoffset="-a.offset"
        :transform="`rotate(-90 ${size / 2} ${size / 2})`"
      />
      <text
        :x="size / 2"
        :y="size / 2"
        text-anchor="middle"
        dominant-baseline="central"
        class="fill-ink"
        font-size="22"
        font-weight="800"
      >
        {{ total }}
      </text>
    </svg>
    <ul class="space-y-1.5">
      <li v-for="s in segments" :key="s.label" class="flex items-center gap-2 text-[12px] text-ink-2">
        <span class="h-3 w-3 rounded-[3px]" :style="{ backgroundColor: s.color }" />
        <span>{{ s.label }}</span>
        <span class="tabular-nums font-bold text-ink">{{ s.value }}</span>
      </li>
      <li v-if="total === 0" class="text-[12px] text-ink-3">还没有生词数据</li>
    </ul>
  </div>
</template>

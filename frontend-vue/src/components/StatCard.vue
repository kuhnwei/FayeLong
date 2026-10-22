<script setup lang="ts">
/** 学习概览卡片（M5）。 */
interface Props {
  label: string
  value: number
  sub?: string
}
defineProps<Props>()
</script>

<template>
  <div class="rounded-xl border border-ink bg-white px-4 py-3">
    <p class="text-[11px] text-ink-3">{{ label }}</p>
    <p class="mt-0.5 text-[20px] font-medium tabular-nums leading-tight text-ink">
      {{ value }}
    </p>
    <p v-if="sub" class="mt-0.5 text-[11px] text-ink-3">{{ sub }}</p>
  </div>
</template>

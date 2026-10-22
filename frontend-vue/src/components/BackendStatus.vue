<script setup lang="ts">
/**
 * 后端状态胶囊（照搬旧 `Layout.tsx::BackendStatus`）。
 * 窄屏放不下，md 以下隐藏（信息仍可在媒体库「环境自检」里看到）。
 */
import { computed } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import { getHealth } from '../api/client'

const { data, isLoading, isError } = useQuery({
  queryKey: ['health'],
  queryFn: getHealth,
})

const dot = computed(() => {
  if (isLoading.value) return 'bg-amber-400'
  if (isError.value) return 'bg-red-500'
  if (data.value) return 'bg-green-500'
  return 'bg-slate-300'
})

const text = computed(() => {
  if (isLoading.value) return '检查后端…'
  if (isError.value) return '后端未连接'
  if (data.value) return `后端正常 · 模型 ${data.value.config.whisper_model}`
  return '检查后端…'
})
</script>

<template>
  <div
    class="hidden items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1.5 md:flex"
  >
    <span class="h-2 w-2 rounded-full" :class="dot" />
    <span class="text-xs text-slate-600">{{ text }}</span>
  </div>
</template>

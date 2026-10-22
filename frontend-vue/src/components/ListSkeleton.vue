<script setup lang="ts">
/** 列表加载骨架屏（M5：替代干巴巴的「加载中…」）。 */
</script>

<template>
  <div class="space-y-3 px-3 py-4 sm:px-5 sm:py-5">
    <div v-for="i in 3" :key="i" class="flex animate-pulse items-center gap-4">
      <div class="h-9 w-9 shrink-0 rounded-full bg-cream-2" />
      <div class="flex-1 space-y-2">
        <div class="h-3.5 w-1/3 rounded bg-cream-2" />
        <div class="h-3 w-2/3 rounded bg-cream-2" />
      </div>
    </div>
  </div>
</template>

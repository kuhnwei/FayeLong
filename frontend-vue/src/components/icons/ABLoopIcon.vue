<script setup lang="ts">
const props = withDefaults(defineProps<{ className?: string }>(), {
  className: 'h-4 w-4',
})
</script>

<template>
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" :class="props.className" aria-hidden="true">
    <path d="M6 6v12M18 6v12" />
    <path d="M6 12h12" />
    <path d="M8.5 9 6 6 3.5 9" />
    <path d="M15.5 15 18 18l2.5-3" />
  </svg>
</template>

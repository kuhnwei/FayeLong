<script setup lang="ts">
const props = withDefaults(defineProps<{ className?: string }>(), {
  className: 'h-4 w-4',
})
</script>

<template>
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" :class="props.className" aria-hidden="true">
    <path d="M20.6 13.4 13.4 20.6a2 2 0 0 1-2.8 0l-7.2-7.2A2 2 0 0 1 2.8 12V4.8a2 2 0 0 1 2-2H12a2 2 0 0 1 1.4.6l7.2 7.2a2 2 0 0 1 0 2.8Z" />
    <path d="M7.5 7.5h.01" />
  </svg>
</template>

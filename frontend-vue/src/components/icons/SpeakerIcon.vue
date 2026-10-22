<script setup lang="ts">
const props = withDefaults(defineProps<{ className?: string }>(), {
  className: 'h-4 w-4',
})
</script>

<template>
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" :class="props.className" aria-hidden="true">
    <path d="M4 9.5h3L11 6v12l-4-3.5H4a1 1 0 0 1-1-1v-3a1 1 0 0 1 1-1Z" />
    <path d="M15 9.5a3.5 3.5 0 0 1 0 5" />
    <path d="M17.8 6.8a7.5 7.5 0 0 1 0 10.4" />
  </svg>
</template>

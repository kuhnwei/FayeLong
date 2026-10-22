<script setup lang="ts">
const props = withDefaults(defineProps<{ className?: string }>(), {
  className: 'h-4 w-4',
})
</script>

<template>
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" :class="props.className" aria-hidden="true">
    <path d="M4 20h16" />
    <path d="M9.2 16.6 4.6 20l1.1-4.4 8.2-8.2a2.1 2.1 0 0 1 3 3L9.2 16.6Z" />
    <path d="M14.4 6.8 17.4 9.8" />
  </svg>
</template>

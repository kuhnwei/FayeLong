<script setup lang="ts">
const props = withDefaults(defineProps<{ className?: string }>(), {
  className: 'h-4 w-4',
})
</script>

<template>
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" :class="props.className" aria-hidden="true">
    <path d="M3 7h3.5l3 3M21 7h-4.5l-8 10H3" />
    <path d="M17 4l4 3-4 3" />
    <path d="M17 14l4 3-4 3" />
  </svg>
</template>

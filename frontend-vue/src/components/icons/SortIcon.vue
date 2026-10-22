<script setup lang="ts">
const props = withDefaults(defineProps<{ className?: string }>(), {
  className: 'h-4 w-4',
})
</script>

<template>
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" :class="props.className" aria-hidden="true">
    <path d="M7 4v16M7 20l-3-3M7 4l3 3" />
    <path d="M17 20V4M17 4l3 3M17 20l-3-3" />
  </svg>
</template>

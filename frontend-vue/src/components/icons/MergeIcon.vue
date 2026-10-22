<script setup lang="ts">
const props = withDefaults(defineProps<{ className?: string }>(), {
  className: 'h-4 w-4',
})
</script>

<template>
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" :class="props.className" aria-hidden="true">
    <path d="M6 3v4l6 6 6-6V3" />
    <path d="M12 13v6" />
    <path d="M9 16.5 12 19.5l3-3" />
  </svg>
</template>

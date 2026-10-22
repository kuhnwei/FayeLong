<script setup lang="ts">
const props = withDefaults(defineProps<{ className?: string }>(), {
  className: 'h-4 w-4',
})
</script>

<template>
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" :class="props.className" aria-hidden="true">
    <path d="M4 5h9M8.5 3v2M10.5 5c0 4-2.5 7-6.5 8" />
    <path d="M11 19l4-9 4 9M12.5 16h5" />
  </svg>
</template>

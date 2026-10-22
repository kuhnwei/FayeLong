<script setup lang="ts">
const props = withDefaults(defineProps<{ className?: string }>(), {
  className: 'h-4 w-4',
})
</script>

<template>
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" :class="props.className" aria-hidden="true">
    <path d="M7 4h10v5a5 5 0 0 1-10 0Z" />
    <path d="M7 5H5a2 2 0 0 0 2 4M17 5h2a2 2 0 0 1-2 4" />
    <path d="M12 14v3M9 20h6M10 17h4" />
  </svg>
</template>

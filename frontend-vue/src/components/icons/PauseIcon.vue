<script setup lang="ts">
const props = withDefaults(defineProps<{ className?: string }>(), {
  className: 'h-4 w-4',
})
</script>

<template>
  <svg viewBox="0 0 24 24" fill="currentColor" :class="props.className" aria-hidden="true">
    <path d="M7 4h3.5v16H7zM13.5 4H17v16h-3.5z" />
  </svg>
</template>

<script setup lang="ts">
const props = withDefaults(defineProps<{ className?: string }>(), {
  className: 'h-4 w-4',
})
</script>

<template>
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" :class="props.className" aria-hidden="true">
    <path d="M12 5v14M5 12h14" />
  </svg>
</template>

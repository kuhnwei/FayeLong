<script setup lang="ts">
const props = withDefaults(defineProps<{ className?: string }>(), {
  className: 'h-4 w-4',
})
</script>

<template>
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" :class="props.className" aria-hidden="true">
    <path d="M3 12a9 9 0 1 0 2.6-6.4" />
    <path d="M3 4v5h5" />
    <path d="M12 8v4.5l3 1.8" />
  </svg>
</template>

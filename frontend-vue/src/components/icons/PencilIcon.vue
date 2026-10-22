<script setup lang="ts">
const props = withDefaults(defineProps<{ className?: string }>(), {
  className: 'h-4 w-4',
})
</script>

<template>
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" :class="props.className" aria-hidden="true">
    <path d="M4 20h4l10-10a2.12 2.12 0 0 0-3-3L5 17v3Z" />
    <path d="M14.5 6.5l3 3" />
  </svg>
</template>

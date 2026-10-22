<script setup lang="ts">
/**
 * 练习设置项的一行（照搬旧 `VocabPracticePage.tsx` 内联的 `Field`）：
 * 左侧固定宽度的标签 + 右侧可折行的选项区。
 */
interface Props {
  label: string
}

defineProps<Props>()
</script>

<template>
  <div class="flex flex-wrap items-start gap-x-4 gap-y-2">
    <span class="w-[64px] shrink-0 pt-2 text-[12px] text-ink-2">{{ label }}</span>
    <div class="flex flex-1 flex-wrap gap-2">
      <slot />
    </div>
  </div>
</template>

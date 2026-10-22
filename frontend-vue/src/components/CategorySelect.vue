<script setup lang="ts">
/**
 * 通用的「导入到分类」选择器（照搬旧 `CategoryChips.tsx` 的具名导出 `CategorySelect`）。
 *
 * 用原生 `<select>`：移动端触摸友好、零额外依赖、键盘可操作。
 * 值用字符串（'' = 未分类），调用方负责转成 `number | null`。
 */
import type { CategoryItem } from '../api/client'

interface Props {
  items: CategoryItem[]
  label?: string
}
defineProps<Props>()

// '' = 未分类；数字串 = 分类 id
const value = defineModel<string>({ required: true })

function onChange(event: Event) {
  value.value = (event.target as HTMLSelectElement).value
}
</script>

<template>
  <label class="flex items-center gap-1.5">
    <span v-if="label" class="shrink-0 text-[12px] text-slate-500">{{ label }}</span>
    <select
      :value="value"
      :aria-label="label ?? '选择分类'"
      class="h-8 max-w-[10rem] rounded-lg border border-slate-200 bg-white px-2 text-[12px] text-slate-700 outline-none transition-colors focus:border-slate-400"
      @change="onChange"
    >
      <option value="">未分类</option>
      <option v-for="c in items" :key="c.id" :value="String(c.id)">{{ c.name }}</option>
    </select>
  </label>
</template>

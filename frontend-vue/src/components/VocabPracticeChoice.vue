<script setup lang="ts">
/**
 * 练习设置里的单个可选项（照搬旧 `VocabPracticePage.tsx` 内联的 `Choice`）。
 *
 * ⚠️ 选中态的 class 必须原样保留 `bg-slate-900`：
 * `scripts/verify_vocab_practice.mjs` 用 `modeBtn.className.includes('bg-slate-900')`
 * 判断「练习方式是否被选中」。
 */
interface Props {
  active: boolean
  disabled?: boolean
  title: string
  desc: string
}

withDefaults(defineProps<Props>(), { disabled: false })

const emit = defineEmits<{ (e: 'select'): void }>()
</script>

<template>
  <button
    type="button"
    :disabled="disabled"
    :class="[
      'min-w-[104px] rounded-lg border px-3 py-2 text-left transition-colors',
      disabled
        ? 'cursor-not-allowed border-slate-100 bg-slate-50 opacity-60'
        : active
          ? 'border-slate-900 bg-slate-900 text-white'
          : 'border-slate-200 text-slate-700 hover:border-slate-400 hover:bg-slate-50',
    ]"
    @click="emit('select')"
  >
    <span class="block text-[12px]">{{ title }}</span>
    <span
      :class="`mt-0.5 block text-[10px] ${active && !disabled ? 'text-slate-300' : 'text-slate-400'}`"
    >
      {{ desc }}
    </span>
  </button>
</template>

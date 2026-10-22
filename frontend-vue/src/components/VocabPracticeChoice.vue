<script setup lang="ts">
/**
 * 练习设置里的单个可选项（照搬旧 `VocabPracticePage.tsx` 内联的 `Choice`）。
 *
 * ⚠️ 选中态用语义锚点 `data-selected="true"` 暴露：
 * `scripts/verify_vocab_practice.mjs` 优先读 `modeBtn.dataset.selected === 'true'`，
 * 换皮后旧配色类 `bg-slate-900` 已不在，fallback 自然失效 —— 所以这里必须带上 data-selected。
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
    :data-selected="active ? 'true' : 'false'"
    :class="[
      'min-w-[104px] rounded-control border px-3 py-2 text-left transition-colors',
      disabled
        ? 'cursor-not-allowed border-cream-2 bg-cream opacity-60'
        : active
          ? 'border-ink bg-lemon-400 text-ink'
          : 'border-ink text-ink hover:border-ink-3 hover:bg-lemon-100',
    ]"
    @click="emit('select')"
  >
    <span class="block text-[12px]">{{ title }}</span>
    <span
      :class="`mt-0.5 block text-[10px] ${active && !disabled ? 'text-ink-2' : 'text-ink-3'}`"
    >
      {{ desc }}
    </span>
  </button>
</template>

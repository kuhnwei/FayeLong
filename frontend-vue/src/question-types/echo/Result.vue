<script setup lang="ts">
/**
 * `echo` 占位题型的**结果渲染**组件（G4-① 预演，仅演示用）。
 *
 * 后端 `echo` 题型的 `GradeResult.detail` 形如 `{"echo": "...", "answer_keys": [...]}`，
 * 这里把它原样显示并标注「永远满分」。
 */

const props = withDefaults(
  defineProps<{ result: { echo?: string | null; accuracy?: number | null }; compact?: boolean }>(),
  { compact: false },
)
</script>

<template>
  <div :class="props.compact ? 'mt-1.5' : 'mt-2.5'">
    <div class="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px]">
      <span class="font-medium tabular-nums text-emerald-600">满分</span>
      <span class="text-slate-400">（占位题型：不做任何判分）</span>
    </div>
    <p class="mt-2 whitespace-pre-wrap break-words text-[15px] leading-relaxed text-slate-700">
      {{ result.echo || '（没有回显内容）' }}
    </p>
  </div>
</template>

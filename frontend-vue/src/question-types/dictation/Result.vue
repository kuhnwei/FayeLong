<script setup lang="ts">
/** `dictation` 题型的**结果渲染**组件（原 `components/DiffResult.vue`，DOM 逐字搬迁）。
 *
 * 听写校验结果展示（FR-S3，四类标记见设计文档 §9.3）。
 *
 * 渲染规则：
 * - `correct` 正常色
 * - `wrong`   显示用户实际写的词（标红 + 波浪下划线），悬停看正确形式
 * - `missing` 显示标准答案里被漏掉的词（红色虚线下划线）
 * - `extra`   显示用户多写的词（灰色删除线）
 *
 * ⚠️ **P4-2 搬迁纪律**：本文件是原 `components/DiffResult.vue` 的**逐字搬迁**，
 * 只有 import 相对路径因目录下移一层而调整（`../types/diff` → `../../types/diff`）。
 * `verify_m4` / `verify_mobile` / `verify_vocab_practice` 等验收脚本靠 DOM 与
 * className 定位，**template 里一个字符都不许改**。
 */
import { computed } from 'vue'
import type { DiffToken } from '../../types/diff'
import type { DiffResultData } from '../../types/diff'

const props = withDefaults(defineProps<{ result: DiffResultData; compact?: boolean }>(), {
  compact: false,
})

const TOKEN_CLASS: Record<DiffToken['type'], string> = {
  correct: 'text-slate-800',
  wrong: 'text-red-600 underline decoration-red-400 decoration-wavy decoration-1 underline-offset-4',
  missing: 'text-red-500 underline decoration-red-300 decoration-dashed decoration-1 underline-offset-4',
  extra: 'text-slate-400 line-through',
}

function tokenText(token: DiffToken): string {
  if (token.type === 'correct') return token.expected ?? ''
  if (token.type === 'wrong') return token.actual ?? ''
  if (token.type === 'missing') return token.expected ?? ''
  return token.actual ?? ''
}

function tokenTitle(token: DiffToken): string {
  if (token.type === 'wrong') return `拼写/用词有误，应为：${token.expected ?? ''}`
  if (token.type === 'missing') return `漏掉了：${token.expected ?? ''}`
  if (token.type === 'extra') return '多写了这个词'
  return token.expected ?? ''
}

const perfect = computed(
  () => props.result.wrong === 0 && props.result.missing === 0 && props.result.extra === 0,
)
// schema 里 tokens 是可选 → 这里兜底空数组（空数组会落到「没有可对比的内容」分支）
const tokens = computed(() => props.result.tokens ?? [])
const corrections = computed(() => tokens.value.filter((t) => t.type !== 'correct'))
const accuracyClass = computed(() =>
  props.result.is_correct
    ? 'text-emerald-600'
    : props.result.accuracy >= 80
      ? 'text-amber-600'
      : 'text-red-600',
)
</script>

<template>
  <div :class="props.compact ? 'mt-1.5' : 'mt-2.5'">
    <div class="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px]">
      <span :class="`font-medium tabular-nums ${accuracyClass}`">
        正确率 {{ result.accuracy }}%
      </span>
      <span class="text-slate-400 tabular-nums">
        正确 {{ result.correct }}/{{ result.total_words }}<template v-if="result.wrong > 0"> · 错 {{ result.wrong }}</template><template v-if="result.missing > 0"> · 漏 {{ result.missing }}</template><template v-if="result.extra > 0"> · 多 {{ result.extra }}</template>
      </span>
      <span
        v-if="perfect"
        class="rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] text-emerald-600"
      >
        完全正确
      </span>
    </div>

    <p
      v-if="tokens.length > 0"
      class="mt-2 flex flex-wrap gap-x-1.5 gap-y-1.5 text-[15px] leading-relaxed sm:text-lg"
    >
      <span
        v-for="(token, index) in tokens"
        :key="`${token.type}-${index}`"
        :class="TOKEN_CLASS[token.type]"
        :title="tokenTitle(token)"
      >
        {{ tokenText(token) }}
      </span>
    </p>
    <p v-else class="mt-2 text-[13px] text-slate-400">（没有可对比的内容）</p>

    <div v-if="corrections.length > 0" class="mt-2 flex flex-wrap items-center gap-1.5">
      <span class="text-[11px] text-slate-400">纠错</span>
      <span
        v-for="(token, index) in corrections"
        :key="`fix-${index}`"
        class="rounded bg-red-50 px-1.5 py-0.5 text-[11px] text-red-600"
      >
        <template v-if="token.type === 'extra'">多余「{{ token.actual }}」</template>
        <template v-else-if="token.type === 'missing'">漏「{{ token.expected }}」</template>
        <template v-else>{{ token.actual }} → <span class="font-medium">{{ token.expected }}</span></template>
      </span>
    </div>
  </div>
</template>

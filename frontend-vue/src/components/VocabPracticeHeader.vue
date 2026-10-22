<script setup lang="ts">
/**
 * 生词练习页顶部条（照搬旧 `VocabPracticePage.tsx` 内联的 `PageHeader`）。
 *
 * 旧版签名是 `onBack: (() => void) | null`：为 null 时渲染「返回生词本」链接，
 * 否则渲染「退出练习」按钮。Vue 里用 `canBack` + `back` 事件表达同一语义
 * （不要用 `onBack` 当 prop 名 —— 会和事件监听器透传混淆）。
 */
import { RouterLink } from 'vue-router'
import { BackIcon } from './icons'

interface Props {
  /** 是否处于可退出状态（答题 / 结果页 true；设置页与空态 false） */
  canBack: boolean
}

defineProps<Props>()

const emit = defineEmits<{ (e: 'back'): void }>()
</script>

<template>
  <div class="flex flex-wrap items-start justify-between gap-3">
    <div>
      <h2 class="text-[15px] font-medium text-slate-900">生词练习</h2>
      <p class="mt-1 text-[13px] text-slate-500">
        用生词本里的词做中译英 / 英译中 / 听写练习，答错的词会单独列出来。
      </p>
    </div>
    <button
      v-if="canBack"
      type="button"
      class="flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-2 text-[12px] text-slate-600 transition-colors hover:bg-slate-50"
      @click="emit('back')"
    >
      <BackIcon class-name="h-3.5 w-3.5" />
      退出练习
    </button>
    <RouterLink
      v-else
      to="/vocab"
      class="flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-2 text-[12px] text-slate-600 transition-colors hover:bg-slate-50"
    >
      <BackIcon class-name="h-3.5 w-3.5" />
      返回生词本
    </RouterLink>
  </div>
</template>

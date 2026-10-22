<script setup lang="ts">
/**
 * 全局错误边界（M5 打磨）。
 *
 * 任何页面组件抛错都不会再让整站白屏：兜底显示可读信息 + 「重新加载」按钮。
 *
 * ⚠️ Vue 的坑：`onErrorCaptured` **只能捕获子孙组件**的错误，捕获不到本组件自身。
 * 所以这里必须是**独立组件**（包住内容），并用 `main.ts` 的 `app.config.errorHandler`
 * 再补一层全局网。返回 `false` 阻止错误继续向上冒泡。
 */
import { onErrorCaptured, ref } from 'vue'

const error = ref<Error | null>(null)

onErrorCaptured((err, _instance, info) => {
  console.error('[FayeLong] 页面渲染出错：', err, info)
  error.value = err instanceof Error ? err : new Error(String(err))
  // 阻止继续传播（否则会一路冒到 app.config.errorHandler，甚至控制台重复报错）
  return false
})

function reload() {
  window.location.reload()
}

function dismiss() {
  error.value = null
}
</script>

<template>
  <slot v-if="!error" />
  <div v-else class="mx-auto max-w-2xl px-6 py-16">
    <div class="rounded-xl border border-red-100 bg-red-50/60 p-6">
      <h2 class="text-[16px] font-medium text-red-700">页面出错了</h2>
      <p class="mt-2 text-[13px] leading-relaxed text-red-600">
        当前界面遇到一个未预期的问题，你的学习数据（音频、笔记、生词、听写记录）都保存在本地，
        不会因此丢失。
      </p>
      <pre class="mt-3 max-h-40 overflow-auto rounded-lg bg-white/70 px-3 py-2 text-[12px] text-slate-600">{{
        error.message || String(error)
      }}</pre>
      <div class="mt-4 flex items-center gap-2">
        <button
          type="button"
          class="rounded-lg bg-slate-900 px-3.5 py-2 text-[13px] text-white transition-colors hover:bg-slate-700"
          @click="reload"
        >
          重新加载页面
        </button>
        <button
          type="button"
          class="rounded-lg border border-slate-300 bg-white px-3.5 py-2 text-[13px] text-slate-600 transition-colors hover:bg-slate-50"
          @click="dismiss"
        >
          尝试忽略并继续
        </button>
      </div>
    </div>
  </div>
</template>

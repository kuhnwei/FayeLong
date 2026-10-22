<script setup lang="ts">
/**
 * `echo` 占位题型的**作答**组件（G4-① 「零改核心即可挂载」预演，仅演示用）。
 *
 * 它只做一件事：把用户输入原样交给父级草稿。判分永远满分（后端 `echo` 题型）。
 *
 * ⚠️ 本组件**默认不注册**（`index.ts` 不 import 它）。启用方式见 `./index.ts`。
 * 之所以把它单独放进 `echo/` 目录而不是删掉：它是「新增题型 = 加两个组件 + 一行
 * register」这条判据的可执行证据 —— 留在这里，下一次加真题型时照抄即可。
 */
import { computed, ref } from 'vue'
import type { Draft } from '../../types/study'

const props = defineProps<{
  disabled: boolean
  draft: Draft
  /** 更新草稿（与 dictation 的 `onDraft` 同签名，宿主才能一视同仁地挂载） */
  onDraft: (patch: Partial<Draft>) => void
}>()

const local = ref(props.draft.text)

const canSubmit = computed(() => !props.disabled && local.value.trim().length > 0)

function onInput(e: Event) {
  local.value = (e.target as HTMLTextAreaElement).value
  props.onDraft({ text: local.value })
}

function submit() {
  if (!canSubmit.value) return
  // 回显题型的「判分」只是把输入照抄进 detail，前端不需要额外请求。
  props.onDraft({ text: local.value.trim() })
}
</script>

<template>
  <div class="shrink-0 rounded-lg border border-dashed border-slate-300 bg-white p-3">
    <p class="text-[11px] text-slate-400">回显题型（演示）：输入什么，结果就显示什么。</p>
    <div class="mt-2 flex items-start gap-2">
      <textarea
        data-testid="echo-input"
        rows="3"
        :value="local"
        :disabled="disabled"
        placeholder="随便写点什么…（Enter 提交）"
        class="min-h-[88px] flex-1 resize-y rounded-lg border border-slate-300 bg-white px-3 py-3 text-[17px] leading-relaxed text-slate-800 outline-none transition-colors focus:border-slate-500 disabled:bg-slate-100"
        @input="onInput"
        @keydown.enter.prevent="submit"
      />
      <button
        type="button"
        :disabled="!canSubmit"
        class="rounded-lg bg-slate-900 px-4 py-2.5 text-[13px] text-white transition-colors hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-40"
        @click="submit"
      >
        回显
      </button>
    </div>
  </div>
</template>

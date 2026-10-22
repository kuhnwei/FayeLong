<script setup lang="ts">
/**
 * 右上角账号菜单。**逐项照搬**旧 `frontend/src/components/Layout.tsx::AccountMenu`：
 * 改密码弹窗 + 退出登录 + 点击别处收起。
 */
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { changePassword, getAuthStatus, logout } from '../api/client'

const queryClient = useQueryClient()
const open = ref(false)
const changing = ref(false)
const current = ref('')
const next = ref('')
const msg = ref<string | null>(null)
const boxRef = ref<HTMLElement | null>(null)

const { data } = useQuery({
  queryKey: ['auth', 'status'],
  queryFn: getAuthStatus,
  staleTime: 0,
})

const signOut = useMutation({
  mutationFn: logout,
  onSuccess: (status) => {
    queryClient.setQueryData(['auth', 'status'], status)
    // 换账号后不要把上一个人的学习数据留在缓存里
    queryClient.removeQueries({ predicate: (q) => q.queryKey[0] !== 'auth' })
  },
})

const savePassword = useMutation({
  mutationFn: () => changePassword(current.value, next.value),
  onSuccess: () => {
    current.value = ''
    next.value = ''
    changing.value = false
    msg.value = '密码已更新'
  },
  onError: (e) => {
    msg.value = (e as Error).message
  },
})

const minLen = computed(() => data.value?.min_password_length ?? 8)
const canSave = computed(
  () => current.value.length > 0 && next.value.length >= minLen.value && !savePassword.isPending.value,
)

/** 点击别处收起。 */
function onDown(event: MouseEvent) {
  if (boxRef.value && !boxRef.value.contains(event.target as Node)) open.value = false
}
onMounted(() => document.addEventListener('mousedown', onDown))
onUnmounted(() => document.removeEventListener('mousedown', onDown))

function startChanging() {
  changing.value = true
  msg.value = null
}

function cancelChanging() {
  changing.value = false
  current.value = ''
  next.value = ''
  msg.value = null
}

function save() {
  msg.value = null
  savePassword.mutate()
}
</script>

<template>
  <div ref="boxRef" class="relative">
    <button
      type="button"
      class="flex items-center gap-1 rounded-full border border-slate-200 bg-white px-2.5 py-1.5 text-xs text-slate-600 transition-colors hover:bg-slate-50 sm:gap-1.5 sm:px-3"
      @click="open = !open"
    >
      <span class="max-w-[6rem] truncate sm:max-w-[10rem]">{{ data?.username ?? '账号' }}</span>
      <span class="text-slate-400">▾</span>
    </button>

    <div
      v-if="open"
      class="absolute right-0 z-50 mt-2 w-64 rounded-xl border border-slate-200 bg-white p-3 shadow-lg"
    >
      <p
        v-if="msg"
        class="mb-2 rounded-lg bg-slate-50 px-2.5 py-1.5 text-[11px] text-slate-600"
      >
        {{ msg }}
      </p>

      <div v-if="changing" class="space-y-2">
        <input
          type="password"
          autocomplete="current-password"
          v-model="current"
          placeholder="当前密码"
          class="w-full rounded-lg border border-slate-300 px-2.5 py-1.5 text-[12px] outline-none focus:border-slate-500"
        />
        <input
          type="password"
          autocomplete="new-password"
          v-model="next"
          :placeholder="`新密码（至少 ${minLen} 位）`"
          class="w-full rounded-lg border border-slate-300 px-2.5 py-1.5 text-[12px] outline-none focus:border-slate-500"
        />
        <div class="flex gap-2">
          <button
            type="button"
            :disabled="!canSave"
            class="flex-1 rounded-lg bg-slate-900 px-3 py-1.5 text-[12px] text-white transition-colors hover:bg-slate-700 disabled:opacity-40"
            @click="save"
          >
            {{ savePassword.isPending.value ? '保存中…' : '保存' }}
          </button>
          <button
            type="button"
            class="rounded-lg border border-slate-200 px-3 py-1.5 text-[12px] text-slate-600 hover:bg-slate-50"
            @click="cancelChanging"
          >
            取消
          </button>
        </div>
      </div>

      <div v-else class="space-y-1">
        <button
          type="button"
          class="w-full rounded-lg px-2.5 py-2 text-left text-[12px] text-slate-600 transition-colors hover:bg-slate-50"
          @click="startChanging"
        >
          修改密码
        </button>
        <button
          type="button"
          class="w-full rounded-lg px-2.5 py-2 text-left text-[12px] text-slate-600 transition-colors hover:bg-slate-50"
          @click="signOut.mutate()"
        >
          退出登录
        </button>
      </div>
    </div>
  </div>
</template>

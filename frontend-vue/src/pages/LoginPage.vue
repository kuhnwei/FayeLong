<script setup lang="ts">
/**
 * 登录 / 首次初始化页（v1.12 单账号门禁）。**逐项照搬**旧 `frontend/src/pages/LoginPage.tsx`。
 *
 * 同一页承载两种形态：
 * - `needs_setup` 为真 → 初始化：设置第一个账号（服务端只允许建一次，建完即锁定）
 * - 否               → 登录
 *
 * 站点在公网，所以这里刻意**不给**「忘记密码」之类的自助入口 ——
 * 重置只能到服务器上直接改数据库，这是有意为之的收紧（重写时不要加回来）。
 */
import { computed, ref } from 'vue'
import { useMutation, useQueryClient } from '@tanstack/vue-query'
import { login, setupAccount, type AuthStatus } from '../api/client'

const props = defineProps<{ status: AuthStatus }>()

const queryClient = useQueryClient()
const setup = computed(() => props.status.needs_setup)
const minLen = computed(() => props.status.min_password_length)

const username = ref('')
const password = ref('')
const confirm = ref('')
const error = ref<string | null>(null)

const submit = useMutation({
  mutationFn: (vars: { username: string; password: string }) =>
    props.status.needs_setup
      ? setupAccount(vars.username, vars.password)
      : login(vars.username, vars.password),
  onSuccess: (data) => {
    password.value = ''
    confirm.value = ''
    error.value = null
    queryClient.setQueryData(['auth', 'status'], data)
    // 换账号后别把上一个人的学习数据留在缓存里
    queryClient.removeQueries({ predicate: (q) => q.queryKey[0] !== 'auth' })
  },
  onError: (e) => {
    error.value = (e as Error).message
  },
})

function onSubmit() {
  const name = username.value.trim()
  if (!name) {
    error.value = '请填写用户名'
    return
  }
  // 校验②③ 用的是**原始** password（不是 trim 后的 name），与原实现一致
  if (password.value.length < props.status.min_password_length) {
    error.value = `密码至少 ${props.status.min_password_length} 位`
    return
  }
  if (props.status.needs_setup && password.value !== confirm.value) {
    error.value = '两次输入的密码不一致'
    return
  }
  error.value = null
  submit.mutate({ username: name, password: password.value })
}

const inputClass =
  'w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-[14px] text-slate-800 outline-none transition-colors placeholder:text-slate-400 focus:border-slate-500'
</script>

<template>
  <div class="flex min-h-screen items-center justify-center bg-slate-50 px-6 py-10">
    <div class="w-full max-w-sm">
      <div class="mb-6 text-center">
        <h1 class="text-[20px] font-medium text-slate-900">FayeLong 英语学习</h1>
        <p class="mt-1.5 text-[13px] text-slate-500">
          {{ setup ? '首次使用，先设置账号' : '请输入账号密码继续' }}
        </p>
      </div>

      <form
        class="space-y-3 rounded-xl border border-slate-200 bg-white p-6"
        @submit.prevent="onSubmit"
      >
        <div>
          <label class="mb-1.5 block text-[12px] text-slate-500" for="username">用户名</label>
          <input
            id="username"
            name="username"
            autocomplete="username"
            autofocus
            v-model="username"
            placeholder="例如 faye"
            :class="inputClass"
          />
        </div>

        <div>
          <label class="mb-1.5 block text-[12px] text-slate-500" for="password">密码</label>
          <input
            id="password"
            name="password"
            type="password"
            :autocomplete="setup ? 'new-password' : 'current-password'"
            v-model="password"
            :placeholder="`至少 ${minLen} 位`"
            :class="inputClass"
          />
        </div>

        <div v-if="setup">
          <label class="mb-1.5 block text-[12px] text-slate-500" for="confirm">再输一次</label>
          <input
            id="confirm"
            name="confirm"
            type="password"
            autocomplete="new-password"
            v-model="confirm"
            placeholder="确认密码"
            :class="inputClass"
          />
        </div>

        <p v-if="error" class="rounded-lg bg-red-50 px-3 py-2 text-[12px] text-red-600">
          {{ error }}
        </p>

        <button
          type="submit"
          :disabled="submit.isPending.value"
          class="w-full rounded-lg bg-slate-900 px-4 py-2.5 text-[14px] text-white transition-colors hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {{ submit.isPending.value ? '处理中…' : setup ? '创建并进入' : '登录' }}
        </button>

        <p v-if="setup" class="text-[11px] leading-relaxed text-slate-400">
          这台服务在公网，请设置一个不容易被猜到的用户名与密码。
          账号只能创建一次；之后想改密码，可在右上角账号菜单里修改。
        </p>
      </form>

      <p class="mt-4 text-center text-[11px] text-slate-400">
        学习数据保存在你自己的服务器上，不上传任何第三方
      </p>
    </div>
  </div>
</template>

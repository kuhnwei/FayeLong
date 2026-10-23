<script setup lang="ts">
/**
 * 管理员「用户管理」页（v1.16.2）。
 *
 * 复用项目既有视觉风格（border-ink + lemon 色 + 卡片），表格壳照 VocabPage 的
 * 三态（加载 / 错误 / 空 / 列表）范式；新建/重置密码用 bottom-sheet 弹层。
 */
import { computed, ref } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import {
  createAdminUser,
  deleteAdminUser,
  listAdminUsers,
  resetAdminUserPassword,
  updateAdminUser,
  type AdminUserOut,
} from '../../api/client'

const queryClient = useQueryClient()

const { data, isLoading, isError, error } = useQuery({
  queryKey: ['admin', 'users'],
  queryFn: listAdminUsers,
})

const items = computed<AdminUserOut[]>(() => data.value?.items ?? [])
const errorText = computed(() => (error.value as Error)?.message ?? '加载失败')

// --------------------------- 新建用户弹层 ---------------------------
const showCreate = ref(false)
const createUsername = ref('')
const createPassword = ref('')
const createRole = ref<'user' | 'admin'>('user')
const formMsg = ref<string | null>(null)

// --------------------------- 重置密码弹层 ---------------------------
const resetting = ref<AdminUserOut | null>(null)
const resetPassword = ref('')
const resetMsg = ref<string | null>(null)

const invalidate = () => queryClient.invalidateQueries({ queryKey: ['admin', 'users'] })

const createMutation = useMutation({
  mutationFn: () =>
    createAdminUser({
      username: createUsername.value.trim(),
      password: createPassword.value,
      role: createRole.value,
    }),
  onSuccess: () => {
    showCreate.value = false
    createUsername.value = ''
    createPassword.value = ''
    createRole.value = 'user'
    formMsg.value = null
    invalidate()
  },
  onError: (e) => {
    formMsg.value = (e as Error).message
  },
})

const resetMutation = useMutation({
  mutationFn: () => resetAdminUserPassword(resetting.value!.id, resetPassword.value),
  onSuccess: () => {
    resetting.value = null
    resetPassword.value = ''
    resetMsg.value = null
  },
  onError: (e) => {
    resetMsg.value = (e as Error).message
  },
})

const toggleMutation = useMutation({
  mutationFn: (u: AdminUserOut) =>
    updateAdminUser(u.id, { is_active: !u.is_active }),
  onSuccess: invalidate,
  onError: (e) => alert((e as Error).message),
})

function onDelete(u: AdminUserOut) {
  if (!window.confirm(`确定要停用用户「${u.username}」吗？其学习数据将保留。`)) return
  deleteMutation.mutate(u)
}
const deleteMutation = useMutation({
  mutationFn: (u: AdminUserOut) => deleteAdminUser(u.id),
  onSuccess: invalidate,
  onError: (e) => alert((e as Error).message),
})

function openReset(u: AdminUserOut) {
  resetting.value = u
  resetPassword.value = ''
  resetMsg.value = null
}

const roleLabel = (role: string) => (role === 'admin' ? '管理员' : '普通用户')
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between gap-3">
      <div>
        <h2 class="text-[18px] font-extrabold text-ink">用户管理</h2>
        <p class="mt-0.5 text-[12px] text-ink-3">增删用户、重置密码、启停账号</p>
      </div>
      <button
        type="button"
        class="rounded-full border-2 border-ink bg-lemon-400 px-4 py-2 text-[13px] font-bold shadow-[0_3px_0_var(--ink)] transition-transform hover:-translate-y-px active:translate-y-[3px] active:shadow-none"
        @click="showCreate = true"
      >
        + 新建用户
      </button>
    </div>

    <p v-if="isLoading" class="rounded-2xl border-2 border-ink bg-white px-3 py-8 text-center text-[13px] text-ink-3">
      加载中…
    </p>
    <p v-else-if="isError" class="rounded-xl border border-red-100 bg-red-50 px-3 py-8 text-center text-[13px] text-red-600">
      {{ errorText }}
    </p>

    <div
      v-else
      class="overflow-hidden rounded-2xl border-2 border-ink bg-white"
    >
      <div
        class="hidden grid-cols-[minmax(0,1.2fr)_88px_70px_minmax(0,1.6fr)_120px] items-center gap-3 border-b-2 border-ink bg-cream-2 px-4 py-2 text-[11px] font-bold tracking-[0.4px] text-ink-3 sm:grid"
      >
        <span>用户名</span>
        <span>角色</span>
        <span class="text-center">状态</span>
        <span>学习概览</span>
        <span class="text-right">操作</span>
      </div>

      <div v-for="u in items" :key="u.id" class="border-b border-ink/10 px-4 py-3 last:border-b-0">
        <div class="flex flex-wrap items-center gap-2 sm:grid sm:grid-cols-[minmax(0,1.2fr)_88px_70px_minmax(0,1.6fr)_120px] sm:gap-3">
          <div class="min-w-0">
            <p class="truncate text-[13px] font-bold text-ink">{{ u.username }}</p>
            <p class="text-[11px] text-ink-3">最近登录：{{ u.last_login_at ?? '从未' }}</p>
          </div>
          <span
            class="rounded-full px-2 py-0.5 text-[11px] font-semibold"
            :class="u.role === 'admin' ? 'bg-amber-100 text-amber-700' : 'bg-slate-100 text-slate-600'"
          >
            {{ roleLabel(u.role) }}
          </span>
          <span
            class="rounded-full px-2 py-0.5 text-center text-[11px] font-semibold"
            :class="u.is_active ? 'bg-emerald-100 text-emerald-700' : 'bg-red-100 text-red-600'"
          >
            {{ u.is_active ? '正常' : '已停用' }}
          </span>
          <div class="text-[11px] text-ink-2">
            听写 {{ u.stats.attempts_total }} · 生词 {{ u.stats.vocab_total }} ·
            连续 {{ u.stats.streak_days }} 天
          </div>
          <div class="flex items-center justify-end gap-1.5">
            <button
              type="button"
              class="rounded-md border border-slate-200 px-2 py-1 text-[11px] text-slate-600 hover:bg-slate-50"
              @click="openReset(u)"
            >
              重置密码
            </button>
            <button
              type="button"
              class="rounded-md border border-slate-200 px-2 py-1 text-[11px] text-slate-600 hover:bg-slate-50"
              @click="toggleMutation.mutate(u)"
            >
              {{ u.is_active ? '停用' : '启用' }}
            </button>
            <button
              type="button"
              class="rounded-md border border-red-200 px-2 py-1 text-[11px] text-red-600 hover:bg-red-50"
              @click="onDelete(u)"
            >
              删除
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- 新建用户弹层 -->
    <div
      v-if="showCreate"
      class="fixed inset-0 z-50 flex items-end justify-center bg-slate-900/40 sm:items-center"
      @click.self="showCreate = false"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="新建用户"
        class="flex max-h-[85dvh] w-full flex-col rounded-t-2xl bg-white p-4 shadow-xl sm:max-w-md sm:rounded-2xl"
      >
        <h3 class="text-[15px] font-extrabold text-ink">新建用户</h3>
        <div class="mt-3 space-y-2.5">
          <input
            v-model="createUsername"
            placeholder="用户名"
            class="w-full rounded-lg border border-slate-300 px-3 py-2 text-[13px] outline-none focus:border-slate-500"
          />
          <input
            v-model="createPassword"
            type="password"
            placeholder="初始密码（至少 8 位）"
            class="w-full rounded-lg border border-slate-300 px-3 py-2 text-[13px] outline-none focus:border-slate-500"
          />
          <div class="flex gap-2">
            <button
              type="button"
              class="flex-1 rounded-lg border px-3 py-2 text-[12px] font-semibold"
              :class="createRole === 'user' ? 'border-ink bg-lemon-200 text-ink' : 'border-slate-200 text-slate-500'"
              @click="createRole = 'user'"
            >
              普通用户
            </button>
            <button
              type="button"
              class="flex-1 rounded-lg border px-3 py-2 text-[12px] font-semibold"
              :class="createRole === 'admin' ? 'border-ink bg-lemon-200 text-ink' : 'border-slate-200 text-slate-500'"
              @click="createRole = 'admin'"
            >
              管理员
            </button>
          </div>
          <p v-if="formMsg" class="text-[12px] text-red-600">{{ formMsg }}</p>
        </div>
        <div class="mt-4 flex gap-2">
          <button
            type="button"
            :disabled="!createUsername.trim() || !createPassword || createMutation.isPending.value"
            class="flex-1 rounded-lg bg-slate-900 px-3 py-2 text-[13px] text-white hover:bg-slate-700 disabled:opacity-40"
            @click="createMutation.mutate()"
          >
            {{ createMutation.isPending.value ? '创建中…' : '创建' }}
          </button>
          <button
            type="button"
            class="rounded-lg border border-slate-200 px-3 py-2 text-[13px] text-slate-600 hover:bg-slate-50"
            @click="showCreate = false"
          >
            取消
          </button>
        </div>
      </div>
    </div>

    <!-- 重置密码弹层 -->
    <div
      v-if="resetting"
      class="fixed inset-0 z-50 flex items-end justify-center bg-slate-900/40 sm:items-center"
      @click.self="resetting = null"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="重置密码"
        class="flex max-h-[85dvh] w-full flex-col rounded-t-2xl bg-white p-4 shadow-xl sm:max-w-md sm:rounded-2xl"
      >
        <h3 class="text-[15px] font-extrabold text-ink">重置「{{ resetting.username }}」的密码</h3>
        <input
          v-model="resetPassword"
          type="password"
          placeholder="新密码（至少 8 位）"
          class="mt-3 w-full rounded-lg border border-slate-300 px-3 py-2 text-[13px] outline-none focus:border-slate-500"
        />
        <p v-if="resetMsg" class="mt-2 text-[12px] text-red-600">{{ resetMsg }}</p>
        <div class="mt-4 flex gap-2">
          <button
            type="button"
            :disabled="resetPassword.length < 8 || resetMutation.isPending.value"
            class="flex-1 rounded-lg bg-slate-900 px-3 py-2 text-[13px] text-white hover:bg-slate-700 disabled:opacity-40"
            @click="resetMutation.mutate()"
          >
            {{ resetMutation.isPending.value ? '重置中…' : '重置' }}
          </button>
          <button
            type="button"
            class="rounded-lg border border-slate-200 px-3 py-2 text-[13px] text-slate-600 hover:bg-slate-50"
            @click="resetting = null"
          >
            取消
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

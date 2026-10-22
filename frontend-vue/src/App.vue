<script setup lang="ts">
/**
 * 应用根组件。
 *
 * 结构照搬旧 `frontend/src/App.tsx`：**登录不是路由**，而是这里的**状态门禁** ——
 * 未登录时整屏渲染 `<LoginPage/>`，不经过 Router；已登录才挂 `<Layout><RouterView/></Layout>`。
 *
 * 用 `ErrorBoundary` 包住整棵树（`onErrorCaptured` 只捕获子孙，故必须是独立组件），
 * 并在 `main.ts` 用 `app.config.errorHandler` 补一层全局网。
 */
import { computed, onMounted, onUnmounted } from 'vue'
import { RouterView } from 'vue-router'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { UNAUTHORIZED_EVENT, getAuthStatus } from './api/client'
import ErrorBoundary from './components/ErrorBoundary.vue'
import Layout from './components/Layout.vue'
import LoginPage from './pages/LoginPage.vue'

const queryClient = useQueryClient()

const { data, isError, error } = useQuery({
  queryKey: ['auth', 'status'],
  queryFn: getAuthStatus,
  retry: false,
  staleTime: 0,
})

// 任意接口返回 401（会话过期、服务端换过签名密钥）都回落登录页，
// 而不是让页面停在「什么都加载不出来」的状态。
function onUnauthorized() {
  void queryClient.invalidateQueries({ queryKey: ['auth', 'status'] })
}
onMounted(() => window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized))
onUnmounted(() => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized))

const splashText = computed(() => {
  if (isError.value) {
    const message = (error.value as Error | null)?.message ?? ''
    return `无法连接后端服务：${message}`
  }
  return '正在检查登录状态…'
})
</script>

<template>
  <ErrorBoundary>
    <div
      v-if="isError || !data"
      class="flex min-h-screen items-center justify-center bg-slate-50 px-6"
    >
      <p class="text-center text-[13px] text-slate-400">{{ splashText }}</p>
    </div>

    <LoginPage v-else-if="data && !data.authenticated" :status="data" />

    <Layout v-else>
      <RouterView />
    </Layout>
  </ErrorBoundary>
</template>

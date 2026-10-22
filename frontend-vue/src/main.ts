import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import App from './App.vue'
import router from './router'
import './index.css'

// queryClient 默认项照搬旧 React 的 main.tsx：
//   { queries: { retry: 1, refetchOnWindowFocus: false } }
const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
})

const app = createApp(App)

// 全局兜底：`ErrorBoundary` 只捕获子孙组件的错误，这里补一层网接住其余。
app.config.errorHandler = (err, _instance, info) => {
  console.error('[FayeLong] 未捕获的组件错误：', err, info)
}

app.use(createPinia()).use(router).use(VueQueryPlugin, { queryClient }).mount('#root')

// 说明：P2-B 时代曾有一个 DEV-only 播放器探针（`__fayePlayer` / `__fayeClip` +
// `src/dev/ClipHarness.vue`），用于在学习页尚未实现时驱动播放语义。
// 学习页（P2-D）已落地，按 `TODO(P2-D)` 约定已删除该空壳与探针块；
// `scripts/verify_vue_player.mjs` 现在直接驱动**真实学习页**。
// 仅存的 DEV 探针是 `window.__fayeApi`（见 src/api/client.ts，与播放无关）。

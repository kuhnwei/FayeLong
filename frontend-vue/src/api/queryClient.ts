/**
 * TanStack Query 的全局单例（从 `main.ts` 抽出，供 `router` 守卫等复用）。
 *
 * 抽出来的原因：`router/index.ts` 的 `beforeEach` 守卫需要读 `['auth','status']`
 * 缓存判断「是否管理员」，而 `main.ts` 里创建 queryClient 会让 router → main 形成
 * 循环依赖。放这里后 router 直接 import 本模块即可。
 */
import { QueryClient } from '@tanstack/vue-query'

export const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
})

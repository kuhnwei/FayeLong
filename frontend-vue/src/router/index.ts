import { createRouter, createWebHistory } from 'vue-router'
import MediaLibraryPage from '../pages/MediaLibraryPage.vue'
import StudyPage from '../pages/StudyPage.vue'
import VocabPage from '../pages/VocabPage.vue'
import VocabPracticePage from '../pages/VocabPracticePage.vue'
import StatsPage from '../pages/StatsPage.vue'
import { queryClient } from '../api/queryClient'
import { getAuthStatus } from '../api/client'
import type { AuthStatus } from '../api/client'

/**
 * 路由表照搬旧 `frontend/src/App.tsx` 的真实结构（4 条 + 管理 2 条 + `*` 兜底）。
 *
 * ⚠️ 计划 §P1-3 写的「5 条路由含 /login」是错的：旧版**登录不是路由**，
 * 而是 App 层的状态门禁（未登录时整屏渲染 `<LoginPage/>`，不经过 Router）。
 *
 * v1.16.2 新增 `/admin/*` 两条管理路由，靠 `meta.requiresAdmin` + `beforeEach`
 * 做角色拦截（真实安全边界在后端 `require_admin`，这里只做前端体验拦截）。
 */
const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'library', component: MediaLibraryPage },
    { path: '/study/:mediaId', name: 'study', component: StudyPage },
    { path: '/vocab', name: 'vocab', component: VocabPage },
    { path: '/vocab/practice', name: 'vocab-practice', component: VocabPracticePage },
    { path: '/stats', name: 'stats', component: StatsPage },
    {
      path: '/admin/users',
      name: 'admin-users',
      component: () => import('../pages/admin/UsersPage.vue'),
      meta: { requiresAdmin: true },
    },
    {
      path: '/admin/stats',
      name: 'admin-stats',
      component: () => import('../pages/admin/ComparePage.vue'),
      meta: { requiresAdmin: true },
    },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

router.beforeEach(async (to) => {
  if (!to.meta.requiresAdmin) return true
  try {
    const status = await queryClient.ensureQueryData<AuthStatus>({
      queryKey: ['auth', 'status'],
      queryFn: getAuthStatus,
      staleTime: 0,
    })
    // 未登录交给 App 门禁处理（这里放行，App 会渲染 LoginPage）；
    // 已登录但非 admin → 回首页。真实权限由后端 `require_admin` 兜底。
    if (!status.authenticated) return true
    return status.role === 'admin' ? true : { name: 'library' }
  } catch {
    return true // 鉴权请求失败时放行，交给 App 门禁 / 后端兜底
  }
})

export default router

import { createRouter, createWebHistory } from 'vue-router'
import MediaLibraryPage from '../pages/MediaLibraryPage.vue'
import StudyPage from '../pages/StudyPage.vue'
import VocabPage from '../pages/VocabPage.vue'
import VocabPracticePage from '../pages/VocabPracticePage.vue'
import StatsPage from '../pages/StatsPage.vue'

/**
 * 路由表照搬旧 `frontend/src/App.tsx` 的真实结构（4 条 + `*` 兜底）。
 *
 * ⚠️ 计划 §P1-3 写的「5 条路由含 /login」是错的：旧版**登录不是路由**，
 * 而是 App 层的状态门禁（未登录时整屏渲染 `<LoginPage/>`，不经过 Router）。
 * 门禁在 P1-3 接线；本表只列真实业务路由。
 */
const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'library', component: MediaLibraryPage },
    { path: '/study/:mediaId', name: 'study', component: StudyPage },
    { path: '/vocab', name: 'vocab', component: VocabPage },
    { path: '/vocab/practice', name: 'vocab-practice', component: VocabPracticePage },
    { path: '/stats', name: 'stats', component: StatsPage },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

export default router

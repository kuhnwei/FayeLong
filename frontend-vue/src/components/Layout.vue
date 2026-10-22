<script setup lang="ts">
/**
 * 应用外壳（历史踩坑区，结构照搬旧 `frontend/src/components/Layout.tsx`）。
 *
 * 「固定高度 + 三段 flex」：
 *   header（shrink-0） / main（flex-1 min-h-0 overflow-y-auto） / 底条（shrink-0）
 *
 * 为什么：旧版用 `fixed bottom-0` 播放条 + 学习页 `calc(100vh - 109px)` 的魔法数字，
 * 数字按桌面顶栏高度（61px）与 main 内边距（24px）算，手机顶栏一换行变高就全错。
 * 改成固定高度 flex 外壳后，学习页只写 `h-full` 就刚好撑满，**与顶栏/底条实际高度无关**。
 *
 * 用 `h-dvh` 而非 `h-screen`：dvh 取动态视口高度，移动端地址栏收起/展开时不会跳动。
 */
import { useRoute } from 'vue-router'
import AccountMenu from './AccountMenu.vue'
import BackendStatus from './BackendStatus.vue'
import PlayerBar from './PlayerBar.vue'

const route = useRoute()

/** 导航项样式：与旧 `navClass` 逐字一致（手机上收紧内边距与字号，桌面上放宽）。 */
function navClass(isActive: boolean): string {
  return [
    'shrink-0 rounded-lg px-2 py-1.5 text-[13px] transition-colors sm:px-3 sm:py-2 sm:text-sm',
    isActive ? 'bg-slate-900 text-white' : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900',
  ].join(' ')
}

/** 「媒体库」只在根路径高亮（对应旧 NavLink 的 `end`）。 */
function isLibraryActive(): boolean {
  return route.path === '/'
}

/** 「生词本」在 /vocab 及其子路径高亮（旧 NavLink 无 `end`，前缀匹配）。 */
function isVocabActive(): boolean {
  return route.path === '/vocab' || route.path.startsWith('/vocab/')
}
</script>

<template>
  <div class="flex h-dvh flex-col overflow-hidden bg-slate-50">
    <header class="shrink-0 border-b border-slate-200 bg-white pt-[env(safe-area-inset-top)]">
      <div class="mx-auto flex w-full max-w-5xl items-center gap-2 px-3 py-2 sm:gap-4 sm:px-6 sm:py-3">
        <!-- 站点 Logo（柚子龙，透明底紧贴裁剪）：alt 留空 —— 标题里已有名字，避免读屏重复播报 -->
        <img
          src="/logo.png"
          alt=""
          draggable="false"
          class="h-6 w-6 shrink-0 select-none sm:h-7 sm:w-7"
        />
        <h1 class="shrink-0 text-[14px] font-medium text-slate-900 sm:text-[15px]">
          <span class="hidden sm:inline">FayeLong 英语学习</span>
          <span class="sm:hidden">FayeLong</span>
        </h1>
        <nav class="flex min-w-0 items-center gap-0.5 sm:gap-1">
          <RouterLink to="/" :class="navClass(isLibraryActive())">媒体库</RouterLink>
          <RouterLink to="/vocab" :class="navClass(isVocabActive())">生词本</RouterLink>
        </nav>
        <div class="ml-auto flex shrink-0 items-center gap-2">
          <BackendStatus />
          <AccountMenu />
        </div>
      </div>
    </header>

    <main class="mx-auto min-h-0 w-full max-w-5xl flex-1 overflow-y-auto px-3 py-3 sm:px-6 sm:py-6">
      <slot />
    </main>

    <!-- 底条：真正的播放条（P2-B）。无 current 时整条不渲染，外壳自然只剩两段 -->
    <PlayerBar />
  </div>
</template>

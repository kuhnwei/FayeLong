<script setup lang="ts">
/**
 * 应用外壳（P1-2 换皮）：顶栏药丸导航 + 移动端底部 Tab（真实 `<footer>`）。
 *
 * 布局沿用 P0 前「固定高度三段 flex」的哲学（不引入 fixed 定位，也不用 100vh 减高度的魔法数字）：
 *   header（shrink-0） / main（flex-1 min-h-0 overflow-y-auto） / PlayerBar（shrink-0） / footer（shrink-0）
 * 移动底栏 Tab 是真正的第三段 `<footer>`，`md` 以下才显示；PlayerBar 作为普通 flex 子项
 * 排在 `<main>` 与 `<footer>` 之间（flex 堆叠、零 z-index 冲突，见 ARCH §4.2 Q3 裁决）。
 *
 * ⚠️ 脚本依赖（改结构前先看）：
 *   - 根容器必须带 `h-dvh`、直接子元素依次是 `<header>` `<main>` `<footer>`（skeleton 三段式断言）
 *   - `header nav a` 是导航探针的锚点；每项须带 `data-active="true|false"`（文本定位）
 *   - `header` 里必须保留 BackendStatus（含「后端」文本）与 AccountMenu（含 `▾` 按钮）
 *   - 桌面（≥md）导航文本可见（skeleton 在 1280px 按文本定位）；移动端（<sm）收成图标
 */
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useQuery } from '@tanstack/vue-query'
import { getAuthStatus } from '../api/client'
import AccountMenu from './AccountMenu.vue'
import BackendStatus from './BackendStatus.vue'
import PlayerBar from './PlayerBar.vue'

const route = useRoute()
const router = useRouter()

const { data: auth } = useQuery({
  queryKey: ['auth', 'status'],
  queryFn: getAuthStatus,
  staleTime: 0,
})
const isAdmin = computed(() => auth.value?.role === 'admin')

interface NavItem {
  key: 'library' | 'vocab' | 'practice' | 'stats' | 'admin-users' | 'admin-stats'
  /** vue-router 的路由 name（`router.hasRoute` 用 name 判断，不是 path） */
  name: string
  to: string
  label: string
  /** 手写内联 SVG（2px 圆头描边，currentColor 继承），顶栏图标与底栏 Tab 共用 */
  icon: string
  /** 仅管理员可见（底栏不显示，顶栏按 isAdmin 过滤） */
  adminOnly?: boolean
}

const NAV_ITEMS: NavItem[] = [
  {
    key: 'library',
    name: 'library',
    to: '/',
    label: '媒体库',
    icon: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 5h16v14H4z"/><path d="M4 9h16"/><path d="M9 13h6"/></svg>',
  },
  {
    key: 'vocab',
    name: 'vocab',
    to: '/vocab',
    label: '生词本',
    icon: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 4h11a3 3 0 013 3v13H8a3 3 0 01-3-3z"/><path d="M9 8h6"/></svg>',
  },
  {
    key: 'practice',
    name: 'vocab-practice',
    to: '/vocab/practice',
    label: '练习',
    icon: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l2.6 5.6 6.1.8-4.5 4.2 1.2 6-5.4-3-5.4 3 1.2-6L3.3 9.4l6.1-.8z"/></svg>',
  },
  {
    key: 'stats',
    name: 'stats',
    to: '/stats',
    label: '统计',
    icon: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20h16"/><path d="M7 20v-6"/><path d="M12 20V8"/><path d="M17 20v-4"/></svg>',
  },
  {
    key: 'admin-users',
    name: 'admin-users',
    to: '/admin/users',
    label: '用户',
    adminOnly: true,
    icon: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="8" r="3.5"/><path d="M3 20c0-3.3 2.7-6 6-6s6 2.7 6 6"/><path d="M16 4.5a3.5 3.5 0 010 7"/><path d="M18 14c2.4 1 4 3 4 6"/></svg>',
  },
  {
    key: 'admin-stats',
    name: 'admin-stats',
    to: '/admin/stats',
    label: '对比',
    adminOnly: true,
    icon: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20h16"/><path d="M8 20v-8"/><path d="M12 20V5"/><path d="M16 20v-11"/></svg>',
  },
]

/** 顶栏可见项（admin 项仅在管理员登录时出现）；底栏始终只有 4 个主项。 */
const visibleNav = computed(() => NAV_ITEMS.filter((i) => !i.adminOnly || isAdmin.value))
const mainNav = computed(() => NAV_ITEMS.filter((i) => !i.adminOnly))

/** 精确匹配：`/vocab` 与 `/vocab/practice` 各自独立点亮，绝不因前缀同时亮两个。 */
function activeKey(): NavItem['key'] | '' {
  const p = route.path
  if (p === '/') return 'library'
  if (p === '/vocab') return 'vocab'
  if (p === '/vocab/practice') return 'practice'
  if (p === '/stats' || p.startsWith('/stats/')) return 'stats'
  if (p.startsWith('/admin/users')) return 'admin-users'
  if (p.startsWith('/admin/stats')) return 'admin-stats'
  return ''
}

const isActive = (key: NavItem['key']) => activeKey() === key
/** `/stats` 路由 T06 才建；未注册时渲染占位 span，不让它跳转报错。 */
const isAvailable = (item: NavItem) => router.hasRoute(item.name)

/** 底栏 Tab 的选中态（`.tab` 语义用工具类拼，active 走 lemon-200 圆角块）。 */
function tabClass(active: boolean): string {
  return [
    'flex min-h-[48px] flex-col items-center justify-center gap-[2px] rounded-control px-1',
    'text-[10.5px] font-semibold transition-colors',
    active ? 'bg-lemon-200 text-ink' : 'text-ink-3',
  ].join(' ')
}
</script>

<template>
  <div class="flex h-dvh flex-col overflow-hidden bg-cream text-ink">
    <!-- ================= 顶栏 ================= -->
    <header class="shrink-0 border-b-[2px] border-ink bg-cream pt-[env(safe-area-inset-top)]">
      <div class="mx-auto flex w-full max-w-5xl items-center gap-2 px-3 py-2 sm:gap-4 sm:px-6 sm:py-3">
        <!-- 站点 Logo（柚子龙，透明底紧贴裁剪）：alt 留空 —— 标题里已有名字，避免读屏重复播报 -->
        <img
          src="/logo.png"
          alt=""
          draggable="false"
          class="h-6 w-6 shrink-0 select-none sm:h-7 sm:w-7"
        />
        <h1 class="shrink-0 text-[14px] font-extrabold tracking-[0.2px] sm:text-[15px]">
          <span class="hidden sm:inline">FayeLong 精听</span>
          <!-- 窄屏（<sm）只留 FayeLong：实测评测 360/375/390px 下带「精听」会让顶栏导航
               溢出（h1 68.3→101.1px，nav 需 166px 但只分到 126.9/141.9/156.9px） -->
          <span class="sm:hidden">FayeLong</span>
        </h1>

        <nav class="flex min-w-0 items-center gap-0.5 sm:gap-1" aria-label="主导航">
          <template v-for="item in visibleNav" :key="item.key">
            <RouterLink
              v-if="isAvailable(item)"
              :to="item.to"
              class="nav-pill px-2 sm:px-3.5"
              :data-active="isActive(item.key) ? 'true' : 'false'"
            >
              <span class="[&>svg]:block" v-html="item.icon" />
              <span class="hidden sm:inline">{{ item.label }}</span>
            </RouterLink>
            <span
              v-else
              class="nav-pill cursor-default px-2 opacity-40 sm:px-3.5"
              :data-active="'false'"
              :title="`${item.label}（即将上线）`"
            >
              <span class="[&>svg]:block" v-html="item.icon" />
              <span class="hidden sm:inline">{{ item.label }}</span>
            </span>
          </template>
        </nav>

        <div class="ml-auto flex shrink-0 items-center gap-2">
          <BackendStatus />
          <AccountMenu />
        </div>
      </div>
    </header>

    <!-- ================= 主体 ================= -->
    <main class="mx-auto min-h-0 w-full max-w-5xl flex-1 overflow-y-auto px-3 py-3 sm:px-6 sm:py-6">
      <slot />
    </main>

    <!-- 播放条：普通 flex 子项，位于 main 与 footer 之间（无 current 时不渲染） -->
    <PlayerBar />

    <!-- ================= 移动端底部 Tab（真实 footer） ================= -->
    <footer class="shrink-0 border-t-[2px] border-ink bg-cream pb-[env(safe-area-inset-bottom)] md:hidden">
      <nav class="grid grid-cols-4 px-2 pt-1.5" aria-label="底部导航">
        <template v-for="item in mainNav" :key="item.key">
          <RouterLink
            v-if="isAvailable(item)"
            :to="item.to"
            :class="tabClass(isActive(item.key))"
            :data-active="isActive(item.key) ? 'true' : 'false'"
          >
            <span class="[&>svg]:block" v-html="item.icon" />
            <span>{{ item.label }}</span>
          </RouterLink>
          <span v-else :class="[tabClass(false), 'cursor-default opacity-40']" :data-active="'false'">
            <span class="[&>svg]:block" v-html="item.icon" />
            <span>{{ item.label }}</span>
          </span>
        </template>
      </nav>
    </footer>
  </div>
</template>

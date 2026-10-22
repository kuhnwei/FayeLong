<script setup lang="ts">
/**
 * 学习统计页（P2 · T12 实数据）。
 *
 * 7 区块全部接 `GET /api/stats/overview` 真值，无占位数字：
 *   ① KPI 四卡  ② 每日听写柱状图  ③ 正确率折线（80% 目标虚线）
 *   ④ 12 周热力图  ⑤ 生词构成环形（两态）  ⑥ 课程完成度  ⑦ 最近听写
 *
 * 空态：`daily` 全零时柱状区显示引导卡（去媒体库上传）；KPI 全 0 非 NaN。
 */
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import { useQuery } from '@tanstack/vue-query'
import { getOverview } from '../api/stats'
import BarChart from '../components/charts/BarChart.vue'
import LineChart from '../components/charts/LineChart.vue'
import Heatmap from '../components/charts/Heatmap.vue'
import Donut from '../components/charts/Donut.vue'

const { data, isLoading, isError, error } = useQuery({
  queryKey: ['stats', 'overview'],
  queryFn: () => getOverview(14),
})

const overview = computed(() => data.value)

const kpis = computed(() => [
  { label: '今日听写', value: overview.value?.kpi.today_attempts ?? 0, unit: '次' },
  { label: '今日正确率', value: Math.round((overview.value?.kpi.today_accuracy ?? 0) * 100), unit: '%' },
  { label: '今日新生词', value: overview.value?.kpi.today_new_vocab ?? 0, unit: '个' },
  { label: '连续天数', value: overview.value?.kpi.streak_days ?? 0, unit: '天' },
])

const emptyDaily = computed(() =>
  (overview.value?.daily ?? []).every((p) => p.attempts === 0),
)

/** 柱状图：x 轴用 MM-DD */
const barData = computed(() =>
  (overview.value?.daily ?? []).map((p) => ({ label: p.date.slice(5), value: p.attempts })),
)

/** 折线图：accuracy 0–1 */
const lineData = computed(() =>
  (overview.value?.daily ?? []).map((p) => ({ label: p.date.slice(5), value: p.accuracy })),
)

/** 热力图：听写次数 */
const heatData = computed(() =>
  (overview.value?.daily ?? []).map((p) => ({ date: p.date, value: p.attempts })),
)

const donutSegments = computed(() => {
  const vocab = overview.value?.vocab ?? { total: 0, mastered: 0 }
  return [
    { label: '已掌握', value: vocab.mastered, color: 'var(--leaf)' },
    { label: '未掌握', value: Math.max(0, vocab.total - vocab.mastered), color: 'var(--lemon-200)' },
  ]
})

const courses = computed(() => overview.value?.courses ?? [])
const recent = computed(() => overview.value?.recent ?? [])

function pctText(v: number): string {
  return `${Number.isFinite(v) ? Math.round(v) : 0}%`
}

function recentTime(iso: string): string {
  return iso.slice(0, 16).replace('T', ' ')
}
</script>

<template>
  <div class="flex flex-col gap-4">
    <div>
      <h2 class="text-[17px] font-bold leading-[1.45] text-ink">学习统计</h2>
      <p class="text-[12.5px] text-ink-3">近 14 天学习数据概览</p>
    </div>

    <!-- 加载 / 错误 -->
    <p v-if="isLoading" class="py-8 text-center text-[13px] text-ink-3">加载中…</p>
    <p v-if="isError" class="py-8 text-center text-[13px] text-red-600">
      读取失败：{{ (error as Error).message }}
    </p>

    <template v-else-if="overview">
      <!-- ① KPI 四卡 -->
      <div class="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <div v-for="kpi in kpis" :key="kpi.label" class="card p-4">
          <p class="text-[12px] text-ink-3">{{ kpi.label }}</p>
          <p class="mt-1 text-[24px] font-extrabold tabular-nums text-ink">
            {{ kpi.value }}<span class="ml-0.5 text-[12px] font-semibold text-ink-3">{{ kpi.unit }}</span>
          </p>
        </div>
      </div>

      <!-- ②③ 柱状 + 折线（≥1024 1.6:1） -->
      <div class="grid grid-cols-1 gap-3 lg:grid-cols-[1.6fr_1fr]">
        <section class="card p-4">
          <h3 class="text-[14px] font-bold text-ink">每日听写</h3>
          <p class="mt-0.5 text-[12px] text-ink-3">近 14 天听写量</p>
          <div v-if="emptyDaily" class="mt-3 flex flex-col items-center justify-center gap-3 py-8 text-center">
            <p class="text-[13px] text-ink-3">先去媒体库上传一段音频，开始你的第一课。</p>
            <RouterLink to="/" class="btn btn-primary">去媒体库</RouterLink>
          </div>
          <div v-else class="mt-3 overflow-x-auto">
            <BarChart :data="barData" :height="180" />
          </div>
        </section>

        <section class="card p-4">
          <h3 class="text-[14px] font-bold text-ink">正确率趋势</h3>
          <p class="mt-0.5 text-[12px] text-ink-3">80% 目标虚线</p>
          <div class="mt-3 overflow-x-auto">
            <LineChart :points="lineData" :height="180" />
          </div>
        </section>
      </div>

      <!-- ④⑤ 热力图 + 环形（≥1024 1:1） -->
      <div class="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <section class="card p-4">
          <h3 class="text-[14px] font-bold text-ink">练习热力图</h3>
          <p class="mt-0.5 text-[12px] text-ink-3">近 12 周听写活跃度</p>
          <div class="mt-3 overflow-x-auto">
            <Heatmap :data="heatData" :weeks="12" />
          </div>
        </section>

        <section class="card p-4">
          <h3 class="text-[14px] font-bold text-ink">生词构成</h3>
          <p class="mt-0.5 text-[12px] text-ink-3">已掌握 / 未掌握</p>
          <div class="mt-3">
            <Donut :segments="donutSegments" :size="140" :thickness="16" />
          </div>
        </section>
      </div>

      <!-- ⑥⑦ 课程完成度 + 最近听写（≥1024 1.5:1） -->
      <div class="grid grid-cols-1 gap-3 lg:grid-cols-[1.5fr_1fr]">
        <section class="card p-4">
          <h3 class="text-[14px] font-bold text-ink">课程完成度</h3>
          <p class="mt-0.5 text-[12px] text-ink-3">各素材听写进度</p>
          <ul v-if="courses.length" class="mt-3 space-y-3">
            <li v-for="c in courses" :key="c.media_id">
              <div class="flex items-baseline justify-between gap-2">
                <span class="min-w-0 truncate text-[13px] text-ink">{{ c.title }}</span>
                <span class="shrink-0 tabular-nums text-[12px] text-ink-3">
                  {{ c.attempted }}/{{ c.total }} · {{ pctText(c.pct) }}
                </span>
              </div>
              <div class="mt-1.5 h-2 w-full overflow-hidden rounded-full bg-cream-2">
                <div
                  class="h-full rounded-full bg-leaf transition-[width] duration-300"
                  :style="{ width: `${Math.max(0, Math.min(100, c.pct))}%` }"
                />
              </div>
            </li>
          </ul>
          <p v-else class="mt-3 text-[12px] text-ink-3">还没有素材。</p>
        </section>

        <section class="card p-4">
          <h3 class="text-[14px] font-bold text-ink">最近听写</h3>
          <p class="mt-0.5 text-[12px] text-ink-3">最近 6 次提交</p>
          <ul v-if="recent.length" class="mt-3 space-y-2.5">
            <li v-for="(r, i) in recent" :key="i" class="border-t border-cream-2 pt-2.5 first:border-0 first:pt-0">
              <p class="line-clamp-2 text-[12.5px] leading-relaxed text-ink">{{ r.sentence_text }}</p>
              <p class="mt-0.5 text-[11px] text-ink-3">
                {{ recentTime(r.created_at) }} · 正确率 {{ Math.round(r.accuracy * 100) }}%
              </p>
            </li>
          </ul>
          <p v-else class="mt-3 text-[12px] text-ink-3">还没有听写记录。</p>
        </section>
      </div>
    </template>
  </div>
</template>

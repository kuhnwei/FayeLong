<script setup lang="ts">
/**
 * 学习统计页（P1-3 骨架 / T06）。
 *
 * 本阶段只搭**路由可达的骨架**：标题 + 7 区块占位卡片，不接接口、不画图、
 * 不显示任何真实/假数据数字 —— 完整数据与 4 个 SVG 图表组件在 P2（T11/T12）落地。
 *
 * 7 区块（优先级与 `design/UI-落地执行计划.md` §5.1 一致）：
 *   ① KPI 四卡（今日听写 / 今日正确率 / 今日新生词 / 连续天数）
 *   ② 每日听写柱状图  ③ 正确率折线（80% 目标虚线）
 *   ④ 12 周热力图      ⑤ 生词构成环形  ⑥ 课程完成度  ⑦ 最近听写
 */

/** 占位区块的标题与语义说明（骨架阶段只渲染标题 + 空态占位，不渲染数字）。 */
const SECTIONS: { title: string; note: string }[] = [
  { title: '每日听写', note: '近 14 天听写量柱状图' },
  { title: '正确率趋势', note: '近 14 天正确率折线（80% 目标虚线）' },
  { title: '练习热力图', note: '近 12 周听写活跃度' },
  { title: '生词构成', note: '已掌握 / 未掌握 环形' },
  { title: '课程完成度', note: '各素材听写进度' },
  { title: '最近听写', note: '最近提交的听写记录' },
]
</script>

<template>
  <div class="flex flex-col gap-4">
    <h2 class="text-[17px] font-bold leading-[1.45] text-ink">学习统计</h2>
    <p class="-mt-2 text-[12.5px] text-ink-3">近 14 天学习数据概览（数据接口即将上线）</p>

    <!-- ① KPI 四卡 -->
    <div class="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <div v-for="kpi in ['今日听写', '今日正确率', '今日新生词', '连续天数']" :key="kpi" class="card p-4">
        <p class="text-[12px] text-ink-3">{{ kpi }}</p>
        <p class="mt-1 text-[24px] font-extrabold tabular-nums text-ink">——</p>
      </div>
    </div>

    <!-- ②–⑦ 六个图表/列表占位区块 -->
    <div class="grid grid-cols-1 gap-3 lg:grid-cols-2">
      <section v-for="s in SECTIONS" :key="s.title" class="card p-4">
        <h3 class="text-[14px] font-bold text-ink">{{ s.title }}</h3>
        <p class="mt-0.5 text-[12px] text-ink-3">{{ s.note }}</p>
        <div class="mt-3 flex h-24 items-center justify-center rounded-control border-2 border-dashed border-ink-3 text-[12px] text-ink-3">
          占位区块 · 数据接入后出图
        </div>
      </section>
    </div>
  </div>
</template>

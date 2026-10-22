/**
 * 统计页图表共享尺寸常量（ARCH §6.3）。
 *
 * 跨 4 个图表组件的**唯一来源**：柱宽 / 柱圆角 / 折线宽 / 热力格尺寸与间距。
 * 组件内部禁止再散写这些魔法数字。
 */
export const CHART = {
  barWidth: 22,
  barRadius: 6,
  lineWidth: 3,
  cellSize: 13,
  cellGap: 3.5,
} as const

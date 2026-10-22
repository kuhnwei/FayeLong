/** 分类筛选 chips 的选中值：null = 全部；'none' = 未分类；数字 = 某分类。
 *
 * 旧版从 `CategoryChips.tsx` 一并导出；Vue 侧一行一组件，类型放独立模块供多处引用。
 */
export type CategoryFilter = number | 'none' | null

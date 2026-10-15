import type { CategoryItem } from '../api/client'
import { TagIcon } from './icons'

/** chips 的选中值：null = 全部；'none' = 未分类；数字 = 某分类 */
export type CategoryFilter = number | 'none' | null

interface CategoryChipsProps {
  items: CategoryItem[]
  uncategorizedCount: number
  /** 服务端分类列表是否还在加载（首帧给占位，避免 chip 跳动） */
  loading?: boolean
  selected: CategoryFilter
  onSelect: (value: CategoryFilter) => void
  onManage: () => void
}

/**
 * 分类筛选 chips 条。
 *
 * 布局：窄屏单行横向滚动（`overflow-x-auto` + `shrink-0`），`sm` 起换行。
 * 计数口径：这里的数字都是**分类子集计数**（来自 `GET /api/categories`），
 * 与顶部 StatCard 的全局计数不同 —— 所以文案用「名称 N」而不是「共 N 个」。
 */
export default function CategoryChips({
  items,
  uncategorizedCount,
  loading = false,
  selected,
  onSelect,
  onManage,
}: CategoryChipsProps) {
  // 「全部」的自洽计数 = 各分类之和 + 未分类（同一个来源，避免与 StatCard 口径打架）
  const allCount = items.reduce((sum, c) => sum + c.media_count, 0) + uncategorizedCount

  const chipClass = (active: boolean, muted = false) =>
    [
      'flex h-8 shrink-0 items-center gap-1.5 rounded-full border px-3 text-[12px] transition-colors',
      active
        ? 'border-slate-900 bg-slate-900 text-white'
        : muted
          ? 'border-slate-200 bg-white text-slate-400'
          : 'border-slate-200 bg-white text-slate-600 hover:border-slate-400 hover:text-slate-900',
    ].join(' ')

  const countClass = (active: boolean) =>
    ['tabular-nums', active ? 'text-white/70' : 'text-slate-400'].join(' ')

  const entries: { key: string; label: string; count: number; value: CategoryFilter }[] = [
    { key: 'all', label: '全部', count: allCount, value: null },
    { key: 'none', label: '未分类', count: uncategorizedCount, value: 'none' },
    ...items.map((c) => ({ key: `c${c.id}`, label: c.name, count: c.media_count, value: c.id })),
  ]

  return (
    <div
      className="-mx-1 flex items-center gap-1.5 overflow-x-auto px-1 pb-1 sm:flex-wrap sm:overflow-x-visible sm:pb-0"
      role="group"
      aria-label="按分类筛选素材"
    >
      {loading && items.length === 0 && (
        <span className="h-8 w-24 shrink-0 animate-pulse rounded-full bg-slate-100" />
      )}

      {entries.map((entry) => {
        const active = selected === entry.value
        return (
          <button
            key={entry.key}
            type="button"
            aria-pressed={active}
            onClick={() => onSelect(entry.value)}
            className={chipClass(active, entry.count === 0 && !active)}
            title={entry.label === '全部' ? '显示全部素材' : `只看「${entry.label}」`}
          >
            <span className="max-w-[8rem] truncate">{entry.label}</span>
            <span className={countClass(active)}>{entry.count}</span>
          </button>
        )
      })}

      <button
        type="button"
        onClick={onManage}
        className="flex h-8 shrink-0 items-center gap-1 rounded-full border border-dashed border-slate-300 px-3 text-[12px] text-slate-500 transition-colors hover:border-slate-500 hover:text-slate-900"
      >
        <TagIcon className="h-3.5 w-3.5" />
        管理分类
      </button>
    </div>
  )
}

interface CategorySelectProps {
  items: CategoryItem[]
  /** '' = 未分类；数字串 = 分类 id */
  value: string
  onChange: (value: string) => void
  label?: string
  className?: string
}

/**
 * 通用的「导入到分类」选择器。
 * 用原生 `<select>`：移动端触摸友好、零额外依赖、键盘可操作。
 * 值用字符串（'' = 未分类），调用方负责转成 `number | null`。
 */
export function CategorySelect({
  items,
  value,
  onChange,
  label,
  className = '',
}: CategorySelectProps) {
  return (
    <label className={['flex items-center gap-1.5', className].join(' ')}>
      {label && <span className="shrink-0 text-[12px] text-slate-500">{label}</span>}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        aria-label={label ?? '选择分类'}
        className="h-8 max-w-[10rem] rounded-lg border border-slate-200 bg-white px-2 text-[12px] text-slate-700 outline-none transition-colors focus:border-slate-400"
      >
        <option value="">未分类</option>
        {items.map((c) => (
          <option key={c.id} value={String(c.id)}>
            {c.name}
          </option>
        ))}
      </select>
    </label>
  )
}

import { useEffect, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import {
  createCategory,
  deleteCategory,
  reorderCategories,
  updateCategory,
  type CategoryItem,
} from '../api/client'
import { ChevronDownIcon, ChevronUpIcon, CloseIcon, PencilIcon, TrashIcon } from './icons'

const NAME_MAX = 32

/** 按「字符」计数（CJK 与 emoji 都各算 1），与后端 1–32 的口径对齐 */
const charLength = (value: string) => [...value].length

/** 把后端错误转成人话；同名冲突统一显示规格里写死的那句 */
function errorText(error: Error): string {
  const message = error.message || ''
  if (/存在|同名|unique/i.test(message)) return '已存在同名分类'
  if (/不能为空|必填/.test(message)) return '分类名不能为空'
  if (/过长|长度|32/.test(message)) return `分类名不能超过 ${NAME_MAX} 个字符`
  return message || '操作失败，请稍后重试'
}

/** 两份分类列表是否「看起来一样」（id 顺序 + 名字 + 计数），用于避免无意义的状态重置 */
function sameCategories(a: CategoryItem[], b: CategoryItem[]): boolean {
  if (a === b) return true
  if (a.length !== b.length) return false
  return a.every(
    (item, i) =>
      item.id === b[i].id && item.name === b[i].name && item.media_count === b[i].media_count,
  )
}

interface CategoryManagerProps {
  items: CategoryItem[]
  onClose: () => void
  /** 数据变了（新建/改名/删除/排序）——调用方去 invalidate ['categories'] 与 ['media'] */
  onChanged: () => void
  onNotify: (text: string, tone?: 'info' | 'error') => void
}

/**
 * 「管理分类」面板：新建 / 行内重命名 / 删除（回落未分类）/ ↑↓ 排序。
 *
 * 形态：桌面居中弹层，窄屏贴底（bottom sheet）。三段式外壳下用 fixed 覆盖，不动布局高度。
 * 排序不做拖拽（新依赖 + 移动端误触），用 ↑/↓ 按钮 —— 点击后本地先重排，再把**整份顺序**提交。
 */
export default function CategoryManager({
  items,
  onClose,
  onChanged,
  onNotify,
}: CategoryManagerProps) {
  // 本地副本：点 ↑/↓ 后先动它，避免等网络往返才看到位移。
  // 同步时比较内容而不是引用 —— 父级若给出「每次渲染都是新数组」的 items，
  // 只按引用同步会让这里无限重渲染。
  const [local, setLocal] = useState<CategoryItem[]>(items)
  useEffect(() => {
    setLocal((prev) => (sameCategories(prev, items) ? prev : items))
  }, [items])

  const [draft, setDraft] = useState('')
  const [createError, setCreateError] = useState<string | null>(null)

  const [editingId, setEditingId] = useState<number | null>(null)
  const [editDraft, setEditDraft] = useState('')
  const [editError, setEditError] = useState<string | null>(null)

  // Esc 关闭面板（行内编辑时让 Esc 先给输入框用）
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && editingId === null) onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [editingId, onClose])

  const createMutation = useMutation({
    mutationFn: (name: string) => createCategory(name),
    onSuccess: () => {
      setDraft('')
      setCreateError(null)
      onChanged()
    },
    onError: (error: Error) => setCreateError(errorText(error)),
  })

  const renameMutation = useMutation({
    mutationFn: ({ id, name }: { id: number; name: string }) => updateCategory(id, name),
    onSuccess: () => {
      setEditingId(null)
      setEditError(null)
      onChanged()
    },
    // 撞名不丢输入：重新打开输入框，把已输入的原文留在里面，只在下面红字提示
    onError: (error: Error, variables) => {
      setEditError(errorText(error))
      setEditingId(variables.id)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (category: CategoryItem) => deleteCategory(category.id),
    onSuccess: (result) => {
      onNotify(`已删除分类「${result.name}」，${result.released} 个素材已移入「未分类」`)
      onChanged()
    },
    onError: (error: Error) => onNotify(`删除失败：${error.message}`, 'error'),
  })

  const orderMutation = useMutation({
    mutationFn: (ids: number[]) => reorderCategories(ids),
    onSuccess: () => onChanged(),
    onError: (error: Error) => {
      setLocal(items)
      onNotify(`排序失败：${error.message}`, 'error')
      onChanged()
    },
  })

  const trimmedDraft = draft.trim()
  const draftLength = charLength(trimmedDraft)
  const canCreate =
    trimmedDraft.length > 0 && draftLength <= NAME_MAX && !createMutation.isPending

  const submitCreate = () => {
    if (!canCreate) return
    setCreateError(null)
    createMutation.mutate(trimmedDraft)
  }

  const startRename = (category: CategoryItem) => {
    setEditDraft(category.name)
    setEditError(null)
    setEditingId(category.id)
  }

  const commitRename = (category: CategoryItem) => {
    const value = editDraft.trim()
    setEditingId(null)
    setEditError(null)
    if (value && value !== category.name) renameMutation.mutate({ id: category.id, name: value })
  }

  const move = (index: number, delta: -1 | 1) => {
    const target = index + delta
    if (target < 0 || target >= local.length) return
    const next = [...local]
    const tmp = next[index]
    next[index] = next[target]
    next[target] = tmp
    setLocal(next)
    // 契约要求提交**当前全部分类 id 的完整有序集合**
    orderMutation.mutate(next.map((c) => c.id))
  }

  const confirmDelete = (category: CategoryItem) => {
    const message =
      `删除分类「${category.name}」后，其中的 ${category.media_count} 个素材会移入「未分类」，不会被删除。确定删除？`
    if (window.confirm(message)) deleteMutation.mutate(category)
  }

  const busy = deleteMutation.isPending || renameMutation.isPending

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-slate-900/40 sm:items-center"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="管理分类"
        onClick={(e) => e.stopPropagation()}
        className="flex max-h-[85dvh] w-full flex-col rounded-t-2xl bg-white shadow-xl sm:max-w-lg sm:rounded-2xl"
      >
        <div className="flex shrink-0 items-center justify-between border-b border-slate-100 px-4 py-3 sm:px-5">
          <h3 className="text-[14px] font-medium text-slate-900">管理分类</h3>
          <button
            type="button"
            onClick={onClose}
            aria-label="关闭"
            className="flex h-8 w-8 items-center justify-center rounded-lg text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700"
          >
            <CloseIcon className="h-4 w-4" />
          </button>
        </div>

        {/* 新建 */}
        <div className="shrink-0 border-b border-slate-100 px-4 py-3 sm:px-5">
          <div className="flex items-center gap-2">
            <input
              value={draft}
              onChange={(e) => {
                setDraft(e.target.value)
                setCreateError(null)
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter') submitCreate()
              }}
              placeholder={`新分类名（1–${NAME_MAX} 个字）`}
              aria-label="新分类名"
              className="h-9 min-w-0 flex-1 rounded-lg border border-slate-300 px-3 text-[13px] text-slate-800 outline-none transition-colors focus:border-slate-500"
            />
            <button
              type="button"
              disabled={!canCreate}
              onClick={submitCreate}
              className="h-9 shrink-0 rounded-lg bg-slate-900 px-4 text-[13px] text-white transition-colors hover:bg-slate-700 disabled:opacity-40"
            >
              {createMutation.isPending ? '新建中…' : '新建'}
            </button>
          </div>
          <div className="mt-1 space-y-0.5">
            {draft.length > 0 && trimmedDraft.length === 0 && (
              <p className="text-[11px] text-red-600">分类名不能为空</p>
            )}
            {draftLength > NAME_MAX && (
              <p className="text-[11px] text-red-600">
                分类名不能超过 {NAME_MAX} 个字符（当前 {draftLength} 个）
              </p>
            )}
            {createError && <p className="text-[11px] text-red-600">{createError}</p>}
          </div>
        </div>

        {/* 列表 */}
        <div className="min-h-0 flex-1 overflow-y-auto px-2 py-2 sm:px-3">
          {local.length === 0 && (
            <p className="px-3 py-8 text-center text-[13px] text-slate-400">
              还没有分类。上面输入一个名字，建好后就能把素材归进去。
            </p>
          )}

          {local.map((category, index) => {
            const editing = editingId === category.id
            return (
              <div
                key={category.id}
                className="flex items-center gap-1.5 rounded-lg px-1.5 py-1.5 hover:bg-slate-50"
              >
                <div className="flex shrink-0 flex-col">
                  <button
                    type="button"
                    disabled={index === 0 || orderMutation.isPending}
                    onClick={() => move(index, -1)}
                    title="上移"
                    aria-label={`将「${category.name}」上移`}
                    className="flex h-8 w-8 items-center justify-center rounded-md text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700 disabled:opacity-30"
                  >
                    <ChevronUpIcon className="h-3.5 w-3.5" />
                  </button>
                  <button
                    type="button"
                    disabled={index === local.length - 1 || orderMutation.isPending}
                    onClick={() => move(index, 1)}
                    title="下移"
                    aria-label={`将「${category.name}」下移`}
                    className="flex h-8 w-8 items-center justify-center rounded-md text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700 disabled:opacity-30"
                  >
                    <ChevronDownIcon className="h-3.5 w-3.5" />
                  </button>
                </div>

                <div className="min-w-0 flex-1">
                  {editing ? (
                    <>
                      <input
                        autoFocus
                        value={editDraft}
                        onChange={(e) => {
                          setEditDraft(e.target.value)
                          setEditError(null)
                        }}
                        onBlur={() => commitRename(category)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') commitRename(category)
                          if (e.key === 'Escape') {
                            setEditDraft(category.name)
                            setEditError(null)
                            setEditingId(null)
                          }
                        }}
                        aria-label={`重命名「${category.name}」`}
                        className="w-full rounded border border-slate-300 px-2 py-1 text-[13px] text-slate-800 outline-none focus:border-slate-500"
                      />
                      <p className="mt-0.5 text-[11px] text-red-600">{editError ?? ''}</p>
                    </>
                  ) : (
                    <>
                      <p className="truncate text-[13px] text-slate-800">{category.name}</p>
                      <p className="text-[11px] text-slate-400">
                        {category.media_count} 个素材
                      </p>
                    </>
                  )}
                </div>

                <button
                  type="button"
                  disabled={busy || editing}
                  onClick={() => startRename(category)}
                  title="重命名"
                  aria-label={`重命名「${category.name}」`}
                  className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700 disabled:opacity-30"
                >
                  <PencilIcon className="h-4 w-4" />
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => confirmDelete(category)}
                  title="删除分类"
                  aria-label={`删除「${category.name}」`}
                  className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-slate-400 transition-colors hover:bg-red-50 hover:text-red-600 disabled:opacity-30"
                >
                  <TrashIcon className="h-4 w-4" />
                </button>
              </div>
            )
          })}
        </div>

        <div className="shrink-0 border-t border-slate-100 px-4 py-2.5 sm:px-5">
          <p className="text-[11px] text-slate-400">
            删除分类不会删除素材：其中的素材会回到「未分类」。用 ↑ ↓ 调整显示顺序。
          </p>
        </div>
      </div>
    </div>
  )
}

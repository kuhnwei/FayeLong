/** 生词本页（M4 / FR-A5）：查看 / 编辑释义 / 标记已掌握 / 删除 / 导出 Markdown。
 *
 * 生词来自学习页的查词浮层（FR-S7），这里做集中管理。
 * 增强：① 每条生词可朗读；② 可进入「练习」页做中译英 / 英译中练习。
 */

import { useDeferredValue, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  deleteVocab,
  listVocab,
  updateVocab,
  vocabExportUrl,
  type VocabItem,
} from '../api/client'
import { speakEnglish } from '../utils/speech'
import {
  BookIcon,
  CheckIcon,
  CloseIcon,
  DownloadIcon,
  PencilIcon,
  SearchIcon,
  SpeakerIcon,
  StarFilledIcon,
  StarIcon,
  TargetIcon,
  TrashIcon,
} from '../components/icons'

type Filter = 'all' | 'todo' | 'mastered'

const FILTERS: { key: Filter; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'todo', label: '待复习' },
  { key: 'mastered', label: '已掌握' },
]

export default function VocabPage() {
  const queryClient = useQueryClient()
  const [filter, setFilter] = useState<Filter>('all')
  const [keyword, setKeyword] = useState('')
  const deferredKeyword = useDeferredValue(keyword)

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['vocab', filter, deferredKeyword],
    queryFn: () =>
      listVocab({
        mastered: filter === 'all' ? undefined : filter === 'mastered',
        q: deferredKeyword.trim() || undefined,
      }),
  })

  const items = data?.items ?? []

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['vocab'] })
  }

  const toggleMutation = useMutation({
    mutationFn: (vars: { id: number; mastered: boolean }) =>
      updateVocab(vars.id, { mastered: vars.mastered }),
    onSuccess: invalidate,
  })

  const editMutation = useMutation({
    mutationFn: (vars: { id: number; translation: string }) =>
      updateVocab(vars.id, { translation: vars.translation }),
    onSuccess: invalidate,
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => deleteVocab(id),
    onSuccess: invalidate,
  })

  const busy = toggleMutation.isPending || editMutation.isPending || deleteMutation.isPending

  /** 有释义的词才能参与练习（中译英需要中文题干，英译中需要正确选项） */
  const practisable = items.filter((item) => (item.translation ?? '').trim()).length

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-[15px] font-medium text-slate-900">生词本</h2>
          <p className="mt-1 text-[13px] text-slate-500">
            学习页中点击单词可查词并一键收藏，这里集中复习、管理，也可以做练习。
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Link
            to="/vocab/practice"
            title={practisable < 2 ? '至少需要 2 个带释义的生词' : '开始中译英 / 英译中练习'}
            className={[
              'flex items-center gap-1.5 rounded-lg px-3.5 py-2 text-[13px] transition-colors',
              practisable >= 2
                ? 'border border-slate-200 bg-white text-slate-700 hover:bg-slate-50'
                : 'pointer-events-none border border-slate-200 bg-white text-slate-300',
            ].join(' ')}
          >
            <TargetIcon className="h-3.5 w-3.5" />
            开始练习
            {practisable >= 2 && (
              <span className="tabular-nums text-slate-400">{practisable}</span>
            )}
          </Link>
          <a
            href={vocabExportUrl(filter === 'mastered' ? true : undefined)}
            className={[
              'flex items-center gap-1.5 rounded-lg px-3.5 py-2 text-[13px] transition-colors',
              items.length
                ? 'bg-slate-900 text-white hover:bg-slate-700'
                : 'pointer-events-none bg-slate-200 text-slate-500',
            ].join(' ')}
          >
            <DownloadIcon className="h-3.5 w-3.5" />
            导出 Markdown
          </a>
        </div>
      </div>

      {/* 工具栏 */}
      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3">
        <div className="flex items-center gap-1 rounded-lg bg-slate-100 p-0.5">
          {FILTERS.map((item) => (
            <button
              key={item.key}
              type="button"
              onClick={() => setFilter(item.key)}
              className={[
                'rounded-md px-3 py-1 text-[12px] transition-colors',
                filter === item.key
                  ? 'bg-white text-slate-900 shadow-sm'
                  : 'text-slate-500 hover:text-slate-800',
              ].join(' ')}
            >
              {item.label}
            </button>
          ))}
        </div>

        <div className="relative ml-auto w-full max-w-[240px]">
          <SearchIcon className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" />
          <input
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            placeholder="搜索单词或释义…"
            className="w-full rounded-lg border border-slate-200 py-1.5 pl-8 pr-3 text-[12px] text-slate-700 outline-none transition-colors focus:border-slate-400"
          />
        </div>

        <span className="text-[12px] text-slate-400">
          共 <span className="tabular-nums text-slate-600">{data?.total ?? 0}</span> 个
          {data && data.mastered > 0 && (
            <>
              ，已掌握 <span className="tabular-nums text-emerald-600">{data.mastered}</span> 个
            </>
          )}
        </span>
      </div>

      {isLoading && (
        <p className="rounded-xl border border-slate-200 bg-white px-3 py-8 sm:px-5 text-center text-[13px] text-slate-400">
          加载中…
        </p>
      )}

      {isError && (
        <p className="rounded-xl border border-red-100 bg-red-50 px-3 py-8 sm:px-5 text-center text-[13px] text-red-600">
          {(error as Error).message}
        </p>
      )}

      {!isLoading && !isError && items.length === 0 && (
        <div className="rounded-xl border border-slate-200 bg-white px-3 py-12 sm:px-5 text-center">
          <BookIcon className="mx-auto h-8 w-8 text-slate-300" />
          <p className="mt-3 text-[13px] text-slate-400">
            {keyword || filter !== 'all'
              ? '没有符合条件的生词。'
              : '还没有生词。到学习页点击原文里的单词，即可查词并加入生词本。'}
          </p>
        </div>
      )}

      {!isLoading && !isError && items.length > 0 && (
        <div className="space-y-2.5">
          {items.map((item) => (
            <VocabRow
              key={item.id}
              item={item}
              busy={busy}
              onToggleMastered={() =>
                toggleMutation.mutate({ id: item.id, mastered: !item.mastered })
              }
              onSaveTranslation={(translation) =>
                editMutation.mutate({ id: item.id, translation })
              }
              onDelete={() => {
                if (window.confirm(`确定从生词本删除「${item.lemma || item.word}」？`)) {
                  deleteMutation.mutate(item.id)
                }
              }}
            />
          ))}
        </div>
      )}
    </div>
  )
}

// --------------------------- 单条生词 ---------------------------

interface RowProps {
  item: VocabItem
  busy: boolean
  onToggleMastered: () => void
  onSaveTranslation: (translation: string) => void
  onDelete: () => void
}

function VocabRow({ item, busy, onToggleMastered, onSaveTranslation, onDelete }: RowProps) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(item.translation ?? '')

  useEffect(() => {
    setDraft(item.translation ?? '')
  }, [item.translation])

  const display = item.lemma && item.lemma !== item.word ? `${item.lemma}` : item.word

  return (
    <div data-vocab-row="" className="rounded-xl border border-slate-200 bg-white px-4 py-3">
      <div className="flex flex-wrap items-start gap-x-4 gap-y-2">
        {/* 单词 */}
        <div className="min-w-[150px] shrink-0">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="text-[15px] font-medium text-slate-900">{display}</span>
            <button
              type="button"
              onClick={() => speakEnglish(display)}
              title={`朗读 ${display}`}
              aria-label={`朗读 ${display}`}
              className="rounded p-0.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700"
            >
              <SpeakerIcon className="h-3.5 w-3.5" />
            </button>
            {item.phonetic && (
              <span className="text-[11px] text-slate-400">/{item.phonetic}/</span>
            )}
          </div>
          {item.lemma && item.lemma !== item.word && (
            <p className="mt-0.5 text-[10px] text-slate-400">原文 {item.word}</p>
          )}
        </div>

        {/* 释义 */}
        <div className="min-w-[220px] flex-1">
          {editing ? (
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              rows={2}
              autoFocus
              className="w-full resize-y rounded-lg border border-slate-300 px-2.5 py-1.5 text-[13px] leading-relaxed text-slate-700 outline-none focus:border-slate-500"
            />
          ) : (
            <p className="text-[13px] leading-relaxed text-slate-700">
              {item.translation || <span className="text-slate-400">（暂无释义）</span>}
            </p>
          )}
          {item.context && (
            <p className="mt-1 text-[11px] leading-relaxed text-slate-400">
              上下文：{item.context}
            </p>
          )}
        </div>

        {/* 来源 */}
        <div className="shrink-0 text-right text-[11px] text-slate-400">
          {item.media_title ? (
            <span title={item.media_title} className="inline-block max-w-[140px] truncate">
              {item.media_title}
            </span>
          ) : (
            <span className="text-slate-300">—</span>
          )}
        </div>

        {/* 操作 */}
        <div className="flex shrink-0 items-center gap-1.5">
          {editing ? (
            <>
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  onSaveTranslation(draft)
                  setEditing(false)
                }}
                className="flex items-center gap-1 rounded-lg bg-slate-900 px-2.5 py-1.5 text-[12px] text-white transition-colors hover:bg-slate-700 disabled:opacity-40"
              >
                <CheckIcon className="h-3.5 w-3.5" />
                保存
              </button>
              <button
                type="button"
                onClick={() => {
                  setDraft(item.translation ?? '')
                  setEditing(false)
                }}
                className="rounded-lg border border-slate-200 p-1.5 text-slate-500 transition-colors hover:bg-slate-50"
                title="取消"
              >
                <CloseIcon className="h-3.5 w-3.5" />
              </button>
            </>
          ) : (
            <>
              <button
                type="button"
                disabled={busy}
                onClick={onToggleMastered}
                title={item.mastered ? '标记为待复习' : '标记为已掌握'}
                className={[
                  'flex items-center gap-1 rounded-lg border px-2.5 py-1.5 text-[12px] transition-colors disabled:opacity-40',
                  item.mastered
                    ? 'border-emerald-200 bg-emerald-50 text-emerald-600'
                    : 'border-slate-200 text-slate-500 hover:bg-slate-50',
                ].join(' ')}
              >
                {item.mastered ? (
                  <StarFilledIcon className="h-3.5 w-3.5" />
                ) : (
                  <StarIcon className="h-3.5 w-3.5" />
                )}
                {item.mastered ? '已掌握' : '标记掌握'}
              </button>
              <button
                type="button"
                onClick={() => setEditing(true)}
                title="编辑释义"
                className="rounded-lg border border-slate-200 p-1.5 text-slate-500 transition-colors hover:bg-slate-50"
              >
                <PencilIcon className="h-3.5 w-3.5" />
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={onDelete}
                title="删除"
                className="rounded-lg border border-slate-200 p-1.5 text-slate-400 transition-colors hover:bg-red-50 hover:text-red-600 disabled:opacity-40"
              >
                <TrashIcon className="h-3.5 w-3.5" />
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

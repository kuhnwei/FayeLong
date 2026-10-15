/** 笔记汇总面板（M5 / FR-A6）。
 *
 * 学习页顶部「笔记」入口打开：列出本媒体所有句子笔记（含原文 / 翻译 / 听写概要），
 * 点击条目可定位到对应句子卡片，右上角可一键导出为 Markdown。
 */

import { createPortal } from 'react-dom'
import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getMediaNotes, mediaNotesExportUrl } from '../api/client'
import { CloseIcon, DownloadIcon, NoteIcon } from './icons'

interface Props {
  mediaId: number
  onClose: () => void
  onJump: (sentenceId: number) => void
}

export default function NotesPanel({ mediaId, onClose, onJump }: Props) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['media-notes', mediaId],
    queryFn: () => getMediaNotes(mediaId),
  })

  // Esc 关闭
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const items = data?.items ?? []

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-slate-900/30 p-3 backdrop-blur-sm sm:p-6"
      onClick={onClose}
    >
      <div
        className="mt-3 flex max-h-[85vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-xl sm:mt-8 sm:max-h-[80vh]"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label="句子笔记汇总"
      >
        <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 px-3 py-3 sm:px-5 sm:py-3.5">
          <NoteIcon className="h-4 w-4 text-slate-400" />
          <h3 className="text-[14px] font-medium text-slate-900">句子笔记</h3>
          {data && (
            <span className="text-[12px] text-slate-400">
              {data.total} 条 / 全篇 {data.sentence_count} 句
            </span>
          )}
          <div className="ml-auto flex items-center gap-2">
            <a
              href={mediaNotesExportUrl(mediaId)}
              className={[
                'flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[12px] transition-colors',
                items.length
                  ? 'bg-slate-900 text-white hover:bg-slate-700'
                  : 'pointer-events-none bg-slate-200 text-slate-500',
              ].join(' ')}
            >
              <DownloadIcon className="h-3.5 w-3.5" />
              导出 Markdown
            </a>
            <button
              type="button"
              onClick={onClose}
              title="关闭"
              className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700"
            >
              <CloseIcon className="h-4 w-4" />
            </button>
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-auto px-3 py-3 sm:px-5 sm:py-4">
          {isLoading && <p className="py-6 text-center text-[13px] text-slate-400">加载中…</p>}
          {isError && (
            <p className="py-6 text-center text-[13px] text-red-600">
              {(error as Error).message}
            </p>
          )}
          {!isLoading && !isError && items.length === 0 && (
            <div className="py-10 text-center">
              <NoteIcon className="mx-auto h-7 w-7 text-slate-300" />
              <p className="mt-3 text-[13px] text-slate-400">
                还没有句子笔记。在句子卡片下方点「添加笔记」记录心得，这里会汇总展示。
              </p>
            </div>
          )}

          <div className="space-y-2.5">
            {items.map((item) => (
              <button
                key={item.sentence_id}
                type="button"
                onClick={() => {
                  onJump(item.sentence_id)
                  onClose()
                }}
                className="block w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-left transition-colors hover:border-slate-300 hover:bg-slate-50 sm:px-4"
              >
                <div className="flex items-center gap-2">
                  <span className="shrink-0 text-[11px] tabular-nums text-slate-400">
                    #{item.idx + 1}
                  </span>
                  {item.attempt_count > 0 && (
                    <span
                      className={[
                        'rounded-full px-2 py-0.5 text-[10px] tabular-nums',
                        item.mastered
                          ? 'bg-emerald-50 text-emerald-600'
                          : 'bg-amber-50 text-amber-600',
                      ].join(' ')}
                    >
                      {item.mastered ? '已掌握' : `最佳 ${item.best_accuracy}%`}
                    </span>
                  )}
                  <span className="ml-auto hidden shrink-0 text-[11px] text-slate-300 sm:inline">点击定位 →</span>
                </div>
                {item.text_en && (
                  <p className="mt-1.5 text-[13px] leading-relaxed text-slate-700">
                    {item.text_en}
                  </p>
                )}
                {item.text_zh && (
                  <p className="mt-0.5 text-[12px] leading-relaxed text-slate-400">
                    {item.text_zh}
                  </p>
                )}
                <p className="mt-1.5 whitespace-pre-wrap rounded-lg bg-amber-50/60 px-2.5 py-1.5 text-[12px] leading-relaxed text-slate-700">
                  {item.content}
                </p>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>,
    document.body,
  )
}

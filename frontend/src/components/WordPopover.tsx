/** 单词浮层：站内释义 + 词形还原 + 跳牛津/朗文 + 一键加入生词本（M4 / FR-S6 · FR-S7）。
 *
 * 交互要点：
 * - 点击原文中的单词弹出；点击遮罩、Esc、关闭按钮均可关闭。
 * - 释义来自本地 ECDICT 词库（离线）；词库未收录时后端可能返回在线翻译兜底。
 * - 「加入生词本」会带上当前句子作为上下文（便于日后复习与导出）。
 */

import { useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useMutation } from '@tanstack/react-query'
import { addVocab, lookupWord, type DictResult, type VocabItem } from '../api/client'
import {
  BookmarkPlusIcon,
  CheckIcon,
  CloseIcon,
  ExternalLinkIcon,
  RefreshIcon,
} from './icons'

export interface WordPopoverTarget {
  word: string
  sentenceId?: number | null
  mediaId?: number | null
  context?: string
  rect: { top: number; left: number; bottom: number; width: number }
}

interface Props {
  target: WordPopoverTarget
  onClose: () => void
}

const CARD_W = 344
const MARGIN = 8

function speak(word: string) {
  try {
    const synth = window.speechSynthesis
    if (!synth) return
    synth.cancel()
    const utter = new SpeechSynthesisUtterance(word)
    utter.lang = 'en-US'
    utter.rate = 0.9
    synth.speak(utter)
  } catch {
    /* 系统不支持朗读时静默忽略 */
  }
}

export default function WordPopover({ target, onClose }: Props) {
  const cardRef = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState({ top: target.rect.bottom + MARGIN, left: target.rect.left })

  const [loading, setLoading] = useState(true)
  const [data, setData] = useState<DictResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [added, setAdded] = useState<'added' | 'exists' | null>(null)

  // 查词（点击即查，避免依赖 react-query 缓存 key 的复杂度）
  const reload = () => {
    setLoading(true)
    setError(null)
    lookupWord(target.word)
      .then((result) => setData(result))
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false))
  }

  // 首次挂载与切换单词时查询，并重置「已加入」状态
  useLayoutEffect(() => {
    setAdded(null)
    reload()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target.word])

  // 定位：优先显示在词下方，空间不足则上移；左右夹在视口内
  useLayoutEffect(() => {
    const el = cardRef.current
    if (!el) return
    const height = el.offsetHeight
    const width = el.offsetWidth || CARD_W
    let top = target.rect.bottom + MARGIN
    if (top + height > window.innerHeight - MARGIN) {
      const above = target.rect.top - MARGIN - height
      top = above > MARGIN ? above : Math.max(MARGIN, window.innerHeight - MARGIN - height)
    }
    const left = Math.min(Math.max(MARGIN, target.rect.left), window.innerWidth - MARGIN - width)
    setPos((prev) => (prev.top === top && prev.left === left ? prev : { top, left }))
  }, [target, loading, data, error])

  // Esc 关闭
  useLayoutEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const addMutation = useMutation({
    mutationFn: () => {
      const entry = data
      return addVocab({
        word: entry?.word || target.word,
        lemma: entry?.lemma ?? null,
        phonetic: entry?.phonetic || null,
        translation: entry?.translation?.length ? entry.translation.join('；') : null,
        media_id: target.mediaId ?? null,
        sentence_id: target.sentenceId ?? null,
        context: target.context ?? null,
      })
    },
    onSuccess: (item: VocabItem) => setAdded(item.duplicated ? 'exists' : 'added'),
  })

  return createPortal(
    <div className="fixed inset-0 z-50" onMouseDown={onClose}>
      <div
        ref={cardRef}
        onMouseDown={(event) => event.stopPropagation()}
        style={{ top: pos.top, left: pos.left, width: CARD_W }}
        className="absolute max-h-[70vh] overflow-y-auto rounded-xl border border-slate-200 bg-white p-4 shadow-xl"
      >
        {/* 头部 */}
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
              <span className="text-[17px] font-medium text-slate-900">{target.word}</span>
              {data?.phonetic && (
                <span className="text-[12px] text-slate-400">/{data.phonetic}/</span>
              )}
              <button
                type="button"
                onClick={() => speak(data?.word || target.word)}
                title="朗读"
                className="rounded border border-slate-200 px-1.5 py-0.5 text-[10px] text-slate-500 transition-colors hover:bg-slate-50"
              >
                朗读
              </button>
            </div>
            {data?.lemma && data.lemma !== data.query && (
              <p className="mt-1 text-[11px] text-slate-400">
                已还原原型：<span className="text-slate-600">{data.lemma}</span>
              </p>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            title="关闭"
            className="shrink-0 rounded p-1 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600"
          >
            <CloseIcon className="h-4 w-4" />
          </button>
        </div>

        {/* 主体 */}
        <div className="mt-3 border-t border-slate-100 pt-3">
          {loading && (
            <p className="flex items-center gap-2 py-3 text-[12px] text-slate-400">
              <RefreshIcon className="h-3.5 w-3.5 animate-spin" />
              查询中…
            </p>
          )}

          {!loading && error && (
            <p className="py-2 text-[12px] text-red-600">查询失败：{error}</p>
          )}

          {!loading && !error && data && (
            <div className="space-y-2.5">
              {/* 标签行 */}
              {(data.tags.length > 0 || data.collins > 0 || data.oxford === 1 || data.source === 'online') && (
                <div className="flex flex-wrap items-center gap-1.5">
                  {data.oxford === 1 && (
                    <span className="rounded bg-sky-50 px-1.5 py-0.5 text-[10px] text-sky-600">
                      牛津核心
                    </span>
                  )}
                  {data.collins > 0 && (
                    <span className="rounded bg-amber-50 px-1.5 py-0.5 text-[10px] text-amber-600">
                      柯林斯 {'★'.repeat(Math.min(5, data.collins))}
                    </span>
                  )}
                  {data.tags.map((tag) => (
                    <span
                      key={tag}
                      className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-500"
                    >
                      {tag}
                    </span>
                  ))}
                  {data.source === 'online' && (
                    <span className="rounded bg-violet-50 px-1.5 py-0.5 text-[10px] text-violet-600">
                      在线参考
                    </span>
                  )}
                </div>
              )}

              {/* 中文释义 */}
              {data.translation.length > 0 ? (
                <ul className="space-y-1">
                  {data.translation.slice(0, 6).map((line, index) => (
                    <li key={index} className="text-[13px] leading-relaxed text-slate-800">
                      {line}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-[13px] text-slate-400">（暂无中文释义）</p>
              )}

              {/* 英文释义 */}
              {data.definition.length > 0 && (
                <details className="text-[12px]">
                  <summary className="cursor-pointer select-none text-slate-400 hover:text-slate-600">
                    英文释义（{data.definition.length}）
                  </summary>
                  <ul className="mt-1.5 space-y-1">
                    {data.definition.slice(0, 4).map((line, index) => (
                      <li key={index} className="leading-relaxed text-slate-500">
                        {line}
                      </li>
                    ))}
                  </ul>
                </details>
              )}

              {/* 词形变化 */}
              {data.forms.length > 0 && (
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-slate-400">
                  {data.forms.slice(0, 6).map((form, index) => (
                    <span key={`${form.label}-${index}`}>
                      {form.label}
                      <span className="ml-1 text-slate-600">{form.value}</span>
                    </span>
                  ))}
                </div>
              )}

              {data.notice && (
                <p className="rounded bg-amber-50 px-2 py-1.5 text-[11px] leading-relaxed text-amber-700">
                  {data.notice}
                </p>
              )}
            </div>
          )}
        </div>

        {/* 底部操作 */}
        <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3">
          <button
            type="button"
            disabled={addMutation.isPending || added !== null}
            onClick={() => addMutation.mutate()}
            className={[
              'flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[12px] transition-colors',
              added
                ? 'bg-emerald-50 text-emerald-600'
                : 'bg-slate-900 text-white hover:bg-slate-700',
              addMutation.isPending ? 'opacity-60' : '',
            ].join(' ')}
          >
            {added ? <CheckIcon className="h-3.5 w-3.5" /> : <BookmarkPlusIcon className="h-3.5 w-3.5" />}
            {added === 'added' ? '已加入生词本' : added === 'exists' ? '已在生词本' : '加入生词本'}
          </button>

          {addMutation.isError && (
            <span className="text-[11px] text-red-600">
              {(addMutation.error as Error).message}
            </span>
          )}

          <div className="ml-auto flex items-center gap-2 text-[11px]">
            <a
              href={data?.oxford_url || '#'}
              target="_blank"
              rel="noreferrer"
              className="flex items-center gap-0.5 text-slate-500 transition-colors hover:text-slate-900"
            >
              牛津
              <ExternalLinkIcon className="h-3 w-3" />
            </a>
            <span className="text-slate-200">·</span>
            <a
              href={data?.longman_url || '#'}
              target="_blank"
              rel="noreferrer"
              className="flex items-center gap-0.5 text-slate-500 transition-colors hover:text-slate-900"
            >
              朗文
              <ExternalLinkIcon className="h-3 w-3" />
            </a>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  )
}

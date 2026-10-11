/** 句子笔记编辑器（M4 / FR-S8）。
 *
 * - 每句至多一条笔记；折叠态显示预览，展开后编辑。
 * - 失焦或点击「保存」时写入后端；内容清空即删除该笔记。
 */

import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { getNote, saveNote, type NoteItem } from '../api/client'
import { CheckIcon, NoteIcon, TrashIcon } from './icons'

interface Props {
  sentenceId: number
}

export default function NoteEditor({ sentenceId }: Props) {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [text, setText] = useState('')
  const [original, setOriginal] = useState('')
  const [status, setStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const [message, setMessage] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const loaded = useRef(false)

  // 首次加载该句笔记
  useEffect(() => {
    let cancelled = false
    loaded.current = false
    setLoading(true)
    getNote(sentenceId)
      .then((note: NoteItem) => {
        if (cancelled) return
        setText(note.content)
        setOriginal(note.content)
        setOpen(Boolean(note.content))     // 已有笔记默认展开
      })
      .catch((err: Error) => {
        if (!cancelled) setMessage(`读取笔记失败：${err.message}`)
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false)
          loaded.current = true
        }
      })
    return () => {
      cancelled = true
    }
  }, [sentenceId])

  const dirty = text.trim() !== original.trim()

  const persist = async (value: string) => {
    if (value.trim() === original.trim()) return
    setStatus('saving')
    setMessage(null)
    try {
      const result = await saveNote(sentenceId, value)
      const content = result?.content ?? ''
      setText(content)
      setOriginal(content)
      queryClient.setQueryData(['note', sentenceId], result)
      setStatus('saved')
      setMessage(result?.exists ? '笔记已保存' : '笔记已清空')
      window.setTimeout(() => setStatus('idle'), 1800)
    } catch (err) {
      setStatus('error')
      setMessage(`保存失败：${(err as Error).message}`)
    }
  }

  return (
    <div className="mt-2 border-t border-slate-100 pt-2">
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="flex items-center gap-1 text-[11px] text-slate-500 transition-colors hover:text-slate-800"
        >
          <NoteIcon className="h-3.5 w-3.5" />
          {open ? '收起笔记' : original ? '查看笔记' : '添加笔记'}
        </button>

        {!open && original && (
          <span className="min-w-0 flex-1 truncate text-[11px] text-slate-400" title={original}>
            {original}
          </span>
        )}

        {message && (
          <span
            className={[
              'ml-auto shrink-0 text-[11px]',
              status === 'error' ? 'text-red-600' : 'text-emerald-600',
            ].join(' ')}
          >
            {message}
          </span>
        )}
      </div>

      {open && (
        <div className="mt-2">
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            onBlur={() => void persist(text)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                e.preventDefault()
                void persist(text)
              }
              if (e.key === 'Escape') setOpen(false)
            }}
            rows={3}
            disabled={loading}
            placeholder="记录这个词的用法、搭配、易错点…（失焦自动保存，Ctrl/Cmd+Enter 立即保存）"
            className="w-full resize-y rounded-lg border border-slate-200 bg-slate-50/60 px-3 py-2 text-[13px] leading-relaxed text-slate-700 outline-none transition-colors focus:border-slate-400 focus:bg-white disabled:bg-slate-100"
          />
          <div className="mt-1.5 flex items-center gap-2">
            <button
              type="button"
              disabled={!dirty || status === 'saving'}
              onClick={() => void persist(text)}
              className="flex items-center gap-1 rounded-lg bg-slate-900 px-2.5 py-1 text-[11px] text-white transition-colors hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <CheckIcon className="h-3.5 w-3.5" />
              {status === 'saving' ? '保存中' : '保存'}
            </button>
            {original && (
              <button
                type="button"
                disabled={status === 'saving'}
                onClick={() => {
                  setText('')
                  void persist('')
                }}
                className="flex items-center gap-1 rounded-lg border border-slate-200 px-2.5 py-1 text-[11px] text-slate-500 transition-colors hover:bg-slate-50 disabled:opacity-40"
              >
                <TrashIcon className="h-3.5 w-3.5" />
                删除笔记
              </button>
            )}
            {dirty && status !== 'saving' && (
              <span className="text-[11px] text-amber-600">未保存</span>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

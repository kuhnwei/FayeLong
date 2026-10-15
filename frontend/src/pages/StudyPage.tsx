/** 学习页：一句一页的听写工作台（v1.12 改版）。
 *
 * 为什么从「卡片滚动列表」改成「一句一页」：
 * 听写本来就是「专注一句」的任务 —— 一屏一句才能把字号放到最大，
 * 也省掉了在长列表里来回滚动找位置。整页不出现滚动条，
 * 翻页靠底部按钮、方向键或数字宫格。
 *
 * 三段式布局（高度锁定在视口内）：
 *   顶部条（媒体信息 + 整体操作）
 *   ├─ 句子舞台（flex-1，正文大字自适应）
 *   └─ 底部（上一句 / 序号 / 下一句 + 句子索引宫格）
 *
 * 原有能力全部保留：单句播放 / 单句循环 / A-B 循环、听写输入与词级标红、
 * 查词浮层、笔记、拆分 / 合并 / 重译 / 编辑。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  PROCESSING_STATUSES,
  STATUS_LABEL,
  clearClips,
  getMedia,
  getMediaNotes,
  listAttempts,
  mergeSentence,
  openProgressStream,
  retranslateSentence,
  retranscribeMedia,
  splitSentence,
  submitAttempt,
  updateSentence,
  type AttemptResult,
  type MediaDetail,
  type ProgressEventData,
  type SentenceItem,
} from '../api/client'
import DiffResult from '../components/DiffResult'
import NoteEditor from '../components/NoteEditor'
import NotesPanel from '../components/NotesPanel'
import WordPopover, { type WordPopoverTarget } from '../components/WordPopover'
import { useClipPlayer } from '../hooks/useClipPlayer'
import { usePlayer } from '../store/player'
import { formatBytes, formatDuration, formatRelative, formatSeconds } from '../utils/format'
import {
  ABLoopIcon,
  AlertIcon,
  CheckIcon,
  EyeIcon,
  EyeOffIcon,
  HistoryIcon,
  LoopIcon,
  MergeIcon,
  NoteIcon,
  PauseIcon,
  PencilIcon,
  PlayIcon,
  RefreshIcon,
  ScissorsIcon,
  SendIcon,
  TargetIcon,
  TranslateIcon,
} from '../components/icons'

// 切片首部留白（与后端 clip_padding_ms 对应），用于回算真实时间点
const CLIP_PAD_MS = 120

/** 提交听写后就地更新的统计（避免整页重新拉取详情） */
interface StatOverride {
  attempt_count: number
  best_accuracy: number
  mastered: boolean
}

/** 逐句的听写草稿：翻页回来时输入的内容与上次校验结果都还在 */
interface Draft {
  text: string
  result: AttemptResult | null
}
const EMPTY_DRAFT: Draft = { result: null, text: '' }

/** 被点击单词在视口中的位置（用于定位浮层） */
export interface WordRect {
  top: number
  left: number
  bottom: number
  width: number
}

/** 正文自适应字号：句子越短，字越大 —— 一句一屏正是放大字号的时机。
 *
 * clamp 的下限按手机宽度定（375px 上 3.4vw 只有 12px，实际会取到下限），
 * 上限保持桌面观感不变；中间靠 vw 平滑过渡，所以不需要媒体查询。
 */
function stageFontSize(length: number): string {
  if (length <= 45) return 'clamp(1.5rem, 3.4vw, 2.9rem)'
  if (length <= 90) return 'clamp(1.25rem, 2.8vw, 2.3rem)'
  if (length <= 150) return 'clamp(1.05rem, 2.1vw, 1.85rem)'
  return 'clamp(0.95rem, 1.7vw, 1.5rem)'
}

/** 译文跟随正文但小一档，避免与原文抢视线 */
function translationFontSize(length: number): string {
  if (length <= 30) return 'clamp(0.9rem, 1.5vw, 1.25rem)'
  if (length <= 60) return 'clamp(0.85rem, 1.3vw, 1.1rem)'
  return 'clamp(0.8rem, 1.1vw, 1rem)'
}

/** 宫格格子的状态色：当前 > 已掌握 > 练过 > 未听 */
function gridClass(sentence: SentenceItem, active: boolean): string {
  if (active) return 'bg-slate-900 text-white ring-2 ring-slate-400'
  if (sentence.mastered) return 'bg-emerald-100 text-emerald-700 hover:bg-emerald-200'
  if (sentence.attempt_count > 0) return 'bg-amber-100 text-amber-700 hover:bg-amber-200'
  return 'bg-slate-100 text-slate-500 hover:bg-slate-200'
}

export default function StudyPage() {
  const { mediaId } = useParams()
  const id = Number(mediaId)
  const queryClient = useQueryClient()
  const openPlayer = usePlayer((s) => s.open)
  const currentMedia = usePlayer((s) => s.current)
  const clip = useClipPlayer()
  const stopClip = clip.stop

  const [live, setLive] = useState<ProgressEventData | null>(null)
  const [revealEn, setRevealEn] = useState<Record<number, boolean>>({})
  const [revealZh, setRevealZh] = useState<Record<number, boolean>>({})
  const [editingId, setEditingId] = useState<number | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [autoReveal, setAutoReveal] = useState(true)
  const [stats, setStats] = useState<Record<number, StatOverride>>({})
  const [wordTarget, setWordTarget] = useState<WordPopoverTarget | null>(null)
  const [notesOpen, setNotesOpen] = useState(false)
  const [toolsOpen, setToolsOpen] = useState(false)
  const [correctOpen, setCorrectOpen] = useState(false)
  const [noteOpen, setNoteOpen] = useState(false)
  const [drafts, setDrafts] = useState<Record<number, Draft>>({})
  const [highlightId, setHighlightId] = useState<number | null>(null)

  //: 当前句在句子数组里的下标（注意与 sentence.idx 不同：后者是切分序号）
  const [index, setIndex] = useState(0)

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['media', id],
    queryFn: () => getMedia(id),
    enabled: Number.isFinite(id),
    // SSE 为主，轮询兜底（SSE 不可用时仍能推进）
    refetchInterval: (query) =>
      query.state.data && PROCESSING_STATUSES.includes(query.state.data.status) ? 2500 : false,
  })

  // 笔记汇总（用于顶部入口的计数与面板）
  const notesQuery = useQuery({
    queryKey: ['media-notes', id],
    queryFn: () => getMediaNotes(id),
    enabled: Number.isFinite(id),
  })
  const noteCount = notesQuery.data?.total ?? 0

  const status = live?.status ?? data?.status ?? ''
  const progress = live?.progress ?? data?.progress ?? 0
  const processing = PROCESSING_STATUSES.includes(status)

  // ---- SSE 进度订阅（处理中才连）----
  useEffect(() => {
    if (!data || !PROCESSING_STATUSES.includes(data.status)) {
      setLive(null)
      return
    }
    const close = openProgressStream(id, (event) => {
      setLive(event)
      if (event.done) {
        void queryClient.invalidateQueries({ queryKey: ['media', id] })
        void queryClient.invalidateQueries({ queryKey: ['media'] })
      }
    })
    return close
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, data?.status])

  const applyDetail = (detail: MediaDetail) => {
    queryClient.setQueryData(['media', id], detail)
  }

  const editMutation = useMutation({
    mutationFn: (vars: { sid: number; patch: { text_en?: string; text_zh?: string } }) =>
      updateSentence(vars.sid, vars.patch),
    onSuccess: (detail) => {
      applyDetail(detail)
      setEditingId(null)
      setNotice('已保存修改')
    },
    onError: (e: Error) => setNotice(`保存失败：${e.message}`),
  })

  const retranslateMutation = useMutation({
    mutationFn: (sid: number) => retranslateSentence(sid),
    onSuccess: applyDetail,
    onError: (e: Error) => setNotice(`重新翻译失败：${e.message}`),
  })

  const splitMutation = useMutation({
    mutationFn: (vars: { sid: number; atMs: number }) =>
      splitSentence(vars.sid, { at_ms: vars.atMs }),
    onSuccess: (detail) => {
      applyDetail(detail)
      setNotice('已拆分')
    },
    onError: (e: Error) => setNotice(`拆分失败：${e.message}`),
  })

  const mergeMutation = useMutation({
    mutationFn: (sid: number) => mergeSentence(sid, 'next'),
    onSuccess: (detail) => {
      applyDetail(detail)
      setNotice('已与下一句合并')
    },
    onError: (e: Error) => setNotice(`合并失败：${e.message}`),
  })

  const rebuildMutation = useMutation({
    mutationFn: () => retranscribeMedia(id),
    onSuccess: () => {
      setNotice('已开始重新识别，完成后自动刷新')
      setStats({})
      setDrafts({})
      void queryClient.invalidateQueries({ queryKey: ['media', id] })
    },
    onError: (e: Error) => setNotice(`重新识别失败：${e.message}`),
  })

  const clearClipsMutation = useMutation({
    mutationFn: () => clearClips(id),
    onSuccess: () => {
      setNotice('切片已清理，释放磁盘空间（逐句播放暂不可用）')
      stopClip()
      void queryClient.invalidateQueries({ queryKey: ['media', id] })
    },
    onError: (e: Error) => setNotice(`清理失败：${e.message}`),
  })

  const sentences = data?.sentences ?? []

  // 把「本次会话刚提交的统计」叠加到服务端数据之上
  const effective = useMemo<SentenceItem[]>(
    () =>
      sentences.map((s) => {
        const patch = stats[s.id]
        return patch ? { ...s, ...patch } : s
      }),
    [sentences, stats],
  )

  const total = effective.length
  const current = total > 0 ? (effective[Math.min(index, total - 1)] ?? null) : null

  // 句子数变化（拆分 / 合并 / 重新识别）后把下标收回合法范围
  useEffect(() => {
    setIndex((i) => Math.min(i, Math.max(sentences.length - 1, 0)))
  }, [sentences.length])

  // 给键盘监听读最新值，避免把回调绑死在下标上反复重绑
  const navRef = useRef({ index, total })
  navRef.current = { index, total }

  /** 跳到第 next 句（越界自动收敛）；切句时停掉上一句的音频 */
  const goTo = useCallback(
    (next: number) => {
      const { total: count } = navRef.current
      const last = Math.max(count - 1, 0)
      const clamped = Math.min(Math.max(next, 0), last)
      setIndex(clamped)
      stopClip()
    },
    [stopClip],
  )

  // ← / → 翻页。焦点在输入框里时不劫持（那时方向键是移动光标）
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey || event.altKey) return
      if (editingId !== null) return
      const el = event.target as HTMLElement | null
      if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable)) {
        return
      }
      if (event.key === 'ArrowRight') {
        event.preventDefault()
        goTo(navRef.current.index + 1)
      } else if (event.key === 'ArrowLeft') {
        event.preventDefault()
        goTo(navRef.current.index - 1)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [goTo, editingId])

  const summary = useMemo(() => {
    const attempted = effective.filter((s) => s.attempt_count > 0)
    const avg = attempted.length
      ? Math.round((attempted.reduce((n, s) => n + s.best_accuracy, 0) / attempted.length) * 10) / 10
      : 0
    return {
      total: effective.length,
      attempted: attempted.length,
      mastered: effective.filter((s) => s.mastered).length,
      attempts: effective.reduce((n, s) => n + s.attempt_count, 0),
      avg,
    }
  }, [effective])

  const playable = Boolean(data && (data.has_audio || status === 'done'))
  const clipsReady = sentences.length > 0 && sentences.every((s) => s.clip_url)
  const noticeRef = useRef<number | null>(null)
  useEffect(() => {
    if (!notice) return
    if (noticeRef.current) window.clearTimeout(noticeRef.current)
    noticeRef.current = window.setTimeout(() => setNotice(null), 3200)
    return () => {
      if (noticeRef.current) window.clearTimeout(noticeRef.current)
    }
  }, [notice])

  const revealAll = (kind: 'en' | 'zh' | 'none') => {
    if (kind === 'none') {
      setRevealEn({})
      setRevealZh({})
      return
    }
    const map = Object.fromEntries(sentences.map((s) => [s.id, true]))
    if (kind === 'en') setRevealEn(map)
    else setRevealZh(map)
  }

  /** 从笔记面板跳到某句：直接翻到那一页 + 展开原文 + 短暂高亮 */
  const jumpToSentence = (sid: number) => {
    const target = effective.findIndex((s) => s.id === sid)
    if (target < 0) return
    setRevealEn((prev) => ({ ...prev, [sid]: true }))
    setHighlightId(sid)
    goTo(target)
    window.setTimeout(() => setHighlightId((cur) => (cur === sid ? null : cur)), 2400)
  }

  const patchDraft = useCallback((sid: number, patch: Partial<Draft>) => {
    setDrafts((prev) => ({ ...prev, [sid]: { ...(prev[sid] ?? EMPTY_DRAFT), ...patch } }))
  }, [])

  return (
    <div className="flex h-full min-h-0 flex-col gap-2 overflow-hidden sm:gap-3">
      {/* 隐藏的句子音频元素 */}
      <audio ref={clip.bind} preload="auto" className="hidden" />

      {/* 单词浮层（M4：查词 + 加入生词本） */}
      {wordTarget && (
        <WordPopover
          key={`${wordTarget.word}-${wordTarget.sentenceId ?? 0}`}
          target={wordTarget}
          onClose={() => setWordTarget(null)}
        />
      )}

      {/* 笔记汇总面板（M5：FR-A6） */}
      {notesOpen && (
        <NotesPanel mediaId={id} onClose={() => setNotesOpen(false)} onJump={jumpToSentence} />
      )}

      {/* --------------------------- 顶部条 --------------------------- */}
      <div className="shrink-0 rounded-xl border border-slate-200 bg-white px-3 py-2 sm:px-4 sm:py-2.5">
        <div className="flex items-center gap-2 sm:gap-3">
          <Link
            to="/"
            title="返回媒体库"
            className="shrink-0 rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs text-slate-600 transition-colors hover:bg-slate-50"
          >
            ←
          </Link>

          <div className="min-w-0 flex-1">
            <div className="flex items-baseline gap-2">
              <h2 className="truncate text-[14px] font-medium text-slate-900">
                {data?.title ?? '加载中…'}
              </h2>
              {total > 0 && (
                <span className="shrink-0 text-[12px] tabular-nums text-slate-400">
                  第 {Math.min(index + 1, total)} / {total} 句
                </span>
              )}
            </div>
            <div className="mt-0.5 flex flex-wrap items-center gap-x-3 text-[11px] text-slate-400">
              <span
                className={[
                  'rounded-full px-2 py-0.5',
                  status === 'failed'
                    ? 'bg-red-50 text-red-600'
                    : processing
                      ? 'bg-amber-50 text-amber-600'
                      : 'bg-emerald-50 text-emerald-600',
                ].join(' ')}
              >
                {STATUS_LABEL[status] ?? status}
                {processing && ` ${progress}%`}
              </span>
              {data && <span className="tabular-nums">{formatDuration(data.duration_ms)}</span>}
              {data && <span className="hidden sm:inline">{formatBytes(data.size_bytes)}</span>}
              {data && (
                <span className="hidden sm:inline">
                  {data.type === 'video' ? '视频（仅音轨）' : '音频'}
                </span>
              )}
              {total > 0 && (
                <span className="flex items-center gap-1">
                  <TargetIcon className="h-3 w-3" />
                  已听写
                  <span className="tabular-nums text-slate-600">
                    {summary.attempted}/{summary.total}
                  </span>
                  · 已掌握 <span className="tabular-nums text-emerald-600">{summary.mastered}</span>
                  {summary.attempted > 0 && (
                    <>
                      · 平均最佳 <span className="tabular-nums text-slate-600">{summary.avg}%</span>
                    </>
                  )}
                </span>
              )}
            </div>
          </div>

          <div className="flex shrink-0 items-center gap-1 sm:gap-1.5">
            <button
              type="button"
              data-testid="open-player"
              disabled={!playable}
              onClick={() => data && openPlayer(data, true)}
              className={[
                'rounded-lg px-2 py-1.5 text-[11px] transition-colors sm:px-2.5 sm:text-xs',
                playable
                  ? 'bg-slate-900 text-white hover:bg-slate-700'
                  : 'cursor-not-allowed bg-slate-100 text-slate-400',
              ].join(' ')}
            >
              {/* 窄屏上标题已经要截断了，按钮文案收缩成「播放 / 播放中」 */}
              <span className="sm:hidden">
                {currentMedia?.id === data?.id ? '播放中' : '播放'}
              </span>
              <span className="hidden sm:inline">
                {currentMedia?.id === data?.id ? '整段播放中' : '整段播放'}
              </span>
            </button>
            {total > 0 && (
              <button
                type="button"
                onClick={() => setNotesOpen(true)}
                title="查看本媒体全部句子笔记"
                className="flex items-center gap-1 rounded-lg border border-slate-200 px-2 py-1.5 text-[11px] text-slate-600 transition-colors hover:bg-slate-50 sm:px-2.5 sm:text-xs"
              >
                <NoteIcon className="h-3.5 w-3.5" />
                笔记{noteCount > 0 ? `（${noteCount}）` : ''}
              </button>
            )}
            <button
              type="button"
              onClick={() => setToolsOpen((v) => !v)}
              title="更多操作"
              className={[
                'rounded-lg border px-2 py-1.5 text-[11px] transition-colors sm:px-2.5 sm:text-xs',
                toolsOpen
                  ? 'border-slate-900 bg-slate-900 text-white'
                  : 'border-slate-200 text-slate-600 hover:bg-slate-50',
              ].join(' ')}
            >
              工具 {toolsOpen ? '▴' : '▾'}
            </button>
          </div>
        </div>

        {/* 工具面板（低频操作收在这里，避免顶部条变高） */}
        {toolsOpen && (
          <div className="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-slate-100 pt-2.5 text-[11px]">
            <label className="flex cursor-pointer items-center gap-1.5 text-slate-500">
              <input
                type="checkbox"
                checked={autoReveal}
                onChange={(e) => setAutoReveal(e.target.checked)}
                className="h-3.5 w-3.5 accent-slate-900"
              />
              答错后自动显示原文
            </label>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => revealAll('en')}
                className="text-slate-500 hover:text-slate-900"
              >
                展开全部原文
              </button>
              <span className="text-slate-200">·</span>
              <button
                type="button"
                onClick={() => revealAll('zh')}
                className="text-slate-500 hover:text-slate-900"
              >
                展开全部翻译
              </button>
              <span className="text-slate-200">·</span>
              <button
                type="button"
                onClick={() => revealAll('none')}
                className="text-slate-500 hover:text-slate-900"
              >
                全部折叠
              </button>
            </div>
            <div className="ml-auto flex items-center gap-2">
              <button
                type="button"
                disabled={rebuildMutation.isPending || processing || !data?.has_audio}
                onClick={() => rebuildMutation.mutate()}
                title="用当前模型重新识别（会重建句子，原笔记与听写记录将清除）"
                className="flex items-center gap-1 rounded-lg border border-slate-200 px-2 py-1 text-[11px] text-slate-600 transition-colors hover:bg-slate-50 disabled:opacity-40"
              >
                <RefreshIcon className="h-3.5 w-3.5" />
                重新识别
              </button>
              {clipsReady && (
                <button
                  type="button"
                  disabled={clearClipsMutation.isPending}
                  onClick={() => clearClipsMutation.mutate()}
                  title="删除句子切片以回收磁盘空间"
                  className="rounded-lg border border-slate-200 px-2 py-1 text-[11px] text-slate-500 transition-colors hover:bg-slate-50 disabled:opacity-40"
                >
                  清理切片
                </button>
              )}
            </div>
          </div>
        )}

        {status === 'failed' && data?.error && (
          <div className="mt-2 flex items-start gap-1.5 rounded-lg bg-red-50 px-3 py-2 text-[12px] text-red-600">
            <AlertIcon className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span>{data.error}</span>
          </div>
        )}

        {processing && (
          <div className="mt-2.5">
            <div className="flex items-center justify-between text-[11px] text-slate-400">
              <span>正在处理：解码 → 识别 → 翻译 → 切片</span>
              <span className="tabular-nums">
                {live?.stage ?? STATUS_LABEL[status] ?? status} {progress}%
              </span>
            </div>
            <div className="mt-1 h-1 w-full overflow-hidden rounded-full bg-slate-100">
              <div
                className="h-full rounded-full bg-slate-900 transition-[width] duration-500"
                style={{ width: `${Math.max(2, progress)}%` }}
              />
            </div>
          </div>
        )}

        {isLoading && <p className="py-3 text-center text-[13px] text-slate-400">加载中…</p>}
        {isError && (
          <p className="py-3 text-center text-[13px] text-red-600">{(error as Error).message}</p>
        )}
        {notice && <p className="pt-2 text-[12px] text-sky-700">{notice}</p>}
      </div>

      {/* --------------------------- 句子舞台 --------------------------- */}
      {current ? (
        <SentenceStage
          key={current.id}
          sentence={current}
          clip={clip}
          highlight={highlightId === current.id}
          showEn={revealEn[current.id] ?? false}
          showZh={revealZh[current.id] ?? false}
          onToggleEn={() => setRevealEn((prev) => ({ ...prev, [current.id]: !(prev[current.id] ?? false) }))}
          onToggleZh={() => setRevealZh((prev) => ({ ...prev, [current.id]: !(prev[current.id] ?? false) }))}
          autoReveal={autoReveal}
          draft={drafts[current.id] ?? EMPTY_DRAFT}
          onDraft={(patch) => patchDraft(current.id, patch)}
          onRecorded={(stat) => setStats((prev) => ({ ...prev, [current.id]: stat }))}
          editing={editingId === current.id}
          onStartEdit={() => setEditingId(current.id)}
          onCancelEdit={() => setEditingId(null)}
          onSave={(patch) => editMutation.mutate({ sid: current.id, patch })}
          onRetranslate={() => retranslateMutation.mutate(current.id)}
          onMergeNext={() => mergeMutation.mutate(current.id)}
          onSplitAtPlayhead={(atMs) => splitMutation.mutate({ sid: current.id, atMs })}
          onWordClick={(word, rect) =>
            setWordTarget({
              word,
              sentenceId: current.id,
              mediaId: id,
              context: current.text_en,
              rect,
            })
          }
          correctOpen={correctOpen}
          setCorrectOpen={setCorrectOpen}
          noteOpen={noteOpen}
          setNoteOpen={setNoteOpen}
          busy={
            editMutation.isPending ||
            retranslateMutation.isPending ||
            splitMutation.isPending ||
            mergeMutation.isPending
          }
        />
      ) : (
        <div className="flex min-h-0 flex-1 items-center justify-center rounded-xl border border-slate-200 bg-white px-5 text-center">
          <p className="text-[13px] text-slate-400">
            {!data
              ? '加载中…'
              : processing
                ? '正在处理，完成后会自动出现句子'
                : status === 'failed'
                  ? '处理失败，请查看上方错误信息后在「工具」里重试'
                  : '还没有句子。'}
          </p>
        </div>
      )}

      {/* --------------------------- 底部：翻页 + 宫格 --------------------------- */}
      {total > 0 && (
        <div className="shrink-0 rounded-xl border border-slate-200 bg-white px-3 py-2 sm:px-4 sm:py-2.5">
          <div className="flex items-center gap-2 sm:gap-3">
            <button
              type="button"
              disabled={index <= 0}
              onClick={() => goTo(index - 1)}
              className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs text-slate-600 transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
            >
              ← 上一句
            </button>

            <div className="flex min-w-0 flex-1 items-center gap-2">
              <span className="shrink-0 text-[11px] tabular-nums text-slate-400">
                {current ? `${formatSeconds(current.start_ms / 1000)} – ${formatSeconds(current.end_ms / 1000)}` : ''}
              </span>
              <div className="ml-auto flex shrink-0 items-center gap-2 text-[10px] text-slate-400">
                <span className="flex items-center gap-1">
                  <span className="h-2.5 w-2.5 rounded-sm bg-emerald-200" />已掌握
                </span>
                <span className="flex items-center gap-1">
                  <span className="h-2.5 w-2.5 rounded-sm bg-amber-200" />练过
                </span>
                <span className="flex items-center gap-1">
                  <span className="h-2.5 w-2.5 rounded-sm bg-slate-200" />未听
                </span>
                <span className="hidden sm:inline">· ← → 翻页</span>
              </div>
            </div>

            <button
              type="button"
              disabled={index >= total - 1}
              onClick={() => goTo(index + 1)}
              className="rounded-lg bg-slate-900 px-3 py-1.5 text-xs text-white transition-colors hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-40"
            >
              下一句 →
            </button>
          </div>

          {/* 句子索引宫格：点击直跳。手机上加高格子到 32px 以满足触摸目标 */}
          <div
            data-testid="sentence-grid"
            className="mt-2 flex max-h-24 flex-wrap gap-1 overflow-y-auto sm:max-h-[7.5rem]"
          >
            {effective.map((sentence, i) => (
              <button
                key={sentence.id}
                type="button"
                onClick={() => goTo(i)}
                title={
                  `第 ${i + 1} 句` +
                  (sentence.attempt_count > 0
                    ? ` · 练过 ${sentence.attempt_count} 次 · 最佳 ${sentence.best_accuracy}%`
                    : ' · 还没听写')
                }
                className={[
                  // 触摸目标统一 32px：手机和 iPad 都是手指操作，按屏宽分档是错的
                  'h-8 min-w-[2rem] rounded-md px-1 text-[11px] tabular-nums transition-colors',
                  gridClass(sentence, i === index),
                ].join(' ')}
              >
                {i + 1}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// --------------------------- 句子舞台 ---------------------------

interface SentenceStageProps {
  sentence: SentenceItem
  clip: ReturnType<typeof useClipPlayer>
  highlight: boolean
  showEn: boolean
  showZh: boolean
  onToggleEn: () => void
  onToggleZh: () => void
  autoReveal: boolean
  draft: Draft
  onDraft: (patch: Partial<Draft>) => void
  onRecorded: (stat: StatOverride) => void
  editing: boolean
  onStartEdit: () => void
  onCancelEdit: () => void
  onSave: (patch: { text_en?: string; text_zh?: string }) => void
  onRetranslate: () => void
  onMergeNext: () => void
  onSplitAtPlayhead: (atMs: number) => void
  onWordClick: (word: string, rect: WordRect) => void
  correctOpen: boolean
  setCorrectOpen: (next: boolean) => void
  noteOpen: boolean
  setNoteOpen: (next: boolean) => void
  busy: boolean
}

function SentenceStage({
  sentence,
  clip,
  highlight,
  showEn,
  showZh,
  onToggleEn,
  onToggleZh,
  autoReveal,
  draft,
  onDraft,
  onRecorded,
  editing,
  onStartEdit,
  onCancelEdit,
  onSave,
  onRetranslate,
  onMergeNext,
  onSplitAtPlayhead,
  onWordClick,
  correctOpen,
  setCorrectOpen,
  noteOpen,
  setNoteOpen,
  busy,
}: SentenceStageProps) {
  const [draftEn, setDraftEn] = useState(sentence.text_en)
  const [draftZh, setDraftZh] = useState(sentence.text_zh)

  useEffect(() => {
    setDraftEn(sentence.text_en)
    setDraftZh(sentence.text_zh)
  }, [sentence.text_en, sentence.text_zh, editing])

  const isActive = clip.activeId === sentence.id
  const isPlaying = isActive && clip.playing
  const canSplit = isActive && clip.currentTime > 0.4

  // 播放位置 → 绝对时间（切片带 120ms 首部留白，这里回算）
  const playheadMs = Math.round(sentence.start_ms - CLIP_PAD_MS + clip.currentTime * 1000)
  const spanMs = sentence.end_ms - sentence.start_ms

  // A-B 循环：A 未设 → 设 A；A 已设 B 未设 → 设 B；都已设 → 清除
  const abActive = isActive && clip.abStart !== null && clip.abEnd !== null
  const cycleAB = () => {
    if (!sentence.clip_url) return
    if (clip.abStart === null) {
      if (isActive) {
        clip.setAB(sentence.id, Math.max(0, clip.currentTime), null)
      } else {
        clip.play(sentence.id, sentence.clip_url)
        clip.setAB(sentence.id, 0, null)
      }
      return
    }
    if (clip.abEnd === null) {
      const t = clip.currentTime
      if (t > clip.abStart + 0.2) clip.setAB(sentence.id, clip.abStart, t)
      else clip.setAB(sentence.id, t, null) // 与 A 太近，视为重设 A
      return
    }
    clip.clearAB()
  }

  const iconBtn =
    'flex h-8 w-8 items-center justify-center rounded-full transition-colors disabled:cursor-not-allowed'
  const chipBtn =
    'flex h-8 items-center gap-1 rounded-lg border px-2 text-[11px] transition-colors'

  return (
    <div
      data-testid="sentence-stage-card"
      className={[
        'flex min-h-0 flex-1 flex-col gap-2 rounded-xl border bg-white p-3 transition-colors sm:gap-3 sm:p-4',
        highlight ? 'border-amber-400 ring-2 ring-amber-200' : 'border-slate-200',
      ].join(' ')}
    >
      {/* 句子工具行 */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="shrink-0 text-[11px] tabular-nums text-slate-400">
          #{sentence.idx + 1}
        </span>

        <button
          type="button"
          disabled={!sentence.clip_url}
          onClick={() => sentence.clip_url && clip.toggle(sentence.id, sentence.clip_url)}
          title={sentence.clip_url ? '播放本句' : '该句切片不可用'}
          className={[
            iconBtn,
            sentence.clip_url
              ? 'bg-slate-900 text-white hover:bg-slate-700'
              : 'bg-slate-100 text-slate-300',
          ].join(' ')}
        >
          {isPlaying ? <PauseIcon className="h-3 w-3" /> : <PlayIcon className="ml-0.5 h-3 w-3" />}
        </button>

        <button
          type="button"
          disabled={!sentence.clip_url}
          onClick={() => clip.setLoop(!clip.loop)}
          title={clip.loop ? '关闭单句循环' : '单句循环'}
          className={[
            chipBtn,
            clip.loop
              ? 'border-slate-900 bg-slate-900 text-white'
              : 'border-slate-200 text-slate-500 hover:bg-slate-50',
            sentence.clip_url ? '' : 'cursor-not-allowed opacity-40',
          ].join(' ')}
        >
          <LoopIcon className="h-3.5 w-3.5" />
          循环
        </button>

        {/* A-B 循环（FR-A1）：点一下设 A、再点设 B、再点清除 */}
        <button
          type="button"
          disabled={!sentence.clip_url}
          onClick={cycleAB}
          title={
            !sentence.clip_url
              ? '该句切片不可用'
              : clip.abStart === null
                ? '设定 A 点（开始片段循环）'
                : clip.abEnd === null
                  ? '在当前位置设定 B 点'
                  : '清除 A-B 循环'
          }
          className={[
            chipBtn,
            'tabular-nums',
            abActive
              ? 'border-sky-600 bg-sky-600 text-white'
              : clip.abStart !== null
                ? 'border-sky-300 bg-sky-50 text-sky-700'
                : 'border-slate-200 text-slate-500 hover:bg-slate-50',
            sentence.clip_url ? '' : 'cursor-not-allowed opacity-40',
          ].join(' ')}
        >
          <ABLoopIcon className="h-3.5 w-3.5" />
          {clip.abStart === null
            ? 'A-B'
            : clip.abEnd === null
              ? `A ${formatSeconds(clip.abStart)}`
              : `${formatSeconds(clip.abStart)}–${formatSeconds(clip.abEnd)}`}
        </button>

        <span className="text-[11px] tabular-nums text-slate-400">
          {formatSeconds(sentence.start_ms / 1000)} – {formatSeconds(sentence.end_ms / 1000)}
          <span className="ml-1 text-slate-300">({(spanMs / 1000).toFixed(1)}s)</span>
        </span>

        {isActive && clip.duration > 0 && (
          <span className="text-[11px] tabular-nums text-slate-500">
            {formatSeconds(clip.currentTime)} / {formatSeconds(clip.duration)}
          </span>
        )}

        {sentence.attempt_count > 0 && (
          <span
            className={[
              'rounded-full px-2 py-0.5 text-[10px] tabular-nums',
              sentence.mastered ? 'bg-emerald-50 text-emerald-600' : 'bg-amber-50 text-amber-600',
            ].join(' ')}
            title={`练过 ${sentence.attempt_count} 次，最佳 ${sentence.best_accuracy}%`}
          >
            {sentence.mastered ? '已掌握' : `最佳 ${sentence.best_accuracy}%`}
          </span>
        )}

        <div className="ml-auto flex items-center gap-1">
          <button
            type="button"
            data-testid="toggle-note"
            onClick={() => setNoteOpen(!noteOpen)}
            title="本句笔记"
            className={[
              chipBtn,
              noteOpen
                ? 'border-slate-900 bg-slate-900 text-white'
                : 'border-slate-200 text-slate-600 hover:bg-slate-50',
            ].join(' ')}
          >
            <NoteIcon className="h-3.5 w-3.5" />
            笔记
          </button>
          <button
            type="button"
            data-testid="toggle-correct"
            onClick={() => setCorrectOpen(!correctOpen)}
            title="校对：改原文 / 改时间 / 拆分 / 合并 / 重译"
            className={[
              chipBtn,
              correctOpen
                ? 'border-slate-900 bg-slate-900 text-white'
                : 'border-slate-200 text-slate-600 hover:bg-slate-50',
            ].join(' ')}
          >
            <PencilIcon className="h-3.5 w-3.5" />
            校对
          </button>
        </div>
      </div>

      {/* 句子级进度条（拖动定位，便于精确设定 A-B 点） */}
      {isActive && clip.duration > 0 && (
        <div className="flex shrink-0 items-center gap-2">
          <input
            type="range"
            min={0}
            max={clip.duration}
            step={0.05}
            value={Math.min(clip.currentTime, clip.duration)}
            onChange={(e) => clip.seek(Number(e.target.value))}
            title="拖动定位（配合 A-B 循环精抠片段）"
            className="h-1 w-full cursor-pointer accent-sky-600"
          />
          <span className="shrink-0 text-[10px] tabular-nums text-slate-400">
            {formatSeconds(clip.currentTime)}/{formatSeconds(clip.duration)}
          </span>
        </div>
      )}

      {editing ? (
        <div className="flex min-h-0 flex-1 flex-col gap-2">
          <textarea
            value={draftEn}
            onChange={(e) => setDraftEn(e.target.value)}
            className="min-h-0 flex-1 resize-none rounded-lg border border-slate-300 px-3 py-2 text-[15px] leading-relaxed text-slate-800 outline-none focus:border-slate-500"
          />
          <textarea
            value={draftZh}
            onChange={(e) => setDraftZh(e.target.value)}
            rows={2}
            className="shrink-0 resize-none rounded-lg border border-slate-300 px-3 py-2 text-[13px] leading-relaxed text-slate-600 outline-none focus:border-slate-500"
          />
          <div className="flex shrink-0 items-center justify-end gap-2">
            <button
              type="button"
              onClick={onCancelEdit}
              className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-50"
            >
              取消
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => onSave({ text_en: draftEn, text_zh: draftZh })}
              className="flex items-center gap-1.5 rounded-lg bg-slate-900 px-3 py-1.5 text-xs text-white hover:bg-slate-700 disabled:opacity-40"
            >
              <CheckIcon className="h-3.5 w-3.5" />
              保存
            </button>
          </div>
        </div>
      ) : (
        <>
          {/* 正文舞台：一句一屏，字号随句长自适应 */}
          <div className="min-h-0 flex-1 overflow-y-auto" data-testid="sentence-stage">
            <div className="flex min-h-full flex-col items-center justify-center py-1 text-center">
              {showEn ? (
              <ClickableText
                text={sentence.text_en}
                onWordClick={onWordClick}
                fontSize={stageFontSize(sentence.text_en.length)}
                trailing={
                  sentence.is_edited ? (
                    <span className="ml-2 rounded bg-amber-50 px-1.5 py-0.5 align-middle text-[10px] text-amber-600">
                      已校对
                    </span>
                  ) : null
                }
              />
            ) : (
              <div className="my-4 flex items-center gap-2 rounded-lg bg-slate-50 px-4 py-2.5 text-[13px] text-slate-400">
                <EyeOffIcon className="h-4 w-4" />
                原文已隐藏 —— 先听，再写下来
              </div>
            )}

            {/* 翻译 */}
            <div className="mt-3">
              {showZh ? (
                <p
                  className="leading-relaxed text-slate-500"
                  style={{ fontSize: translationFontSize(sentence.text_zh.length) }}
                >
                  {sentence.text_zh || (
                    <span className="text-amber-600">翻译缺失，可用「校对」重译或手改</span>
                  )}
                </p>
              ) : (
                <span className="text-[12px] text-slate-300">翻译已隐藏</span>
              )}
            </div>

            <div className="mt-2 flex items-center gap-3">
              <button
                type="button"
                onClick={onToggleEn}
                className="flex items-center gap-1 text-[11px] text-slate-500 transition-colors hover:text-slate-800"
              >
                {showEn ? <EyeOffIcon className="h-3.5 w-3.5" /> : <EyeIcon className="h-3.5 w-3.5" />}
                {showEn ? '隐藏原文' : '显示原文'}
              </button>
              <button
                type="button"
                onClick={onToggleZh}
                className="flex items-center gap-1 text-[11px] text-slate-500 transition-colors hover:text-slate-800"
              >
                {showZh ? <EyeOffIcon className="h-3.5 w-3.5" /> : <EyeIcon className="h-3.5 w-3.5" />}
                {showZh ? '隐藏翻译' : '显示翻译'}
              </button>
            </div>
            </div>
          </div>

          {/* 校对面板（低频，默认收起） */}
          {correctOpen && (
            <div className="flex shrink-0 flex-wrap items-center gap-2 rounded-lg border border-slate-200 bg-slate-50/70 px-3 py-2">
              <span className="text-[11px] text-slate-400">校对：</span>
              {canSplit && (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => onSplitAtPlayhead(playheadMs)}
                  title={`在播放位置（${formatSeconds(playheadMs / 1000)}）拆分`}
                  className="flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-2 py-1 text-[11px] text-slate-600 transition-colors hover:bg-slate-50 disabled:opacity-40"
                >
                  <ScissorsIcon className="h-3.5 w-3.5" />
                  在 {formatSeconds(playheadMs / 1000)} 拆分
                </button>
              )}
              <button
                type="button"
                disabled={busy}
                onClick={onMergeNext}
                title="与下一句合并"
                className="flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-2 py-1 text-[11px] text-slate-600 transition-colors hover:bg-slate-50 disabled:opacity-40"
              >
                <MergeIcon className="h-3.5 w-3.5" />
                合并下句
              </button>
              <button
                type="button"
                disabled={busy || !sentence.text_en}
                onClick={onRetranslate}
                title="重新翻译本句"
                className="flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-2 py-1 text-[11px] text-slate-600 transition-colors hover:bg-slate-50 disabled:opacity-40"
              >
                <TranslateIcon className="h-3.5 w-3.5" />
                重译
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={onStartEdit}
                title="编辑原文 / 翻译"
                className="flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-2 py-1 text-[11px] text-slate-600 transition-colors hover:bg-slate-50 disabled:opacity-40"
              >
                <PencilIcon className="h-3.5 w-3.5" />
                编辑原文
              </button>
            </div>
          )}

          {/* 句子笔记（M4 / FR-S8） */}
          {noteOpen && (
            <div className="shrink-0">
              <NoteEditor sentenceId={sentence.id} />
            </div>
          )}

          {/* 听写练习区（FR-S2 / FR-S3） */}
          <DictationBox
            sentence={sentence}
            disabled={!sentence.text_en}
            autoReveal={autoReveal}
            draft={draft}
            onDraft={onDraft}
            onReplay={() => {
              if (!sentence.clip_url) return
              clip.seek(0)
              clip.play(sentence.id, sentence.clip_url)
            }}
            onRevealEn={onToggleEn}
            onRecorded={onRecorded}
          />
        </>
      )}
    </div>
  )
}

// --------------------------- 听写输入与校验 ---------------------------

interface DictationBoxProps {
  sentence: SentenceItem
  disabled: boolean
  autoReveal: boolean
  draft: Draft
  onDraft: (patch: Partial<Draft>) => void
  onReplay: () => void
  onRevealEn: () => void
  onRecorded: (stat: StatOverride) => void
}

function DictationBox({
  sentence,
  disabled,
  autoReveal,
  draft,
  onDraft,
  onReplay,
  onRevealEn,
  onRecorded,
}: DictationBoxProps) {
  const queryClient = useQueryClient()
  const [showHistory, setShowHistory] = useState(false)

  // 输入内容与校验结果存在父级（按句 id 归档），翻页回来不会丢
  const text = draft.text
  const result = draft.result

  const submit = useMutation({
    mutationFn: (input: string) => submitAttempt(sentence.id, input),
    onSuccess: (data) => {
      onDraft({ result: data })
      onRecorded({
        attempt_count: data.attempt_count,
        best_accuracy: data.best_accuracy,
        mastered: data.mastered,
      })
      if (autoReveal && !data.is_correct) onRevealEn()
      void queryClient.invalidateQueries({ queryKey: ['attempts', sentence.id] })
    },
  })

  const history = useQuery({
    queryKey: ['attempts', sentence.id],
    queryFn: () => listAttempts(sentence.id, 20),
    enabled: showHistory,
    staleTime: 0,
  })

  const trimmed = text.trim()
  const canSubmit = !disabled && trimmed.length > 0 && !submit.isPending

  const handleSubmit = () => {
    if (!canSubmit) return
    submit.mutate(trimmed)
  }

  return (
    <div className="shrink-0 rounded-lg border border-slate-200 bg-slate-50/70 p-3">
      <div className="flex items-start gap-2">
        <textarea
          data-testid="dictation-input"
          value={text}
          onChange={(e) => onDraft({ text: e.target.value })}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault()
              handleSubmit()
            }
          }}
          rows={2}
          disabled={disabled}
          placeholder={
            disabled
              ? '该句没有标准答案，无法听写'
              : '听音频，写下你听到的内容…（Enter 提交，Shift+Enter 换行）'
          }
          className="min-h-[46px] flex-1 resize-y rounded-lg border border-slate-300 bg-white px-3 py-2 text-[14px] leading-relaxed text-slate-800 outline-none transition-colors focus:border-slate-500 disabled:bg-slate-100"
        />
        <div className="flex shrink-0 flex-col gap-1.5">
          <button
            type="button"
            disabled={!canSubmit}
            onClick={handleSubmit}
            className="flex items-center justify-center gap-1.5 rounded-lg bg-slate-900 px-3 py-2 text-xs text-white transition-colors hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-40"
          >
            <SendIcon className="h-3.5 w-3.5" />
            {submit.isPending ? '校验中' : '提交'}
          </button>
          <div className="flex gap-1.5">
            <button
              type="button"
              disabled={!sentence.clip_url}
              onClick={onReplay}
              title="重听本句"
              className="flex-1 rounded-lg border border-slate-200 bg-white px-2 py-1 text-[11px] text-slate-600 transition-colors hover:bg-slate-50 disabled:opacity-40"
            >
              重听
            </button>
            <button
              type="button"
              disabled={!text}
              onClick={() => {
                onDraft({ text: '', result: null })
                submit.reset()
              }}
              title="清空输入并收起校验结果"
              className="flex-1 rounded-lg border border-slate-200 bg-white px-2 py-1 text-[11px] text-slate-600 transition-colors hover:bg-slate-50 disabled:opacity-40"
            >
              清空
            </button>
          </div>
        </div>
      </div>

      {submit.isError && (
        <p className="mt-2 text-[12px] text-red-600">
          提交失败：{(submit.error as Error).message}
        </p>
      )}

      {result && <DiffResult result={result} />}

      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-slate-400">
        <button
          type="button"
          onClick={() => setShowHistory((v) => !v)}
          className="flex items-center gap-1 text-slate-500 transition-colors hover:text-slate-800"
        >
          <HistoryIcon className="h-3.5 w-3.5" />
          {showHistory ? '收起历史' : '听写历史'}
          {sentence.attempt_count > 0 && `（${sentence.attempt_count}）`}
        </button>
        {sentence.last_accuracy !== null && sentence.attempt_count > 0 && (
          <span>
            上次 {sentence.last_accuracy}%
            {sentence.last_input && (
              <span className="text-slate-400">「{truncate(sentence.last_input, 40)}」</span>
            )}
          </span>
        )}
      </div>

      {showHistory && (
        <div className="mt-2 rounded-lg border border-slate-200 bg-white p-2">
          {history.isLoading && <p className="px-1 py-1 text-[12px] text-slate-400">加载中…</p>}
          {history.isError && (
            <p className="px-1 py-1 text-[12px] text-red-500">{(history.error as Error).message}</p>
          )}
          {history.data && history.data.items.length === 0 && (
            <p className="px-1 py-1 text-[12px] text-slate-400">还没有听写记录</p>
          )}
          {history.data && history.data.items.length > 1 && (
            <div className="mb-2 flex items-end gap-[2px] px-1" title="按时间顺序的正确率（左旧右新）">
              {[...history.data.items].reverse().map((item) => (
                <span
                  key={item.id}
                  title={`${item.accuracy}%`}
                  className={[
                    'w-full max-w-[16px] rounded-sm',
                    item.is_correct
                      ? 'bg-emerald-400'
                      : item.accuracy >= 60
                        ? 'bg-amber-400'
                        : 'bg-rose-400',
                  ].join(' ')}
                  style={{ height: `${Math.max(6, Math.round(item.accuracy * 0.32))}px` }}
                />
              ))}
            </div>
          )}
          {history.data?.items.map((item) => (
            <div
              key={item.id}
              className="flex items-baseline justify-between gap-3 border-b border-slate-50 px-1 py-1 text-[12px] last:border-0"
            >
              <span className="min-w-0 flex-1 truncate text-slate-600" title={item.input}>
                {item.input || <span className="text-slate-300">（空）</span>}
              </span>
              <span
                className={`shrink-0 tabular-nums ${item.is_correct ? 'text-emerald-600' : 'text-slate-500'}`}
              >
                {item.accuracy}%
              </span>
              <span className="shrink-0 text-[11px] text-slate-300">
                {formatRelative(item.created_at)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function truncate(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max)}…` : text
}

// --------------------------- 可点击原文（M4） ---------------------------

/** 分隔出单词；捕获组让 split 结果里奇数索引为单词本身。 */
const WORD_SPLIT = /([A-Za-z][A-Za-z'’-]*)/g

/** 把英文原文按单词拆开渲染，单词可点击以唤起查词浮层（FR-S6）。 */
function ClickableText({
  text,
  onWordClick,
  fontSize,
  trailing,
}: {
  text: string
  onWordClick: (word: string, rect: WordRect) => void
  fontSize: string
  trailing?: React.ReactNode
}) {
  if (!text) {
    return <p className="text-[15px] leading-relaxed text-slate-400">（空）</p>
  }
  const parts = text.split(WORD_SPLIT)
  return (
    <p
      data-testid="sentence-text"
      className="font-medium leading-[1.4] text-slate-800"
      style={{ fontSize }}
    >
      {parts.map((part, index) =>
        index % 2 === 1 ? (
          <button
            key={index}
            type="button"
            onClick={(event) => {
              const rect = event.currentTarget.getBoundingClientRect()
              onWordClick(part, {
                top: rect.top,
                left: rect.left,
                bottom: rect.bottom,
                width: rect.width,
              })
            }}
            title={`查询「${part}」`}
            className="rounded px-0.5 transition-colors hover:bg-sky-100 hover:text-sky-800 focus:bg-sky-100 focus:outline-none"
          >
            {part}
          </button>
        ) : (
          <span key={index}>{part}</span>
        ),
      )}
      {trailing}
    </p>
  )
}

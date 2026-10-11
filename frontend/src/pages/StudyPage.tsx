/** 学习页：单句听写 + 标红校验 + 结果校对（M2 / M3）。
 *
 * M2 交付：识别原文 / 中文翻译 / 句子切片 + 人工校对（改文本 / 改时间 / 拆分 / 合并 / 重译）。
 * M3 交付：听写输入框、词级标红校验、正确率与掌握度、听写历史（FR-S1~S5、FR-A4）。
 */

import { useEffect, useMemo, useRef, useState } from 'react'
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

/** 被点击单词在视口中的位置（用于定位浮层） */
export interface WordRect {
  top: number
  left: number
  bottom: number
  width: number
}

export default function StudyPage() {
  const { mediaId } = useParams()
  const id = Number(mediaId)
  const queryClient = useQueryClient()
  const openPlayer = usePlayer((s) => s.open)
  const currentMedia = usePlayer((s) => s.current)
  const clip = useClipPlayer()

  const [live, setLive] = useState<ProgressEventData | null>(null)
  const [revealEn, setRevealEn] = useState<Record<number, boolean>>({})
  const [revealZh, setRevealZh] = useState<Record<number, boolean>>({})
  const [editingId, setEditingId] = useState<number | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [autoReveal, setAutoReveal] = useState(true)
  const [stats, setStats] = useState<Record<number, StatOverride>>({})
  const [wordTarget, setWordTarget] = useState<WordPopoverTarget | null>(null)
  const [notesOpen, setNotesOpen] = useState(false)
  const [highlightId, setHighlightId] = useState<number | null>(null)

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
      void queryClient.invalidateQueries({ queryKey: ['media', id] })
    },
    onError: (e: Error) => setNotice(`重新识别失败：${e.message}`),
  })

  const clearClipsMutation = useMutation({
    mutationFn: () => clearClips(id),
    onSuccess: () => {
      setNotice('切片已清理，释放磁盘空间（逐句播放暂不可用）')
      clip.stop()
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

  /** 从笔记面板跳到某句：展开原文 + 滚动定位 + 短暂高亮 */
  const jumpToSentence = (sid: number) => {
    setRevealEn((prev) => ({ ...prev, [sid]: true }))
    setHighlightId(sid)
    window.setTimeout(() => {
      document
        .getElementById(`sentence-${sid}`)
        ?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }, 80)
    window.setTimeout(() => setHighlightId((cur) => (cur === sid ? null : cur)), 2400)
  }

  return (
    <div className="space-y-5">
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

      <div className="flex flex-wrap items-center gap-3">
        <Link
          to="/"
          className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs text-slate-600 transition-colors hover:bg-slate-50"
        >
          ← 媒体库
        </Link>
        <span className="text-[12px] text-slate-400">
          学习页 · 听音频 → 输入听到的内容 → 提交后标红比对
        </span>
        <label className="ml-auto flex cursor-pointer items-center gap-1.5 text-[12px] text-slate-500">
          <input
            type="checkbox"
            checked={autoReveal}
            onChange={(e) => setAutoReveal(e.target.checked)}
            className="h-3.5 w-3.5 accent-slate-900"
          />
          提交后自动显示原文
        </label>
      </div>

      {isLoading && (
        <p className="rounded-xl border border-slate-200 bg-white px-5 py-8 text-center text-[13px] text-slate-400">
          加载中…
        </p>
      )}

      {isError && (
        <p className="rounded-xl border border-red-100 bg-red-50 px-5 py-8 text-center text-[13px] text-red-600">
          {(error as Error).message}
        </p>
      )}

      {notice && (
        <div className="rounded-lg border border-sky-100 bg-sky-50 px-4 py-2.5 text-[13px] text-sky-700">
          {notice}
        </div>
      )}

      {data && (
        <>
          {/* 头部信息 */}
          <div className="rounded-xl border border-slate-200 bg-white p-5">
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <h2 className="truncate text-[16px] font-medium text-slate-900">{data.title}</h2>
                <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-slate-400">
                  <span className="tabular-nums">{formatDuration(data.duration_ms)}</span>
                  <span>{formatBytes(data.size_bytes)}</span>
                  <span>{data.type === 'video' ? '视频（仅音轨）' : '音频'}</span>
                  {sentences.length > 0 && <span>共 {sentences.length} 句</span>}
                  <span className="truncate">{data.original_name}</span>
                </div>
              </div>

              <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">
                <span
                  className={[
                    'rounded-full px-2.5 py-1 text-[11px]',
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
                <button
                  type="button"
                  disabled={!playable}
                  onClick={() => openPlayer(data, true)}
                  className={[
                    'flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs transition-colors',
                    playable
                      ? 'bg-slate-900 text-white hover:bg-slate-700'
                      : 'cursor-not-allowed bg-slate-100 text-slate-400',
                  ].join(' ')}
                >
                  <PlayIcon className="h-3 w-3" />
                  {currentMedia?.id === data.id ? '正在整段播放' : '整段播放'}
                </button>
                <button
                  type="button"
                  disabled={rebuildMutation.isPending || processing || !data.has_audio}
                  onClick={() => rebuildMutation.mutate()}
                  title="用当前模型重新识别（会重建句子，原笔记与听写记录将清除）"
                  className="flex items-center gap-1.5 rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs text-slate-600 transition-colors hover:bg-slate-50 disabled:opacity-40"
                >
                  <RefreshIcon className="h-3.5 w-3.5" />
                  重新识别
                </button>
                {sentences.length > 0 && (
                  <button
                    type="button"
                    onClick={() => setNotesOpen(true)}
                    title="查看本媒体全部句子笔记"
                    className="flex items-center gap-1.5 rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs text-slate-600 transition-colors hover:bg-slate-50"
                  >
                    <NoteIcon className="h-3.5 w-3.5" />
                    笔记{noteCount > 0 ? `（${noteCount}）` : ''}
                  </button>
                )}
                {clipsReady && (
                  <button
                    type="button"
                    disabled={clearClipsMutation.isPending}
                    onClick={() => clearClipsMutation.mutate()}
                    title="删除句子切片以回收磁盘空间"
                    className="rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs text-slate-500 transition-colors hover:bg-slate-50 disabled:opacity-40"
                  >
                    清理切片
                  </button>
                )}
              </div>
            </div>

            {status === 'failed' && data.error && (
              <div className="mt-3 flex items-start gap-1.5 rounded-lg bg-red-50 px-3 py-2 text-[12px] text-red-600">
                <AlertIcon className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                <span>{data.error}</span>
              </div>
            )}

            {processing && (
              <div className="mt-3">
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
                <p className="mt-1 text-[11px] text-slate-400">
                  {live?.sentence_count
                    ? `已切分出 ${live.sentence_count} 句`
                    : '完成后会自动出现句子列表'}
                </p>
              </div>
            )}

            {!processing && status === 'done' && !clipsReady && sentences.length > 0 && (
              <p className="mt-3 text-[12px] text-amber-600">
                句子音频切片未就绪（可能已被清理），点击「重新识别」可重建。
              </p>
            )}

            {/* 听写进度 */}
            {sentences.length > 0 && (
              <div className="mt-4 border-t border-slate-100 pt-3">
                <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px]">
                  <span className="flex items-center gap-1.5 text-slate-600">
                    <TargetIcon className="h-3.5 w-3.5 text-slate-400" />
                    已听写
                    <span className="font-medium tabular-nums text-slate-900">
                      {summary.attempted}/{summary.total}
                    </span>
                    句
                  </span>
                  <span className="text-slate-400">
                    已掌握 <span className="tabular-nums text-emerald-600">{summary.mastered}</span> 句
                  </span>
                  <span className="text-slate-400">
                    提交 <span className="tabular-nums">{summary.attempts}</span> 次
                  </span>
                  {summary.attempted > 0 && (
                    <span className="text-slate-400">
                      平均最佳 <span className="tabular-nums text-slate-600">{summary.avg}%</span>
                    </span>
                  )}
                  <div className="ml-auto flex items-center gap-2 text-[11px]">
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
                </div>
                <div className="mt-2 h-1 w-full overflow-hidden rounded-full bg-slate-100">
                  <div
                    className="h-full rounded-full bg-emerald-500 transition-[width] duration-500"
                    style={{
                      width: `${summary.total ? (summary.mastered / summary.total) * 100 : 0}%`,
                    }}
                  />
                </div>
              </div>
            )}
          </div>

          {/* 句子列表 */}
          <div className="space-y-3">
            {sentences.length === 0 && !processing && (
              <div className="rounded-xl border border-slate-200 bg-white px-5 py-10 text-center">
                <p className="text-[13px] text-slate-400">
                  {status === 'failed'
                    ? '处理失败，请查看上方错误信息后重试'
                    : '还没有句子。'}
                </p>
              </div>
            )}

            {effective.map((sentence) => (
              <SentenceCard
                key={sentence.id}
                sentence={sentence}
                clip={clip}
                highlight={highlightId === sentence.id}
                revealEn={revealEn}
                revealZh={revealZh}
                setRevealEn={setRevealEn}
                setRevealZh={setRevealZh}
                autoReveal={autoReveal}
                onRecorded={(stat) => setStats((prev) => ({ ...prev, [sentence.id]: stat }))}
                editing={editingId === sentence.id}
                onStartEdit={() => setEditingId(sentence.id)}
                onCancelEdit={() => setEditingId(null)}
                onSave={(patch) => editMutation.mutate({ sid: sentence.id, patch })}
                onRetranslate={() => retranslateMutation.mutate(sentence.id)}
                onMergeNext={() => mergeMutation.mutate(sentence.id)}
                onSplitAtPlayhead={(atMs) =>
                  splitMutation.mutate({ sid: sentence.id, atMs })
                }
                onWordClick={(word, rect) =>
                  setWordTarget({
                    word,
                    sentenceId: sentence.id,
                    mediaId: id,
                    context: sentence.text_en,
                    rect,
                  })
                }
                busy={
                  editMutation.isPending ||
                  retranslateMutation.isPending ||
                  splitMutation.isPending ||
                  mergeMutation.isPending
                }
              />
            ))}
          </div>
        </>
      )}
    </div>
  )
}

// --------------------------- 句子卡片 ---------------------------

interface SentenceCardProps {
  sentence: SentenceItem
  clip: ReturnType<typeof useClipPlayer>
  highlight: boolean
  revealEn: Record<number, boolean>
  revealZh: Record<number, boolean>
  setRevealEn: React.Dispatch<React.SetStateAction<Record<number, boolean>>>
  setRevealZh: React.Dispatch<React.SetStateAction<Record<number, boolean>>>
  autoReveal: boolean
  onRecorded: (stat: StatOverride) => void
  editing: boolean
  onStartEdit: () => void
  onCancelEdit: () => void
  onSave: (patch: { text_en?: string; text_zh?: string }) => void
  onRetranslate: () => void
  onMergeNext: () => void
  onSplitAtPlayhead: (atMs: number) => void
  onWordClick: (word: string, rect: WordRect) => void
  busy: boolean
}

function SentenceCard({
  sentence,
  clip,
  highlight,
  revealEn,
  revealZh,
  setRevealEn,
  setRevealZh,
  autoReveal,
  onRecorded,
  editing,
  onStartEdit,
  onCancelEdit,
  onSave,
  onRetranslate,
  onMergeNext,
  onSplitAtPlayhead,
  onWordClick,
  busy,
}: SentenceCardProps) {
  const [draftEn, setDraftEn] = useState(sentence.text_en)
  const [draftZh, setDraftZh] = useState(sentence.text_zh)

  useEffect(() => {
    setDraftEn(sentence.text_en)
    setDraftZh(sentence.text_zh)
  }, [sentence.text_en, sentence.text_zh, editing])

  const isActive = clip.activeId === sentence.id
  const isPlaying = isActive && clip.playing
  const showEn = revealEn[sentence.id] ?? false
  const showZh = revealZh[sentence.id] ?? false
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

  return (
    <div
      id={`sentence-${sentence.id}`}
      className={[
        'rounded-xl border bg-white p-4 transition-colors',
        highlight
          ? 'border-amber-400 ring-2 ring-amber-200'
          : isActive
            ? 'border-slate-900'
            : 'border-slate-200',
      ].join(' ')}
    >
      {/* 工具栏 */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="w-9 shrink-0 text-[11px] tabular-nums text-slate-400">
          #{sentence.idx + 1}
        </span>

        <button
          type="button"
          disabled={!sentence.clip_url}
          onClick={() =>
            sentence.clip_url && clip.toggle(sentence.id, sentence.clip_url)
          }
          title={sentence.clip_url ? '播放本句' : '该句切片不可用'}
          className={[
            'flex h-8 w-8 items-center justify-center rounded-full transition-colors',
            sentence.clip_url
              ? 'bg-slate-900 text-white hover:bg-slate-700'
              : 'cursor-not-allowed bg-slate-100 text-slate-300',
          ].join(' ')}
        >
          {isPlaying ? (
            <PauseIcon className="h-3 w-3" />
          ) : (
            <PlayIcon className="ml-0.5 h-3 w-3" />
          )}
        </button>

        <button
          type="button"
          disabled={!sentence.clip_url}
          onClick={() => clip.setLoop(!clip.loop)}
          title={clip.loop ? '关闭单句循环' : '单句循环'}
          className={[
            'flex h-8 items-center gap-1 rounded-lg border px-2 text-[11px] transition-colors',
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
            'flex h-8 items-center gap-1 rounded-lg border px-2 text-[11px] tabular-nums transition-colors',
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
              sentence.mastered
                ? 'bg-emerald-50 text-emerald-600'
                : 'bg-amber-50 text-amber-600',
            ].join(' ')}
            title={`练过 ${sentence.attempt_count} 次，最佳 ${sentence.best_accuracy}%`}
          >
            {sentence.mastered ? '已掌握' : `最佳 ${sentence.best_accuracy}%`}
          </span>
        )}

        <div className="ml-auto flex items-center gap-1">
          {canSplit && (
            <button
              type="button"
              disabled={busy}
              onClick={() => onSplitAtPlayhead(playheadMs)}
              title={`在播放位置（${formatSeconds(playheadMs / 1000)}）拆分`}
              className="flex items-center gap-1 rounded-lg border border-slate-200 px-2 py-1 text-[11px] text-slate-600 transition-colors hover:bg-slate-50 disabled:opacity-40"
            >
              <ScissorsIcon className="h-3.5 w-3.5" />
              在此处拆分
            </button>
          )}
          <button
            type="button"
            disabled={busy}
            onClick={onMergeNext}
            title="与下一句合并"
            className="flex items-center gap-1 rounded-lg border border-slate-200 px-2 py-1 text-[11px] text-slate-600 transition-colors hover:bg-slate-50 disabled:opacity-40"
          >
            <MergeIcon className="h-3.5 w-3.5" />
            合并下句
          </button>
          <button
            type="button"
            disabled={busy || !sentence.text_en}
            onClick={onRetranslate}
            title="重新翻译本句"
            className="flex items-center gap-1 rounded-lg border border-slate-200 px-2 py-1 text-[11px] text-slate-600 transition-colors hover:bg-slate-50 disabled:opacity-40"
          >
            <TranslateIcon className="h-3.5 w-3.5" />
            重译
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={onStartEdit}
            title="编辑原文 / 翻译"
            className="flex items-center gap-1 rounded-lg border border-slate-200 px-2 py-1 text-[11px] text-slate-600 transition-colors hover:bg-slate-50 disabled:opacity-40"
          >
            <PencilIcon className="h-3.5 w-3.5" />
            编辑
          </button>
        </div>
      </div>

      {/* 句子级进度条（拖动定位，便于精确设定 A-B 点） */}
      {isActive && clip.duration > 0 && (
        <div className="mt-2 flex items-center gap-2">
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

      {/* 内容区 */}
      {editing ? (
        <div className="mt-3 space-y-2">
          <textarea
            value={draftEn}
            onChange={(e) => setDraftEn(e.target.value)}
            rows={2}
            className="w-full resize-y rounded-lg border border-slate-300 px-3 py-2 text-[14px] leading-relaxed text-slate-800 outline-none focus:border-slate-500"
          />
          <textarea
            value={draftZh}
            onChange={(e) => setDraftZh(e.target.value)}
            rows={2}
            className="w-full resize-y rounded-lg border border-slate-300 px-3 py-2 text-[13px] leading-relaxed text-slate-600 outline-none focus:border-slate-500"
          />
          <div className="flex items-center justify-end gap-2">
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
        <div className="mt-3 space-y-3">
          {/* 听写练习区（FR-S2 / FR-S3） */}
          <DictationBox
            sentence={sentence}
            disabled={!sentence.text_en}
            autoReveal={autoReveal}
            onReplay={() => {
              if (!sentence.clip_url) return
              clip.seek(0)
              clip.play(sentence.id, sentence.clip_url)
            }}
            onRevealEn={() => setRevealEn((prev) => ({ ...prev, [sentence.id]: true }))}
            onRecorded={onRecorded}
          />

          {/* 原文（单词可点击查词，FR-S6） */}
          <div className="border-t border-slate-100 pt-2">
            {showEn ? (
              <ClickableText
                text={sentence.text_en}
                onWordClick={onWordClick}
                trailing={
                  sentence.is_edited ? (
                    <span className="ml-2 rounded bg-amber-50 px-1.5 py-0.5 text-[10px] align-middle text-amber-600">
                      已校对
                    </span>
                  ) : null
                }
              />
            ) : (
              <div className="flex h-[26px] items-center rounded bg-slate-50 px-3 text-[12px] text-slate-400">
                原文已隐藏
              </div>
            )}
            <button
              type="button"
              onClick={() => setRevealEn((prev) => ({ ...prev, [sentence.id]: !showEn }))}
              className="mt-1.5 flex items-center gap-1 text-[11px] text-slate-500 transition-colors hover:text-slate-800"
            >
              {showEn ? <EyeOffIcon className="h-3.5 w-3.5" /> : <EyeIcon className="h-3.5 w-3.5" />}
              {showEn ? '隐藏原文' : '显示原文'}
            </button>
          </div>

          {/* 翻译 */}
          <div>
            {showZh ? (
              <p className="text-[13px] leading-relaxed text-slate-600">
                {sentence.text_zh || (
                  <span className="text-amber-600">翻译缺失，可点「重译」或手动编辑</span>
                )}
              </p>
            ) : (
              <div className="flex h-[22px] items-center rounded bg-slate-50 px-3 text-[12px] text-slate-400">
                翻译已隐藏
              </div>
            )}
            <button
              type="button"
              onClick={() => setRevealZh((prev) => ({ ...prev, [sentence.id]: !showZh }))}
              className="mt-1.5 flex items-center gap-1 text-[11px] text-slate-500 transition-colors hover:text-slate-800"
            >
              {showZh ? <EyeOffIcon className="h-3.5 w-3.5" /> : <EyeIcon className="h-3.5 w-3.5" />}
              {showZh ? '隐藏翻译' : '显示翻译'}
            </button>
          </div>

          {/* 句子笔记（M4 / FR-S8） */}
          <NoteEditor sentenceId={sentence.id} />
        </div>
      )}
    </div>
  )
}

// --------------------------- 听写输入与校验 ---------------------------

interface DictationBoxProps {
  sentence: SentenceItem
  disabled: boolean
  autoReveal: boolean
  onReplay: () => void
  onRevealEn: () => void
  onRecorded: (stat: StatOverride) => void
}

function DictationBox({
  sentence,
  disabled,
  autoReveal,
  onReplay,
  onRevealEn,
  onRecorded,
}: DictationBoxProps) {
  const queryClient = useQueryClient()
  const [text, setText] = useState('')
  const [result, setResult] = useState<AttemptResult | null>(null)
  const [showHistory, setShowHistory] = useState(false)

  const submit = useMutation({
    mutationFn: (input: string) => submitAttempt(sentence.id, input),
    onSuccess: (data) => {
      setResult(data)
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
    <div className="rounded-lg border border-slate-200 bg-slate-50/70 p-3">
      <div className="flex items-start gap-2">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault()
              handleSubmit()
            }
          }}
          rows={2}
          disabled={disabled}
          placeholder={
            disabled ? '该句没有标准答案，无法听写' : '听音频，写下你听到的内容…（Enter 提交，Shift+Enter 换行）'
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
                setText('')
                setResult(null)
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
            <p className="px-1 py-1 text-[12px] text-red-500">
              {(history.error as Error).message}
            </p>
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
  trailing,
}: {
  text: string
  onWordClick: (word: string, rect: WordRect) => void
  trailing?: React.ReactNode
}) {
  if (!text) {
    return <p className="text-[15px] leading-relaxed text-slate-400">（空）</p>
  }
  const parts = text.split(WORD_SPLIT)
  return (
    <p className="text-[15px] leading-relaxed text-slate-800">
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

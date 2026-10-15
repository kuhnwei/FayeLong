import { useCallback, useEffect, useRef, useState } from 'react'
import { PLAYBACK_RATES, bindAudioElement, usePlayer } from '../store/player'
import { formatSeconds } from '../utils/format'
import { BackIcon, CloseIcon, ForwardIcon, LoopIcon, PauseIcon, PlayIcon } from './icons'

/** 底部常驻播放条：播放/暂停、前后跳、进度、语速、单曲循环。
 *
 * 布局：两行「标题 + 控制」。
 * 之所以不挤成一行：375px 的手机放不下「±5 秒 + 进度条 + 语速 + 循环 + 关闭」，
 * 硬挤会让进度条被压成一条缝。标题单独一行后，剩下的宽度全给进度条。
 *
 * 它现在是外壳 flex 列里的一段（`shrink-0`），不再是 `fixed` 覆盖层 ——
 * 这样学习页的高度计算不必再为它留 `pb-28` 之类的魔法内边距。
 */
export default function PlayerBar() {
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const [error, setError] = useState<string | null>(null)

  const current = usePlayer((s) => s.current)
  const isPlaying = usePlayer((s) => s.isPlaying)
  const rate = usePlayer((s) => s.rate)
  const loop = usePlayer((s) => s.loop)
  const position = usePlayer((s) => s.position)
  const duration = usePlayer((s) => s.duration)
  const setPlaying = usePlayer((s) => s.setPlaying)
  const setRate = usePlayer((s) => s.setRate)
  const setLoop = usePlayer((s) => s.setLoop)
  const setTimeline = usePlayer((s) => s.setTimeline)
  const seek = usePlayer((s) => s.seek)
  const nudge = usePlayer((s) => s.nudge)
  const close = usePlayer((s) => s.close)
  const toggle = usePlayer((s) => s.toggle)

  /* 用回调 ref 注册 DOM 元素（元素随 current 出现/消失） */
  const attachAudio = useCallback((el: HTMLAudioElement | null) => {
    audioRef.current = el
    bindAudioElement(el)
  }, [])

  /* 切源与播放意图统一在这里处理 */
  useEffect(() => {
    const audio = audioRef.current
    if (!audio || !current) return

    if (audio.dataset.src !== current.stream_url) {
      audio.dataset.src = current.stream_url
      audio.src = current.stream_url
      audio.load()
      setError(null)
    }

    if (isPlaying) {
      void audio.play().catch((err: unknown) => {
        // 快速切换音源时 pending 的 play() 会被中断，属正常情况
        if (err instanceof DOMException && err.name === 'AbortError') return
        setPlaying(false)
      })
    } else {
      audio.pause()
    }
  }, [current, isPlaying, setPlaying])

  useEffect(() => {
    if (audioRef.current) audioRef.current.playbackRate = rate
  }, [rate, current])

  useEffect(() => {
    if (audioRef.current) audioRef.current.loop = loop
  }, [loop, current])

  if (!current) return null

  const max = duration || 0
  const iconBtn = 'shrink-0 rounded-lg p-2 transition-colors'

  return (
    <div
      data-testid="player-bar"
      className="shrink-0 border-t border-slate-200 bg-white pb-[env(safe-area-inset-bottom)]"
    >
      <audio
        ref={attachAudio}
        preload="metadata"
        onLoadedMetadata={(e) => setTimeline(e.currentTarget.currentTime, e.currentTarget.duration)}
        onDurationChange={(e) => setTimeline(e.currentTarget.currentTime, e.currentTarget.duration)}
        onTimeUpdate={(e) => setTimeline(e.currentTarget.currentTime, e.currentTarget.duration)}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => setPlaying(false)}
        onError={() => {
          setPlaying(false)
          setError('音频加载失败，可能仍在处理中')
        }}
      />

      <div className="mx-auto w-full max-w-5xl px-3 py-2 sm:px-6 sm:py-2.5">
        {/* 第一行：标题 + 时间。窄屏上标题独占一行，进度条才有足够宽度 */}
        <div className="mb-1 flex items-baseline gap-2">
          <span className="min-w-0 flex-1 truncate text-[12px] font-medium text-slate-900 sm:text-[13px]">
            {current.title}
          </span>
          <span className="shrink-0 text-[10px] tabular-nums text-slate-400 sm:text-[11px]">
            {error ?? `${formatSeconds(position)} / ${formatSeconds(duration)}`}
          </span>
        </div>

        {/* 第二行：控制 + 进度 */}
        <div className="flex items-center gap-1.5 sm:gap-3">
          <button
            type="button"
            onClick={() => nudge(-5)}
            title="后退 5 秒"
            aria-label="后退 5 秒"
            className={`${iconBtn} text-slate-500 hover:bg-slate-100 hover:text-slate-900`}
          >
            <BackIcon className="h-4 w-4" />
          </button>

          <button
            type="button"
            onClick={toggle}
            title={isPlaying ? '暂停' : '播放'}
            aria-label={isPlaying ? '暂停' : '播放'}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-slate-900 text-white transition-colors hover:bg-slate-700 sm:h-9 sm:w-9"
          >
            {isPlaying ? (
              <PauseIcon className="h-4 w-4" />
            ) : (
              <PlayIcon className="ml-0.5 h-4 w-4" />
            )}
          </button>

          <button
            type="button"
            onClick={() => nudge(5)}
            title="前进 5 秒"
            aria-label="前进 5 秒"
            className={`${iconBtn} text-slate-500 hover:bg-slate-100 hover:text-slate-900`}
          >
            <ForwardIcon className="h-4 w-4" />
          </button>

          <input
            type="range"
            min={0}
            max={max}
            step={0.1}
            value={Math.min(position, max)}
            disabled={max <= 0}
            aria-label="播放进度"
            onChange={(e) => seek(Number(e.target.value))}
            className="h-1 min-w-0 flex-1 cursor-pointer accent-slate-900 disabled:cursor-not-allowed"
          />

          <select
            value={rate}
            onChange={(e) => setRate(Number(e.target.value))}
            title="播放语速"
            aria-label="播放语速"
            className="shrink-0 rounded-lg border border-slate-200 bg-white px-1 py-1 text-[11px] text-slate-600 outline-none focus:border-slate-400 sm:px-2 sm:text-xs"
          >
            {PLAYBACK_RATES.map((value) => (
              <option key={value} value={value}>
                {value}x
              </option>
            ))}
          </select>

          <button
            type="button"
            onClick={() => setLoop(!loop)}
            title={loop ? '关闭单曲循环' : '开启单曲循环'}
            aria-label={loop ? '关闭单曲循环' : '开启单曲循环'}
            className={[
              iconBtn,
              loop
                ? 'bg-slate-900 text-white hover:bg-slate-700'
                : 'text-slate-500 hover:bg-slate-100 hover:text-slate-900',
            ].join(' ')}
          >
            <LoopIcon className="h-4 w-4" />
          </button>

          <button
            type="button"
            onClick={close}
            title="关闭播放器"
            aria-label="关闭播放器"
            className={`${iconBtn} text-slate-400 hover:bg-slate-100 hover:text-slate-700`}
          >
            <CloseIcon className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  )
}

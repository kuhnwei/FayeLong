import { useCallback, useEffect, useRef, useState } from 'react'
import { PLAYBACK_RATES, bindAudioElement, usePlayer } from '../store/player'
import { formatSeconds } from '../utils/format'
import { BackIcon, CloseIcon, ForwardIcon, LoopIcon, PauseIcon, PlayIcon } from './icons'

/** 底部常驻播放条：播放/暂停、前后跳、进度、语速、单曲循环。 */
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

  return (
    <div className="fixed inset-x-0 bottom-0 z-40 border-t border-slate-200 bg-white/95 backdrop-blur">
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

      <div className="mx-auto flex max-w-5xl items-center gap-3 px-6 py-2.5">
        <button
          type="button"
          onClick={() => nudge(-5)}
          title="后退 5 秒"
          className="rounded-lg p-2 text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-900"
        >
          <BackIcon className="h-4 w-4" />
        </button>

        <button
          type="button"
          onClick={toggle}
          title={isPlaying ? '暂停' : '播放'}
          className="flex h-9 w-9 items-center justify-center rounded-full bg-slate-900 text-white transition-colors hover:bg-slate-700"
        >
          {isPlaying ? <PauseIcon className="h-4 w-4" /> : <PlayIcon className="ml-0.5 h-4 w-4" />}
        </button>

        <button
          type="button"
          onClick={() => nudge(5)}
          title="前进 5 秒"
          className="rounded-lg p-2 text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-900"
        >
          <ForwardIcon className="h-4 w-4" />
        </button>

        <div className="min-w-0 flex-1">
          <div className="flex items-baseline justify-between gap-3">
            <span className="truncate text-[13px] font-medium text-slate-900">
              {current.title}
            </span>
            <span className="shrink-0 text-[11px] tabular-nums text-slate-400">
              {error ?? `${formatSeconds(position)} / ${formatSeconds(duration)}`}
            </span>
          </div>
          <input
            type="range"
            min={0}
            max={max}
            step={0.1}
            value={Math.min(position, max)}
            disabled={max <= 0}
            onChange={(e) => seek(Number(e.target.value))}
            className="mt-1 h-1 w-full cursor-pointer accent-slate-900 disabled:cursor-not-allowed"
          />
        </div>

        <select
          value={rate}
          onChange={(e) => setRate(Number(e.target.value))}
          title="播放语速"
          className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs text-slate-600 outline-none focus:border-slate-400"
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
          className={[
            'rounded-lg p-2 transition-colors',
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
          className="rounded-lg p-2 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700"
        >
          <CloseIcon className="h-4 w-4" />
        </button>
      </div>
    </div>
  )
}

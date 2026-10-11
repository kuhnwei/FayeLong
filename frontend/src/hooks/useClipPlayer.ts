/** 句子级音频播放（学习页专用，与底部整段播放条并存）。
 *
 * 设计：整页共用一个隐藏的 <audio> 元素，切换句子时替换 src。
 * 播放句子时主动暂停整段播放器，避免两个音源同时出声。
 *
 * 支持三种循环：
 * - 单句循环（loop）：整句播完自动从头再来；
 * - A-B 循环（abStart/abEnd）：只在这两点之间反复，便于精抠某一小段。
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { usePlayer } from '../store/player'

export interface ClipPlayer {
  activeId: number | null
  playing: boolean
  loop: boolean
  currentTime: number
  duration: number
  available: boolean
  /** A-B 循环的 A / B 点（秒）；两者都非空时才生效 */
  abStart: number | null
  abEnd: number | null
  play: (sentenceId: number, url: string) => void
  toggle: (sentenceId: number, url: string) => void
  stop: () => void
  seek: (seconds: number) => void
  setLoop: (loop: boolean) => void
  /** 设定 A / B 点（a 传 null 表示清除） */
  setAB: (sentenceId: number, a: number | null, b: number | null) => void
  clearAB: () => void
  bind: (el: HTMLAudioElement | null) => void
}

export function useClipPlayer(): ClipPlayer {
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const [activeId, setActiveId] = useState<number | null>(null)
  const [playing, setPlaying] = useState(false)
  const [loop, setLoop] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [available, setAvailable] = useState(true)
  const [abStart, setAbStart] = useState<number | null>(null)
  const [abEnd, setAbEnd] = useState<number | null>(null)

  // 时间轴回调里需要读到最新的 A/B 点，用 ref 避免反复重绑事件
  const abRef = useRef<{ a: number | null; b: number | null }>({ a: null, b: null })
  abRef.current = { a: abStart, b: abEnd }
  // A-B 点所属的句子；切到别的句子时自动失效
  const abSidRef = useRef<number | null>(null)

  const pauseGlobal = useCallback(() => {
    if (usePlayer.getState().isPlaying) usePlayer.getState().setPlaying(false)
  }, [])

  const bind = useCallback((el: HTMLAudioElement | null) => {
    audioRef.current = el
  }, [])

  const play = useCallback(
    (sentenceId: number, url: string) => {
      const audio = audioRef.current
      if (!audio) return
      pauseGlobal()
      if (activeId !== sentenceId) {
        audio.src = url
        audio.currentTime = 0
        setActiveId(sentenceId)
        setAvailable(true)
      }
      void audio.play().catch(() => setAvailable(false))
    },
    [activeId, pauseGlobal],
  )

  const stop = useCallback(() => {
    const audio = audioRef.current
    if (!audio) return
    audio.pause()
    audio.removeAttribute('src')
    audio.load()
    setActiveId(null)
    setPlaying(false)
    setCurrentTime(0)
    setDuration(0)
  }, [])

  const toggle = useCallback(
    (sentenceId: number, url: string) => {
      const audio = audioRef.current
      if (!audio) return
      if (activeId === sentenceId && playing) {
        audio.pause()
        return
      }
      play(sentenceId, url)
    },
    [activeId, playing, play],
  )

  const seek = useCallback((seconds: number) => {
    const audio = audioRef.current
    if (!audio) return
    audio.currentTime = Math.max(0, seconds)
  }, [])

  const setAB = useCallback((sentenceId: number, a: number | null, b: number | null) => {
    abSidRef.current = a === null ? null : sentenceId
    setAbStart(a)
    setAbEnd(b)
  }, [])

  const clearAB = useCallback(() => {
    abSidRef.current = null
    setAbStart(null)
    setAbEnd(null)
  }, [])

  // 与整段播放器互斥：整段开始播放时停掉句子播放
  const globalPlaying = usePlayer((s) => s.isPlaying)
  useEffect(() => {
    if (globalPlaying && playing) {
      audioRef.current?.pause()
    }
  }, [globalPlaying, playing])

  // 事件绑定
  useEffect(() => {
    const audio = audioRef.current
    if (!audio) return
    const onTime = () => {
      const { a, b } = abRef.current
      // A-B 循环：越过后自动回到 A 点
      if (a !== null && b !== null && b > a && audio.currentTime >= b) {
        audio.currentTime = a
        setCurrentTime(a)
        return
      }
      setCurrentTime(audio.currentTime)
    }
    const onMeta = () => setDuration(audio.duration || 0)
    const onPlay = () => setPlaying(true)
    const onPause = () => setPlaying(false)
    const onEnded = () => {
      const { a, b } = abRef.current
      if (a !== null && b !== null && b > a) {
        audio.currentTime = a
        void audio.play()
      } else if (loop) {
        audio.currentTime = 0
        void audio.play()
      } else {
        setPlaying(false)
      }
    }
    const onError = () => {
      setAvailable(false)
      setPlaying(false)
    }
    audio.addEventListener('timeupdate', onTime)
    audio.addEventListener('loadedmetadata', onMeta)
    audio.addEventListener('play', onPlay)
    audio.addEventListener('pause', onPause)
    audio.addEventListener('ended', onEnded)
    audio.addEventListener('error', onError)
    return () => {
      audio.removeEventListener('timeupdate', onTime)
      audio.removeEventListener('loadedmetadata', onMeta)
      audio.removeEventListener('play', onPlay)
      audio.removeEventListener('pause', onPause)
      audio.removeEventListener('ended', onEnded)
      audio.removeEventListener('error', onError)
    }
  }, [loop])

  // 切句时重置时间轴；若切到了别的句子，先前的 A-B 点失效
  useEffect(() => {
    setCurrentTime(0)
    if (abSidRef.current !== null && abSidRef.current !== activeId) {
      abSidRef.current = null
      setAbStart(null)
      setAbEnd(null)
    }
  }, [activeId])

  return {
    activeId,
    playing,
    loop,
    currentTime,
    duration,
    available,
    abStart,
    abEnd,
    play,
    toggle,
    stop,
    seek,
    setLoop,
    setAB,
    clearAB,
    bind,
  }
}

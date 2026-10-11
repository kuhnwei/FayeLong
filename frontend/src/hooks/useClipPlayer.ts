/** 句子级音频播放（学习页专用，与底部整段播放条并存）。
 *
 * 设计：整页共用一个隐藏的 <audio> 元素，切换句子时替换 src。
 * 播放句子时主动暂停整段播放器，避免两个音源同时出声。
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
  play: (sentenceId: number, url: string) => void
  toggle: (sentenceId: number, url: string) => void
  stop: () => void
  seek: (seconds: number) => void
  setLoop: (loop: boolean) => void
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
    const onTime = () => setCurrentTime(audio.currentTime)
    const onMeta = () => setDuration(audio.duration || 0)
    const onPlay = () => setPlaying(true)
    const onPause = () => setPlaying(false)
    const onEnded = () => {
      if (loop) {
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

  // 切句时重置时间轴
  useEffect(() => {
    setCurrentTime(0)
  }, [activeId])

  return {
    activeId,
    playing,
    loop,
    currentTime,
    duration,
    available,
    play,
    toggle,
    stop,
    seek,
    setLoop,
    bind,
  }
}

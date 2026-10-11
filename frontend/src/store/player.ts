/** 全局播放器状态（底部播放条 + 后续学习页共用）。

实际的 <audio> 元素由 <PlayerBar/> 持有，这里只保存「意图」与时间轴，
通过 bindAudioElement 把 DOM 元素注册进来，供 seek / nudge 使用。
*/

import { create } from 'zustand'
import type { MediaItem } from '../api/client'

let audioEl: HTMLAudioElement | null = null

export function bindAudioElement(el: HTMLAudioElement | null) {
  audioEl = el
}

interface PlayerState {
  current: MediaItem | null
  isPlaying: boolean
  rate: number
  loop: boolean
  position: number
  duration: number

  open: (media: MediaItem, autoplay?: boolean) => void
  toggle: () => void
  setPlaying: (playing: boolean) => void
  setRate: (rate: number) => void
  setLoop: (loop: boolean) => void
  setTimeline: (position: number, duration: number) => void
  seek: (seconds: number) => void
  nudge: (delta: number) => void
  close: () => void
}

export const PLAYBACK_RATES = [0.5, 0.75, 1, 1.25, 1.5]

export const usePlayer = create<PlayerState>((set, get) => ({
  current: null,
  isPlaying: false,
  rate: 1,
  loop: false,
  position: 0,
  duration: 0,

  open: (media, autoplay = true) => {
    const { current } = get()
    if (current?.id === media.id) {
      set({ isPlaying: autoplay })
      return
    }
    set({ current: media, isPlaying: autoplay, position: 0, duration: 0 })
  },

  toggle: () => set((state) => ({ isPlaying: !state.isPlaying })),

  setPlaying: (playing) => set({ isPlaying: playing }),

  setRate: (rate) => set({ rate }),

  setLoop: (loop) => set({ loop }),

  setTimeline: (position, duration) => {
    const nextDuration = Number.isFinite(duration) && duration > 0 ? duration : get().duration
    set({ position, duration: nextDuration })
  },

  seek: (seconds) => {
    const { duration } = get()
    const target = Math.max(0, duration > 0 ? Math.min(seconds, duration) : seconds)
    if (audioEl === null) return
    audioEl.currentTime = target
    set({ position: target })
  },

  nudge: (delta) => {
    const { position } = get()
    get().seek(position + delta)
  },

  close: () => {
    if (audioEl) {
      audioEl.pause()
      audioEl.removeAttribute('src')
      audioEl.load()
    }
    set({ current: null, isPlaying: false, position: 0, duration: 0 })
  },
}))

/**
 * 全局播放器状态（底部播放条 + 后续学习页共用）。
 *
 * 语义与旧 `frontend/src/store/player.ts`（zustand，88 行）**逐条一致**：
 * 实际的 <audio> 元素由 <PlayerBar> 持有，这里只保存「意图」与时间轴，
 * 通过 bindAudioElement 把 DOM 元素注册进来，供 seek / nudge 使用。
 */

import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { MediaItem } from '../api/client'

// 模块级单例：<audio> 元素不属于 store 状态，而是外部注册的 DOM 引用。
let audioEl: HTMLAudioElement | null = null

/** 由 <PlayerBar> 在挂载/卸载时注册/注销底层 <audio> 元素。 */
export function bindAudioElement(el: HTMLAudioElement | null) {
  audioEl = el
}

/** 可选播放速率（原样保留）。 */
export const PLAYBACK_RATES = [0.5, 0.75, 1, 1.25, 1.5]

export const usePlayer = defineStore('player', () => {
  const current = ref<MediaItem | null>(null)
  const isPlaying = ref(false)
  const rate = ref(1)
  const loop = ref(false)
  const position = ref(0)
  const duration = ref(0)

  /**
   * 打开一个媒体。
   * 同 id 只改 isPlaying、**不重置时间轴**；不同 id 才重置 position/duration。
   */
  function open(media: MediaItem, autoplay = true) {
    if (current.value?.id === media.id) {
      isPlaying.value = autoplay
      return
    }
    current.value = media
    isPlaying.value = autoplay
    position.value = 0
    duration.value = 0
  }

  function toggle() {
    isPlaying.value = !isPlaying.value
  }

  function setPlaying(playing: boolean) {
    isPlaying.value = playing
  }

  function setRate(next: number) {
    rate.value = next
  }

  function setLoop(next: boolean) {
    loop.value = next
  }

  /** duration 非有限或 ≤0 时**保留旧 duration**。 */
  function setTimeline(nextPosition: number, nextDuration: number) {
    const keep = Number.isFinite(nextDuration) && nextDuration > 0 ? nextDuration : duration.value
    position.value = nextPosition
    duration.value = keep
  }

  /** duration > 0 时把目标夹到 [0, duration]；**audioEl 为 null 直接 return（不改 state）**。 */
  function seek(seconds: number) {
    const target = Math.max(0, duration.value > 0 ? Math.min(seconds, duration.value) : seconds)
    if (audioEl === null) return
    audioEl.currentTime = target
    position.value = target
  }

  function nudge(delta: number) {
    seek(position.value + delta)
  }

  function close() {
    if (audioEl) {
      audioEl.pause()
      audioEl.removeAttribute('src')
      audioEl.load()
    }
    current.value = null
    isPlaying.value = false
    position.value = 0
    duration.value = 0
  }

  return {
    current,
    isPlaying,
    rate,
    loop,
    position,
    duration,
    open,
    toggle,
    setPlaying,
    setRate,
    setLoop,
    setTimeline,
    seek,
    nudge,
    close,
  }
})

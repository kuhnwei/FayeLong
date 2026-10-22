<script setup lang="ts">
/**
 * 底部常驻播放条（P2-B）。逐行照搬旧 `frontend/src/components/PlayerBar.tsx`（197 行）。
 *
 * 它是外壳 flex 列里的一段（`shrink-0`），不再是 `fixed` 覆盖层 —— 学习页高度计算
 * 不必再为它留 `pb-28` 之类的魔法内边距。无 `current` 时整条不渲染。
 *
 * `<audio>` 元素**由本组件持有**；注册给 store（`bindAudioElement`）供 seek / nudge。
 */
import { computed, ref, watch } from 'vue'
import { PLAYBACK_RATES, bindAudioElement, usePlayer } from '../stores/player'
import { formatSeconds } from '../utils/format'
import {
  BackIcon,
  CloseIcon,
  ForwardIcon,
  LoopIcon,
  PauseIcon,
  PlayIcon,
} from './icons'

const player = usePlayer()
const audioEl = ref<HTMLAudioElement | null>(null)
const error = ref<string | null>(null)
/** 已加载的音源，等价于旧实现里的 `audio.dataset.src` */
let loadedSrc: string | null = null

// 把 DOM 元素注册给 store（元素随 current 出现/消失）
watch(audioEl, (el) => bindAudioElement(el), { immediate: true })

/** 切源与播放意图统一在这里处理。 */
function applySource() {
  const audio = audioEl.value
  const current = player.current
  if (!audio || !current) return

  if (loadedSrc !== current.stream_url) {
    loadedSrc = current.stream_url
    audio.src = current.stream_url
    audio.load()
    error.value = null
  }

  if (player.isPlaying) {
    void audio.play().catch((err: unknown) => {
      // 快速切换音源时 pending 的 play() 会被中断，属正常情况
      if (err instanceof DOMException && err.name === 'AbortError') return
      player.setPlaying(false)
    })
  } else {
    audio.pause()
  }
}

watch([audioEl, () => player.current, () => player.isPlaying], applySource, {
  immediate: true,
  flush: 'post',
})

watch([() => player.rate, () => player.current], () => {
  if (audioEl.value) audioEl.value.playbackRate = player.rate
})

watch([() => player.loop, () => player.current], () => {
  if (audioEl.value) audioEl.value.loop = player.loop
})

const max = computed(() => player.duration || 0)
// 模板里用 computed（v-if 后能可靠窄化类型）
const current = computed(() => player.current)

function onTimeline(e: Event) {
  const audio = e.currentTarget as HTMLAudioElement
  player.setTimeline(audio.currentTime, audio.duration)
}

function onEnded() {
  player.setPlaying(false)
}

function onError() {
  player.setPlaying(false)
  error.value = '音频加载失败，可能仍在处理中'
}

function onSeek(e: Event) {
  player.seek(Number((e.target as HTMLInputElement).value))
}

function onRate(e: Event) {
  player.setRate(Number((e.target as HTMLSelectElement).value))
}

const iconBtn = 'shrink-0 rounded-lg p-2 transition-colors'
</script>

<template>
  <div
    v-if="current"
    data-testid="player-bar"
    class="shrink-0 border-t border-slate-200 bg-white pb-[env(safe-area-inset-bottom)]"
  >
    <audio
      ref="audioEl"
      preload="metadata"
      @loadedmetadata="onTimeline"
      @durationchange="onTimeline"
      @timeupdate="onTimeline"
      @play="player.setPlaying(true)"
      @pause="player.setPlaying(false)"
      @ended="onEnded"
      @error="onError"
    />

    <div class="mx-auto w-full max-w-5xl px-3 py-2 sm:px-6 sm:py-2.5">
      <!-- 第一行：标题 + 时间。窄屏上标题独占一行，进度条才有足够宽度 -->
      <div class="mb-1 flex items-baseline gap-2">
        <span
          class="min-w-0 flex-1 truncate text-[12px] font-medium text-slate-900 sm:text-[13px]"
        >
          {{ current.title }}
        </span>
        <span class="shrink-0 text-[10px] tabular-nums text-slate-400 sm:text-[11px]">
          {{ error ?? `${formatSeconds(player.position)} / ${formatSeconds(player.duration)}` }}
        </span>
      </div>

      <!-- 第二行：控制 + 进度 -->
      <div class="flex items-center gap-1.5 sm:gap-3">
        <button
          type="button"
          title="后退 5 秒"
          aria-label="后退 5 秒"
          :class="[iconBtn, 'text-slate-500 hover:bg-slate-100 hover:text-slate-900']"
          @click="player.nudge(-5)"
        >
          <BackIcon class-name="h-4 w-4" />
        </button>

        <button
          type="button"
          :title="player.isPlaying ? '暂停' : '播放'"
          :aria-label="player.isPlaying ? '暂停' : '播放'"
          class="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-slate-900 text-white transition-colors hover:bg-slate-700 sm:h-9 sm:w-9"
          @click="player.toggle()"
        >
          <PauseIcon v-if="player.isPlaying" class-name="h-4 w-4" />
          <PlayIcon v-else class-name="ml-0.5 h-4 w-4" />
        </button>

        <button
          type="button"
          title="前进 5 秒"
          aria-label="前进 5 秒"
          :class="[iconBtn, 'text-slate-500 hover:bg-slate-100 hover:text-slate-900']"
          @click="player.nudge(5)"
        >
          <ForwardIcon class-name="h-4 w-4" />
        </button>

        <input
          type="range"
          :min="0"
          :max="max"
          :step="0.1"
          :value="Math.min(player.position, max)"
          :disabled="max <= 0"
          aria-label="播放进度"
          class="h-1 min-w-0 flex-1 cursor-pointer accent-slate-900 disabled:cursor-not-allowed"
          @input="onSeek"
        />

        <select
          :value="player.rate"
          title="播放语速"
          aria-label="播放语速"
          class="shrink-0 rounded-lg border border-slate-200 bg-white px-1 py-1 text-[11px] text-slate-600 outline-none focus:border-slate-400 sm:px-2 sm:text-xs"
          @change="onRate"
        >
          <option v-for="value in PLAYBACK_RATES" :key="value" :value="value">{{ value }}x</option>
        </select>

        <button
          type="button"
          :title="player.loop ? '关闭单曲循环' : '开启单曲循环'"
          :aria-label="player.loop ? '关闭单曲循环' : '开启单曲循环'"
          :class="[
            iconBtn,
            player.loop
              ? 'bg-slate-900 text-white hover:bg-slate-700'
              : 'text-slate-500 hover:bg-slate-100 hover:text-slate-900',
          ]"
          @click="player.setLoop(!player.loop)"
        >
          <LoopIcon class-name="h-4 w-4" />
        </button>

        <button
          type="button"
          title="关闭播放器"
          aria-label="关闭播放器"
          :class="[iconBtn, 'text-slate-400 hover:bg-slate-100 hover:text-slate-700']"
          @click="player.close()"
        >
          <CloseIcon class-name="h-4 w-4" />
        </button>
      </div>
    </div>
  </div>
</template>

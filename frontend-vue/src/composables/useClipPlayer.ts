/**
 * 句子级音频播放（学习页专用，与底部整段播放条并存）。
 *
 * 逐行照搬旧 `frontend/src/hooks/useClipPlayer.ts`（204 行）：内部全是**原生
 * `HTMLAudioElement` API**（timeupdate / loadedmetadata / ended / error + A-B 循环
 * + 与整段播放互斥），与框架无关；这里只把手握方式从 `useState/useRef/useCallback`
 * 换成 `ref/shallowRef`（并用手握 `bind` 作为 Vue 的**函数式模板 ref**）。
 *
 * 设计：整页共用一个隐藏的 <audio> 元素，切换句子时替换 src。
 * 播放句子时主动暂停整段播放器，避免两个音源同时出声。
 *
 * 三种循环：
 * - 单句循环（loop）：整句播完自动从头再来；
 * - A-B 循环（abStart/abEnd）：只在这两点之间反复，便于精抠某一小段。
 *
 * 用法（在组件 setup 里）：
 *   const clip = useClipPlayer()
 *   <audio :ref="clip.bind" />
 * 解构使用可保留响应式：`const { activeId, play } = useClipPlayer()`
 */
import { onUnmounted, ref, shallowRef, watch, type ComponentPublicInstance, type Ref } from 'vue'
import { usePlayer } from '../stores/player'

/** 可作为 `<audio :ref="clip.bind">` 传入的值（Vue 模板 ref 的调用签名）。 */
export type AudioRefTarget = HTMLAudioElement | Element | ComponentPublicInstance | null

export interface ClipPlayer {
  activeId: Ref<number | null>
  playing: Ref<boolean>
  loop: Ref<boolean>
  currentTime: Ref<number>
  duration: Ref<number>
  available: Ref<boolean>
  /** A-B 循环的 A / B 点（秒）；两者都非空时才生效 */
  abStart: Ref<number | null>
  abEnd: Ref<number | null>
  play: (sentenceId: number, url: string) => void
  toggle: (sentenceId: number, url: string) => void
  stop: () => void
  seek: (seconds: number) => void
  setLoop: (loop: boolean) => void
  /** 设定 A / B 点（a 传 null 表示清除） */
  setAB: (sentenceId: number, a: number | null, b: number | null) => void
  clearAB: () => void
  /** 作为 Vue 函数式模板 ref 用：`:ref="bind"`（非 `<audio>` 元素按 null 处理） */
  bind: (el: AudioRefTarget) => void
}

export function useClipPlayer(): ClipPlayer {
  // 需在组件 setup 里调用（Pinia 已激活）
  const player = usePlayer()

  const audioRef = shallowRef<HTMLAudioElement | null>(null)
  const activeId = ref<number | null>(null)
  const playing = ref(false)
  const loop = ref(false)
  const currentTime = ref(0)
  const duration = ref(0)
  const available = ref(true)
  const abStart = ref<number | null>(null)
  const abEnd = ref<number | null>(null)

  // A-B 点所属的句子；切到别的句子时自动失效
  const abSid = ref<number | null>(null)

  function pauseGlobal() {
    if (player.isPlaying) player.setPlaying(false)
  }

  // ---- 事件处理：只绑一次；回调里读 ref 拿最新值（不必因 loop 变化重绑）----
  function onTime() {
    const audio = audioRef.value
    if (!audio) return
    const a = abStart.value
    const b = abEnd.value
    // A-B 循环：越过后自动回到 A 点
    if (a !== null && b !== null && b > a && audio.currentTime >= b) {
      audio.currentTime = a
      currentTime.value = a
      return
    }
    currentTime.value = audio.currentTime
  }

  function onMeta() {
    const audio = audioRef.value
    if (audio) duration.value = audio.duration || 0
  }

  function onPlay() {
    playing.value = true
  }

  function onPause() {
    playing.value = false
  }

  function onEnded() {
    const audio = audioRef.value
    if (!audio) return
    const a = abStart.value
    const b = abEnd.value
    if (a !== null && b !== null && b > a) {
      // A-B 循环：回到 A 点续播
      audio.currentTime = a
      void audio.play()
    } else if (loop.value) {
      // 单句循环：从头再来
      audio.currentTime = 0
      void audio.play()
    } else {
      playing.value = false
    }
  }

  function onError() {
    available.value = false
    playing.value = false
  }

  function attach(el: HTMLAudioElement) {
    el.addEventListener('timeupdate', onTime)
    el.addEventListener('loadedmetadata', onMeta)
    el.addEventListener('play', onPlay)
    el.addEventListener('pause', onPause)
    el.addEventListener('ended', onEnded)
    el.addEventListener('error', onError)
  }

  function detach(el: HTMLAudioElement) {
    el.removeEventListener('timeupdate', onTime)
    el.removeEventListener('loadedmetadata', onMeta)
    el.removeEventListener('play', onPlay)
    el.removeEventListener('pause', onPause)
    el.removeEventListener('ended', onEnded)
    el.removeEventListener('error', onError)
  }

  /** 函数式模板 ref：挂载时传元素、卸载时传 null。 */
  function bind(el: AudioRefTarget) {
    const next = el instanceof HTMLAudioElement ? el : null
    const prev = audioRef.value
    if (prev && prev !== next) detach(prev)
    audioRef.value = next
    if (next && next !== prev) attach(next)
  }

  function play(sentenceId: number, url: string) {
    const audio = audioRef.value
    if (!audio) return
    pauseGlobal()
    if (activeId.value !== sentenceId) {
      audio.src = url
      audio.currentTime = 0
      activeId.value = sentenceId
      available.value = true
    }
    void audio.play().catch(() => {
      available.value = false
    })
  }

  function stop() {
    const audio = audioRef.value
    if (!audio) return
    audio.pause()
    audio.removeAttribute('src')
    audio.load()
    activeId.value = null
    playing.value = false
    currentTime.value = 0
    duration.value = 0
  }

  function toggle(sentenceId: number, url: string) {
    const audio = audioRef.value
    if (!audio) return
    if (activeId.value === sentenceId && playing.value) {
      audio.pause()
      return
    }
    play(sentenceId, url)
  }

  function seek(seconds: number) {
    const audio = audioRef.value
    if (!audio) return
    audio.currentTime = Math.max(0, seconds)
  }

  function setLoop(next: boolean) {
    loop.value = next
  }

  function setAB(sentenceId: number, a: number | null, b: number | null) {
    abSid.value = a === null ? null : sentenceId
    abStart.value = a
    abEnd.value = b
  }

  function clearAB() {
    abSid.value = null
    abStart.value = null
    abEnd.value = null
  }

  // 与整段播放器互斥：整段开始播放时停掉句子播放
  watch([() => player.isPlaying, playing], () => {
    if (player.isPlaying && playing.value) audioRef.value?.pause()
  })

  // 切句时重置时间轴；若切到了别的句子，先前的 A-B 点失效
  watch(activeId, () => {
    currentTime.value = 0
    if (abSid.value !== null && abSid.value !== activeId.value) {
      abSid.value = null
      abStart.value = null
      abEnd.value = null
    }
  })

  onUnmounted(() => {
    const el = audioRef.value
    if (el) detach(el)
  })

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

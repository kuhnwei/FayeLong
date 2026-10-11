/** 浏览器内置语音合成（Web Speech API）封装：朗读英文，离线可用、不依赖任何付费服务。
 *
 * 说明：
 * - 只朗读英文，其余交给调用方决定（中文释义朗读在中文 TTS 质量参差，不做）。
 * - Chrome 的 `getVoices()` 首次调用常返回空数组（语音列表异步加载），因此**不缓存空结果**。
 * - 系统不支持或朗读被阻止时静默返回 false，调用方可据此提示「浏览器不支持朗读」。
 */

let voiceCache: SpeechSynthesisVoice[] = []

/** 当前环境是否支持语音合成 */
export function speechAvailable(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof window.speechSynthesis !== 'undefined' &&
    typeof window.SpeechSynthesisUtterance !== 'undefined'
  )
}

/** 挑选一个英文音色：优先 en-US，其次任意 en-** */
function pickEnglishVoice(): SpeechSynthesisVoice | null {
  if (!speechAvailable()) return null
  if (!voiceCache.length) {
    try {
      voiceCache = window.speechSynthesis.getVoices() ?? []
    } catch {
      voiceCache = []
    }
  }
  const voices = voiceCache
  if (!voices.length) return null
  return (
    voices.find((voice) => /^en[-_]US$/i.test(voice.lang)) ??
    voices.find((voice) => /^en[-_]GB$/i.test(voice.lang)) ??
    voices.find((voice) => /^en/i.test(voice.lang)) ??
    null
  )
}

/**
 * 朗读一段英文。
 *
 * @param text 待朗读文本（会自动 trim；空串直接返回 false）
 * @param rate 语速，默认 0.9（略慢，便于跟读）
 * @returns 是否成功发起朗读
 */
export function speakEnglish(text: string, rate = 0.9): boolean {
  const clean = (text ?? '').trim()
  if (!clean || !speechAvailable()) return false
  const synth = window.speechSynthesis
  try {
    synth.cancel() // 打断上一次，避免连点堆积
    const utterance = new SpeechSynthesisUtterance(clean)
    const voice = pickEnglishVoice()
    if (voice) {
      utterance.voice = voice
      utterance.lang = voice.lang
    } else {
      utterance.lang = 'en-US'
    }
    utterance.rate = rate
    synth.speak(utterance)
    return true
  } catch {
    return false
  }
}

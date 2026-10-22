/**
 * P2-E 生词本 / 生词练习共享的类型、常量与纯函数。
 *
 * 为什么单独成文件（照 `types/study.ts` 的先例）：
 * 出题与判分是**纯函数**，可以被页面复用而不该放在 `<script setup>` 顶层
 * （那样每个组件实例都会重建一份闭包）。把它们放这里，页面只负责状态与视图。
 *
 * ⚠️ 逻辑**逐行照搬**旧 `frontend/src/pages/VocabPracticePage.tsx`，不要「优化」判分口径：
 * 判分规则（接受原词与原型、归一化只留字母数字与撇号）改一个字就会改变历史通过率。
 */
import type { VocabItem } from '../api/client'

/** 练习方式：中译英 / 英译中 / 听写 */
export type Mode = 'zh2en' | 'en2zh' | 'dictation'

/** 练习范围：全部 / 待复习 / 已掌握 */
export type Scope = 'all' | 'todo' | 'mastered'

/** 页面阶段：设置 / 答题 / 结果（空态走独立的 `data-practice-phase="empty"`，不入状态机） */
export type Phase = 'setup' | 'quiz' | 'result'

/** 题量：0 表示全部 */
export type CountOption = 10 | 20 | 0

/** 听写语速：0.9 正常 / 0.6 慢速 */
export type RateOption = 0.9 | 0.6

export interface Question {
  item: VocabItem
  /** 拼写类（中译英 / 听写）：可接受的答案（已归一化） */
  accept: string[]
  /** 英译中：选项（含正确项）；不足 2 项时为 undefined，该题会被剔除 */
  options?: string[]
  /** 英译中：正确选项原文 */
  correctOption?: string
}

/** 各模式的文案（题干标签 / 结果页说明 / 设置项） */
export const MODE_META: Record<Mode, { badge: string; result: string; title: string; desc: string }> = {
  zh2en: {
    badge: '中文 → 英文',
    result: '中文译英文（手输拼写）',
    title: '看中文写英文',
    desc: '手输单词拼写，自动判分',
  },
  en2zh: {
    badge: '英文 → 中文',
    result: '英文译中文（四选一）',
    title: '看英文选释义',
    desc: '四选一，选项来自其它生词',
  },
  dictation: {
    badge: '听写',
    result: '听写（听发音写拼写）',
    title: '听发音写单词',
    desc: '只给发音不给文字，自动判分',
  },
}

/** 题量可选项（旧版是内联的 `[10, 20, 0] as CountOption[]`） */
export const COUNT_OPTIONS: CountOption[] = [10, 20, 0]

// --------------------------- 出题与判分（纯函数）---------------------------

/** 英文归一化：小写、去标点，只留字母数字与撇号 */
export const normEn = (text: string): string => text.toLowerCase().replace(/[^a-z0-9']/g, '')

/** Fisher–Yates 洗牌（返回新数组，不改入参） */
export function shuffle<T>(list: readonly T[]): T[] {
  const out = [...list]
  for (let i = out.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1))
    const tmp = out[i]
    out[i] = out[j]
    out[j] = tmp
  }
  return out
}

/** 从生词池出题（不切片，题量由调用方决定） */
export function buildQuestions(pool: readonly VocabItem[], mode: Mode): Question[] {
  // 拼写类（中译英 / 听写）共用同一套判分口径：接受原词与原型
  if (mode !== 'en2zh') {
    return pool.map((item) => ({
      item,
      accept: [
        ...new Set([item.word, item.lemma].filter((v): v is string => !!v?.trim()).map(normEn)),
      ],
    }))
  }

  return pool.map((item) => {
    const correctOption = (item.translation ?? '').trim()
    const others = pool
      .filter((o) => o.id !== item.id && (o.translation ?? '').trim() !== correctOption)
      .map((o) => (o.translation ?? '').trim())

    const distractors: string[] = []
    for (const candidate of shuffle(others)) {
      if (!distractors.includes(candidate)) distractors.push(candidate)
      if (distractors.length >= 3) break
    }
    if (!distractors.length) return { item, accept: [], correctOption }
    return {
      item,
      accept: [],
      correctOption,
      options: shuffle([correctOption, ...distractors]),
    }
  })
}

/** 用时文案：`1 分 5 秒` / `42 秒`
 *
 * ⚠️ 与 `utils/format.ts` 的 `formatDuration`（毫秒级媒体时长）**同名但不是同一个函数**：
 * 这里是**秒**级、且是「X 分 Y 秒」文案。刻意保留旧版命名（旧 `VocabPracticePage.tsx`
 * 里就有一个局部的 `formatDuration`），两个模块互不 import，不会串。
 */
export function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return m > 0 ? `${m} 分 ${s} 秒` : `${s} 秒`
}

/** 生词的展示名：有原型时用原型（`went` → `go`），否则用原词 */
export const DISPLAY_NAME = (item: VocabItem): string => item.lemma || item.word

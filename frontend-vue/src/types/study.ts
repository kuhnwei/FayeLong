/**
 * P2-D 学习页共享的类型与纯函数（SentenceStage / ClickableText / StudyPage 共用）。
 *
 * 抽成独立模块的原因：SentenceStage / DictationBox / ClickableText 是从 StudyPage
 * 里拆出来的独立 SFC，但它们与 StudyPage 本体共享这几个类型 / 常量 / 纯函数。
 */
import type { SentenceItem } from '../api/client'
import type { AttemptResult } from '../api/client'

/** 切片首部留白（与后端 clip_padding_ms 对应），用于回算真实时间点 */
export const CLIP_PAD_MS = 120

/** 提交听写后就地更新的统计（避免整页重新拉取详情） */
export interface StatOverride {
  attempt_count: number
  best_accuracy: number
  mastered: boolean
}

/** 逐句的听写草稿：翻页回来时输入的内容与上次校验结果都还在 */
export interface Draft {
  text: string
  result: AttemptResult | null
}

export const EMPTY_DRAFT: Draft = { result: null, text: '' }

/** 被点击单词在视口中的位置（用于定位浮层） */
export interface WordRect {
  top: number
  left: number
  bottom: number
  width: number
}

/** 单词浮层的定位目标（查词 + 加入生词本） */
export interface WordPopoverTarget {
  word: string
  sentenceId?: number | null
  mediaId?: number | null
  context?: string
  rect: WordRect
}

/** 正文自适应字号：句子越短，字越大 —— 一句一屏正是放大字号的时机。
 *
 * clamp 的下限按手机宽度定（375px 上 3.4vw 只有 12px，实际会取到下限），
 * 上限保持桌面观感不变；中间靠 vw 平滑过渡，所以不需要媒体查询。
 */
export function stageFontSize(length: number): string {
  if (length <= 45) return 'clamp(1.5rem, 3.4vw, 2.9rem)'
  if (length <= 90) return 'clamp(1.25rem, 2.8vw, 2.3rem)'
  if (length <= 150) return 'clamp(1.05rem, 2.1vw, 1.85rem)'
  return 'clamp(0.95rem, 1.7vw, 1.5rem)'
}

/** 译文跟随正文但小一档，避免与原文抢视线（v1.14 整体上调一档） */
export function translationFontSize(length: number): string {
  if (length <= 30) return 'clamp(1.05rem, 1.7vw, 1.5rem)'
  if (length <= 60) return 'clamp(1rem, 1.5vw, 1.35rem)'
  return 'clamp(0.95rem, 1.3vw, 1.2rem)'
}

/** 宫格格子的状态色：当前 > 已掌握 > 练过 > 未听 */
export function gridClass(sentence: SentenceItem, active: boolean): string {
  if (active) return 'bg-lemon-400 text-ink ring-2 ring-ink'
  if (sentence.mastered) return 'bg-emerald-100 text-emerald-700 hover:bg-emerald-200'
  if (sentence.attempt_count > 0) return 'bg-amber-100 text-amber-700 hover:bg-amber-200'
  return 'bg-cream-2 text-ink-3 hover:bg-cream'
}

/**
 * 宫格四态语义锚点（ARCH §5.1.5 / §3.2）：`verify_m5` 优先读 `data-state`，
 * 缺失才回落旧配色类名。与 `gridClass` 同源，二者必须保持同一分支顺序。
 */
export type GridState = 'active' | 'mastered' | 'attempted' | 'fresh'

export function gridState(sentence: SentenceItem, active: boolean): GridState {
  if (active) return 'active'
  if (sentence.mastered) return 'mastered'
  if (sentence.attempt_count > 0) return 'attempted'
  return 'fresh'
}

/**
 * ⭐ 分词正则必须与 `backend/app/services/marks.py::word_count` **一字不差**；
 * 改动必须两边同步（词序下标契约）。
 *
 * `sentences.marks` 记的是词序下标（0 基闭区间）：前端分词与后端不一致 →
 * 高亮错位，且这种错位只在特定句式出现，很难复现。
 * 对拍靠 `scripts/verify_marks.mjs`（19 项，含点击标记的词序下标断言）。
 *
 * 后端（逐字）：
 *   WORD_RE = re.compile(r"[A-Za-z][A-Za-z'’-]*")
 *   return len(WORD_RE.findall(text or ""))
 * 前端（逐字，捕获组让 split 结果里奇数索引为单词本身）：
 */
export const WORD_SPLIT = /([A-Za-z][A-Za-z'’-]*)/g

/**
 * ⭐⭐ **「下一句 / 下一题」按钮绝对不能加 `autoFocus` 或 `v-focus`**（v1.12 踩过的坑）。
 *
 * 原因：听写输入框里按 Enter 提交（见 DictationBox），提交成功后如果焦点恰好在
 * 「下一句」按钮上，同一个 Enter 会**先命中按钮** → 立刻翻页，用户根本看不到校验结果
 * （Enter 双触发）。所以：
 *   - 听写输入框在动态插入时用 `v-focus` 指令聚焦（`autofocus` 属性对 DOM API 插入
 *     的元素无效）；
 *   - 「下一句 / 下一题」按钮**永远不聚焦**。
 * 这条写在共享模块里，是为了让 StudyPage 本体（下一轮）一眼看到。
 */

/** 闭区间列表 → 词下标集合（标记区间左右都算在内） */
export function rangesToWords(ranges: number[][]): Set<number> {
  const set = new Set<number>()
  for (const [a, b] of ranges) {
    for (let i = Math.min(a, b); i <= Math.max(a, b); i += 1) set.add(i)
  }
  return set
}

/** 词下标集合 → 归并后的闭区间（服务端 `services/marks.py` 还会再归并一次兜底） */
export function wordsToRanges(words: number[]): number[][] {
  const sorted = [...new Set(words)].sort((a, b) => a - b)
  const out: number[][] = []
  for (const i of sorted) {
    const last = out[out.length - 1]
    if (last && i === last[1] + 1) last[1] = i
    else out.push([i, i])
  }
  return out
}

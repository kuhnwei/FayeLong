/**
 * 题型 → 前端组件的映射表（P4-2）。
 *
 * 设计要点
 * ========
 * 1. **一个题型 = 一个作答组件 + 一个结果渲染组件**（ADR-001 §5.5.1），
 *    按 `code` 动态挂载，宿主页面（`StudyPage.vue` / `SentenceStage.vue`）
 *    不认识任何具体题型。
 * 2. **找不到就降级到 dictation，绝不白屏**。降级是必须的：后端可能先上线一个
 *    新题型（`GET /api/question-types` 会下发它），而前端 bundle 还是旧版本；
 *    此时用户点进去至少还能用听写界面，而不是一片空白。
 * 3. 清单本身来自后端（`GET /api/question-types`），本文件的映射只负责
 *    「有没有对应的 Vue 组件」—— 两侧不一致时以**后端清单为准、前端降级**。
 *
 * 新增一个题型要改什么
 * ==================
 * 只加目录 + 一行 `registerQuestionType('xxx', { Answer, Result })`。
 * **不要**改 `StudyPage.vue` / `SentenceStage.vue` —— 它们是按 code 挂载的。
 */

import type { Component } from 'vue'
import DictationAnswer from './dictation/Answer.vue'
import DictationResult from './dictation/Result.vue'

/** 一个题型在前端需要的两个组件。 */
export interface QuestionTypeComponents {
  /** 作答组件：接收 `sentence` / `draft` / `onDraft` 等（形状见 `types/study.ts`）。 */
  Answer: Component
  /** 结果渲染组件：接收 `result`（+ 可选 `compact`）。 */
  Result: Component
}

/**
 * 兜底题型的 `code`。
 *
 * 为什么兜底是 dictation 而不是「什么都不渲染」：听写是本站的**默认练习形态**，
 * 它的组件对「没有标准答案」的句子已经有明确的禁用态（`disabled` → 提示
 * 「该句没有标准答案，无法听写」），因此当兜底比空白更接近用户的预期。
 */
export const FALLBACK_CODE = 'dictation'

/** `code` → 组件映射。用 `Map` 而不是对象字面量：避免 `__proto__` 之类的键污染。 */
const REGISTRY = new Map<string, QuestionTypeComponents>()

/** 已经 warn 过的未知 code（同一个 code 只提示一次，避免每次渲染都刷控制台）。 */
const warned = new Set<string>()

/**
 * 注册一个题型的组件。
 *
 * @param code 题型标识，必须与后端 `GET /api/question-types` 下发的 `code` 一致。
 * @param components 该题型的作答组件与结果渲染组件。
 */
export function registerQuestionType(code: string, components: QuestionTypeComponents): void {
  const key = String(code ?? '').trim()
  if (!key) {
    throw new Error('registerQuestionType 需要非空的 code')
  }
  REGISTRY.set(key, components)
}

/** 是否已有该 `code` 的组件实现（用于「后端有、前端没有」的显式提示）。 */
export function hasQuestionType(code: string | null | undefined): boolean {
  return REGISTRY.has(String(code ?? ''))
}

/** 已注册的 `code` 列表（按 `code` 升序，便于断言与调试）。 */
export function registeredCodes(): string[] {
  return [...REGISTRY.keys()].sort()
}

/**
 * 按 `code` 取组件；**找不到时降级到 dictation**（并在控制台留一条 warn）。
 *
 * @param code 题型标识；`null` / `undefined` / 空串都按兜底处理。
 * @returns 该题型的 `{ Answer, Result }`，永远非空（注册表里至少有 dictation）。
 */
export function resolve(code: string | null | undefined): QuestionTypeComponents {
  const key = String(code ?? '').trim()
  const hit = REGISTRY.get(key)
  if (hit) return hit

  const fallback = REGISTRY.get(FALLBACK_CODE)
  if (!fallback) {
    // 结构性不可达：本模块底部会注册 dictation。留这条是为了「降级链本身断了」
    // 时给出可读的错误，而不是 `undefined.Answer` 的崩溃栈。
    throw new Error(
      `题型组件注册表缺少兜底题型 ${FALLBACK_CODE}：前端初始化逻辑可能被破坏`,
    )
  }
  if (key && !warned.has(key)) {
    warned.add(key)
    console.warn(
      `[question-types] 未知题型 code=${key}，已降级到 ${FALLBACK_CODE}。` +
        '后端已下发该题型但前端 bundle 还是旧版本？（新增题型请在 ' +
        'src/question-types/ 下补 Answer.vue + Result.vue 并 registerQuestionType）',
    )
  }
  return fallback
}

// ---------------------------------------------------------------------------
// 内置题型（生产清单）
// ---------------------------------------------------------------------------

registerQuestionType(FALLBACK_CODE, {
  Answer: DictationAnswer,
  Result: DictationResult,
})

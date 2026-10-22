/**
 * 听写比对结果的展示类型（FR-S3，四类标记见设计文档 §9.3）。
 *
 * `DiffToken` / `DiffTokenType` 直接取自后端契约（`contracts/api-types.d.ts` 的 `DiffToken`，
 * 其 `type` 就是 `'correct' | 'wrong' | 'missing' | 'extra'` 的字面量联合）。
 * `DiffResultData` 是 `DiffResult` 组件真正依赖的字段子集 —— 抽成独立模块，
 * 避免「组件 re-export 类型」这种脆弱的耦合。
 */
import type { Schemas } from '../api/schema'

/** 词级对齐结果中的一个位置。 */
export type DiffToken = Schemas['DiffToken']

/** 四类标记。 */
export type DiffTokenType = DiffToken['type']

/**
 * DiffResult 组件真正依赖的字段子集。
 *
 * 抽出来的目的：历史记录 `AttemptRecord` 没有 `sentence_id` / `attempt_count`
 * 等与展示无关的字段，有了这个更小的接口就能直接喂进来，不必在前端伪造数据。
 * 判定仍只在服务端做 —— 这里的字段全部是服务端算好的结果。
 */
export interface DiffResultData {
  /** 本次正确率（0-100） */
  accuracy: number
  /** 是否完全正确 */
  is_correct: boolean
  /** 词级对齐结果（后端 schema 里为可选，组件侧用 `tokens ?? []` 兜底） */
  tokens?: DiffToken[]
  /** 标准答案总词数 */
  total_words: number
  /** 正确的词数 */
  correct: number
  /** 拼错 / 用错的词数 */
  wrong: number
  /** 漏掉的词数 */
  missing: number
  /** 多写的词数 */
  extra: number
}

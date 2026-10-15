/** 听写校验结果展示（FR-S3，四类标记见设计文档 §9.3）。
 *
 * 渲染规则：
 * - `correct` 正常色
 * - `wrong`   显示用户实际写的词（标红 + 波浪下划线），悬停看正确形式
 * - `missing` 显示标准答案里被漏掉的词（红色虚线下划线）
 * - `extra`   显示用户多写的词（灰色删除线）
 */

import type { AttemptResult, DiffToken } from '../api/client'

const TOKEN_CLASS: Record<DiffToken['type'], string> = {
  correct: 'text-slate-800',
  wrong: 'text-red-600 underline decoration-red-400 decoration-wavy decoration-1 underline-offset-4',
  missing: 'text-red-500 underline decoration-red-300 decoration-dashed decoration-1 underline-offset-4',
  extra: 'text-slate-400 line-through',
}

function tokenText(token: DiffToken): string {
  if (token.type === 'correct') return token.expected ?? ''
  if (token.type === 'wrong') return token.actual ?? ''
  if (token.type === 'missing') return token.expected ?? ''
  return token.actual ?? ''
}

function tokenTitle(token: DiffToken): string {
  if (token.type === 'wrong') return `拼写/用词有误，应为：${token.expected ?? ''}`
  if (token.type === 'missing') return `漏掉了：${token.expected ?? ''}`
  if (token.type === 'extra') return '多写了这个词'
  return token.expected ?? ''
}

interface Props {
  result: AttemptResult
  /** 紧凑模式（历史记录里用） */
  compact?: boolean
}

export default function DiffResult({ result, compact = false }: Props) {
  const perfect = result.wrong === 0 && result.missing === 0 && result.extra === 0
  const corrections = result.tokens.filter((t) => t.type !== 'correct')

  const accuracyClass = result.is_correct
    ? 'text-emerald-600'
    : result.accuracy >= 80
      ? 'text-amber-600'
      : 'text-red-600'

  return (
    <div className={compact ? 'mt-1.5' : 'mt-2.5'}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px]">
        <span className={`font-medium tabular-nums ${accuracyClass}`}>
          正确率 {result.accuracy}%
        </span>
        <span className="text-slate-400 tabular-nums">
          正确 {result.correct}/{result.total_words}
          {result.wrong > 0 && ` · 错 ${result.wrong}`}
          {result.missing > 0 && ` · 漏 ${result.missing}`}
          {result.extra > 0 && ` · 多 ${result.extra}`}
        </span>
        {perfect && (
          <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] text-emerald-600">
            完全正确
          </span>
        )}
      </div>

      {result.tokens.length > 0 ? (
        <p className="mt-2 flex flex-wrap gap-x-1.5 gap-y-1.5 text-[15px] leading-relaxed sm:text-lg">
          {result.tokens.map((token, index) => (
            <span key={`${token.type}-${index}`} className={TOKEN_CLASS[token.type]} title={tokenTitle(token)}>
              {tokenText(token)}
            </span>
          ))}
        </p>
      ) : (
        <p className="mt-2 text-[13px] text-slate-400">（没有可对比的内容）</p>
      )}

      {corrections.length > 0 && (
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          <span className="text-[11px] text-slate-400">纠错</span>
          {corrections.map((token, index) => (
            <span
              key={`fix-${index}`}
              className="rounded bg-red-50 px-1.5 py-0.5 text-[11px] text-red-600"
            >
              {token.type === 'extra' ? (
                <>多余「{token.actual}」</>
              ) : token.type === 'missing' ? (
                <>漏「{token.expected}」</>
              ) : (
                <>
                  {token.actual} → <span className="font-medium">{token.expected}</span>
                </>
              )}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

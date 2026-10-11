/** 生词本练习页：中译英（手输拼写） / 英译中（四选一） / 听写（听发音手输拼写）。
 *
 * 设计要点：
 * - 题目全部来自生词本（`GET /api/vocab`），**纯前端出题与判分**，后端无需改动。
 * - 中译英：题干是中文释义，手输英文；判分用「归一化比对」，接受**原词与原型**（`word` / `lemma`）。
 * - 英译中：题干是英文单词，四选一；干扰项从生词本中其它词的释义随机抽取（自动判分 100% 准确）。
 * - 听写：题干**只给发音、不给文字**（进入题目自动播一次，可重播/慢速），手输拼写后判分口径与中译英一致。
 * - 判分分两类：**拼写类**（中译英 / 听写，需要打字）与**选择类**（英译中，点选项）。
 * - 只有「带释义」的生词能参与练习；英译中至少需要 2 个这样的词才够生成选项。
 * - 朗读复用 `utils/speech.ts`；中译英题目**不提供朗读**（否则等于报答案），作答后才可听发音。
 */

import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { listVocab, type VocabItem } from '../api/client'
import { speakEnglish, speechAvailable } from '../utils/speech'
import {
  AlertIcon,
  BackIcon,
  BookIcon,
  CheckIcon,
  CloseIcon,
  LightbulbIcon,
  RefreshIcon,
  ShuffleIcon,
  SpeakerIcon,
  TargetIcon,
  TrophyIcon,
} from '../components/icons'

type Mode = 'zh2en' | 'en2zh' | 'dictation'
type Scope = 'all' | 'todo' | 'mastered'
type Phase = 'setup' | 'quiz' | 'result'

/** 题量：0 表示全部 */
type CountOption = 10 | 20 | 0

/** 听写语速：0.9 正常 / 0.6 慢速 */
type RateOption = 0.9 | 0.6

interface Question {
  item: VocabItem
  /** 拼写类（中译英 / 听写）：可接受的答案（已归一化） */
  accept: string[]
  /** 英译中：选项（含正确项）；不足 2 项时为 undefined，该题会被剔除 */
  options?: string[]
  /** 英译中：正确选项原文 */
  correctOption?: string
}

/** 各模式的文案（题干标签 / 结果页说明 / 设置项） */
const MODE_META: Record<Mode, { badge: string; result: string; title: string; desc: string }> = {
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

// --------------------------- 出题与判分（纯函数）---------------------------

/** 英文归一化：小写、去标点，只留字母数字与撇号 */
const normEn = (text: string) => text.toLowerCase().replace(/[^a-z0-9']/g, '')

function shuffle<T>(list: readonly T[]): T[] {
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
function buildQuestions(pool: readonly VocabItem[], mode: Mode): Question[] {
  // 拼写类（中译英 / 听写）共用同一套判分口径：接受原词与原型
  if (mode !== 'en2zh') {
    return pool.map((item) => ({
      item,
      accept: [...new Set([item.word, item.lemma].filter((v): v is string => !!v?.trim()).map(normEn))],
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

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return m > 0 ? `${m} 分 ${s} 秒` : `${s} 秒`
}

const DISPLAY_NAME = (item: VocabItem) => item.lemma || item.word

// --------------------------- 页面 ---------------------------

export default function VocabPracticePage() {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['vocab', 'practice-pool'],
    queryFn: () => listVocab({}),
  })

  const allItems = data?.items ?? []
  /** 带释义的生词才能出题 */
  const withMeaning = useMemo(
    () => allItems.filter((item) => (item.translation ?? '').trim()),
    [allItems],
  )

  const canSpeak = useMemo(() => speechAvailable(), [])

  const [phase, setPhase] = useState<Phase>('setup')
  const [mode, setMode] = useState<Mode>('zh2en')
  const [scope, setScope] = useState<Scope>('all')
  const [count, setCount] = useState<CountOption>(10)
  /** 听写语速 */
  const [rate, setRate] = useState<RateOption>(0.9)

  const [questions, setQuestions] = useState<Question[]>([])
  const [index, setIndex] = useState(0)
  const [input, setInput] = useState('')
  const [picked, setPicked] = useState<string | null>(null)
  const [revealed, setRevealed] = useState(false)
  const [results, setResults] = useState<boolean[]>([])
  const [elapsed, setElapsed] = useState(0)
  /** 听写：当前题已听次数 */
  const [plays, setPlays] = useState(0)

  const startedAtRef = useRef(0)
  const inputRef = useRef<HTMLInputElement>(null)
  /** 供定时器/事件回调读取最新题目，避免把 questions 塞进依赖数组 */
  const questionsRef = useRef<Question[]>(questions)
  questionsRef.current = questions

  const scoped = useMemo(() => {
    if (scope === 'todo') return withMeaning.filter((item) => !item.mastered)
    if (scope === 'mastered') return withMeaning.filter((item) => item.mastered)
    return withMeaning
  }, [withMeaning, scope])

  const en2zhReady = withMeaning.length >= 2
  // 选择类（英译中）需要至少 2 个词才能生成选项；拼写类 1 个即可
  const enough = mode === 'en2zh' ? scoped.length >= 2 : scoped.length >= 1

  const current = questions[index]
  const answered = results.length > index ? results[index] : null
  /** 拼写类：中译英 + 听写（需要打字） */
  const isSpelling = mode !== 'en2zh'
  const isDictation = mode === 'dictation'
  /** 听写依赖浏览器语音合成；不支持时禁用该模式 */
  const canDictate = canSpeak

  // 作答区自动聚焦（拼写类需要打字）
  useEffect(() => {
    if (phase === 'quiz' && isSpelling && !revealed) inputRef.current?.focus()
  }, [phase, isSpelling, revealed, index])

  /** 听写：进入每一题都自动播一次发音（并重置计数） */
  useEffect(() => {
    if (phase !== 'quiz' || mode !== 'dictation' || !canSpeak) return
    setPlays(0)
    const timer = window.setTimeout(() => {
      const item = questionsRef.current[index]?.item
      if (item && speakEnglish(DISPLAY_NAME(item), rate)) setPlays(1)
    }, 300)
    return () => window.clearTimeout(timer)
    // 只在切题/进入答题时触发；rate 变化不重播（用「播放」按钮即可）
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, index, mode, canSpeak])

  const begin = (source: readonly VocabItem[]) => {
    const built = buildQuestions(source, mode)
    const usable = mode === 'en2zh' ? built.filter((q) => (q.options?.length ?? 0) >= 2) : built
    if (!usable.length) return
    setQuestions(usable)
    setIndex(0)
    setInput('')
    setPicked(null)
    setRevealed(false)
    setResults([])
    setElapsed(0)
    setPlays(0)
    startedAtRef.current = Date.now()
    setPhase('quiz')
  }

  const start = () => {
    const limited = count > 0 ? shuffle(scoped).slice(0, count) : shuffle(scoped)
    begin(limited)
  }

  const submitSpelling = () => {
    if (!current || revealed) return
    const value = normEn(input)
    const ok = value.length > 0 && current.accept.includes(value)
    setResults((prev) => [...prev, ok])
    setRevealed(true)
  }

  const giveUp = () => {
    if (!current || revealed) return
    setResults((prev) => [...prev, false])
    setRevealed(true)
  }

  const choose = (option: string) => {
    if (!current || revealed) return
    setPicked(option)
    setResults((prev) => [...prev, option === current.correctOption])
    setRevealed(true)
  }

  /** 听写：播放当前题发音（rate 可覆盖，用于「慢速」） */
  const listen = (useRate: number = rate) => {
    if (!current) return
    if (speakEnglish(DISPLAY_NAME(current.item), useRate)) setPlays((n) => n + 1)
  }

  const next = () => {
    if (index + 1 >= questions.length) {
      setElapsed(Math.max(1, Math.round((Date.now() - startedAtRef.current) / 1000)))
      setPhase('result')
      return
    }
    setIndex((i) => i + 1)
    setInput('')
    setPicked(null)
    setRevealed(false)
    setPlays(0)
  }

  // 回车：未作答则提交，已作答则下一题
  useEffect(() => {
    if (phase !== 'quiz') return
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Enter' || event.isComposing) return
      event.preventDefault()
      if (revealed) next()
      else if (isSpelling) submitSpelling()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  const correctCount = results.filter(Boolean).length
  const accuracy = results.length ? Math.round((correctCount / results.length) * 100) : 0
  const wrongItems = questions.filter((_, i) => results[i] === false).map((q) => q.item)

  // ---------- 加载 / 错误 / 生词不足 ----------

  if (isLoading) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white px-5 py-10 text-center text-[13px] text-slate-400">
        加载生词本…
      </div>
    )
  }

  if (isError) {
    return (
      <div className="rounded-xl border border-red-100 bg-red-50 px-5 py-10 text-center text-[13px] text-red-600">
        {(error as Error).message}
      </div>
    )
  }

  if (!withMeaning.length) {
    return (
      <div data-practice-phase="empty" className="space-y-4">
        <PageHeader onBack={null} />
        <div className="rounded-xl border border-slate-200 bg-white px-5 py-12 text-center">
          <BookIcon className="mx-auto h-8 w-8 text-slate-300" />
          <p className="mt-3 text-[13px] text-slate-500">
            生词本里还没有「带释义」的生词，暂时无法出题。
          </p>
          <p className="mt-1 text-[12px] text-slate-400">
            到学习页点击原文里的单词，查词后加入生词本，这里就能开始练习了。
          </p>
          <Link
            to="/vocab"
            className="mt-4 inline-flex items-center gap-1.5 rounded-lg bg-slate-900 px-3.5 py-2 text-[13px] text-white transition-colors hover:bg-slate-700"
          >
            返回生词本
          </Link>
        </div>
      </div>
    )
  }

  // ---------- 设置 ----------

  if (phase === 'setup') {
    return (
      <div data-practice-phase="setup" className="space-y-5">
        <PageHeader onBack={null} />

        <div className="space-y-5 rounded-xl border border-slate-200 bg-white p-5">
          <Field label="练习方式">
            <Choice
              active={mode === 'zh2en'}
              onClick={() => setMode('zh2en')}
              title={MODE_META.zh2en.title}
              desc={MODE_META.zh2en.desc}
            />
            <Choice
              active={mode === 'en2zh'}
              disabled={!en2zhReady}
              onClick={() => setMode('en2zh')}
              title={MODE_META.en2zh.title}
              desc={en2zhReady ? MODE_META.en2zh.desc : '需要至少 2 个带释义的生词'}
            />
            <Choice
              active={mode === 'dictation'}
              disabled={!canDictate}
              onClick={() => setMode('dictation')}
              title={MODE_META.dictation.title}
              desc={canDictate ? MODE_META.dictation.desc : '当前浏览器不支持语音合成'}
            />
          </Field>

          {isDictation && (
            <Field label="语速">
              <Choice
                active={rate === 0.9}
                onClick={() => setRate(0.9)}
                title="正常"
                desc="默认语速"
              />
              <Choice
                active={rate === 0.6}
                onClick={() => setRate(0.6)}
                title="慢速"
                desc="便于听清发音"
              />
              <span data-practice-rate={String(rate)} />               
            </Field>
          )}

          <Field label="练习范围">
            <Choice
              active={scope === 'all'}
              onClick={() => setScope('all')}
              title="全部"
              desc={`${withMeaning.length} 个`}
            />
            <Choice
              active={scope === 'todo'}
              onClick={() => setScope('todo')}
              title="待复习"
              desc={`${withMeaning.filter((i) => !i.mastered).length} 个`}
            />
            <Choice
              active={scope === 'mastered'}
              onClick={() => setScope('mastered')}
              title="已掌握"
              desc={`${withMeaning.filter((i) => i.mastered).length} 个`}
            />
          </Field>

          <Field label="题量">
            {([10, 20, 0] as CountOption[]).map((value) => (
              <Choice
                key={value}
                active={count === value}
                onClick={() => setCount(value)}
                title={value === 0 ? '全部' : `${value} 题`}
                desc={value === 0 ? `${scoped.length} 个` : value <= scoped.length ? '随机抽题' : '不足则用全部'}
              />
            ))}
          </Field>

          <div className="flex flex-wrap items-center gap-3 border-t border-slate-100 pt-4">
            <button
              type="button"
              disabled={!enough}
              onClick={start}
              className="flex items-center gap-1.5 rounded-lg bg-slate-900 px-4 py-2 text-[13px] text-white transition-colors hover:bg-slate-700 disabled:cursor-not-allowed disabled:bg-slate-200 disabled:text-slate-500"
            >
              <TargetIcon className="h-4 w-4" />
              开始练习
            </button>
            {!enough && (
              <span
                data-practice-hint=""
                className="flex items-center gap-1 text-[12px] text-amber-600"
              >
                <AlertIcon className="h-3.5 w-3.5" />
                {mode === 'en2zh'
                  ? '当前范围内带释义的生词不足 2 个，换个范围或改用「中译英 / 听写」'
                  : '当前范围内没有带释义的生词，换个范围试试'}
              </span>
            )}
            <span className="ml-auto flex items-center gap-1 text-[11px] text-slate-400">
              <kbd className="rounded border border-slate-200 px-1.5 py-0.5">Enter</kbd>
              提交 / 下一题
            </span>
          </div>
        </div>
      </div>
    )
  }

  // ---------- 结果 ----------

  if (phase === 'result') {
    return (
      <div data-practice-phase="result" className="space-y-5">
        <PageHeader onBack={() => setPhase('setup')} />

        <div className="rounded-xl border border-slate-200 bg-white p-6 text-center">
          <TrophyIcon
            className={`mx-auto h-9 w-9 ${
              accuracy >= 80 ? 'text-amber-500' : accuracy >= 60 ? 'text-slate-400' : 'text-slate-300'
            }`}
          />
          <p
            data-practice-accuracy=""
            className="mt-3 text-[28px] font-medium tabular-nums text-slate-900"
          >
            {accuracy}%
          </p>
          <p className="mt-1 text-[13px] text-slate-500">
            答对 <span className="tabular-nums text-emerald-600">{correctCount}</span> /{' '}
            <span className="tabular-nums">{questions.length}</span> 题　·　用时{' '}
            {formatDuration(elapsed)}
          </p>
          <p className="mt-2 text-[12px] text-slate-400">{MODE_META[mode].result}</p>

          <div className="mt-5 flex flex-wrap items-center justify-center gap-2">
            <button
              type="button"
              onClick={() => setPhase('setup')}
              className="flex items-center gap-1.5 rounded-lg border border-slate-200 px-3.5 py-2 text-[13px] text-slate-700 transition-colors hover:bg-slate-50"
            >
              <ShuffleIcon className="h-3.5 w-3.5" />
              换个设置
            </button>
            {wrongItems.length > 0 && (
              <button
                type="button"
                data-practice-retry-wrong=""
                onClick={() => begin(wrongItems)}
                className="flex items-center gap-1.5 rounded-lg border border-slate-200 px-3.5 py-2 text-[13px] text-slate-700 transition-colors hover:bg-slate-50"
              >
                <RefreshIcon className="h-3.5 w-3.5" />
                重练错题（{wrongItems.length}）
              </button>
            )}
            <button
              type="button"
              onClick={start}
              className="flex items-center gap-1.5 rounded-lg bg-slate-900 px-3.5 py-2 text-[13px] text-white transition-colors hover:bg-slate-700"
            >
              <TargetIcon className="h-3.5 w-3.5" />
              再练一次
            </button>
            <Link
              to="/vocab"
              className="flex items-center gap-1.5 rounded-lg border border-slate-200 px-3.5 py-2 text-[13px] text-slate-700 transition-colors hover:bg-slate-50"
            >
              返回生词本
            </Link>
          </div>
        </div>

        {wrongItems.length > 0 && (
          <div className="rounded-xl border border-slate-200 bg-white p-5">
            <h3 className="text-[13px] font-medium text-slate-900">
              错题回顾（{wrongItems.length}）
            </h3>
            <ul className="mt-3 space-y-2.5">
              {wrongItems.map((item) => (
                <li
                  key={item.id}
                  className="flex flex-wrap items-baseline gap-x-2 gap-y-1 border-t border-slate-100 pt-2.5 first:border-0 first:pt-0"
                >
                  <span className="text-[14px] font-medium text-slate-900">
                    {DISPLAY_NAME(item)}
                  </span>
                  {canSpeak && (
                    <button
                      type="button"
                      onClick={() => speakEnglish(DISPLAY_NAME(item))}
                      title={`朗读 ${DISPLAY_NAME(item)}`}
                      className="rounded p-0.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700"
                    >
                      <SpeakerIcon className="h-3.5 w-3.5" />
                    </button>
                  )}
                  {item.phonetic && (
                    <span className="text-[11px] text-slate-400">/{item.phonetic}/</span>
                  )}
                  <span className="w-full text-[12px] leading-relaxed text-slate-600">
                    {item.translation}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    )
  }

  // ---------- 答题 ----------

  if (!current) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white px-5 py-10 text-center text-[13px] text-slate-400">
        没有可用题目。
      </div>
    )
  }

  const progress = ((index + (revealed ? 1 : 0)) / questions.length) * 100
  const correctText = isSpelling ? DISPLAY_NAME(current.item) : current.correctOption ?? ''

  return (
    <div data-practice-phase="quiz" className="space-y-5">
      <PageHeader onBack={() => setPhase('setup')} />

      {/* 进度 */}
      <div className="flex items-center gap-3">
        <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-100">
          <div
            data-practice-progress=""
            className="h-full rounded-full bg-slate-900 transition-all duration-300"
            style={{ width: `${progress}%` }}
          />
        </div>
        <span className="shrink-0 text-[12px] tabular-nums text-slate-500">
          {index + 1} / {questions.length}
        </span>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-6">
        {/* 题干 */}
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span
            data-practice-badge={mode}
            className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-500"
          >
            {MODE_META[mode].badge}
          </span>
          {current.item.media_title && (
            <span className="text-[10px] text-slate-400">来自《{current.item.media_title}》</span>
          )}
        </div>

        {isDictation ? (
          /* 听写：只给发音，不给任何文字（单词/音标都不显示） */
          <div className="mt-3">
            <button
              type="button"
              data-practice-play=""
              onClick={() => listen()}
              className="flex items-center gap-2.5 rounded-xl border border-slate-200 bg-slate-50 px-5 py-3.5 text-[14px] text-slate-700 transition-colors hover:border-slate-400 hover:bg-slate-100"
            >
              <SpeakerIcon className="h-5 w-5 text-slate-500" />
              {plays === 0 ? '点击播放发音' : '再听一次'}
            </button>
            <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1.5">
              <button
                type="button"
                data-practice-play-slow=""
                onClick={() => listen(0.6)}
                className="rounded-lg border border-slate-200 px-2.5 py-1 text-[11px] text-slate-500 transition-colors hover:bg-slate-50"
              >
                慢速重播
              </button>
              <span data-practice-plays="" className="text-[11px] text-slate-400">
                已听 {plays} 次
              </span>
            </div>
          </div>
        ) : isSpelling ? (
          <p data-practice-prompt="" className="mt-3 text-[17px] leading-relaxed text-slate-900">
            {current.item.translation}
          </p>
        ) : (
          <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1">
            <span data-practice-prompt="" className="text-[26px] font-medium text-slate-900">
              {DISPLAY_NAME(current.item)}
            </span>
            {current.item.phonetic && (
              <span className="text-[12px] text-slate-400">/{current.item.phonetic}/</span>
            )}
            {canSpeak && (
              <button
                type="button"
                data-practice-speak=""
                onClick={() => speakEnglish(DISPLAY_NAME(current.item))}
                title="朗读"
                className="flex items-center gap-1 rounded-lg border border-slate-200 px-2 py-1 text-[11px] text-slate-500 transition-colors hover:bg-slate-50"
              >
                <SpeakerIcon className="h-3.5 w-3.5" />
                朗读
              </button>
            )}
          </div>
        )}

        {(isSpelling && mode === 'zh2en') && current.item.context && (
          <p className="mt-2 text-[11px] leading-relaxed text-slate-400">
            上下文：{current.item.context}
          </p>
        )}

        {/* 作答区 */}
        <div className="mt-5 border-t border-slate-100 pt-5">
          {isSpelling ? (
            <div className="flex flex-wrap items-center gap-2">
              <input
                ref={inputRef}
                data-practice-input=""
                value={input}
                disabled={revealed}
                onChange={(e) => setInput(e.target.value)}
                placeholder={isDictation ? '写下你听到的单词，回车提交' : '输入英文单词，回车提交'}
                autoComplete="off"
                autoCapitalize="off"
                spellCheck={false}
                className={[
                  'w-full max-w-[320px] rounded-lg border px-3 py-2 text-[15px] text-slate-800 outline-none transition-colors disabled:bg-slate-50',
                  revealed
                    ? answered
                      ? 'border-emerald-300 bg-emerald-50/40'
                      : 'border-red-300 bg-red-50/40'
                    : 'border-slate-300 focus:border-slate-500',
                ].join(' ')}
              />
              {!revealed && (
                <>
                  <button
                    type="button"
                    data-practice-submit=""
                    onClick={submitSpelling}
                    className="rounded-lg bg-slate-900 px-4 py-2 text-[13px] text-white transition-colors hover:bg-slate-700"
                  >
                    提交
                  </button>
                  <button
                    type="button"
                    onClick={giveUp}
                    className="flex items-center gap-1 rounded-lg border border-slate-200 px-3 py-2 text-[12px] text-slate-500 transition-colors hover:bg-slate-50"
                  >
                    <LightbulbIcon className="h-3.5 w-3.5" />
                    不会，看答案
                  </button>
                </>
              )}
            </div>
          ) : (
            <div className="grid gap-2 sm:grid-cols-2">
              {(current.options ?? []).map((option) => {
                const isCorrectOption = option === current.correctOption
                const isPickedOption = option === picked
                let tone = 'border-slate-200 hover:border-slate-400 hover:bg-slate-50'
                if (revealed && isCorrectOption) {
                  tone = 'border-emerald-300 bg-emerald-50 text-emerald-800'
                } else if (revealed && isPickedOption) {
                  tone = 'border-red-300 bg-red-50 text-red-700'
                }
                return (
                  <button
                    key={option}
                    type="button"
                    data-practice-option=""
                    disabled={revealed}
                    onClick={() => choose(option)}
                    className={`rounded-lg border px-3 py-2.5 text-left text-[12px] leading-relaxed text-slate-700 transition-colors disabled:cursor-default ${tone}`}
                  >
                    {option}
                    {revealed && isCorrectOption && (
                      <CheckIcon className="ml-1 inline h-3.5 w-3.5 align-[-2px] text-emerald-600" />
                    )}
                    {revealed && isPickedOption && !isCorrectOption && (
                      <CloseIcon className="ml-1 inline h-3.5 w-3.5 align-[-2px] text-red-500" />
                    )}
                  </button>
                )
              })}
            </div>
          )}

          {/* 反馈 */}
          {revealed && (
            <div
              data-practice-feedback={answered ? 'correct' : 'wrong'}
              className={[
                'mt-4 flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-lg px-3 py-2.5 text-[12px]',
                answered
                  ? 'bg-emerald-50 text-emerald-700'
                  : 'bg-red-50 text-red-700',
              ].join(' ')}
            >
              <span className="flex items-center gap-1 font-medium">
                {answered ? <CheckIcon className="h-3.5 w-3.5" /> : <CloseIcon className="h-3.5 w-3.5" />}
                {answered ? '回答正确' : '回答错误'}
              </span>
              {!answered && (
                <span className="text-slate-700">
                  正确答案：
                  <span className="font-medium text-slate-900">{correctText}</span>
                  {isSpelling && current.item.phonetic && (
                    <span className="ml-1.5 text-slate-400">/{current.item.phonetic}/</span>
                  )}
                </span>
              )}
              {canSpeak && (
                <button
                  type="button"
                  data-practice-speak=""
                  onClick={() => speakEnglish(DISPLAY_NAME(current.item))}
                  title="朗读正确发音"
                  className="flex items-center gap-1 rounded border border-slate-200 bg-white px-2 py-0.5 text-[11px] text-slate-600 transition-colors hover:bg-slate-50"
                >
                  <SpeakerIcon className="h-3 w-3" />
                  朗读
                </button>
              )}
              <button
                type="button"
                data-practice-next=""
                onClick={next}
                className="ml-auto rounded-lg bg-slate-900 px-3.5 py-1.5 text-[12px] text-white transition-colors hover:bg-slate-700"
              >
                {index + 1 >= questions.length ? '看结果' : '下一题'}
              </button>
            </div>
          )}

          {isSpelling && !revealed && current.accept.length > 0 && (
            <p className="mt-2 text-[11px] text-slate-400">
              {isDictation
                ? '大小写与标点不计；没听清可以多点几次播放，或试试「慢速重播」。'
                : '大小写与标点不计；填原型也可以（如 went → go）。'}
            </p>
          )}

          {isDictation && revealed && (current.item.translation ?? '').trim() && (
            <p className="mt-2 text-[11px] leading-relaxed text-slate-400">
              释义：{current.item.translation}
            </p>
          )}
        </div>
      </div>
    </div>
  )
}

// --------------------------- 小组件 ---------------------------

function PageHeader({ onBack }: { onBack: (() => void) | null }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h2 className="text-[15px] font-medium text-slate-900">生词练习</h2>
        <p className="mt-1 text-[13px] text-slate-500">
          用生词本里的词做中译英 / 英译中 / 听写练习，答错的词会单独列出来。
        </p>
      </div>
      {onBack ? (
        <button
          type="button"
          onClick={onBack}
          className="flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-2 text-[12px] text-slate-600 transition-colors hover:bg-slate-50"
        >
          <BackIcon className="h-3.5 w-3.5" />
          退出练习
        </button>
      ) : (
        <Link
          to="/vocab"
          className="flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-2 text-[12px] text-slate-600 transition-colors hover:bg-slate-50"
        >
          <BackIcon className="h-3.5 w-3.5" />
          返回生词本
        </Link>
      )}
    </div>
  )
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-start gap-x-4 gap-y-2">
      <span className="w-[64px] shrink-0 pt-2 text-[12px] text-slate-500">{label}</span>
      <div className="flex flex-1 flex-wrap gap-2">{children}</div>
    </div>
  )
}

function Choice({
  active,
  disabled,
  onClick,
  title,
  desc,
}: {
  active: boolean
  disabled?: boolean
  onClick: () => void
  title: string
  desc: string
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={[
        'min-w-[104px] rounded-lg border px-3 py-2 text-left transition-colors',
        disabled
          ? 'cursor-not-allowed border-slate-100 bg-slate-50 opacity-60'
          : active
            ? 'border-slate-900 bg-slate-900 text-white'
            : 'border-slate-200 text-slate-700 hover:border-slate-400 hover:bg-slate-50',
      ].join(' ')}
    >
      <span className="block text-[12px]">{title}</span>
      <span className={`mt-0.5 block text-[10px] ${active && !disabled ? 'text-slate-300' : 'text-slate-400'}`}>
        {desc}
      </span>
    </button>
  )
}

/**
 * Tailwind 配置（P0 · token 挂接）
 *
 * 原则（见 `docs/ARCH-UI-落地-v1.md` §2.2）：
 *   - **只挂高频键**，不重写默认 theme —— 存量页面的 `bg-slate-*` / `text-emerald-*` 等语义
 *     保持可用，P1 逐页换皮时可逐页回滚；
 *   - 所有值一律指向 `src/styles/tokens.css` 的 CSS 变量 → token 单一真相，改色只改一处；
 *   - 注意：用 `var()` 挂接的颜色**不支持 `/opacity` 修饰符**（`bg-lemon-400/50` 无效），
 *     需要半透明时用独立变量（如 `--fl-ring`）或 `color-mix()`，不要硬编码色值。
 */

/** @type {import('tailwindcss').Config} */
export default {
  // 旧前端只扫 .ts/.tsx；Vue 版必须同时含 .vue，否则模板里的 className 会被 purge 掉。
  content: ['./index.html', './src/**/*.{ts,vue}'],
  theme: {
    extend: {
      colors: {
        // 主色：柠檬黄（100 最淡 → 500 最深）
        lemon: {
          100: 'var(--lemon-100)',
          200: 'var(--lemon-200)',
          300: 'var(--lemon-300)',
          400: 'var(--lemon-400)',
          500: 'var(--lemon-500)',
        },
        // 墨 / 文字：text-ink / text-ink-2 / text-ink-3
        ink: {
          DEFAULT: 'var(--ink)',
          2: 'var(--ink-2)',
          3: 'var(--ink-3)',
        },
        // 叶绿（成功 / 进度）：bg-leaf / bg-leaf-1
        leaf: {
          DEFAULT: 'var(--leaf)',
          1: 'var(--leaf-1)',
        },
        // 桃红（提醒 / 危险）：bg-peach / bg-peach-1
        peach: {
          DEFAULT: 'var(--peach)',
          1: 'var(--peach-1)',
        },
        // 面：bg-cream / bg-cream-2
        cream: {
          DEFAULT: 'var(--cream)',
          2: 'var(--cream-2)',
        },
        // 卡片面：bg-card
        card: 'var(--card)',
      },
      borderRadius: {
        // 契约 §3：圆角只 3 档 —— 卡片 20 / 控件 14 / 药丸 999
        card: 'var(--radius-card)',
        control: 'var(--radius-control)',
        pill: 'var(--radius-pill)',
      },
      boxShadow: {
        // 贴纸式硬阴影：sticker 常态 / sticker-lift 抬起
        sticker: 'var(--shadow-sticker)',
        'sticker-lift': 'var(--shadow-sticker-lift)',
        // 焦点光环（输入框 focus / :focus-visible 用，替代 ring）
        ring: 'var(--fl-ring)',
      },
      fontFamily: {
        // 纯系统字体栈，零外网依赖（契约 §2）
        sans: ['var(--font-sans)'],
      },
      borderWidth: {
        // 契约 §3：统一 2px 描边 → border-stroke
        stroke: 'var(--fl-stroke)',
      },
      // 注意：**不挂 `spacing`**。契约 §3 的 7 档间距（8/12/14/18/22/26/34）已在
      // tokens.css 里以 `--fl-space-*` 提供；若挂进 spacing，`14` 会覆盖 tailwind 默认的
      // `p-14 = 3.5rem`（56px）→ 存量页面可能被静默改距，与本阶段「不动页面」冲突。
      // 需要用时直接写 `p-[var(--fl-space-18)]` 或既有数值类。
    },
  },
  plugins: [],
}

/** @type {import('tailwindcss').Config} */
export default {
  // 旧前端只扫 .ts/.tsx；Vue 版必须同时含 .vue，否则模板里的 className 会被 purge 掉。
  content: ['./index.html', './src/**/*.{ts,vue}'],
  theme: {
    extend: {},
  },
  plugins: [],
}

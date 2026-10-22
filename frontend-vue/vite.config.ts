import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发服务器跑在 5174（错开旧 React 前端的 5173，便于双跑比对）。
// strictPort: 端口被占直接报错，绝不静默换端口 —— 本机历史高频坑。
//
// /api 代理目标可用环境变量 `FAYELONG_API_TARGET` 覆盖（默认本机 8000）：
// 破坏性验证要跑在「隔离后端」上时，用
//   FAYELONG_API_TARGET=http://127.0.0.1:8010 npm run dev
// 起一个把 /api 指到隔离实例的 dev，从而绝不误伤真实库。
const API_TARGET = process.env.FAYELONG_API_TARGET || 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5174,
    strictPort: true,
    proxy: {
      '/api': {
        target: API_TARGET,
        changeOrigin: true,
      },
    },
  },
})

/**
 * `echo` 占位题型的注册入口（G4-① 「零改核心即可挂载」预演）。
 *
 * 为什么单独一个函数而不是模块顶层自注册
 * ====================================
 * 演示题型不该出现在生产清单里。**顶层自注册**会让「谁 import 了它」变成隐式
 * 副作用（打包器还可能因为它没被用到而 tree-shake 掉，导致行为随构建方式变化）。
 * 显式调用 `registerEcho()` 才有确定的时机与确定的后果。
 *
 * 启用方式（二选一，均**不需要**改 `question-types/index.ts` 或宿主页面）：
 *
 * ```ts
 * // ① 在入口（main.ts）显式启用
 * import { registerEcho } from './question-types/echo'
 * registerEcho()
 *
 * // ② 或在某个只在演示环境加载的模块里启用
 * ```
 *
 * ⚠️ 后端也要同时注册，否则 `GET /api/question-types` 的清单里没有 `echo`，
 * 页面永远不会选到它（前端清单以外后端的下发为准）。
 */

import { registerQuestionType } from '../index'
import EchoAnswer from './Answer.vue'
import EchoResult from './Result.vue'

/** 把 `echo` 题型挂进前端组件注册表（幂等）。 */
export function registerEcho(): void {
  registerQuestionType('echo', { Answer: EchoAnswer, Result: EchoResult })
}

/**
 * 后端契约类型入口 —— 由 `contracts/api-types.d.ts`（后端 OpenAPI 生成）转出。
 *
 * ⚠️ **纯类型**：用 `import type` 引用，编译后被完全抹掉，运行时不会去请求 `contracts/`，
 * Vite 打包也不会把它带进产物。
 */
import type { components } from '../../../contracts/api-types'

/** 后端全部 schema 的命名空间：`Schemas['MediaOut']` 即后端 `MediaOut`。 */
export type Schemas = components['schemas']

<script setup lang="ts">
/**
 * 登录 / 首次初始化页（v1.12 单账号门禁）。
 *
 * 视觉：`design/page-5-login.html`（左品牌面 + 右表单卡）。**只换皮，不改逻辑**：
 * 提交、校验、错误文案、缓存失效行为全部逐字沿用旧实现。
 *
 * ⚠️ 脚本依赖（改文案前先看这里，动了就红）：
 *   - `#username` / `#password` / `#confirm` 三个 id（verify_vue_login 用 id 探针）
 *   - `form button[type=submit]` **唯一**，文案必须是 `登录` / `创建并进入` / `处理中…`
 *   - placeholder 逐字：`例如 faye` / `至少 N 位` / `确认密码`
 *   - 错误元素必须留在 form 内且带 `text-red-600`（`verify_vue_login` 用 `form .text-red-600` 取错误文案）
 *   - 首个 `<p>` 是形态副标题（probe 取 `h1 + p, p`），setup 形态必须含「首次使用」
 *     → 品牌面板的 slogan 因此用 `<div>` 而不是 `<p>`，且 feats 里也不放 `<p>`
 *   - 页面内必须出现「这台服务在公网」与「学习数据保存在你自己的服务器上」两段文案
 *
 * 刻意**不给**「忘记密码」自助入口（站点在公网，重置只能改数据库）、
 * 也**不做**「保持登录」假开关（会话 cookie 本身就是长效的）—— 设计稿里的这两个控件是展示用的。
 */
import { computed, ref } from 'vue'
import { useMutation, useQueryClient } from '@tanstack/vue-query'
import { login, setupAccount, type AuthStatus } from '../api/client'

const props = defineProps<{ status: AuthStatus }>()

const queryClient = useQueryClient()
const setup = computed(() => props.status.needs_setup)
const minLen = computed(() => props.status.min_password_length)

const username = ref('')
const password = ref('')
const confirm = ref('')
const error = ref<string | null>(null)

const submit = useMutation({
  mutationFn: (vars: { username: string; password: string }) =>
    props.status.needs_setup
      ? setupAccount(vars.username, vars.password)
      : login(vars.username, vars.password),
  onSuccess: (data) => {
    password.value = ''
    confirm.value = ''
    error.value = null
    queryClient.setQueryData(['auth', 'status'], data)
    // 换账号后别把上一个人的学习数据留在缓存里
    queryClient.removeQueries({ predicate: (q) => q.queryKey[0] !== 'auth' })
  },
  onError: (e) => {
    error.value = (e as Error).message
  },
})

function onSubmit() {
  const name = username.value.trim()
  if (!name) {
    error.value = '请填写用户名'
    return
  }
  // 校验②③ 用的是**原始** password（不是 trim 后的 name），与原实现一致
  if (password.value.length < props.status.min_password_length) {
    error.value = `密码至少 ${props.status.min_password_length} 位`
    return
  }
  if (props.status.needs_setup && password.value !== confirm.value) {
    error.value = '两次输入的密码不一致'
    return
  }
  error.value = null
  submit.mutate({ username: name, password: password.value })
}

/** 契约 §4「输入框」：白底 14px 圆角控件 + 2px 半透明棕描边，focus 转实棕并加 4px 黄光环。 */
const inputClass = 'input h-[50px] text-[15px] rounded-control'

/** 品牌面三条特性（图标为手写内联 SVG，2px 圆头描边，currentColor 继承）。 */
const feats = [
  { title: '上传就切成句', desc: '解码 → 识别 → 翻译 → 切片，全自动，不用手动打点' },
  { title: '答案不在页面里', desc: '听写判定只在服务端完成，打开 F12 也看不到原文' },
  { title: '点一下就收进生词本', desc: '句子里的词随手收，隔天自动排进复习' },
] as const
</script>

<template>
  <div class="grid min-h-dvh grid-cols-1 bg-cream text-ink md:grid-cols-[1.05fr_.95fr]">
    <!-- ============ 左：品牌面（≤767 收到顶部一条） ============ -->
    <aside
      class="relative flex items-center justify-center overflow-hidden border-b-[2px] border-ink bg-lemon-100 px-[22px] pb-[22px] pt-[26px] md:items-center md:border-b-0 md:border-r-[2px] md:px-12 md:py-14"
    >
      <!-- 三色光斑（纯 CSS，无外链资源） -->
      <span
        class="pointer-events-none absolute -left-[100px] -top-[90px] h-[260px] w-[260px] rounded-full bg-lemon-200 opacity-[0.85] md:-left-[130px] md:-top-[120px] md:h-[420px] md:w-[420px]"
      />
      <span
        class="pointer-events-none absolute -bottom-[90px] -right-[70px] h-[190px] w-[190px] rounded-full bg-leaf-1 opacity-80 md:-bottom-[80px] md:-right-[90px] md:h-[300px] md:w-[300px]"
      />
      <span
        class="pointer-events-none absolute right-[44px] top-[34px] h-[76px] w-[76px] rounded-full bg-peach-1 opacity-70 md:right-[70px] md:top-[56px] md:h-[120px] md:w-[120px]"
      />

      <div class="relative w-full max-w-[430px]">
        <img
          src="/logo.png"
          alt="FayeLong 标志"
          draggable="false"
          class="mb-2.5 block h-16 w-16 -rotate-[4deg] select-none md:mb-6 md:h-[120px] md:w-[120px]"
        />
        <h1 class="text-[22px] font-extrabold leading-tight tracking-[0.4px] md:text-[34px]">
          FayeLong
        </h1>
        <!-- 用 div 而非 p：登录页探针把「首个 p」当成形态副标题，这里不能抢位 -->
        <div class="mt-1.5 text-[16px] font-bold leading-normal md:mt-3 md:text-[22px]">
          一句一句，<br />
          <span class="bg-lemon-200 px-0.5">把英语听进去。</span>
        </div>

        <!-- 三条特性：移动端隐藏（省高度，与设计稿一致） -->
        <ul class="mt-[30px] hidden list-none flex-col gap-3.5 p-0 md:flex">
          <li v-for="(f, i) in feats" :key="f.title" class="flex items-start gap-3">
            <span
              class="grid h-[34px] w-[34px] shrink-0 place-items-center rounded-full border-[2px] border-ink bg-card text-ink"
            >
              <svg
                v-if="i === 0"
                width="17"
                height="17"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2.1"
                stroke-linecap="round"
                stroke-linejoin="round"
              >
                <path d="M3 12h2" />
                <path d="M8 8v8" />
                <path d="M13 5v14" />
                <path d="M18 9v6" />
                <path d="M21 11v2" />
              </svg>
              <svg
                v-else-if="i === 1"
                width="17"
                height="17"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2.1"
                stroke-linecap="round"
                stroke-linejoin="round"
              >
                <rect x="4" y="10" width="16" height="10" rx="2" />
                <path d="M8 10V7a4 4 0 018 0v3" />
              </svg>
              <svg
                v-else
                width="17"
                height="17"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2.1"
                stroke-linecap="round"
                stroke-linejoin="round"
              >
                <path d="M5 4h11a3 3 0 013 3v13H8a3 3 0 01-3-3z" />
                <path d="M9 9h6" />
              </svg>
            </span>
            <div>
              <b class="block text-[13.5px] font-bold leading-normal">{{ f.title }}</b>
              <span class="block text-[12.5px] leading-relaxed text-ink-2">{{ f.desc }}</span>
            </div>
          </li>
        </ul>
      </div>
    </aside>

    <!-- ============ 右：表单卡 ============ -->
    <main class="relative flex flex-col items-center justify-center px-[18px] pb-9 pt-6 md:px-10 md:py-12">
      <form
        class="relative w-full max-w-[404px] rounded-[22px] border-[2px] border-ink bg-card px-5 pb-[22px] pt-[26px] shadow-sticker md:max-w-[404px] md:rounded-[26px] md:px-[30px] md:pb-7 md:pt-8"
        @submit.prevent="onSubmit"
      >
        <!-- 探头小龙贴纸 -->
        <img
          src="/logo.png"
          alt=""
          aria-hidden="true"
          draggable="false"
          class="pointer-events-none absolute -right-1.5 -top-6 h-[62px] w-[62px] rotate-[8deg] select-none md:-right-3.5 md:-top-[30px] md:h-[78px] md:w-[78px]"
        />

        <h2 class="text-[21px] font-extrabold tracking-[0.3px] md:text-[24px]">
          {{ setup ? '首次登录 FayeLong' : '登录 FayeLong' }}
        </h2>
        <p class="mt-1.5 text-[13px] leading-relaxed text-ink-3">
          {{ setup ? '首次使用，先设置账号' : '只属于你一个人的听力教室' }}
        </p>

        <label class="mt-5 block" for="username">
          <span class="mb-[7px] block text-[12.5px] font-bold text-ink-2">用户名</span>
          <input
            id="username"
            name="username"
            autocomplete="username"
            autofocus
            v-model="username"
            placeholder="例如 faye"
            :class="inputClass"
          />
        </label>

        <label class="mt-4 block" for="password">
          <span class="mb-[7px] block text-[12.5px] font-bold text-ink-2">密码</span>
          <input
            id="password"
            name="password"
            type="password"
            :autocomplete="setup ? 'new-password' : 'current-password'"
            v-model="password"
            :placeholder="`至少 ${minLen} 位`"
            :class="inputClass"
          />
        </label>

        <label v-if="setup" class="mt-4 block" for="confirm">
          <span class="mb-[7px] block text-[12.5px] font-bold text-ink-2">再输一次</span>
          <input
            id="confirm"
            name="confirm"
            type="password"
            autocomplete="new-password"
            v-model="confirm"
            placeholder="确认密码"
            :class="inputClass"
          />
        </label>

        <p
          v-if="error"
          class="mt-4 rounded-control border-[2px] border-peach bg-peach-1 px-3 py-2 text-[12px] font-bold text-red-600"
        >
          {{ error }}
        </p>

        <button
          type="submit"
          :disabled="submit.isPending.value"
          class="btn btn-primary mt-[22px] h-[52px] w-full text-[15px] md:h-[50px]"
        >
          {{ submit.isPending.value ? '处理中…' : setup ? '创建并进入' : '登录' }}
          <svg
            v-if="!(submit.isPending.value)"
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2.4"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <path d="M5 12h13" />
            <path d="M13 6l6 6-6 6" />
          </svg>
        </button>

        <p v-if="setup" class="mt-4 text-[11.5px] leading-relaxed text-ink-3">
          这台服务在公网，请设置一个不容易被猜到的用户名与密码。 账号只能创建一次；之后想改密码，可在右上角账号菜单里修改。
        </p>

        <p
          class="mt-[18px] border-t-[1.5px] border-dashed border-ink-3 pt-4 text-center text-[11.5px] leading-relaxed text-ink-3"
        >
          学习数据保存在你自己的服务器上，不上传任何第三方
        </p>
      </form>

      <p class="mt-3.5 flex items-center justify-center gap-[7px] text-[11.5px] text-ink-3">
        <i class="h-2 w-2 rounded-full bg-leaf" />本地服务 · 数据只在这台机器
      </p>
    </main>
  </div>
</template>

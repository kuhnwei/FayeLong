/** 登录 / 首次初始化页（v1.12 单账号门禁）。
 *
 * 同一页承载两种形态：
 * - `needs_setup` 为真 → 初始化：设置第一个账号（服务端只允许建一次，建完即锁定）
 * - 否               → 登录
 *
 * 站点在公网，所以这里刻意不给「忘记密码」之类的自助入口 ——
 * 重置只能到服务器上直接改数据库，这是有意为之的收紧。
 */

import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { login, setupAccount, type AuthStatus } from '../api/client'

export default function LoginPage({ status }: { status: AuthStatus }) {
  const queryClient = useQueryClient()
  const setup = status.needs_setup
  const minLen = status.min_password_length

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<string | null>(null)

  const submit = useMutation({
    mutationFn: (vars: { username: string; password: string }) =>
      setup ? setupAccount(vars.username, vars.password) : login(vars.username, vars.password),
    onSuccess: (data) => {
      setPassword('')
      setConfirm('')
      setError(null)
      queryClient.setQueryData(['auth', 'status'], data)
      // 换账号后别把上一个人的学习数据留在缓存里
      queryClient.removeQueries({ predicate: (q) => q.queryKey[0] !== 'auth' })
    },
    onError: (e: Error) => setError(e.message),
  })

  const onSubmit = (event: React.FormEvent) => {
    event.preventDefault()
    const name = username.trim()
    if (!name) {
      setError('请填写用户名')
      return
    }
    if (password.length < minLen) {
      setError(`密码至少 ${minLen} 位`)
      return
    }
    if (setup && password !== confirm) {
      setError('两次输入的密码不一致')
      return
    }
    setError(null)
    submit.mutate({ username: name, password })
  }

  const inputClass =
    'w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-[14px] text-slate-800 outline-none transition-colors placeholder:text-slate-400 focus:border-slate-500'

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-6 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-6 text-center">
          <h1 className="text-[20px] font-medium text-slate-900">FayeLong 英语学习</h1>
          <p className="mt-1.5 text-[13px] text-slate-500">
            {setup ? '首次使用，先设置账号' : '请输入账号密码继续'}
          </p>
        </div>

        <form
          onSubmit={onSubmit}
          className="space-y-3 rounded-xl border border-slate-200 bg-white p-6"
        >
          <div>
            <label className="mb-1.5 block text-[12px] text-slate-500" htmlFor="username">
              用户名
            </label>
            <input
              id="username"
              name="username"
              autoComplete="username"
              autoFocus
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="例如 faye"
              className={inputClass}
            />
          </div>

          <div>
            <label className="mb-1.5 block text-[12px] text-slate-500" htmlFor="password">
              密码
            </label>
            <input
              id="password"
              name="password"
              type="password"
              autoComplete={setup ? 'new-password' : 'current-password'}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={`至少 ${minLen} 位`}
              className={inputClass}
            />
          </div>

          {setup && (
            <div>
              <label className="mb-1.5 block text-[12px] text-slate-500" htmlFor="confirm">
                再输一次
              </label>
              <input
                id="confirm"
                name="confirm"
                type="password"
                autoComplete="new-password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                placeholder="确认密码"
                className={inputClass}
              />
            </div>
          )}

          {error && (
            <p className="rounded-lg bg-red-50 px-3 py-2 text-[12px] text-red-600">{error}</p>
          )}

          <button
            type="submit"
            disabled={submit.isPending}
            className="w-full rounded-lg bg-slate-900 px-4 py-2.5 text-[14px] text-white transition-colors hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {submit.isPending ? '处理中…' : setup ? '创建并进入' : '登录'}
          </button>

          {setup && (
            <p className="text-[11px] leading-relaxed text-slate-400">
              这台服务在公网，请设置一个不容易被猜到的用户名与密码。
              账号只能创建一次；之后想改密码，可在右上角账号菜单里修改。
            </p>
          )}
        </form>

        <p className="mt-4 text-center text-[11px] text-slate-400">
          学习数据保存在你自己的服务器上，不上传任何第三方
        </p>
      </div>
    </div>
  )
}

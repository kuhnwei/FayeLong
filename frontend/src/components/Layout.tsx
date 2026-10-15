import { useEffect, useRef, useState, type ReactNode } from 'react'
import { NavLink } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { changePassword, getAuthStatus, getHealth, logout } from '../api/client'
import PlayerBar from './PlayerBar'

/** 导航项：手机上收紧内边距与字号，桌面上放宽。 */
const navClass = ({ isActive }: { isActive: boolean }) =>
  [
    'shrink-0 rounded-lg px-2 py-1.5 text-[13px] transition-colors sm:px-3 sm:py-2 sm:text-sm',
    isActive
      ? 'bg-slate-900 text-white'
      : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900',
  ].join(' ')

/** 后端状态胶囊。窄屏放不下，md 以下隐藏（信息仍可在媒体库「环境自检」里看到）。 */
function BackendStatus() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['health'],
    queryFn: getHealth,
  })

  let dot = 'bg-slate-300'
  let text = '检查后端…'
  if (isLoading) {
    dot = 'bg-amber-400'
  } else if (isError) {
    dot = 'bg-red-500'
    text = '后端未连接'
  } else if (data) {
    dot = 'bg-green-500'
    text = `后端正常 · 模型 ${data.config.whisper_model}`
  }

  return (
    <div className="hidden items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1.5 md:flex">
      <span className={`h-2 w-2 rounded-full ${dot}`} />
      <span className="text-xs text-slate-600">{text}</span>
    </div>
  )
}

/** 右上角账号菜单：改密码 / 退出登录。 */
function AccountMenu() {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [changing, setChanging] = useState(false)
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [msg, setMsg] = useState<string | null>(null)
  const boxRef = useRef<HTMLDivElement | null>(null)

  const { data } = useQuery({
    queryKey: ['auth', 'status'],
    queryFn: getAuthStatus,
    staleTime: 0,
  })

  // 点击别处收起
  useEffect(() => {
    if (!open) return
    const onDown = (event: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  const signOut = useMutation({
    mutationFn: logout,
    onSuccess: (status) => {
      queryClient.setQueryData(['auth', 'status'], status)
      // 换账号后不要把上一个人的学习数据留在缓存里
      queryClient.removeQueries({ predicate: (q) => q.queryKey[0] !== 'auth' })
    },
  })

  const savePassword = useMutation({
    mutationFn: () => changePassword(current, next),
    onSuccess: () => {
      setCurrent('')
      setNext('')
      setChanging(false)
      setMsg('密码已更新')
    },
    onError: (e: Error) => setMsg(e.message),
  })

  const minLen = data?.min_password_length ?? 8
  const canSave = current.length > 0 && next.length >= minLen && !savePassword.isPending

  return (
    <div ref={boxRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1 rounded-full border border-slate-200 bg-white px-2.5 py-1.5 text-xs text-slate-600 transition-colors hover:bg-slate-50 sm:gap-1.5 sm:px-3"
      >
        <span className="max-w-[6rem] truncate sm:max-w-[10rem]">{data?.username ?? '账号'}</span>
        <span className="text-slate-400">▾</span>
      </button>

      {open && (
        <div className="absolute right-0 z-50 mt-2 w-64 rounded-xl border border-slate-200 bg-white p-3 shadow-lg">
          {msg && (
            <p className="mb-2 rounded-lg bg-slate-50 px-2.5 py-1.5 text-[11px] text-slate-600">
              {msg}
            </p>
          )}

          {changing ? (
            <div className="space-y-2">
              <input
                type="password"
                autoComplete="current-password"
                value={current}
                onChange={(e) => setCurrent(e.target.value)}
                placeholder="当前密码"
                className="w-full rounded-lg border border-slate-300 px-2.5 py-1.5 text-[12px] outline-none focus:border-slate-500"
              />
              <input
                type="password"
                autoComplete="new-password"
                value={next}
                onChange={(e) => setNext(e.target.value)}
                placeholder={`新密码（至少 ${minLen} 位）`}
                className="w-full rounded-lg border border-slate-300 px-2.5 py-1.5 text-[12px] outline-none focus:border-slate-500"
              />
              <div className="flex gap-2">
                <button
                  type="button"
                  disabled={!canSave}
                  onClick={() => {
                    setMsg(null)
                    savePassword.mutate()
                  }}
                  className="flex-1 rounded-lg bg-slate-900 px-3 py-1.5 text-[12px] text-white transition-colors hover:bg-slate-700 disabled:opacity-40"
                >
                  {savePassword.isPending ? '保存中…' : '保存'}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setChanging(false)
                    setCurrent('')
                    setNext('')
                    setMsg(null)
                  }}
                  className="rounded-lg border border-slate-200 px-3 py-1.5 text-[12px] text-slate-600 hover:bg-slate-50"
                >
                  取消
                </button>
              </div>
            </div>
          ) : (
            <div className="space-y-1">
              <button
                type="button"
                onClick={() => {
                  setChanging(true)
                  setMsg(null)
                }}
                className="w-full rounded-lg px-2.5 py-2 text-left text-[12px] text-slate-600 transition-colors hover:bg-slate-50"
              >
                修改密码
              </button>
              <button
                type="button"
                onClick={() => signOut.mutate()}
                className="w-full rounded-lg px-2.5 py-2 text-left text-[12px] text-slate-600 transition-colors hover:bg-slate-50"
              >
                退出登录
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

/**
 * 应用外壳。
 *
 * 结构是「固定高度 + 三段 flex」：
 *   header（shrink-0） / main（flex-1 min-h-0 overflow-y-auto） / PlayerBar（shrink-0）
 *
 * 为什么这么做：旧版用 `fixed bottom-0` 的播放条 + 学习页 `calc(100vh - 109px)` 的魔法数字。
 * 那些数字是按桌面顶栏高度（61px）与 main 内边距（24px）算出来的，手机上顶栏一换行变高就全错。
 * 改成固定高度的 flex 外壳后，学习页只写 `h-full` 就刚好撑满可用空间，**与顶栏/播放条实际高度无关**。
 *
 * 用 `h-dvh` 而不是 `h-screen`：dvh 取动态视口高度，移动端地址栏收起/展开时不会跳动。
 */
export default function Layout({ children }: { children: ReactNode }) {
  return (
    <div className="flex h-dvh flex-col overflow-hidden bg-slate-50">
      <header className="shrink-0 border-b border-slate-200 bg-white pt-[env(safe-area-inset-top)]">
        <div className="mx-auto flex w-full max-w-5xl items-center gap-2 px-3 py-2 sm:gap-4 sm:px-6 sm:py-3">
          <h1 className="shrink-0 text-[14px] font-medium text-slate-900 sm:text-[15px]">
            <span className="hidden sm:inline">FayeLong 英语学习</span>
            <span className="sm:hidden">FayeLong</span>
          </h1>
          <nav className="flex min-w-0 items-center gap-0.5 sm:gap-1">
            <NavLink to="/" className={navClass} end>
              媒体库
            </NavLink>
            <NavLink to="/vocab" className={navClass}>
              生词本
            </NavLink>
          </nav>
          <div className="ml-auto flex shrink-0 items-center gap-2">
            <BackendStatus />
            <AccountMenu />
          </div>
        </div>
      </header>

      <main className="mx-auto min-h-0 w-full max-w-5xl flex-1 overflow-y-auto px-3 py-3 sm:px-6 sm:py-6">
        {children}
      </main>

      <PlayerBar />
    </div>
  )
}

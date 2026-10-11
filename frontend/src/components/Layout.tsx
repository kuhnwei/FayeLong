import type { ReactNode } from 'react'
import { NavLink } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { getHealth } from '../api/client'
import { usePlayer } from '../store/player'
import PlayerBar from './PlayerBar'

const navClass = ({ isActive }: { isActive: boolean }) =>
  [
    'rounded-lg px-3 py-2 text-sm transition-colors',
    isActive
      ? 'bg-slate-900 text-white'
      : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900',
  ].join(' ')

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
    <div className="flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1.5">
      <span className={`h-2 w-2 rounded-full ${dot}`} />
      <span className="text-xs text-slate-600">{text}</span>
    </div>
  )
}

export default function Layout({ children }: { children: ReactNode }) {
  const hasPlayer = usePlayer((s) => s.current !== null)

  return (
    <div className="min-h-full">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-3">
          <div className="flex items-center gap-6">
            <h1 className="text-[15px] font-medium text-slate-900">
              FayeLong 英语学习
            </h1>
            <nav className="flex items-center gap-1">
              <NavLink to="/" className={navClass} end>
                媒体库
              </NavLink>
              <NavLink to="/vocab" className={navClass}>
                生词本
              </NavLink>
            </nav>
          </div>
          <BackendStatus />
        </div>
      </header>
      <main className={`mx-auto max-w-5xl px-6 py-6 ${hasPlayer ? 'pb-28' : ''}`}>
        {children}
      </main>
      <PlayerBar />
    </div>
  )
}

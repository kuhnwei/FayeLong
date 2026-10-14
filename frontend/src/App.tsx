import { useEffect } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { UNAUTHORIZED_EVENT, getAuthStatus } from './api/client'
import Layout from './components/Layout'
import LoginPage from './pages/LoginPage'
import MediaLibraryPage from './pages/MediaLibraryPage'
import StudyPage from './pages/StudyPage'
import VocabPage from './pages/VocabPage'
import VocabPracticePage from './pages/VocabPracticePage'

/** 全屏占位（检查登录态 / 连不上后端时用） */
function Splash({ text }: { text: string }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-6">
      <p className="text-center text-[13px] text-slate-400">{text}</p>
    </div>
  )
}

export default function App() {
  const queryClient = useQueryClient()

  const auth = useQuery({
    queryKey: ['auth', 'status'],
    queryFn: getAuthStatus,
    retry: false,
    staleTime: 0,
  })

  // 任意接口返回 401（会话过期、服务端换过签名密钥）都回落登录页，
  // 而不是让页面停在「什么都加载不出来」的状态。
  useEffect(() => {
    const onUnauthorized = () => {
      void queryClient.invalidateQueries({ queryKey: ['auth', 'status'] })
    }
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
  }, [queryClient])

  if (auth.isError) {
    return <Splash text={`无法连接后端服务：${(auth.error as Error).message}`} />
  }
  if (!auth.data) {
    return <Splash text="正在检查登录状态…" />
  }
  if (!auth.data.authenticated) {
    return <LoginPage status={auth.data} />
  }

  return (
    <Layout>
      <Routes>
        <Route path="/" element={<MediaLibraryPage />} />
        <Route path="/study/:mediaId" element={<StudyPage />} />
        <Route path="/vocab" element={<VocabPage />} />
        <Route path="/vocab/practice" element={<VocabPracticePage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  )
}

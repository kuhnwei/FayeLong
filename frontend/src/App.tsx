import { Navigate, Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import MediaLibraryPage from './pages/MediaLibraryPage'
import StudyPage from './pages/StudyPage'
import VocabPage from './pages/VocabPage'

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<MediaLibraryPage />} />
        <Route path="/study/:mediaId" element={<StudyPage />} />
        <Route path="/vocab" element={<VocabPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  )
}

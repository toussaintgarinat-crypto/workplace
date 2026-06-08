import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useEffect, useState } from 'react'
import AppLayout from './components/layout/AppLayout'
import Dashboard from './pages/Dashboard'
import NotePage from './pages/NotePage'
import SearchPage from './pages/SearchPage'
import PalacePage from './pages/PalacePage'
import GraphPage from './pages/GraphPage'
import GardienPage from './pages/GardienPage'
import TemplatesPage from './pages/TemplatesPage'
import CollectionsPage from './pages/CollectionsPage'
import SettingsPage from './pages/SettingsPage'
import { loadToken, getSpaces, getSpaceId } from './services/api'
import { useAppStore } from './stores/appStore'

function RequireAuth({ children }: { children: React.ReactNode }) {
  const token = localStorage.getItem('auth_token')
  if (!token) return <Navigate to="/memory/settings" replace />
  return <>{children}</>
}

export default function App() {
  const setActiveSpace = useAppStore((s) => s.setActiveSpace)
  const [initDone, setInitDone] = useState(false)

  useEffect(() => {
    loadToken()
    const token = localStorage.getItem('auth_token')
    if (token && !getSpaceId()) {
      getSpaces().then(async (spaces) => {
        if (spaces.length > 0) {
          setActiveSpace(spaces[0].id)
        } else {
          const res = await fetch('/api/v1/spaces', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
            body: JSON.stringify({ name: 'My Space', description: 'My personal memory space' }),
          })
          if (res.ok) {
            const space = await res.json()
            setActiveSpace(space.id)
          }
        }
      }).catch(() => {}).finally(() => setInitDone(true))
    } else {
      setInitDone(true)
    }
  }, [setActiveSpace])

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/memory" element={<AppLayout />}>
          <Route index element={<RequireAuth><Dashboard initDone={initDone} /></RequireAuth>} />
          <Route path="note/:id" element={<RequireAuth><NotePage /></RequireAuth>} />
          <Route path="search" element={<RequireAuth><SearchPage /></RequireAuth>} />
          <Route path="palace" element={<RequireAuth><PalacePage /></RequireAuth>} />
          <Route path="graph" element={<RequireAuth><GraphPage /></RequireAuth>} />
          <Route path="gardien" element={<RequireAuth><GardienPage /></RequireAuth>} />
          <Route path="templates" element={<RequireAuth><TemplatesPage /></RequireAuth>} />
          <Route path="collections" element={<RequireAuth><CollectionsPage /></RequireAuth>} />
          <Route path="settings" element={<SettingsPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/memory" replace />} />
      </Routes>
    </BrowserRouter>
  )
}

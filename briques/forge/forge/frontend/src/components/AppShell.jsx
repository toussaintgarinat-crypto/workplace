import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'
import { sessions as sessionsApi } from '../services/api'
import Sidebar from '../views/WorkspaceView/Sidebar'
import SettingsPanel from '../views/WorkspaceView/SettingsPanel'
import LanguagePicker from './LanguagePicker'
import styles from './AppShell.module.css'
import { DegradedBanner } from '@workspace/shared-ui/components'

const fetchDegraded = (apiUrl) => fetch(`${apiUrl}/admin/degraded`, {
  headers: { Authorization: `Bearer ${localStorage.getItem('forge_token') || ''}` },
}).then(r => (r.ok ? r.json() : null)).catch(() => null)

/**
 * Shell global — Sidebar persistante sur toutes les vues authentifiées.
 * Les enfants (WorkspaceView, CommandBridgeView) s'affichent dans la zone principale.
 */
export default function AppShell({ children }) {
  const navigate = useNavigate()
  const { user } = useAuth()
  const [sessionsList, setSessionsList] = useState([])
  const [showSettings, setShowSettings] = useState(false)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)

  useEffect(() => {
    if (!user) return
    sessionsApi.list().then(setSessionsList).catch(() => {})
  }, [user])

  // ctx : { poleId?, poleNom?, poleEmoji?, ventureId?, ventureNom?, ventureEmoji?, scope? }
  async function createSession(ctx = {}) {
    const session = await sessionsApi.create({
      poleId:    ctx.poleId    ?? undefined,
      ventureId: ctx.ventureId ?? undefined,
      scope:     ctx.scope     ?? 'user',
    })
    // Enrichir localement avec les noms passés en contexte
    const enriched = {
      ...session,
      poleName:    ctx.poleNom    ?? null,
      poleEmoji:   ctx.poleEmoji  ?? null,
      ventureName: ctx.ventureNom ?? null,
      ventureEmoji: ctx.ventureEmoji ?? null,
    }
    setSessionsList(prev => [enriched, ...prev])
    navigate(`/workspace/${session.id}`)
  }

  async function renameSession(id, name) {
    await sessionsApi.rename(id, name)
    setSessionsList(prev => prev.map(s => s.id === id ? { ...s, name } : s))
  }

  async function deleteSession(id) {
    await sessionsApi.delete(id)
    setSessionsList(prev => prev.filter(s => s.id !== id))
    navigate('/workspace')
  }

  return (
    <div className={`${styles.shell} ${sidebarCollapsed ? styles.shellCollapsed : ''}`}>
      <Sidebar
        sessions={sessionsList}
        onNew={() => createSession()}
        onNewInContext={createSession}
        onSelect={id => navigate(`/workspace/${id}`)}
        onRename={renameSession}
        onDelete={deleteSession}
        onSettings={() => setShowSettings(v => !v)}
        collapsed={sidebarCollapsed}
        onToggleCollapse={() => setSidebarCollapsed(v => !v)}
      />

      <main className={styles.main}>
        <DegradedBanner fetcher={() => fetchDegraded(import.meta.env.VITE_API_URL || '')} />
        {children}
      </main>

      {showSettings && <SettingsPanel onClose={() => setShowSettings(false)} />}

      <LanguagePicker style={{ position: 'fixed', bottom: 12, left: sidebarCollapsed ? 12 : 220, zIndex: 100 }} />
    </div>
  )
}

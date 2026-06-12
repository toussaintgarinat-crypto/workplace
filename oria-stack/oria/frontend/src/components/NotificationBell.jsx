import { useState, useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../services/api.js'
import keycloak from '../keycloak'

const BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'

export default function NotificationBell() {
  const { t, i18n } = useTranslation()
  const [count, setCount]     = useState(0)
  const [open, setOpen]       = useState(false)
  const [notifs, setNotifs]   = useState([])
  const panelRef              = useRef(null)
  const esRef                 = useRef(null)
  const fallbackRef           = useRef(null)

  useEffect(() => {
    startStream()
    return () => {
      esRef.current?.close()
      clearInterval(fallbackRef.current)
    }
  }, [])

  function startStream() {
    const token = keycloak.token
    if (!token) {
      // Pas encore authentifié — polling classique
      fetchCount()
      fallbackRef.current = setInterval(fetchCount, 30000)
      return
    }
    const url = `${BASE}/api/social/notifs/stream?token=${encodeURIComponent(token)}`
    const es = new EventSource(url)
    esRef.current = es

    es.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data)
        if (typeof data.count === 'number') setCount(data.count)
      } catch {}
    }

    es.onerror = () => {
      es.close()
      esRef.current = null
      // Fallback polling si SSE échoue
      if (!fallbackRef.current) {
        fetchCount()
        fallbackRef.current = setInterval(fetchCount, 30000)
      }
    }
  }

  useEffect(() => {
    if (!open) return
    function onOutside(e) {
      if (panelRef.current && !panelRef.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', onOutside)
    return () => document.removeEventListener('mousedown', onOutside)
  }, [open])

  async function fetchCount() {
    const data = await api.get('/social/notifs/unread-count')
    if (data) setCount(data.count)
  }

  async function openPanel() {
    const data = await api.get('/social/notifs')
    if (data) setNotifs(data)
    setOpen(v => !v)
  }

  async function markAll() {
    await api.patch('/social/notifs/read-all')
    setCount(0)
    setNotifs(prev => prev.map(n => ({ ...n, read: true })))
  }

  function labelNotif(n) {
    if (n.type === 'new_follower') {
      return t('notif.newFollower', { avatar: n.data.follower_avatar, nom: n.data.follower_nom })
    }
    if (n.type === 'new_world_public') {
      return t('notif.newWorld', { avatar: n.data.owner_avatar, nom: n.data.owner_nom, world: n.data.world_nom })
    }
    return t('notif.generic')
  }

  return (
    <div className="notif-bell-wrap" ref={panelRef}>
      <button className={`world-btn nav-btn ${open ? 'actif' : ''}`} onClick={openPanel} title={t('notif.title')}>
        <span>🔔</span>
        {count > 0 && <span className="notif-badge">{count > 9 ? '9+' : count}</span>}
        <span className="world-btn-tooltip">{t('notif.title')}</span>
      </button>

      {open && (
        <div className="notif-panel">
          <div className="notif-panel-header">
            <span>{t('notif.title')}</span>
            {count > 0 && <button className="notif-mark-all" onClick={markAll}>{t('notif.markAll')}</button>}
          </div>
          {notifs.length === 0 ? (
            <div className="notif-empty">{t('notif.empty')}</div>
          ) : (
            <ul className="notif-list">
              {notifs.map(n => (
                <li key={n.id} className={`notif-item ${n.read ? 'read' : 'unread'}`}>
                  <span className="notif-dot" />
                  <span className="notif-text">{labelNotif(n)}</span>
                  <span className="notif-time">{new Date(n.created_at).toLocaleDateString(i18n.language)}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}

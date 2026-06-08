import { useState, useEffect } from 'react'

const RECONNECTING_STATES = new Set(['ERROR', 'RECONNECTING'])

export default function SyncStatus() {
  const [status, setStatus] = useState(null) // null = pas encore de sync

  useEffect(() => {
    function onStatus(e) { setStatus(e.detail) }
    window.addEventListener('oria:matrix-status', onStatus)
    return () => window.removeEventListener('oria:matrix-status', onStatus)
  }, [])

  if (!status || !RECONNECTING_STATES.has(status)) return null

  return (
    <div className="sync-status-banner">
      <span className="sync-spinner" />
      Reconnexion au serveur de messagerie…
    </div>
  )
}

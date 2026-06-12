import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'

const RECONNECTING_STATES = new Set(['ERROR', 'RECONNECTING'])

export default function SyncStatus() {
  const { t } = useTranslation()
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
      {t('sync.reconnecting')}
    </div>
  )
}

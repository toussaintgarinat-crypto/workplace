import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../services/api.js'

export default function InviteModal({ world, onFermer }) {
  const { t } = useTranslation()
  const [token, setToken]   = useState(null)
  const [copie, setCopie]   = useState(false)
  const [loading, setLoading] = useState(false)

  useEffect(() => { generer() }, [])

  async function generer() {
    setLoading(true)
    const data = await api.post('/invitations/', { world_id: world.id })
    setToken(data.token)
    setLoading(false)
  }

  const lien = token ? `${window.location.origin}/?invite=${token}` : ''

  async function copier() {
    await navigator.clipboard.writeText(lien)
    setCopie(true)
    setTimeout(() => setCopie(false), 2000)
  }

  return (
    <div className="modal-overlay" onClick={onFermer}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <h2 className="modal-titre">{t('invite.title', { world: `${world.emoji} ${world.nom}` })}</h2>
        <p style={{ color: 'var(--text-mut)', fontSize: 13, marginBottom: 20 }}>
          {t('invite.hint')}
        </p>
        {loading ? (
          <div style={{ textAlign: 'center', padding: 20, color: 'var(--text-mut)' }}>{t('invite.generating')}</div>
        ) : (
          <div className="invite-link-box">
            <span className="invite-link-text">{lien}</span>
            <button className="btn-copier" onClick={copier}>
              {copie ? t('invite.copied') : t('invite.copy')}
            </button>
          </div>
        )}
        <div className="modal-actions">
          <button type="button" className="btn-annuler" onClick={onFermer}>{t('common.close')}</button>
          <button type="button" className="btn-creer" onClick={generer} disabled={loading}>
            {t('invite.newLink')}
          </button>
        </div>
      </div>
    </div>
  )
}

import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { api, authHeaders } from '../services/api.js'
import AppearanceSettings from './AppearanceSettings.jsx'

const AVATARS = ['👤','🧑','👩','🧔','👨‍💻','👩‍💻','🧑‍🎨','👩‍🎤','🧑‍🚀','🦊','🐺','🐸']

export default function SettingsModal({ moi, onSauvegarde, onDeconnexion, onFermer }) {
  const { t } = useTranslation()
  const [nom, setNom]         = useState(moi.nom)
  const [avatar, setAvatar]   = useState(moi.avatar_emoji)
  const [chargement, setChargement] = useState(false)
  const [totpEnabled, setTotpEnabled]   = useState(null) // null=chargement, true, false
  const [totpUri, setTotpUri]           = useState(null) // URI provisionnement
  const [totpSecret, setTotpSecret]     = useState(null)
  const [totpCode, setTotpCode]         = useState('')
  const [totpMsg, setTotpMsg]           = useState('')
  const [desactivePass, setDesactivePass] = useState('')

  useEffect(() => {
    api.get('/auth/me/2fa-status').then(d => d && setTotpEnabled(d.totp_enabled))
  }, [])

  async function setup2fa() {
    const d = await api.post('/auth/2fa/setup', {})
    if (d?.uri) { setTotpUri(d.uri); setTotpSecret(d.secret); setTotpMsg('') }
  }

  async function enable2fa() {
    const d = await api.post('/auth/2fa/enable', { code: totpCode })
    if (d?.ok) { setTotpEnabled(true); setTotpUri(null); setTotpCode(''); setTotpMsg(t('settings.twoFaEnabled')) }
    else setTotpMsg(d?.detail || t('settings.wrongCode'))
  }

  async function disable2fa() {
    if (!desactivePass) return
    const d = await api.post('/auth/2fa/disable', { password: desactivePass })
    if (d?.ok) { setTotpEnabled(false); setDesactivePass(''); setTotpMsg(t('settings.twoFaDisabled')) }
    else setTotpMsg(d?.detail || t('settings.wrongPassword'))
  }

  async function exporterDonnees() {
    const r = await fetch(`${import.meta.env.VITE_API_URL || 'http://localhost:8000'}/api/auth/me/export`, {
      credentials: 'include',
      headers: authHeaders(),
    })
    if (r.ok) {
      const data = await r.json()
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a'); a.href = url; a.download = 'mes-donnees-oria.json'; a.click()
      URL.revokeObjectURL(url)
    }
  }

  async function supprimerCompte() {
    if (!confirm(t('settings.confirmDelete'))) return
    const r = await fetch(`${import.meta.env.VITE_API_URL || 'http://localhost:8000'}/api/auth/me`, {
      method: 'DELETE',
      credentials: 'include',
      headers: authHeaders(),
    })
    if (r.ok) {
      onDeconnexion()
    }
  }

  async function sauvegarder(e) {
    e.preventDefault()
    if (!nom.trim()) return
    setChargement(true)
    const data = await api.patch('/auth/me', { nom: nom.trim(), avatar_emoji: avatar })
    setChargement(false)
    if (data?.user) {
      onSauvegarde(data.user)
    }
  }

  return (
    <div className="modal-overlay" onClick={onFermer}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h2>{t('settings.title')}</h2>
          <button className="modal-close" onClick={onFermer}>✕</button>
        </div>

        <form onSubmit={sauvegarder} className="modal-body">
          <label className="modal-label">{t('settings.avatar')}</label>
          <div className="avatar-grid">
            {AVATARS.map(a => (
              <button
                key={a} type="button"
                className={`avatar-option ${avatar === a ? 'selected' : ''}`}
                onClick={() => setAvatar(a)}
              >{a}</button>
            ))}
          </div>

          <label className="modal-label" style={{ marginTop: 16 }}>{t('settings.displayName')}</label>
          <input
            className="modal-input"
            value={nom}
            onChange={e => setNom(e.target.value)}
            maxLength={32}
            required
          />

          <div style={{ display: 'flex', gap: 8, marginTop: 20 }}>
            <button type="submit" className="btn-primary" disabled={chargement || !nom.trim()}>
              {chargement ? t('settings.saving') : t('settings.save')}
            </button>
            <button type="button" className="btn-danger" onClick={onDeconnexion}>
              {t('settings.logout')}
            </button>
          </div>

          {/* Apparence */}
          <div style={{ marginTop: 20, borderTop: '1px solid var(--line)', paddingTop: 16 }}>
            <p style={{ fontSize: 11, color: 'var(--text-mut)', margin: '0 0 10px' }}>{t('settings.appearance')}</p>
            <AppearanceSettings />
          </div>

          {/* 2FA */}
          <div style={{ marginTop: 20, borderTop: '1px solid var(--ink-700)', paddingTop: 16 }}>
            <p style={{ fontSize: 11, color: 'var(--text-mut)', margin: '0 0 10px' }}>{t('settings.twoFa')}</p>
            {totpEnabled === null && <p style={{ fontSize: 12, color: 'var(--text-mut)' }}>{t('settings.loading')}</p>}
            {totpEnabled === true && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <p style={{ fontSize: 12, color: 'var(--vert)', margin: 0 }}>{t('settings.twoFaOn')}</p>
                <input className="modal-input" type="password" placeholder={t('settings.disablePassPlaceholder')}
                  value={desactivePass} onChange={e => setDesactivePass(e.target.value)} />
                <button type="button" className="btn-danger" onClick={disable2fa} style={{ fontSize: 12 }}>
                  {t('settings.disable2fa')}
                </button>
                {totpMsg && <p style={{ fontSize: 12, color: 'var(--or-400)', margin: 0 }}>{totpMsg}</p>}
              </div>
            )}
            {totpEnabled === false && !totpUri && (
              <button type="button" className="btn-secondary" onClick={setup2fa}>
                {t('settings.enable2fa')}
              </button>
            )}
            {totpEnabled === false && totpUri && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <p style={{ fontSize: 12, color: 'var(--text)', margin: 0 }}>
                  {t('settings.scanHint')}
                </p>
                <code style={{ fontSize: 11, wordBreak: 'break-all', background: 'var(--ink-850)', padding: 8, borderRadius: 4, color: 'var(--text)' }}>
                  {totpSecret}
                </code>
                <input className="modal-input" type="text" placeholder={t('settings.sixDigit')}
                  value={totpCode} onChange={e => setTotpCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                  maxLength={6} style={{ letterSpacing: 4, textAlign: 'center' }} />
                <button type="button" className="btn-primary" onClick={enable2fa} disabled={totpCode.length < 6}>
                  {t('settings.confirmActivation')}
                </button>
                {totpMsg && <p style={{ fontSize: 12, color: 'var(--rouge)', margin: 0 }}>{totpMsg}</p>}
              </div>
            )}
          </div>

          {/* Tour de découverte */}
          <div style={{ marginTop: 20, borderTop: '1px solid var(--ink-700)', paddingTop: 16 }}>
            <p style={{ fontSize: 11, color: 'var(--text-mut)', margin: '0 0 8px' }}>{t('settings.onboarding')}</p>
            <button
              type="button"
              className="btn-secondary"
              onClick={async () => {
                await api.del('/auth/me/setup-complete')
                window.location.reload()
              }}
            >
              {t('settings.redoTour')}
            </button>
          </div>

          {/* RGPD */}
          <div style={{ marginTop: 20, borderTop: '1px solid var(--ink-700)', paddingTop: 16, display: 'flex', flexDirection: 'column', gap: 8 }}>
            <p style={{ fontSize: 11, color: 'var(--text-mut)', margin: '0 0 8px' }}>{t('settings.gdpr')}</p>
            <button type="button" className="btn-secondary" onClick={exporterDonnees}>
              {t('settings.exportData')}
            </button>
            <button type="button" className="btn-danger" onClick={supprimerCompte} style={{ fontSize: 12 }}>
              {t('settings.deleteAccount')}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

import { useState, useEffect } from 'react'
import { token } from '../../../services/api'
import styles from './Panel.module.css'

const BASE = ''
async function req(path, opts = {}) {
  const t = token.get()
  const res = await fetch(`${BASE}${path}`, {
    ...opts,
    headers: { 'Content-Type': 'application/json', ...(t ? { Authorization: `Bearer ${t}` } : {}), ...opts.headers }
  })
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || 'Erreur')
  return res.json()
}

const PLATFORMS = {
  instagram: { label: 'Instagram',   emoji: '📸', color: '#e1306c' },
  linkedin:  { label: 'LinkedIn',    emoji: '💼', color: '#0077b5' },
  facebook:  { label: 'Facebook',    emoji: '📘', color: '#1877f2' },
  twitter:   { label: 'X / Twitter', emoji: '🐦', color: '#000000' },
  tiktok:    { label: 'TikTok',      emoji: '🎵', color: '#ff0050' },
  youtube:   { label: 'YouTube',     emoji: '▶️', color: '#ff0000' },
  bluesky:   { label: 'Bluesky',     emoji: '🦋', color: '#0085ff' },
  pinterest: { label: 'Pinterest',   emoji: '📌', color: '#e60023' },
  threads:   { label: 'Threads',     emoji: '🧵', color: '#1c1c1e' },
  mastodon:  { label: 'Mastodon',    emoji: '🐘', color: '#6364ff' },
}

export default function SocialPanel({ poleId }) {
  const [accounts, setAccounts] = useState([])
  const [form, setForm]         = useState({ platform: 'instagram', nom: '' })
  const [showForm, setShow]     = useState(false)
  const [loading, setLoading]   = useState(false)

  useEffect(() => {
    req(`/api/poles/${poleId}/social`).then(setAccounts).catch(() => {})
  }, [poleId])

  async function submit(e) {
    e.preventDefault()
    setLoading(true)
    try {
      const a = await req(`/api/poles/${poleId}/social`, { method: 'POST', body: JSON.stringify(form) })
      setAccounts(prev => [a, ...prev])
      setForm({ platform: 'instagram', nom: '' })
      setShow(false)
    } finally { setLoading(false) }
  }

  async function toggle(id, actif) {
    const updated = await req(`/api/social/${id}`, { method: 'PATCH', body: JSON.stringify({ actif: !actif }) })
    setAccounts(prev => prev.map(a => a.id === id ? updated : a))
  }

  async function remove(id) {
    await req(`/api/social/${id}`, { method: 'DELETE' })
    setAccounts(prev => prev.filter(a => a.id !== id))
  }

  return (
    <div className={styles.panel}>
      <div className={styles.toolbar}>
        <button className={styles.btnPrimary} onClick={() => setShow(v => !v)}>+ Compte social</button>
      </div>

      {showForm && (
        <form className={styles.form} onSubmit={submit}>
          <select className={styles.select} value={form.platform} onChange={e => setForm(f => ({ ...f, platform: e.target.value }))}>
            {Object.entries(PLATFORMS).map(([k, v]) => (
              <option key={k} value={k}>{v.emoji} {v.label}</option>
            ))}
          </select>
          <input className={styles.input} placeholder="Nom du compte (ex: @monentreprise)" required
            value={form.nom} onChange={e => setForm(f => ({ ...f, nom: e.target.value }))} />
          <div className={styles.formActions}>
            <button type="submit" className={styles.btnPrimary} disabled={loading}>Ajouter</button>
            <button type="button" className={styles.btnGhost} onClick={() => setShow(false)}>Annuler</button>
          </div>
        </form>
      )}

      {accounts.length === 0 && !showForm && <p className={styles.empty}>Aucun compte social configuré.</p>}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 12 }}>
        {accounts.map(acc => {
          const meta = PLATFORMS[acc.platform] ?? { label: acc.platform, emoji: '🌐', color: '#64748b' }
          return (
            <div key={acc.id} className={styles.card} style={{ borderLeft: `3px solid ${meta.color}`, opacity: acc.actif ? 1 : 0.5 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                <span style={{ fontSize: 22 }}>{meta.emoji}</span>
                <div style={{ display: 'flex', gap: 4 }}>
                  <button className={styles.micro} onClick={() => toggle(acc.id, acc.actif)}>{acc.actif ? '⏸' : '▶'}</button>
                  <button className={styles.micro} style={{ color: '#ef4444' }} onClick={() => remove(acc.id)}>✕</button>
                </div>
              </div>
              <div className={styles.rowTitle}>{acc.nom}</div>
              <div className={styles.rowSub} style={{ color: meta.color }}>{meta.label}</div>
              <div className={styles.rowSub}>{acc.actif ? '✅ Actif' : '⏸ Pausé'}</div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

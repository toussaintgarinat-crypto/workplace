import { useState, useEffect } from 'react'
import { token } from '../../../services/api'
import styles from './Panel.module.css'

async function req(path, opts = {}) {
  const t = token.get()
  const res = await fetch(path, {
    ...opts,
    headers: { 'Content-Type': 'application/json', ...(t ? { Authorization: `Bearer ${t}` } : {}), ...opts.headers },
  })
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || 'Erreur')
  return res.json()
}

const STATUS_COLORS = { libre: '#10b981', occupe: '#f59e0b' }
const STATUS_LABELS = { libre: 'Libre', occupe: 'Occupé' }

export default function ServersPanel() {
  const [servers, setServers]   = useState([])
  const [showForm, setShowForm] = useState(false)
  const [loading, setLoading]   = useState(false)
  const [err, setErr]           = useState('')
  const [form, setForm]         = useState({ label: '', ip: '', sshKey: '', sshUser: 'root', region: '' })

  useEffect(() => {
    req('/api/servers').then(setServers).catch(() => {})
  }, [])

  async function addServer(e) {
    e.preventDefault()
    setLoading(true)
    setErr('')
    try {
      const srv = await req('/api/servers', { method: 'POST', body: JSON.stringify(form) })
      setServers(prev => [...prev, srv])
      setForm({ label: '', ip: '', sshKey: '', sshUser: 'root', region: '' })
      setShowForm(false)
    } catch (e) {
      setErr(e.message)
    } finally {
      setLoading(false)
    }
  }

  async function deleteServer(id) {
    try {
      await req(`/api/servers/${id}`, { method: 'DELETE' })
      setServers(prev => prev.filter(s => s.id !== id))
    } catch (e) {
      setErr(e.message)
    }
  }

  return (
    <div className={styles.panel}>
      <div className={styles.toolbar}>
        <h3 style={{ margin: 0, fontSize: 14, fontWeight: 600, color: '#e5e7eb' }}>
          Parc de serveurs ({servers.length})
        </h3>
        <button className={styles.btnPrimary} onClick={() => setShowForm(s => !s)}>
          {showForm ? 'Annuler' : '+ Ajouter'}
        </button>
      </div>

      {showForm && (
        <form className={styles.form} onSubmit={addServer}>
          <input className={styles.input} placeholder="Label (ex: VPS France 1) *" required
            value={form.label} onChange={e => setForm(f => ({ ...f, label: e.target.value }))} />
          <input className={styles.input} placeholder="Adresse IP *" required
            value={form.ip} onChange={e => setForm(f => ({ ...f, ip: e.target.value }))} />
          <input className={styles.input} placeholder="Utilisateur SSH (défaut: root)"
            value={form.sshUser} onChange={e => setForm(f => ({ ...f, sshUser: e.target.value }))} />
          <input className={styles.input} placeholder="Région / datacenter (optionnel)"
            value={form.region} onChange={e => setForm(f => ({ ...f, region: e.target.value }))} />
          <textarea className={styles.textarea} placeholder="Clé SSH privée (-----BEGIN...) *" required
            value={form.sshKey} onChange={e => setForm(f => ({ ...f, sshKey: e.target.value }))}
            style={{ fontFamily: 'monospace', fontSize: 11, minHeight: 100 }} />
          {err && <p style={{ color: '#ef4444', fontSize: 12 }}>{err}</p>}
          <div className={styles.formActions}>
            <button type="submit" className={styles.btnPrimary} disabled={loading}>
              {loading ? 'Ajout…' : 'Ajouter le serveur'}
            </button>
          </div>
        </form>
      )}

      {err && !showForm && <p style={{ color: '#ef4444', fontSize: 12, padding: '0 0 8px' }}>{err}</p>}

      {servers.length === 0 && !showForm && (
        <p className={styles.empty}>
          Aucun serveur dans votre parc.<br />
          Ajoutez des serveurs pour déployer des instances Forge chez vos clients en un clic.
        </p>
      )}

      {servers.map(s => (
        <div key={s.id} style={{
          background: '#1f2937', borderRadius: 8, padding: '10px 14px', marginBottom: 8,
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          borderLeft: `3px solid ${STATUS_COLORS[s.status] || '#6b7280'}`,
        }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 13, fontWeight: 600, color: '#e5e7eb' }}>🖥️ {s.label}</span>
              <span style={{
                fontSize: 10, fontWeight: 700, padding: '2px 6px', borderRadius: 4,
                background: (STATUS_COLORS[s.status] || '#6b7280') + '22',
                color: STATUS_COLORS[s.status] || '#6b7280',
              }}>{STATUS_LABELS[s.status] || s.status}</span>
            </div>
            <div style={{ fontSize: 11, color: '#6b7280', marginTop: 3 }}>
              {s.sshUser}@{s.ip}{s.region ? ` · ${s.region}` : ''}
            </div>
          </div>
          <button
            className={styles.micro}
            style={{ color: s.status === 'occupe' ? '#4b5563' : '#ef4444' }}
            title={s.status === 'occupe' ? 'Serveur occupé — libérez l\'instance d\'abord' : 'Supprimer'}
            disabled={s.status === 'occupe'}
            onClick={() => deleteServer(s.id)}
          >✕</button>
        </div>
      ))}

      <p style={{ fontSize: 11, color: '#4b5563', marginTop: 12 }}>
        Les clés SSH sont chiffrées AES-256 en base de données.
      </p>
    </div>
  )
}

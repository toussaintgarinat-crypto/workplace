import { useState, useEffect } from 'react'
import { api } from '../../services/api'
import styles from './Team.module.css'

const ROLES = ['founder', 'admin', 'agent', 'viewer']
const ROLE_COLORS = { founder: '#f59e0b', admin: '#818cf8', agent: '#10b981', viewer: '#6b6b80' }
const ROLE_ICONS = { founder: '👑', admin: '🔑', agent: '🤖', viewer: '👁️' }

export default function TeamView() {
  const [members, setMembers] = useState([])
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState({ nom: '', email: '', role: 'viewer' })
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    api.get('/api/team').then(r => setMembers(Array.isArray(r) ? r : [])).catch(() => {})
  }, [])

  async function submit(e) {
    e.preventDefault()
    setSaving(true)
    try {
      const m = await api.post('/api/team', form)
      setMembers(ms => [...ms, m])
      setForm({ nom: '', email: '', role: 'viewer' })
      setShowForm(false)
    } finally { setSaving(false) }
  }

  async function updateRole(id, role) {
    await api.patch(`/api/team/${id}`, { role })
    setMembers(ms => ms.map(m => m.id === id ? { ...m, role } : m))
  }

  async function remove(id) {
    await api.delete(`/api/team/${id}`)
    setMembers(ms => ms.filter(m => m.id !== id))
  }

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <h1 className={styles.title}>👥 Équipe</h1>
        <button className={styles.btnPrimary} onClick={() => setShowForm(v => !v)}>+ Membre</button>
      </div>

      {showForm && (
        <form className={styles.form} onSubmit={submit}>
          <input className={styles.input} placeholder="Nom *" required value={form.nom}
            onChange={e => setForm(f => ({ ...f, nom: e.target.value }))} />
          <input className={styles.input} type="email" placeholder="Email" value={form.email}
            onChange={e => setForm(f => ({ ...f, email: e.target.value }))} />
          <select className={styles.select} value={form.role} onChange={e => setForm(f => ({ ...f, role: e.target.value }))}>
            {ROLES.map(r => <option key={r} value={r}>{ROLE_ICONS[r]} {r}</option>)}
          </select>
          <div className={styles.formActions}>
            <button type="submit" className={styles.btnPrimary} disabled={saving}>{saving ? '...' : 'Inviter'}</button>
            <button type="button" className={styles.btnGhost} onClick={() => setShowForm(false)}>Annuler</button>
          </div>
        </form>
      )}

      <div className={styles.list}>
        {members.length === 0 && <p className={styles.empty}>Aucun membre d'équipe.</p>}
        {members.map(m => (
          <div key={m.id} className={styles.memberCard}>
            <div className={styles.memberAvatar} style={{ background: ROLE_COLORS[m.role] + '22', color: ROLE_COLORS[m.role] }}>
              {ROLE_ICONS[m.role]}
            </div>
            <div className={styles.memberInfo}>
              <div className={styles.memberName}>{m.nom}</div>
              {m.email && <div className={styles.memberEmail}>{m.email}</div>}
              <div className={styles.memberMeta}>
                <span className={styles.statutBadge} style={{ background: m.statut === 'actif' ? '#10b98122' : '#6b6b8022', color: m.statut === 'actif' ? '#10b981' : '#6b6b80' }}>
                  {m.statut}
                </span>
              </div>
            </div>
            <div className={styles.memberRight}>
              <select className={styles.select} value={m.role} onChange={e => updateRole(m.id, e.target.value)}>
                {ROLES.map(r => <option key={r} value={r}>{ROLE_ICONS[r]} {r}</option>)}
              </select>
              <button className={styles.deleteBtn} onClick={() => remove(m.id)}>✕</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

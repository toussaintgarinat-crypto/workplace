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

const SEV_COLORS  = { critique: '#ef4444', haute: '#f97316', moyenne: '#f59e0b', basse: '#6b7280' }
const SEV_LABELS  = { critique: '🔴 Critique', haute: '🟠 Haute', moyenne: '🟡 Moyenne', basse: '⚪ Basse' }
const STAT_COLORS = { ouvert: '#ef4444', en_cours: '#f59e0b', resolu: '#10b981', ferme: '#6b7280' }
const STAT_LABELS = { ouvert: 'Ouvert', en_cours: 'En cours', resolu: 'Résolu', ferme: 'Fermé' }

export default function IncidentsPanel({ poleId }) {
  const [incidents, setIncidents] = useState([])
  const [form, setForm]           = useState({ titre: '', description: '', severite: 'moyenne' })
  const [showForm, setShow]       = useState(false)
  const [loading, setLoading]     = useState(false)
  const [filter, setFilter]       = useState('')

  useEffect(() => {
    req(`/api/poles/${poleId}/incidents`).then(setIncidents).catch(() => {})
  }, [poleId])

  async function submit(e) {
    e.preventDefault()
    setLoading(true)
    try {
      const i = await req(`/api/poles/${poleId}/incidents`, { method: 'POST', body: JSON.stringify(form) })
      setIncidents(prev => [i, ...prev])
      setForm({ titre: '', description: '', severite: 'moyenne' })
      setShow(false)
    } finally { setLoading(false) }
  }

  async function update(id, updates) {
    const i = await req(`/api/incidents/${id}`, { method: 'PATCH', body: JSON.stringify(updates) })
    setIncidents(prev => prev.map(x => x.id === id ? i : x))
  }

  async function remove(id) {
    await req(`/api/incidents/${id}`, { method: 'DELETE' })
    setIncidents(prev => prev.filter(x => x.id !== id))
  }

  const filtered = filter ? incidents.filter(i => i.statut === filter) : incidents
  const openCount = incidents.filter(i => i.statut === 'ouvert').length
  const critCount = incidents.filter(i => i.severite === 'critique' && i.statut !== 'ferme').length

  return (
    <div className={styles.panel}>
      <div className={styles.stats}>
        <div className={styles.stat}>
          <div className={styles.statLabel}>Ouverts</div>
          <div className={styles.statValue} style={{ color: openCount > 0 ? '#ef4444' : '#10b981' }}>{openCount}</div>
        </div>
        <div className={styles.stat}>
          <div className={styles.statLabel}>Critiques actifs</div>
          <div className={styles.statValue} style={{ color: critCount > 0 ? '#ef4444' : '#10b981' }}>{critCount}</div>
        </div>
        <div className={styles.stat}>
          <div className={styles.statLabel}>Total</div>
          <div className={styles.statValue}>{incidents.length}</div>
        </div>
      </div>

      <div className={styles.toolbar}>
        <div className={styles.filterGroup}>
          {['', 'ouvert', 'en_cours', 'resolu', 'ferme'].map(s => (
            <button key={s} className={`${styles.filterBtn} ${filter === s ? styles.active : ''}`} onClick={() => setFilter(s)}>
              {s ? STAT_LABELS[s] : 'Tous'}
            </button>
          ))}
        </div>
        <button className={styles.btnPrimary} onClick={() => setShow(true)}>+ Incident</button>
      </div>

      {showForm && (
        <form className={styles.form} onSubmit={submit}>
          <input className={styles.input} placeholder="Titre *" required value={form.titre} onChange={e => setForm(f => ({ ...f, titre: e.target.value }))} />
          <textarea className={styles.textarea} placeholder="Description" value={form.description} onChange={e => setForm(f => ({ ...f, description: e.target.value }))} />
          <select className={styles.select} value={form.severite} onChange={e => setForm(f => ({ ...f, severite: e.target.value }))}>
            <option value="critique">🔴 Critique</option>
            <option value="haute">🟠 Haute</option>
            <option value="moyenne">🟡 Moyenne</option>
            <option value="basse">⚪ Basse</option>
          </select>
          <div className={styles.formActions}>
            <button type="submit" className={styles.btnPrimary} disabled={loading}>Déclarer</button>
            <button type="button" className={styles.btnGhost} onClick={() => setShow(false)}>Annuler</button>
          </div>
        </form>
      )}

      <div className={styles.list}>
        {filtered.length === 0 && <p className={styles.empty}>Aucun incident.</p>}
        {filtered.map(i => (
          <div key={i.id} className={styles.leadCard} style={{ borderLeft: `3px solid ${SEV_COLORS[i.severite]}` }}>
            <div className={styles.leadHeader}>
              <div>
                <div className={styles.rowTitle}>{i.titre}</div>
                {i.description && <div className={styles.rowSub}>{i.description}</div>}
                <div className={styles.rowSub}>{SEV_LABELS[i.severite]} · {new Date(i.createdAt).toLocaleString('fr-FR')}</div>
              </div>
              <span className={styles.statutBadge} style={{ background: STAT_COLORS[i.statut] + '22', color: STAT_COLORS[i.statut] }}>
                {STAT_LABELS[i.statut]}
              </span>
            </div>
            <div className={styles.cardActions}>
              {i.statut === 'ouvert'   && <button className={styles.micro} onClick={() => update(i.id, { statut: 'en_cours' })}>→ En cours</button>}
              {i.statut === 'en_cours' && <button className={styles.micro} onClick={() => update(i.id, { statut: 'resolu' })}>✓ Résoudre</button>}
              {i.statut === 'resolu'   && <button className={styles.micro} onClick={() => update(i.id, { statut: 'ferme' })}>Fermer</button>}
              <button className={styles.micro} style={{ color: '#ef4444' }} onClick={() => remove(i.id)}>✕</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

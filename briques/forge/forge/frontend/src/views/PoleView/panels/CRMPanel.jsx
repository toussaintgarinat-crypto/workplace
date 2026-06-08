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

const STATUTS = ['prospect', 'qualifie', 'gagne', 'perdu']
const STATUT_COLORS = { prospect: '#6366f1', qualifie: '#f59e0b', gagne: '#10b981', perdu: '#6b7280' }
const STATUT_LABELS = { prospect: 'Prospect', qualifie: 'Qualifié', gagne: 'Gagné', perdu: 'Perdu' }

export default function CRMPanel({ poleId }) {
  const [leads, setLeads]     = useState([])
  const [filter, setFilter]   = useState('')
  const [form, setForm]       = useState({ nom: '', email: '', entreprise: '', valeur: '', statut: 'prospect', notes: '' })
  const [editId, setEditId]   = useState(null)
  const [showForm, setShow]   = useState(false)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    const url = filter ? `/api/poles/${poleId}/crm?statut=${filter}` : `/api/poles/${poleId}/crm`
    req(url).then(setLeads).catch(() => {})
  }, [poleId, filter])

  async function submit(e) {
    e.preventDefault()
    setLoading(true)
    try {
      const body = { ...form, valeur: form.valeur ? parseInt(form.valeur) : 0 }
      if (editId) {
        const updated = await req(`/api/crm/${editId}`, { method: 'PATCH', body: JSON.stringify(body) })
        setLeads(prev => prev.map(l => l.id === editId ? updated : l))
      } else {
        const lead = await req(`/api/poles/${poleId}/crm`, { method: 'POST', body: JSON.stringify(body) })
        setLeads(prev => [lead, ...prev])
      }
      setForm({ nom: '', email: '', entreprise: '', valeur: '', statut: 'prospect', notes: '' })
      setEditId(null)
      setShow(false)
    } finally { setLoading(false) }
  }

  async function changeStatut(id, statut) {
    const updated = await req(`/api/crm/${id}`, { method: 'PATCH', body: JSON.stringify({ statut }) })
    setLeads(prev => prev.map(l => l.id === id ? updated : l))
  }

  async function remove(id) {
    await req(`/api/crm/${id}`, { method: 'DELETE' })
    setLeads(prev => prev.filter(l => l.id !== id))
  }

  function edit(lead) {
    setForm({ nom: lead.nom, email: lead.email, entreprise: lead.entreprise, valeur: lead.valeur, statut: lead.statut, notes: lead.notes })
    setEditId(lead.id)
    setShow(true)
  }

  return (
    <div className={styles.panel}>
      <div className={styles.toolbar}>
        <div className={styles.filterGroup}>
          <button className={`${styles.filterBtn} ${filter === '' ? styles.active : ''}`} onClick={() => setFilter('')}>Tous</button>
          {STATUTS.map(s => (
            <button key={s} className={`${styles.filterBtn} ${filter === s ? styles.active : ''}`}
              onClick={() => setFilter(s)} style={filter === s ? { borderColor: STATUT_COLORS[s], color: STATUT_COLORS[s] } : {}}>
              {STATUT_LABELS[s]}
            </button>
          ))}
        </div>
        <button className={styles.btnPrimary} onClick={() => { setEditId(null); setForm({ nom: '', email: '', entreprise: '', valeur: '', statut: 'prospect', notes: '' }); setShow(true) }}>
          + Lead
        </button>
      </div>

      {showForm && (
        <form className={styles.form} onSubmit={submit}>
          <input className={styles.input} placeholder="Nom *" required value={form.nom}
            onChange={e => setForm(f => ({ ...f, nom: e.target.value }))} />
          <input className={styles.input} type="email" placeholder="Email" value={form.email}
            onChange={e => setForm(f => ({ ...f, email: e.target.value }))} />
          <input className={styles.input} placeholder="Entreprise" value={form.entreprise}
            onChange={e => setForm(f => ({ ...f, entreprise: e.target.value }))} />
          <input className={styles.input} type="number" placeholder="Valeur (€)" value={form.valeur}
            onChange={e => setForm(f => ({ ...f, valeur: e.target.value }))} />
          <select className={styles.select} value={form.statut} onChange={e => setForm(f => ({ ...f, statut: e.target.value }))}>
            {STATUTS.map(s => <option key={s} value={s}>{STATUT_LABELS[s]}</option>)}
          </select>
          <textarea className={styles.textarea} placeholder="Notes" value={form.notes}
            onChange={e => setForm(f => ({ ...f, notes: e.target.value }))} />
          <div className={styles.formActions}>
            <button type="submit" className={styles.btnPrimary} disabled={loading}>{editId ? 'Modifier' : 'Ajouter'}</button>
            <button type="button" className={styles.btnGhost} onClick={() => setShow(false)}>Annuler</button>
          </div>
        </form>
      )}

      <div className={styles.list}>
        {leads.length === 0 && <p className={styles.empty}>Aucun lead.</p>}
        {leads.map(lead => (
          <div key={lead.id} className={styles.leadCard}>
            <div className={styles.leadHeader}>
              <div>
                <div className={styles.rowTitle}>{lead.nom}</div>
                {lead.entreprise && <div className={styles.rowSub}>{lead.entreprise}</div>}
                {lead.email && <div className={styles.rowSub}>{lead.email}</div>}
              </div>
              <div className={styles.leadRight}>
                {lead.valeur > 0 && <span className={styles.valeur}>{lead.valeur.toLocaleString()} €</span>}
                <span className={styles.statutBadge} style={{ background: STATUT_COLORS[lead.statut] + '22', color: STATUT_COLORS[lead.statut] }}>
                  {STATUT_LABELS[lead.statut]}
                </span>
              </div>
            </div>
            {lead.notes && <div className={styles.notes}>{lead.notes}</div>}
            <div className={styles.cardActions}>
              {STATUTS.filter(s => s !== lead.statut).map(s => (
                <button key={s} className={styles.micro} onClick={() => changeStatut(lead.id, s)}>→ {STATUT_LABELS[s]}</button>
              ))}
              <button className={styles.micro} onClick={() => edit(lead)}>✎</button>
              <button className={styles.micro} style={{ color: '#ef4444' }} onClick={() => remove(lead.id)}>✕</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

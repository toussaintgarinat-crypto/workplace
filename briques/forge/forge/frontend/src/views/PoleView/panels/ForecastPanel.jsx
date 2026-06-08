import { useState, useEffect } from 'react'
import { api } from '../../../services/api'
import styles from './Panel.module.css'

export default function ForecastPanel({ poleId }) {
  const [entries, setEntries] = useState([])
  const [form, setForm] = useState({ anneeMois: new Date().toISOString().slice(0, 7), montant: '', type: 'recette', categorie: '' })
  const [showForm, setShowForm] = useState(false)
  const [saving, setSaving] = useState(false)

  useEffect(() => { load() }, [poleId])

  async function load() {
    const data = await api.get(`/api/poles/${poleId}/forecast`).catch(() => [])
    setEntries(Array.isArray(data) ? data : [])
  }

  async function submit(e) {
    e.preventDefault()
    setSaving(true)
    try {
      await api.post(`/api/poles/${poleId}/forecast`, { ...form, montant: parseFloat(form.montant) })
      await load()
      setForm({ anneeMois: new Date().toISOString().slice(0, 7), montant: '', type: 'recette', categorie: '' })
      setShowForm(false)
    } finally { setSaving(false) }
  }

  async function remove(id) {
    await api.delete(`/api/forecast/${id}`)
    setEntries(es => es.filter(e => e.id !== id))
  }

  const grouped = entries.reduce((acc, e) => {
    if (!acc[e.anneeMois]) acc[e.anneeMois] = { recettes: 0, depenses: 0, items: [] }
    if (e.type === 'recette') acc[e.anneeMois].recettes += e.montant
    else acc[e.anneeMois].depenses += e.montant
    acc[e.anneeMois].items.push(e)
    return acc
  }, {})

  return (
    <div className={styles.panel}>
      <div className={styles.toolbar}>
        <button className={styles.btnPrimary} onClick={() => setShowForm(v => !v)}>+ Prévision</button>
      </div>

      {showForm && (
        <form className={styles.form} onSubmit={submit}>
          <input className={styles.input} type="month" required value={form.anneeMois}
            onChange={e => setForm(f => ({ ...f, anneeMois: e.target.value }))} />
          <input className={styles.input} type="number" placeholder="Montant (€)" required value={form.montant}
            onChange={e => setForm(f => ({ ...f, montant: e.target.value }))} />
          <select className={styles.select} value={form.type} onChange={e => setForm(f => ({ ...f, type: e.target.value }))}>
            <option value="recette">💚 Recette prévue</option>
            <option value="depense">🔴 Dépense prévue</option>
          </select>
          <input className={styles.input} placeholder="Catégorie" value={form.categorie}
            onChange={e => setForm(f => ({ ...f, categorie: e.target.value }))} />
          <div className={styles.formActions}>
            <button type="submit" className={styles.btnPrimary} disabled={saving}>Ajouter</button>
            <button type="button" className={styles.btnGhost} onClick={() => setShowForm(false)}>Annuler</button>
          </div>
        </form>
      )}

      {Object.keys(grouped).length === 0 && <p className={styles.empty}>Aucune prévision.</p>}

      {Object.entries(grouped).sort((a, b) => a[0].localeCompare(b[0])).map(([mois, data]) => (
        <div key={mois} className={styles.form}>
          <div className={styles.stats} style={{ marginBottom: 0 }}>
            <div className={styles.stat}>
              <div className={styles.statLabel}>{mois}</div>
            </div>
            <div className={styles.stat}>
              <div className={styles.statLabel}>Recettes prévues</div>
              <div className={styles.statValue} style={{ color: '#10b981', fontSize: 16 }}>+{data.recettes.toLocaleString()} €</div>
            </div>
            <div className={styles.stat}>
              <div className={styles.statLabel}>Dépenses prévues</div>
              <div className={styles.statValue} style={{ color: '#ef4444', fontSize: 16 }}>-{data.depenses.toLocaleString()} €</div>
            </div>
          </div>
          {data.items.map(e => (
            <div key={e.id} className={styles.row} style={{ marginTop: 4 }}>
              <div>
                <div className={styles.rowTitle}>{e.categorie || (e.type === 'recette' ? 'Recette' : 'Dépense')}</div>
              </div>
              <div className={styles.rowRight}>
                <span style={{ color: e.type === 'recette' ? '#10b981' : '#ef4444', fontWeight: 600 }}>
                  {e.type === 'recette' ? '+' : '-'}{e.montant.toLocaleString()} €
                </span>
                <button className={styles.micro} style={{ color: '#ef4444' }} onClick={() => remove(e.id)}>✕</button>
              </div>
            </div>
          ))}
        </div>
      ))}
    </div>
  )
}

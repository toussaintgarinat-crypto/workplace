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

export default function BudgetPanel({ poleId }) {
  const [data, setData]   = useState({ entries: [], total: 0, recettes: 0, depenses: 0 })
  const [form, setForm]   = useState({ label: '', montant: '', type: 'recette', categorie: '' })
  const [showForm, setShow] = useState(false)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    req(`/api/poles/${poleId}/budget`).then(setData).catch(() => {})
  }, [poleId])

  async function submit(e) {
    e.preventDefault()
    setLoading(true)
    try {
      await req(`/api/poles/${poleId}/budget`, {
        method: 'POST',
        body: JSON.stringify({ ...form, montant: parseInt(form.montant) })
      })
      const updated = await req(`/api/poles/${poleId}/budget`)
      setData(updated)
      setForm({ label: '', montant: '', type: 'recette', categorie: '' })
      setShow(false)
    } finally { setLoading(false) }
  }

  async function remove(id) {
    await req(`/api/budget/${id}`, { method: 'DELETE' })
    const updated = await req(`/api/poles/${poleId}/budget`)
    setData(updated)
  }

  return (
    <div className={styles.panel}>
      {/* Résumé */}
      <div className={styles.stats}>
        <div className={styles.stat}>
          <div className={styles.statLabel}>Solde</div>
          <div className={styles.statValue} style={{ color: data.total >= 0 ? '#10b981' : '#ef4444' }}>
            {data.total >= 0 ? '+' : ''}{data.total.toLocaleString()} €
          </div>
        </div>
        <div className={styles.stat}>
          <div className={styles.statLabel}>Recettes</div>
          <div className={styles.statValue} style={{ color: '#10b981' }}>+{data.recettes.toLocaleString()} €</div>
        </div>
        <div className={styles.stat}>
          <div className={styles.statLabel}>Dépenses</div>
          <div className={styles.statValue} style={{ color: '#ef4444' }}>-{data.depenses.toLocaleString()} €</div>
        </div>
      </div>

      <div className={styles.toolbar}>
        <button className={styles.btnPrimary} onClick={() => setShow(v => !v)}>+ Entrée</button>
      </div>

      {showForm && (
        <form className={styles.form} onSubmit={submit}>
          <input className={styles.input} placeholder="Libellé" required value={form.label}
            onChange={e => setForm(f => ({ ...f, label: e.target.value }))} />
          <input className={styles.input} type="number" placeholder="Montant (€)" required min="1" value={form.montant}
            onChange={e => setForm(f => ({ ...f, montant: e.target.value }))} />
          <select className={styles.select} value={form.type} onChange={e => setForm(f => ({ ...f, type: e.target.value }))}>
            <option value="recette">💚 Recette</option>
            <option value="depense">🔴 Dépense</option>
          </select>
          <input className={styles.input} placeholder="Catégorie (optionnel)" value={form.categorie}
            onChange={e => setForm(f => ({ ...f, categorie: e.target.value }))} />
          <div className={styles.formActions}>
            <button type="submit" className={styles.btnPrimary} disabled={loading}>Ajouter</button>
            <button type="button" className={styles.btnGhost} onClick={() => setShow(false)}>Annuler</button>
          </div>
        </form>
      )}

      <div className={styles.list}>
        {data.entries.length === 0 && <p className={styles.empty}>Aucune entrée.</p>}
        {data.entries.map(e => (
          <div key={e.id} className={styles.row}>
            <div>
              <div className={styles.rowTitle}>{e.label}</div>
              {e.categorie && <div className={styles.rowSub}>{e.categorie}</div>}
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
    </div>
  )
}

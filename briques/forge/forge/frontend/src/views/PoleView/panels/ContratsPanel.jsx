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

const STATUT_COLORS = { brouillon: '#6b7280', actif: '#6366f1', signe: '#10b981', expire: '#f59e0b', resilie: '#ef4444' }
const STATUT_LABELS = { brouillon: 'Brouillon', actif: 'Actif', signe: 'Signé', expire: 'Expiré', resilie: 'Résilié' }

export default function ContratsPanel({ poleId }) {
  const [contrats, setContrats] = useState([])
  const [selected, setSelected] = useState(null)
  const [form, setForm]         = useState({ titre: '', type: 'Autre', parties: '', valeur: '', dateDebut: '', dateFin: '', notes: '', contenu: '' })
  const [showForm, setShow]     = useState(false)
  const [showSign, setShowSign] = useState(false)
  const [signePar, setSignePar] = useState('')
  const [loading, setLoading]   = useState(false)

  useEffect(() => {
    req(`/api/poles/${poleId}/contrats`).then(setContrats).catch(() => {})
  }, [poleId])

  async function submit(e) {
    e.preventDefault()
    setLoading(true)
    try {
      const c = await req(`/api/poles/${poleId}/contrats`, {
        method: 'POST',
        body: JSON.stringify({ ...form, valeur: form.valeur ? parseInt(form.valeur) : 0 })
      })
      setContrats(prev => [c, ...prev])
      setForm({ titre: '', type: 'Autre', parties: '', valeur: '', dateDebut: '', dateFin: '', notes: '', contenu: '' })
      setShow(false)
    } finally { setLoading(false) }
  }

  async function updateStatut(id, statut) {
    const updated = await req(`/api/contrats/${id}`, { method: 'PATCH', body: JSON.stringify({ statut }) })
    setContrats(prev => prev.map(c => c.id === id ? updated : c))
    if (selected?.id === id) setSelected(updated)
  }

  async function signer(id) {
    if (!signePar.trim()) return
    const updated = await req(`/api/contrats/${id}/signer`, { method: 'POST', body: JSON.stringify({ signePar }) })
    setContrats(prev => prev.map(c => c.id === id ? updated : c))
    setSelected(updated)
    setShowSign(false)
    setSignePar('')
  }

  async function remove(id) {
    await req(`/api/contrats/${id}`, { method: 'DELETE' })
    setContrats(prev => prev.filter(c => c.id !== id))
    if (selected?.id === id) setSelected(null)
  }

  return (
    <div className={styles.panel}>
      <div className={styles.toolbar}>
        <button className={styles.btnPrimary} onClick={() => setShow(true)}>+ Contrat</button>
      </div>

      {showForm && (
        <form className={styles.form} onSubmit={submit}>
          <input className={styles.input} placeholder="Titre *" required value={form.titre} onChange={e => setForm(f => ({ ...f, titre: e.target.value }))} />
          <select className={styles.select} value={form.type} onChange={e => setForm(f => ({ ...f, type: e.target.value }))}>
            {['CDI', 'CDD', 'Freelance', 'Prestation', 'Partenariat', 'SaaS', 'NDA', 'Autre'].map(t => <option key={t} value={t}>{t}</option>)}
          </select>
          <input className={styles.input} placeholder="Parties (ex: Société A / Société B)" value={form.parties} onChange={e => setForm(f => ({ ...f, parties: e.target.value }))} />
          <input className={styles.input} type="number" placeholder="Valeur (€)" value={form.valeur} onChange={e => setForm(f => ({ ...f, valeur: e.target.value }))} />
          <div style={{ display: 'flex', gap: 8 }}>
            <input className={styles.input} type="date" placeholder="Début" value={form.dateDebut} onChange={e => setForm(f => ({ ...f, dateDebut: e.target.value }))} />
            <input className={styles.input} type="date" placeholder="Fin" value={form.dateFin} onChange={e => setForm(f => ({ ...f, dateFin: e.target.value }))} />
          </div>
          <textarea className={styles.textarea} placeholder="Contenu du contrat" value={form.contenu} onChange={e => setForm(f => ({ ...f, contenu: e.target.value }))} />
          <textarea className={styles.textarea} placeholder="Notes" value={form.notes} onChange={e => setForm(f => ({ ...f, notes: e.target.value }))} />
          <div className={styles.formActions}>
            <button type="submit" className={styles.btnPrimary} disabled={loading}>Créer</button>
            <button type="button" className={styles.btnGhost} onClick={() => setShow(false)}>Annuler</button>
          </div>
        </form>
      )}

      <div className={styles.docLayout}>
        <div className={styles.docList}>
          {contrats.length === 0 && <p className={styles.empty}>Aucun contrat.</p>}
          {contrats.map(c => (
            <div key={c.id} className={`${styles.docItem} ${selected?.id === c.id ? styles.activeDoc : ''}`} onClick={() => setSelected(c)}>
              <span>📋</span>
              <div className={styles.docMeta}>
                <div className={styles.rowTitle}>{c.titre}</div>
                <div className={styles.rowSub}>{c.type} · <span style={{ color: STATUT_COLORS[c.statut] }}>{STATUT_LABELS[c.statut]}</span></div>
              </div>
            </div>
          ))}
        </div>

        {selected && (
          <div className={styles.docPreview}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
              <div>
                <h3 className={styles.docTitle}>{selected.titre}</h3>
                <span className={styles.statutBadge} style={{ background: STATUT_COLORS[selected.statut] + '22', color: STATUT_COLORS[selected.statut] }}>
                  {STATUT_LABELS[selected.statut]}
                </span>
              </div>
              <div style={{ display: 'flex', gap: 6 }}>
                {selected.statut === 'brouillon' && <button className={styles.btnSecondary} onClick={() => updateStatut(selected.id, 'actif')}>Activer</button>}
                {selected.statut === 'actif' && <button className={styles.btnSecondary} onClick={() => setShowSign(true)}>✍ Signer</button>}
                <button className={styles.micro} style={{ color: '#ef4444' }} onClick={() => remove(selected.id)}>✕</button>
              </div>
            </div>

            {showSign && selected.statut === 'actif' && (
              <div className={styles.form} style={{ marginBottom: 16 }}>
                <input className={styles.input} placeholder="Signé par (nom)" value={signePar} onChange={e => setSignePar(e.target.value)} />
                <div className={styles.formActions}>
                  <button className={styles.btnPrimary} onClick={() => signer(selected.id)}>Confirmer</button>
                  <button className={styles.btnGhost} onClick={() => setShowSign(false)}>Annuler</button>
                </div>
              </div>
            )}

            {selected.parties && <p className={styles.rowSub}>👥 {selected.parties}</p>}
            {selected.valeur > 0 && <p className={styles.rowSub}>💶 {selected.valeur.toLocaleString()} €</p>}
            {selected.dateDebut && <p className={styles.rowSub}>📅 {selected.dateDebut} → {selected.dateFin || '∞'}</p>}
            {selected.signePar && <p className={styles.rowSub}>✍ Signé par {selected.signePar}</p>}
            {selected.contenu && <div className={styles.analyse} style={{ marginTop: 12 }}>{selected.contenu}</div>}
            {selected.notes && <div className={styles.notes} style={{ marginTop: 8 }}>{selected.notes}</div>}
          </div>
        )}
      </div>
    </div>
  )
}

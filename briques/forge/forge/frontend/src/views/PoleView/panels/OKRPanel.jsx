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

const STATUT_COLORS = { actif: '#6366f1', atteint: '#10b981', abandonne: '#6b7280' }
const STATUT_LABELS = { actif: 'Actif', atteint: '✅ Atteint', abandonne: '⏹ Abandonné' }

function ProgressBar({ value }) {
  const pct = Math.min(Math.max(value, 0), 100)
  const color = pct >= 80 ? '#10b981' : pct >= 50 ? '#f59e0b' : '#6366f1'
  return (
    <div style={{ background: '#1e1e2e', borderRadius: 4, height: 6, overflow: 'hidden', marginTop: 6 }}>
      <div style={{ width: `${pct}%`, background: color, height: '100%', borderRadius: 4, transition: 'width 0.3s' }} />
    </div>
  )
}

export default function OKRPanel({ poleId }) {
  const [okrs, setOkrs]         = useState([])
  const [selected, setSelected] = useState(null)
  const [showForm, setShow]     = useState(false)
  const [showKR, setShowKR]     = useState(false)
  const [form, setForm]         = useState({ titre: '', description: '', periode: '' })
  const [krForm, setKrForm]     = useState({ titre: '', valeurCible: 100, valeurActuelle: 0, unite: '%' })
  const [loading, setLoading]   = useState(false)

  useEffect(() => { load() }, [poleId])

  async function load() {
    const data = await req(`/api/poles/${poleId}/okrs`).catch(() => [])
    setOkrs(data)
    if (selected) setSelected(data.find(o => o.id === selected.id) ?? null)
  }

  async function createOKR(e) {
    e.preventDefault()
    setLoading(true)
    try {
      const o = await req(`/api/poles/${poleId}/okrs`, { method: 'POST', body: JSON.stringify(form) })
      setOkrs(prev => [o, ...prev])
      setSelected(o)
      setForm({ titre: '', description: '', periode: '' })
      setShow(false)
    } finally { setLoading(false) }
  }

  async function addKR(e) {
    e.preventDefault()
    if (!selected) return
    setLoading(true)
    try {
      await req(`/api/okrs/${selected.id}/kr`, { method: 'POST', body: JSON.stringify(krForm) })
      await load()
      setKrForm({ titre: '', valeurCible: 100, valeurActuelle: 0, unite: '%' })
      setShowKR(false)
    } finally { setLoading(false) }
  }

  async function updateKR(krId, valeurActuelle) {
    await req(`/api/kr/${krId}`, { method: 'PATCH', body: JSON.stringify({ valeurActuelle }) })
    load()
  }

  async function deleteKR(krId) {
    await req(`/api/kr/${krId}`, { method: 'DELETE' })
    load()
  }

  async function updateStatut(id, statut) {
    await req(`/api/okrs/${id}`, { method: 'PATCH', body: JSON.stringify({ statut }) })
    load()
  }

  async function deleteOKR(id) {
    await req(`/api/okrs/${id}`, { method: 'DELETE' })
    setOkrs(prev => prev.filter(o => o.id !== id))
    if (selected?.id === id) setSelected(null)
  }

  return (
    <div className={styles.panel}>
      <div className={styles.toolbar}>
        <button className={styles.btnPrimary} onClick={() => setShow(v => !v)}>+ OKR</button>
      </div>

      {showForm && (
        <form className={styles.form} onSubmit={createOKR}>
          <input className={styles.input} placeholder="Objectif *" required value={form.titre} onChange={e => setForm(f => ({ ...f, titre: e.target.value }))} />
          <input className={styles.input} placeholder="Période (ex: Q2 2026)" value={form.periode} onChange={e => setForm(f => ({ ...f, periode: e.target.value }))} />
          <textarea className={styles.textarea} placeholder="Description" value={form.description} onChange={e => setForm(f => ({ ...f, description: e.target.value }))} />
          <div className={styles.formActions}>
            <button type="submit" className={styles.btnPrimary} disabled={loading}>Créer</button>
            <button type="button" className={styles.btnGhost} onClick={() => setShow(false)}>Annuler</button>
          </div>
        </form>
      )}

      <div className={styles.docLayout}>
        {/* Liste OKRs */}
        <div className={styles.docList}>
          {okrs.length === 0 && <p className={styles.empty}>Aucun OKR.</p>}
          {okrs.map(o => (
            <div key={o.id} className={`${styles.docItem} ${selected?.id === o.id ? styles.activeDoc : ''}`} onClick={() => setSelected(o)}>
              <span>🎯</span>
              <div className={styles.docMeta}>
                <div className={styles.rowTitle}>{o.titre}</div>
                <div className={styles.rowSub} style={{ color: STATUT_COLORS[o.statut] }}>{STATUT_LABELS[o.statut]}</div>
                <ProgressBar value={o.progression ?? 0} />
                <div style={{ fontSize: 10, color: '#6b6b80', marginTop: 2 }}>{o.progression ?? 0}%</div>
              </div>
            </div>
          ))}
        </div>

        {/* Détail OKR */}
        {selected && (
          <div className={styles.docPreview}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
              <div>
                <h3 className={styles.docTitle}>{selected.titre}</h3>
                {selected.periode && <div className={styles.rowSub}>📅 {selected.periode}</div>}
                <span className={styles.statutBadge} style={{ background: STATUT_COLORS[selected.statut] + '22', color: STATUT_COLORS[selected.statut] }}>
                  {STATUT_LABELS[selected.statut]}
                </span>
              </div>
              <div style={{ display: 'flex', gap: 6 }}>
                {selected.statut === 'actif' && <button className={styles.btnSecondary} onClick={() => updateStatut(selected.id, 'atteint')}>✅ Atteint</button>}
                <button className={styles.micro} style={{ color: '#ef4444' }} onClick={() => deleteOKR(selected.id)}>✕</button>
              </div>
            </div>

            {selected.description && <p className={styles.rowSub} style={{ marginBottom: 16 }}>{selected.description}</p>}

            {/* Progression globale */}
            <div style={{ marginBottom: 16 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                <span style={{ fontSize: 12, color: '#6b6b80' }}>Progression globale</span>
                <span style={{ fontSize: 14, fontWeight: 700, color: '#e8e8f0' }}>{selected.progression ?? 0}%</span>
              </div>
              <ProgressBar value={selected.progression ?? 0} />
            </div>

            {/* Key Results */}
            <div className={styles.docsSection}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                <h4 className={styles.docsTitle}>Key Results</h4>
                <button className={styles.btnSecondary} onClick={() => setShowKR(v => !v)}>+ KR</button>
              </div>

              {showKR && (
                <form className={styles.form} onSubmit={addKR} style={{ marginBottom: 12 }}>
                  <input className={styles.input} placeholder="Résultat clé *" required value={krForm.titre} onChange={e => setKrForm(f => ({ ...f, titre: e.target.value }))} />
                  <div style={{ display: 'flex', gap: 8 }}>
                    <input className={styles.input} type="number" placeholder="Cible" value={krForm.valeurCible} onChange={e => setKrForm(f => ({ ...f, valeurCible: +e.target.value }))} />
                    <input className={styles.input} type="number" placeholder="Actuel" value={krForm.valeurActuelle} onChange={e => setKrForm(f => ({ ...f, valeurActuelle: +e.target.value }))} />
                    <input className={styles.input} placeholder="Unité" value={krForm.unite} onChange={e => setKrForm(f => ({ ...f, unite: e.target.value }))} style={{ width: 70 }} />
                  </div>
                  <div className={styles.formActions}>
                    <button type="submit" className={styles.btnPrimary} disabled={loading}>Ajouter</button>
                    <button type="button" className={styles.btnGhost} onClick={() => setShowKR(false)}>Annuler</button>
                  </div>
                </form>
              )}

              {(selected.keyResults ?? []).length === 0 && <p className={styles.empty}>Aucun Key Result.</p>}
              {(selected.keyResults ?? []).map(kr => {
                const pct = Math.round(Math.min((kr.valeurActuelle / kr.valeurCible) * 100, 100))
                return (
                  <div key={kr.id} className={styles.docCard} style={{ marginBottom: 8 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 4 }}>
                      <span className={styles.rowTitle} style={{ fontSize: 13 }}>{kr.titre}</span>
                      <button className={styles.micro} style={{ color: '#ef4444' }} onClick={() => deleteKR(kr.id)}>✕</button>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                      <input
                        type="range" min={0} max={kr.valeurCible} step={kr.valeurCible / 100}
                        value={kr.valeurActuelle}
                        onChange={e => updateKR(kr.id, +e.target.value)}
                        style={{ flex: 1 }}
                      />
                      <span style={{ fontSize: 12, color: '#a8a8c0', minWidth: 80, textAlign: 'right' }}>
                        {kr.valeurActuelle} / {kr.valeurCible} {kr.unite} ({pct}%)
                      </span>
                    </div>
                    <ProgressBar value={pct} />
                  </div>
                )
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

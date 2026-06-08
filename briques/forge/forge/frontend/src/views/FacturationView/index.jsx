import { useState, useEffect, useCallback } from 'react'
import { token } from '../../services/api'
import styles from './Facturation.module.css'

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

const STATUS_COLORS = {
  brouillon: '#6b7280', envoyé: '#f59e0b', envoyée: '#f59e0b',
  accepté: '#10b981', payée: '#10b981', refusé: '#ef4444',
  annulée: '#ef4444', transformé: '#6366f1',
}

function newLigne() { return { description: '', quantite: 1, prixUnitaire: 0, tva: 20 } }
function calcLignes(lignes, tvaTaux = 20) {
  const ht  = lignes.reduce((s, l) => s + (l.quantite || 0) * (l.prixUnitaire || 0), 0)
  const tva = lignes.reduce((s, l) => s + (l.quantite || 0) * (l.prixUnitaire || 0) * ((l.tva ?? tvaTaux) / 100), 0)
  return { ht: Math.round(ht * 100) / 100, tva: Math.round(tva * 100) / 100, ttc: Math.round((ht + tva) * 100) / 100 }
}

export default function FacturationView() {
  const [onglet, setOnglet]       = useState('factures')
  const [docs, setDocs]           = useState([])
  const [stats, setStats]         = useState(null)
  const [selected, setSelected]   = useState(null)
  const [showModal, setShowModal] = useState(false)
  const [loading, setLoading]     = useState(false)
  const [form, setForm]           = useState({
    type: 'facture', clientNom: '', clientEmail: '', clientAdresse: '',
    lignes: [newLigne()], tvaTaux: 20, notes: '', conditions: 'Paiement à 30 jours',
    dateEmission: '', dateEcheance: '',
  })

  const load = useCallback(async () => {
    setLoading(true)
    const { items, stats: s } = await req(`/api/facturation?type=${onglet === 'factures' ? 'facture' : 'devis'}`).catch(() => ({ items: [], stats: null }))
    setDocs(items ?? [])
    setStats(s ?? null)
    setLoading(false)
  }, [onglet])

  useEffect(() => { load() }, [load])

  async function submit(e) {
    e.preventDefault()
    const lignesParsed = form.lignes.map(l => ({ ...l, quantite: +l.quantite, prixUnitaire: +l.prixUnitaire, tva: +l.tva }))
    const doc = await req('/api/facturation', { method: 'POST', body: JSON.stringify({ ...form, lignes: lignesParsed, type: onglet === 'factures' ? 'facture' : 'devis' }) })
    setDocs(prev => [doc, ...prev])
    setSelected(doc)
    setShowModal(false)
    setForm({ type: 'facture', clientNom: '', clientEmail: '', clientAdresse: '', lignes: [newLigne()], tvaTaux: 20, notes: '', conditions: 'Paiement à 30 jours', dateEmission: '', dateEcheance: '' })
    load()
  }

  async function changerStatut(id, statut) {
    await req(`/api/facturation/${id}`, { method: 'PATCH', body: JSON.stringify({ statut }) })
    load()
    if (selected?.id === id) {
      const d = await req(`/api/facturation/${id}`)
      setSelected(d)
    }
  }

  async function supprimer(id) {
    if (!confirm('Supprimer ce document ?')) return
    await req(`/api/facturation/${id}`, { method: 'DELETE' })
    setDocs(prev => prev.filter(d => d.id !== id))
    if (selected?.id === id) setSelected(null)
    load()
  }

  async function transformer(id) {
    await req(`/api/facturation/${id}/transformer`, { method: 'POST', body: '{}' })
    setOnglet('factures')
  }

  function updateLigne(i, field, val) {
    setForm(f => {
      const lignes = [...f.lignes]
      lignes[i] = { ...lignes[i], [field]: val }
      return { ...f, lignes }
    })
  }

  const { ht, tva, ttc } = calcLignes(form.lignes, form.tvaTaux)

  const parseLignes = (raw) => { try { return typeof raw === 'string' ? JSON.parse(raw) : raw } catch { return [] } }

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <span className={styles.icon}>🧾</span>
        <div>
          <div className={styles.title}>Facturation</div>
          <div className={styles.subtitle}>Devis & Factures</div>
        </div>
        <div className={styles.tabs}>
          {['factures', 'devis'].map(t => (
            <button key={t} className={`${styles.tab} ${onglet === t ? styles.tabActive : ''}`} onClick={() => setOnglet(t)}>
              {t === 'factures' ? '🧾 Factures' : '📄 Devis'}
            </button>
          ))}
          <button className={styles.btnPrimary} onClick={() => setShowModal(true)}>+ Nouveau</button>
        </div>
      </header>

      {/* Stats */}
      {stats && (
        <div className={styles.statsRow}>
          {[
            { label: 'CA encaissé',  val: `${(stats.caTotal || 0).toLocaleString('fr-FR')} €`,     color: '#10b981' },
            { label: 'En attente',   val: `${(stats.caEnAttente || 0).toLocaleString('fr-FR')} €`,  color: '#f59e0b' },
            { label: 'Factures',     val: stats.nbFactures, color: '#a8a8c0' },
            { label: 'Devis',        val: stats.nbDevis,    color: '#a8a8c0' },
          ].map(k => (
            <div key={k.label} className={styles.stat}>
              <div className={styles.statVal} style={{ color: k.color }}>{k.val}</div>
              <div className={styles.statLabel}>{k.label}</div>
            </div>
          ))}
        </div>
      )}

      <div className={styles.layout}>
        {/* Liste */}
        <div className={styles.list}>
          {loading && <div className={styles.empty}>Chargement…</div>}
          {!loading && docs.length === 0 && <div className={styles.empty}>Aucun document.</div>}
          {docs.map(d => {
            const lignes = parseLignes(d.lignes)
            return (
              <div key={d.id} className={`${styles.docItem} ${selected?.id === d.id ? styles.docActive : ''}`} onClick={() => setSelected(d)}>
                <div className={styles.docNum}>{d.numero}</div>
                <div className={styles.docClient}>{d.clientNom}</div>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4 }}>
                  <span className={styles.badge} style={{ background: (STATUS_COLORS[d.statut] ?? '#6b7280') + '22', color: STATUS_COLORS[d.statut] ?? '#6b7280' }}>
                    {d.statut}
                  </span>
                  <span className={styles.amount}>{(d.totalTtc ?? 0).toLocaleString('fr-FR')} €</span>
                </div>
              </div>
            )
          })}
        </div>

        {/* Détail */}
        {selected && (() => {
          const lignes = parseLignes(selected.lignes)
          return (
            <div className={styles.detail}>
              <div className={styles.detailHeader}>
                <div>
                  <div className={styles.detailNum}>{selected.numero}</div>
                  <span className={styles.badge} style={{ background: (STATUS_COLORS[selected.statut] ?? '#6b7280') + '22', color: STATUS_COLORS[selected.statut] ?? '#6b7280' }}>
                    {selected.statut}
                  </span>
                </div>
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                  {selected.statut === 'brouillon' && selected.type === 'facture' &&
                    <button className={styles.btnSecondary} onClick={() => changerStatut(selected.id, 'envoyée')}>Envoyer</button>}
                  {selected.statut === 'brouillon' && selected.type === 'devis' &&
                    <button className={styles.btnSecondary} onClick={() => changerStatut(selected.id, 'envoyé')}>Envoyer</button>}
                  {selected.statut === 'envoyée' &&
                    <button className={styles.btnSecondary} onClick={() => changerStatut(selected.id, 'payée')}>✓ Payée</button>}
                  {selected.statut === 'envoyé' &&
                    <button className={styles.btnSecondary} onClick={() => changerStatut(selected.id, 'accepté')}>✓ Accepté</button>}
                  {selected.statut === 'accepté' && selected.type === 'devis' &&
                    <button className={styles.btnSecondary} onClick={() => transformer(selected.id)}>→ Facture</button>}
                  <button className={styles.btnDanger} onClick={() => supprimer(selected.id)}>✕</button>
                </div>
              </div>

              <div className={styles.clientBlock}>
                <div className={styles.clientNom}>{selected.clientNom}</div>
                {selected.clientEmail && <div className={styles.clientMeta}>{selected.clientEmail}</div>}
                {selected.clientAdresse && <div className={styles.clientMeta}>{selected.clientAdresse}</div>}
              </div>

              {selected.dateEmission && <div className={styles.dates}>📅 Émis le {selected.dateEmission}{selected.dateEcheance ? ` · Échéance : ${selected.dateEcheance}` : ''}</div>}

              {/* Lignes */}
              <table className={styles.table}>
                <thead>
                  <tr><th>Description</th><th>Qté</th><th>P.U.</th><th>TVA</th><th>Total</th></tr>
                </thead>
                <tbody>
                  {lignes.map((l, i) => (
                    <tr key={i}>
                      <td>{l.description}</td>
                      <td>{l.quantite}</td>
                      <td>{(l.prixUnitaire ?? 0).toLocaleString('fr-FR')} €</td>
                      <td>{l.tva ?? 20}%</td>
                      <td>{((l.quantite || 0) * (l.prixUnitaire || 0)).toLocaleString('fr-FR')} €</td>
                    </tr>
                  ))}
                </tbody>
              </table>

              <div className={styles.totaux}>
                <div className={styles.totauxRow}><span>HT</span><span>{(selected.totalHt ?? 0).toLocaleString('fr-FR')} €</span></div>
                <div className={styles.totauxRow}><span>TVA</span><span>{(selected.totalTva ?? 0).toLocaleString('fr-FR')} €</span></div>
                <div className={`${styles.totauxRow} ${styles.totauxTTC}`}><span>TTC</span><span>{(selected.totalTtc ?? 0).toLocaleString('fr-FR')} €</span></div>
              </div>

              {selected.notes && <div className={styles.notes}><strong>Notes :</strong> {selected.notes}</div>}
              {selected.conditions && <div className={styles.notes}>{selected.conditions}</div>}
            </div>
          )
        })()}
      </div>

      {/* Modal création */}
      {showModal && (
        <div className={styles.overlay} onClick={() => setShowModal(false)}>
          <div className={styles.modal} onClick={e => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <span>Nouveau {onglet === 'factures' ? 'facture' : 'devis'}</span>
              <button className={styles.close} onClick={() => setShowModal(false)}>✕</button>
            </div>
            <form onSubmit={submit} className={styles.modalForm}>
              <input className={styles.input} placeholder="Client *" required value={form.clientNom} onChange={e => setForm(f => ({ ...f, clientNom: e.target.value }))} />
              <input className={styles.input} placeholder="Email client" value={form.clientEmail} onChange={e => setForm(f => ({ ...f, clientEmail: e.target.value }))} />
              <input className={styles.input} placeholder="Adresse" value={form.clientAdresse} onChange={e => setForm(f => ({ ...f, clientAdresse: e.target.value }))} />
              <div style={{ display: 'flex', gap: 8 }}>
                <input className={styles.input} type="date" placeholder="Date émission" value={form.dateEmission} onChange={e => setForm(f => ({ ...f, dateEmission: e.target.value }))} />
                <input className={styles.input} type="date" placeholder="Échéance" value={form.dateEcheance} onChange={e => setForm(f => ({ ...f, dateEcheance: e.target.value }))} />
              </div>

              {/* Lignes */}
              <div className={styles.lignesHeader}>
                <span>Lignes</span>
                <button type="button" className={styles.btnSecondary} onClick={() => setForm(f => ({ ...f, lignes: [...f.lignes, newLigne()] }))}>+ Ligne</button>
              </div>
              {form.lignes.map((l, i) => (
                <div key={i} className={styles.ligne}>
                  <input className={styles.input} placeholder="Description" value={l.description} onChange={e => updateLigne(i, 'description', e.target.value)} style={{ flex: 3 }} />
                  <input className={styles.input} type="number" placeholder="Qté" value={l.quantite} onChange={e => updateLigne(i, 'quantite', e.target.value)} style={{ width: 60 }} />
                  <input className={styles.input} type="number" placeholder="P.U." value={l.prixUnitaire} onChange={e => updateLigne(i, 'prixUnitaire', e.target.value)} style={{ width: 80 }} />
                  <input className={styles.input} type="number" placeholder="TVA%" value={l.tva} onChange={e => updateLigne(i, 'tva', e.target.value)} style={{ width: 60 }} />
                  {form.lignes.length > 1 && <button type="button" className={styles.btnDanger} onClick={() => setForm(f => ({ ...f, lignes: f.lignes.filter((_, j) => j !== i) }))}>✕</button>}
                </div>
              ))}

              <div className={styles.totalPreview}>
                <span>HT: {ht.toLocaleString('fr-FR')} €</span>
                <span>TVA: {tva.toLocaleString('fr-FR')} €</span>
                <strong>TTC: {ttc.toLocaleString('fr-FR')} €</strong>
              </div>

              <textarea className={styles.input} placeholder="Notes" value={form.notes} onChange={e => setForm(f => ({ ...f, notes: e.target.value }))} style={{ minHeight: 60, resize: 'vertical' }} />
              <input className={styles.input} placeholder="Conditions (ex: Paiement à 30 jours)" value={form.conditions} onChange={e => setForm(f => ({ ...f, conditions: e.target.value }))} />

              <div className={styles.modalActions}>
                <button type="submit" className={styles.btnPrimary}>Créer</button>
                <button type="button" className={styles.btnGhost} onClick={() => setShowModal(false)}>Annuler</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}

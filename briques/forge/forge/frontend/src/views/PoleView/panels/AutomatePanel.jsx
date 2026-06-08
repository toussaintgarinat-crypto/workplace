import { useState, useEffect } from 'react'
import { api, polesApi } from '../../../services/api'
import styles from './AutomatePanel.module.css'

const STATUS_LABELS = {
  pending:   { label: 'En attente',  color: '#f59e0b' },
  analyzing: { label: 'Analyse IA',  color: '#3b82f6' },
  analyzed:  { label: 'Analysé',     color: '#8b5cf6' },
  building:  { label: 'En cours',    color: '#6366f1' },
  deployed:  { label: 'Déployé',     color: '#10b981' },
  rejected:  { label: 'Rejeté',      color: '#ef4444' },
}

const FREQ_LABELS = {
  daily:    'Quotidien',
  weekly:   'Hebdomadaire',
  on_event: 'Sur événement',
  manual:   'Manuel',
}

export default function AutomatePanel({ poleId }) {
  const [pole, setPole]         = useState(null)
  const [requests, setRequests] = useState([])
  const [showForm, setShowForm] = useState(false)
  const [selected, setSelected] = useState(null)
  const [saving, setSaving]     = useState(false)
  const [form, setForm] = useState({
    title: '', description: '', frequency: 'manual', priority: 'medium',
  })

  useEffect(() => {
    if (!poleId) return
    polesApi.get(poleId).then(setPole).catch(() => {})
    api.get(`/api/poles/${poleId}/dev-requests`).then(setRequests).catch(() => {})
  }, [poleId])

  async function submit(e) {
    e.preventDefault()
    if (!pole) return
    setSaving(true)
    try {
      const r = await api.post(`/api/poles/${poleId}/dev-requests`, {
        ...form,
        sourcePoleName:  pole.nom,
        sourcePoleEmoji: pole.emoji,
      })
      setRequests(rs => [r, ...rs])
      setForm({ title: '', description: '', frequency: 'manual', priority: 'medium' })
      setShowForm(false)
      setSelected(r)
    } finally { setSaving(false) }
  }

  const st = selected ? STATUS_LABELS[selected.status] ?? STATUS_LABELS.pending : null

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <div>
          <h2 className={styles.title}>🤖 Demandes au Pôle Dev</h2>
          <p className={styles.sub}>Soumettez vos tâches répétitives pour automatisation</p>
        </div>
        <button className={styles.btnPrimary} onClick={() => setShowForm(v => !v)}>
          + Nouvelle demande
        </button>
      </div>

      {showForm && (
        <form className={styles.form} onSubmit={submit}>
          <input
            className={styles.input}
            placeholder="Titre de la tâche répétitive *"
            required value={form.title}
            onChange={e => setForm(f => ({ ...f, title: e.target.value }))}
          />
          <textarea
            className={styles.textarea}
            placeholder="Décrivez la tâche en détail : que faites-vous, à quelle fréquence, combien de temps ça prend, quels systèmes sont impliqués…"
            required rows={4} value={form.description}
            onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
          />
          <div className={styles.row}>
            <div className={styles.field}>
              <label className={styles.label}>Fréquence</label>
              <select className={styles.select} value={form.frequency}
                onChange={e => setForm(f => ({ ...f, frequency: e.target.value }))}>
                <option value="daily">Quotidien</option>
                <option value="weekly">Hebdomadaire</option>
                <option value="on_event">Sur événement</option>
                <option value="manual">Manuel</option>
              </select>
            </div>
            <div className={styles.field}>
              <label className={styles.label}>Priorité</label>
              <select className={styles.select} value={form.priority}
                onChange={e => setForm(f => ({ ...f, priority: e.target.value }))}>
                <option value="low">Faible</option>
                <option value="medium">Moyenne</option>
                <option value="high">Haute</option>
                <option value="critical">Critique</option>
              </select>
            </div>
          </div>
          <div className={styles.formActions}>
            <button type="submit" className={styles.btnPrimary} disabled={saving}>
              {saving ? '…' : 'Envoyer au Pôle Dev'}
            </button>
            <button type="button" className={styles.btnGhost} onClick={() => setShowForm(false)}>
              Annuler
            </button>
          </div>
        </form>
      )}

      <div className={styles.split}>
        <div className={styles.list}>
          {requests.length === 0 && (
            <div className={styles.empty}>Aucune demande envoyée.<br/>Le Pôle Dev attend vos tâches répétitives.</div>
          )}
          {requests.map(r => {
            const s = STATUS_LABELS[r.status] ?? STATUS_LABELS.pending
            return (
              <div
                key={r.id}
                className={`${styles.item} ${selected?.id === r.id ? styles.itemActive : ''}`}
                onClick={() => setSelected(r)}
              >
                <div className={styles.itemHeader}>
                  <span className={styles.itemTitle}>{r.title}</span>
                  <span className={styles.badge} style={{ background: s.color + '22', color: s.color }}>
                    {s.label}
                  </span>
                </div>
                <div className={styles.itemMeta}>
                  <span>{FREQ_LABELS[r.frequency] ?? r.frequency}</span>
                  <span className={styles.dot}>·</span>
                  <span>{new Date(r.createdAt).toLocaleDateString('fr-FR')}</span>
                </div>
              </div>
            )
          })}
        </div>

        <div className={styles.detail}>
          {!selected && (
            <div className={styles.detailEmpty}>
              Sélectionnez une demande pour voir son statut
            </div>
          )}
          {selected && (
            <>
              <div className={styles.detailHeader}>
                <h3 className={styles.detailTitle}>{selected.title}</h3>
                <span className={styles.badge} style={{ background: st.color + '22', color: st.color }}>
                  {st.label}
                </span>
              </div>
              <p className={styles.detailDesc}>{selected.description}</p>
              <div className={styles.detailMeta}>
                <span>📅 {FREQ_LABELS[selected.frequency]}</span>
                <span>⚡ Priorité {selected.priority}</span>
              </div>

              {selected.analysis && (
                <div className={styles.section}>
                  <div className={styles.sectionTitle}>🔍 Analyse IA</div>
                  <p className={styles.sectionBody}>{selected.analysis}</p>
                </div>
              )}
              {selected.proposedSolution && (
                <div className={styles.section}>
                  <div className={styles.sectionTitle}>💡 Solution proposée</div>
                  <p className={styles.sectionBody}>{selected.proposedSolution}</p>
                </div>
              )}
              {selected.status === 'deployed' && (
                <div className={styles.deployedBanner}>
                  ✅ Automatisation déployée par le Pôle Dev
                </div>
              )}
              {selected.status === 'rejected' && selected.rejectionReason && (
                <div className={styles.rejectedBanner}>
                  ❌ Rejetée : {selected.rejectionReason}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}

import { useState, useEffect } from 'react'
import { api } from '../../services/api'
import styles from './Automation.module.css'

const TRIGGERS = ['session.created', 'decision.approved', 'incident.opened', 'crm.lead.won', 'sprint.completed', 'brief.generated']

export default function AutomationView() {
  const [rules, setRules] = useState([])
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState({ nom: '', description: '', trigger: TRIGGERS[0], actif: true })
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    api.get('/api/automation').then(r => setRules(Array.isArray(r) ? r : [])).catch(() => {})
  }, [])

  async function submit(e) {
    e.preventDefault()
    setSaving(true)
    try {
      const rule = await api.post('/api/automation', form)
      setRules(rs => [rule, ...rs])
      setForm({ nom: '', description: '', trigger: TRIGGERS[0], actif: true })
      setShowForm(false)
    } finally { setSaving(false) }
  }

  async function toggle(id, actif) {
    await api.patch(`/api/automation/${id}`, { actif })
    setRules(rs => rs.map(r => r.id === id ? { ...r, actif } : r))
  }

  async function remove(id) {
    await api.delete(`/api/automation/${id}`)
    setRules(rs => rs.filter(r => r.id !== id))
  }

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <h1 className={styles.title}>⚡ Automation Rules</h1>
        <button className={styles.btnPrimary} onClick={() => setShowForm(v => !v)}>+ Règle</button>
      </div>

      {showForm && (
        <form className={styles.form} onSubmit={submit}>
          <input className={styles.input} placeholder="Nom de la règle *" required value={form.nom}
            onChange={e => setForm(f => ({ ...f, nom: e.target.value }))} />
          <input className={styles.input} placeholder="Description (optionnel)" value={form.description}
            onChange={e => setForm(f => ({ ...f, description: e.target.value }))} />
          <div className={styles.field}>
            <label className={styles.label}>Trigger</label>
            <select className={styles.select} value={form.trigger} onChange={e => setForm(f => ({ ...f, trigger: e.target.value }))}>
              {TRIGGERS.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          <div className={styles.formActions}>
            <button type="submit" className={styles.btnPrimary} disabled={saving}>{saving ? '...' : 'Créer'}</button>
            <button type="button" className={styles.btnGhost} onClick={() => setShowForm(false)}>Annuler</button>
          </div>
        </form>
      )}

      <div className={styles.list}>
        {rules.length === 0 && <p className={styles.empty}>Aucune règle d'automation configurée.</p>}
        {rules.map(r => (
          <div key={r.id} className={styles.ruleCard}>
            <div className={styles.ruleLeft}>
              <div className={styles.ruleName}>{r.nom}</div>
              {r.description && <div className={styles.ruleSub}>{r.description}</div>}
              <div className={styles.ruleMeta}>
                <span className={styles.chip}>Trigger: {r.trigger}</span>
                <span className={styles.executions}>{r.executions ?? 0} exécutions</span>
              </div>
            </div>
            <div className={styles.ruleRight}>
              <button className={`${styles.toggleBtn} ${r.actif ? styles.on : styles.off}`}
                onClick={() => toggle(r.id, !r.actif)}>
                {r.actif ? '✅ Actif' : '⏸️ Inactif'}
              </button>
              <button className={styles.deleteBtn} onClick={() => remove(r.id)}>✕</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

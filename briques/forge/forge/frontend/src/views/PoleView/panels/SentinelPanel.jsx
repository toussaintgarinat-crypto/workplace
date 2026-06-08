import { useState, useEffect } from 'react'
import { api } from '../../../services/api'
import styles from './Panel.module.css'

export default function SentinelPanel({ poleId }) {
  const [checklist, setChecklist] = useState([])
  const [checks, setChecks] = useState({})
  const [form, setForm] = useState({ entreprise: '', secteur: '' })
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    api.get('/api/sentinel-rgpd/checklist').then(list => {
      setChecklist(list)
      const defaults = {}
      list.forEach(item => { defaults[item.id] = false })
      setChecks(defaults)
    }).catch(() => {})
  }, [])

  async function runAudit(e) {
    e.preventDefault()
    setLoading(true)
    try {
      const data = await api.post('/api/sentinel-rgpd/audit', { ...form, checklist: checks })
      setResult(data)
    } finally { setLoading(false) }
  }

  const scoreColor = result ? (result.score >= 80 ? '#10b981' : result.score >= 50 ? '#f59e0b' : '#ef4444') : '#6b6b80'

  return (
    <div className={styles.panel}>
      <form className={styles.form} onSubmit={runAudit}>
        <input className={styles.input} placeholder="Entreprise *" required value={form.entreprise}
          onChange={e => setForm(f => ({ ...f, entreprise: e.target.value }))} />
        <input className={styles.input} placeholder="Secteur d'activité" value={form.secteur}
          onChange={e => setForm(f => ({ ...f, secteur: e.target.value }))} />

        <div className={styles.rowTitle} style={{ marginTop: 4 }}>Checklist RGPD</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxHeight: 220, overflowY: 'auto' }}>
          {checklist.map(item => (
            <label key={item.id} style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontSize: 13, color: checks[item.id] ? '#e8e8f0' : '#6b6b80' }}>
              <input type="checkbox" checked={checks[item.id] ?? false}
                onChange={e => setChecks(c => ({ ...c, [item.id]: e.target.checked }))} />
              {item.label}
              <span style={{ marginLeft: 'auto', fontSize: 11, color: '#6366f1' }}>{item.articles.join(', ')}</span>
            </label>
          ))}
        </div>

        <button type="submit" className={styles.btnPrimary} disabled={loading}>
          {loading ? 'Audit en cours...' : '🔍 Lancer l\'audit RGPD'}
        </button>
      </form>

      {result && (
        <div className={styles.form}>
          <div className={styles.stats}>
            <div className={styles.stat}>
              <div className={styles.statLabel}>Score RGPD</div>
              <div className={styles.statValue} style={{ color: scoreColor }}>{result.score}/100</div>
            </div>
          </div>
          <div className={styles.rowTitle}>Analyse</div>
          <div style={{ fontSize: 13, color: '#a8a8c0', lineHeight: 1.7, whiteSpace: 'pre-wrap', maxHeight: 350, overflowY: 'auto' }}>
            {result.analyse}
          </div>
        </div>
      )}
    </div>
  )
}

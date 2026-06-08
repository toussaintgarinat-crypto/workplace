import { useState, useEffect } from 'react'
import { api } from '../../../services/api'
import styles from './Panel.module.css'

export default function LegalAgentPanel({ poleId }) {
  const [templates, setTemplates] = useState([])
  const [selected, setSelected] = useState('')
  const [parties, setParties] = useState({ partie_a: '', partie_b: '' })
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [tab, setTab] = useState('generate')
  const [analyseText, setAnalyseText] = useState('')
  const [analyseResult, setAnalyseResult] = useState(null)
  const [analyseLoading, setAnalyseLoading] = useState(false)

  useEffect(() => {
    api.get('/api/legal-agent/templates').then(setTemplates).catch(() => {})
  }, [])

  async function generate(e) {
    e.preventDefault()
    if (!selected) return
    setLoading(true)
    try {
      const data = await api.post('/api/legal-agent/generate', { type: selected, parties })
      setResult(data)
    } finally { setLoading(false) }
  }

  async function analyze(e) {
    e.preventDefault()
    if (!analyseText.trim()) return
    setAnalyseLoading(true)
    try {
      const data = await api.post('/api/legal-agent/analyze', { contenu: analyseText })
      setAnalyseResult(data.analyse)
    } finally { setAnalyseLoading(false) }
  }

  return (
    <div className={styles.panel}>
      <div className={styles.toolbar}>
        <div className={styles.filterGroup}>
          <button className={`${styles.filterBtn} ${tab === 'generate' ? styles.active : ''}`} onClick={() => setTab('generate')}>📄 Générer</button>
          <button className={`${styles.filterBtn} ${tab === 'analyze' ? styles.active : ''}`} onClick={() => setTab('analyze')}>🔍 Analyser</button>
        </div>
      </div>

      {tab === 'generate' && (
        <form className={styles.form} onSubmit={generate}>
          <select className={styles.select} value={selected} onChange={e => setSelected(e.target.value)} required>
            <option value="">Choisir un type de document...</option>
            {templates.map(t => <option key={t.key} value={t.key}>{t.label}</option>)}
          </select>
          <input className={styles.input} placeholder="Partie A (ex: Votre société)" value={parties.partie_a}
            onChange={e => setParties(p => ({ ...p, partie_a: e.target.value }))} />
          <input className={styles.input} placeholder="Partie B (ex: Client SAS)" value={parties.partie_b}
            onChange={e => setParties(p => ({ ...p, partie_b: e.target.value }))} />
          <button type="submit" className={styles.btnPrimary} disabled={loading || !selected}>
            {loading ? 'Génération...' : '📄 Générer le document'}
          </button>
        </form>
      )}

      {tab === 'generate' && result && (
        <div className={styles.form}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
            <span className={styles.rowTitle}>{result.template}</span>
            <button className={styles.micro} onClick={() => navigator.clipboard?.writeText(result.document)}>📋 Copier</button>
          </div>
          <div style={{ fontSize: 13, color: '#a8a8c0', lineHeight: 1.7, whiteSpace: 'pre-wrap', maxHeight: 400, overflowY: 'auto' }}>
            {result.document}
          </div>
          <p style={{ fontSize: 11, color: '#6b6b80', fontStyle: 'italic', margin: 0 }}>
            ⚠️ Document généré à titre indicatif. À valider par un professionnel du droit.
          </p>
        </div>
      )}

      {tab === 'analyze' && (
        <form className={styles.form} onSubmit={analyze}>
          <textarea className={styles.textarea} placeholder="Collez votre document juridique ici..." value={analyseText}
            onChange={e => setAnalyseText(e.target.value)} rows={6} required />
          <button type="submit" className={styles.btnPrimary} disabled={analyseLoading}>
            {analyseLoading ? 'Analyse...' : '🔍 Analyser'}
          </button>
        </form>
      )}

      {tab === 'analyze' && analyseResult && (
        <div className={styles.form}>
          <div className={styles.rowTitle}>Analyse juridique</div>
          <div style={{ fontSize: 13, color: '#a8a8c0', lineHeight: 1.7, whiteSpace: 'pre-wrap', maxHeight: 400, overflowY: 'auto' }}>
            {analyseResult}
          </div>
        </div>
      )}
    </div>
  )
}

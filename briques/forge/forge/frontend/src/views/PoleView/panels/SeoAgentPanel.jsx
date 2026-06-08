import { useState } from 'react'
import { api } from '../../../services/api'
import styles from './Panel.module.css'

export default function SeoAgentPanel({ poleId }) {
  const [url, setUrl] = useState('')
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [tab, setTab] = useState('analyse')
  const [kwSujet, setKwSujet] = useState('')
  const [keywords, setKeywords] = useState([])
  const [kwLoading, setKwLoading] = useState(false)

  async function analyzeUrl(e) {
    e.preventDefault()
    if (!url.trim()) return
    setLoading(true)
    try {
      const data = await api.post('/api/seo-agent/analyze', { url, poleId })
      setResult(data)
    } finally { setLoading(false) }
  }

  async function findKeywords(e) {
    e.preventDefault()
    if (!kwSujet.trim()) return
    setKwLoading(true)
    try {
      const data = await api.post('/api/seo-agent/keywords', { sujet: kwSujet })
      setKeywords(data.keywords ?? [])
    } finally { setKwLoading(false) }
  }

  return (
    <div className={styles.panel}>
      <div className={styles.toolbar}>
        <div className={styles.filterGroup}>
          <button className={`${styles.filterBtn} ${tab === 'analyse' ? styles.active : ''}`} onClick={() => setTab('analyse')}>🔍 Analyse URL</button>
          <button className={`${styles.filterBtn} ${tab === 'keywords' ? styles.active : ''}`} onClick={() => setTab('keywords')}>🔑 Mots-clés</button>
        </div>
      </div>

      {tab === 'analyse' && (
        <>
          <form className={styles.form} onSubmit={analyzeUrl}>
            <input className={styles.input} type="url" placeholder="https://exemple.com" required value={url}
              onChange={e => setUrl(e.target.value)} />
            <button type="submit" className={styles.btnPrimary} disabled={loading}>
              {loading ? 'Analyse en cours...' : '🔍 Analyser'}
            </button>
          </form>
          {result && (
            <div className={styles.form}>
              <div className={styles.rowTitle}>Résultats pour {result.url}</div>
              <div style={{ fontSize: 13, color: '#a8a8c0', lineHeight: 1.7, whiteSpace: 'pre-wrap' }}>
                {result.analyse}
              </div>
            </div>
          )}
        </>
      )}

      {tab === 'keywords' && (
        <>
          <form className={styles.form} onSubmit={findKeywords}>
            <input className={styles.input} placeholder="Sujet ou secteur (ex: SaaS RH, crypto, fitness...)" required value={kwSujet}
              onChange={e => setKwSujet(e.target.value)} />
            <button type="submit" className={styles.btnPrimary} disabled={kwLoading}>
              {kwLoading ? 'Recherche...' : '🔑 Trouver des mots-clés'}
            </button>
          </form>
          {keywords.length > 0 && (
            <div className={styles.list}>
              {keywords.map((k, i) => (
                <div key={i} className={styles.row}>
                  <div className={styles.rowTitle}>{k.keyword}</div>
                  <div className={styles.rowRight}>
                    <span className={styles.micro}>{k.volume}</span>
                    <span className={styles.micro}>{k.intention}</span>
                    <span className={styles.micro} style={{ color: k.difficulte >= 7 ? '#ef4444' : k.difficulte >= 4 ? '#f59e0b' : '#10b981' }}>
                      diff: {k.difficulte}/10
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}

import { useState, useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../../services/api'
import styles from './Search.module.css'

const CATEGORY_ICONS = { KB: '📚', Conversation: '💬', CRM: '🤝', Incident: '🚨', Contrat: '📄' }

export default function SearchView() {
  const [q, setQ] = useState('')
  const [results, setResults] = useState([])
  const [loading, setLoading] = useState(false)
  const searchTimer = useRef(null)

  const search = useCallback(async (query) => {
    if (!query.trim()) { setResults([]); return }
    setLoading(true)
    try {
      const data = await api.get(`/api/search?q=${encodeURIComponent(query)}`)
      setResults(data.results ?? [])
    } finally { setLoading(false) }
  }, [])

  function handleChange(e) {
    setQ(e.target.value)
    clearTimeout(searchTimer.current)
    searchTimer.current = setTimeout(() => search(e.target.value), 300)
  }

  return (
    <div className={styles.page}>
      <h1 className={styles.title}>🔍 Recherche globale</h1>
      <div className={styles.searchBox}>
        <span className={styles.searchIcon}>🔍</span>
        <input
          className={styles.searchInput}
          placeholder="Rechercher dans KB, CRM, Incidents, Contrats, Conversations..."
          value={q} onChange={handleChange} autoFocus
        />
        {loading && <span className={styles.loader}>...</span>}
      </div>

      {q && results.length === 0 && !loading && (
        <p className={styles.empty}>Aucun résultat pour « {q} »</p>
      )}

      {results.length > 0 && (
        <div className={styles.results}>
          {results.map((r, i) => (
            <div key={`${r.category}-${r.id}-${i}`} className={styles.result}>
              <span className={styles.categoryIcon}>{CATEGORY_ICONS[r.category] ?? '📄'}</span>
              <div className={styles.resultInfo}>
                <div className={styles.resultTitle}>{r.titre}</div>
                {r.entity && <div className={styles.resultSub}>{String(r.entity).slice(0, 120)}</div>}
              </div>
              <span className={styles.categoryBadge}>{r.category}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

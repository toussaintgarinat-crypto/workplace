import { useState, useRef } from 'react'
import { api } from '../services/api.js'

const SECTION_ICONS = {}
const SECTION_LABELS = {}

export default function SearchPanel({ world, moi, onFermer, onNavigate }) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState(null)
  const [loading, setLoading] = useState(false)
  const debounceRef = useRef(null)

  function handleChange(e) {
    const q = e.target.value
    setQuery(q)
    clearTimeout(debounceRef.current)
    if (q.length < 2) { setResults(null); return }
    debounceRef.current = setTimeout(() => rechercher(q), 350)
  }

  async function rechercher(q) {
    setLoading(true)
    const data = await api.get(`/search/?q=${encodeURIComponent(q)}&world_id=${world.id}`)
    setResults(data)
    setLoading(false)
  }

  const hasResults = results && results.total > 0

  return (
    <div className="mairie-panel">
      <div className="mairie-panel-header">
        <div className="mairie-panel-title"><span>🔍</span><h2>Recherche</h2></div>
        <div className="mairie-panel-actions">
          <button className="mairie-btn-close" onClick={onFermer}>✕</button>
        </div>
      </div>

      <div className="search-input-wrapper">
        <span className="search-icon">🔍</span>
        <input
          className="search-input"
          value={query}
          onChange={handleChange}
          placeholder="Rechercher délibérations, arrêtés, agents, tickets..."
          autoFocus
        />
        {loading && <span className="search-spinner">⏳</span>}
      </div>

      <div className="mairie-list">
        {query.length >= 2 && !loading && results?.total === 0 && (
          <div className="mairie-empty">Aucun résultat pour « {query} »</div>
        )}

        {hasResults && Object.entries(results.results).map(([section, items]) => {
          if (!items.length) return null
          return (
            <div key={section} className="search-section">
              <div className="search-section-title">
                {SECTION_ICONS[section]} {SECTION_LABELS[section]}
                <span className="search-section-count">{items.length}</span>
              </div>
              {items.map(item => (
                <div
                  key={item.id}
                  className="search-result-item"
                  onClick={() => onNavigate?.(section, item)}
                >
                  <span className="search-result-label">{item.label}</span>
                  <span className="search-result-meta">
                    {item.date || item.fonction || item.statut || item.citoyen || ''}
                  </span>
                </div>
              ))}
            </div>
          )
        })}
      </div>
    </div>
  )
}

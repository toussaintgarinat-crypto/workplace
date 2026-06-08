import { useState, useEffect, useRef } from 'react'
import { api, authHeaders } from '../services/api.js'
import { formatBytes } from '@workspace/shared-ui/utils'

const BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'
const ACCEPT = '.pdf,.doc,.docx,.txt,.md,.csv,.xlsx,.ppt,.pptx,.png,.jpg,.mp3,.mp4'

export default function DocumentsManager({ moi, worldId }) {
  const [docs, setDocs]           = useState([])
  const [loading, setLoading]     = useState(true)
  const [uploading, setUploading] = useState(false)
  const [selected, setSelected]   = useState(null)
  const [indexing, setIndexing]   = useState(null)
  const [search, setSearch]       = useState('')
  const [searchResults, setSearchResults] = useState(null)
  const [searching, setSearching] = useState(false)
  const fileRef = useRef(null)

  useEffect(() => { fetchDocs() }, [worldId])

  async function fetchDocs() {
    setLoading(true)
    const params = worldId ? `?world_id=${worldId}` : ''
    const data = await api.get(`/documents/${params}`)
    setDocs(Array.isArray(data) ? data : [])
    setLoading(false)
  }

  async function upload(e) {
    const files = Array.from(e.target.files || [])
    if (!files.length) return
    setUploading(true)

    for (const file of files) {
      const form = new FormData()
      form.append('file', file)
      if (worldId) form.append('world_id', worldId)
      form.append('index_memory', 'true')

      try {
        const r = await fetch(`${BASE}/api/documents/upload`, {
          method: 'POST',
          credentials: 'include',
          headers: authHeaders(),
          body: form,
        })
        if (!r.ok) {
          const err = await r.json().catch(() => ({}))
          window.dispatchEvent(new CustomEvent('oria:error', { detail: err.detail || `Erreur upload ${r.status}` }))
        }
      } catch {
        window.dispatchEvent(new CustomEvent('oria:error', { detail: 'Erreur upload' }))
      }
    }

    setUploading(false)
    fetchDocs()
    if (fileRef.current) fileRef.current.value = ''
  }

  async function indexDoc(docId) {
    setIndexing(docId)
    await api.post(`/documents/${docId}/index-memory`, {})
    setIndexing(null)
    fetchDocs()
  }

  async function deleteDoc(docId) {
    if (!confirm('Supprimer ce document ?')) return
    await api.del(`/documents/${docId}`)
    if (selected?.id === docId) setSelected(null)
    fetchDocs()
  }

  async function loadContent(doc) {
    if (selected?.id === doc.id) { setSelected(null); return }
    const data = await api.get(`/documents/${doc.id}/content`)
    setSelected(data)
  }

  async function searchMemory(e) {
    e.preventDefault()
    if (!search.trim()) return
    setSearching(true)
    const data = await api.post('/documents/memory/search', { query: search, limit: 5 })
    setSearchResults(data?.results || [])
    setSearching(false)
  }

  function fileIcon(mime) {
    if (mime?.includes('pdf')) return '📄'
    if (mime?.includes('word') || mime?.includes('docx')) return '📝'
    if (mime?.includes('excel') || mime?.includes('sheet')) return '📊'
    if (mime?.includes('image')) return '🖼'
    if (mime?.includes('audio')) return '🎵'
    if (mime?.includes('video')) return '🎬'
    if (mime?.includes('text')) return '📃'
    return '📎'
  }

  // formatSize remplacé par formatBytes (@workspace/shared-ui/utils) — sprint S98
  const formatSize = (b) => formatBytes(b, { placeholder: '—' })

  return (
    <div className="documents-manager">
      {/* Header */}
      <div className="docs-header">
        <h2>📁 Mes Dossiers</h2>
        <div className="docs-header-actions">
          <button
            className="btn-upload"
            onClick={() => fileRef.current?.click()}
            disabled={uploading}
          >
            {uploading ? '⏳ Import…' : '⬆️ Importer'}
          </button>
          <input
            ref={fileRef}
            type="file"
            multiple
            accept={ACCEPT}
            onChange={upload}
            style={{ display: 'none' }}
          />
        </div>
      </div>

      <p className="docs-info">
        Tes fichiers sont convertis en Markdown et indexés dans ta mémoire MemPalace.
        Tes agents IA peuvent les consulter lors des conversations.
      </p>

      {/* Recherche mémoire */}
      <form className="docs-search" onSubmit={searchMemory}>
        <input
          type="text"
          placeholder="Rechercher dans ta mémoire…"
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
        <button type="submit" disabled={searching}>
          {searching ? '⏳' : '🔍 Chercher'}
        </button>
      </form>

      {searchResults !== null && (
        <div className="docs-search-results">
          <div className="search-results-header">
            <span>Résultats mémoire ({searchResults.length})</span>
            <button onClick={() => setSearchResults(null)}>✕</button>
          </div>
          {searchResults.length === 0 ? (
            <p className="search-empty">Aucun résultat trouvé dans ta mémoire.</p>
          ) : (
            searchResults.map((r, i) => (
              <div key={i} className="search-result-item">
                <div className="sr-source">{r.metadata?.doc_nom || 'Mémoire'}</div>
                <div className="sr-text">{r.text?.slice(0, 300)}…</div>
                <div className="sr-score">Score : {(r.score * 100).toFixed(0)}%</div>
              </div>
            ))
          )}
        </div>
      )}

      {/* Liste docs */}
      <div className="docs-layout">
        <div className="docs-list">
          {loading ? (
            <div className="docs-loading"><div className="spinner"/></div>
          ) : docs.length === 0 ? (
            <div className="docs-empty">
              <span>📂</span>
              <p>Aucun document. Importe des fichiers pour commencer.</p>
              <small>Formats : PDF, Word, Excel, PowerPoint, images, audio…</small>
            </div>
          ) : (
            docs.map(doc => (
              <div
                key={doc.id}
                className={`doc-item ${selected?.id === doc.id ? 'active' : ''}`}
                onClick={() => loadContent(doc)}
              >
                <span className="doc-icon">{fileIcon(doc.type_mime)}</span>
                <div className="doc-info">
                  <div className="doc-nom">{doc.nom}</div>
                  <div className="doc-meta">
                    {formatSize(doc.taille)}
                    {doc.indexe_memory && <span className="doc-indexed">🧠</span>}
                    {doc.has_content && <span className="doc-md">MD</span>}
                  </div>
                </div>
                <div className="doc-actions" onClick={e => e.stopPropagation()}>
                  {!doc.indexe_memory && doc.has_content && (
                    <button
                      className="doc-btn"
                      title="Indexer dans MemPalace"
                      onClick={() => indexDoc(doc.id)}
                      disabled={indexing === doc.id}
                    >
                      {indexing === doc.id ? '⏳' : '🧠'}
                    </button>
                  )}
                  <button
                    className="doc-btn danger"
                    title="Supprimer"
                    onClick={() => deleteDoc(doc.id)}
                  >🗑</button>
                </div>
              </div>
            ))
          )}
        </div>

        {/* Preview contenu MD */}
        {selected && (
          <div className="doc-preview">
            <div className="doc-preview-header">
              <span>{selected.nom}</span>
              <button onClick={() => setSelected(null)}>✕</button>
            </div>
            <div className="doc-preview-content">
              <pre>{selected.content_md || 'Contenu non disponible.'}</pre>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

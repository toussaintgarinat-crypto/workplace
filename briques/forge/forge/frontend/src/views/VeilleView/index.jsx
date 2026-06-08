import { useState, useEffect } from 'react'
import { token } from '../../services/api'
import styles from './Veille.module.css'

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

const TYPE_LABELS = { rss: '📡 RSS', web: '🌐 Web' }

export default function VeilleView() {
  const [sources, setSources]     = useState([])
  const [articles, setArticles]   = useState([])
  const [selected, setSelected]   = useState(null) // selected source
  const [showForm, setShowForm]   = useState(false)
  const [form, setForm]           = useState({ nom: '', url: '', type: 'rss' })
  const [fetching, setFetching]   = useState(null)
  const [loading, setLoading]     = useState(false)

  useEffect(() => { loadSources() }, [])
  useEffect(() => { loadArticles(selected?.id) }, [selected])

  async function loadSources() {
    const data = await req('/api/veille/sources').catch(() => [])
    setSources(data)
  }

  async function loadArticles(sourceId) {
    const data = await req(`/api/veille/articles${sourceId ? `?sourceId=${sourceId}` : ''}`).catch(() => [])
    setArticles(data)
  }

  async function addSource(e) {
    e.preventDefault()
    setLoading(true)
    try {
      const src = await req('/api/veille/sources', { method: 'POST', body: JSON.stringify(form) })
      setSources(prev => [src, ...prev])
      setForm({ nom: '', url: '', type: 'rss' })
      setShowForm(false)
    } finally { setLoading(false) }
  }

  async function deleteSource(id) {
    await req(`/api/veille/sources/${id}`, { method: 'DELETE' })
    setSources(prev => prev.filter(s => s.id !== id))
    if (selected?.id === id) { setSelected(null); setArticles([]) }
  }

  async function fetchSource(src) {
    setFetching(src.id)
    try {
      const { added } = await req(`/api/veille/fetch/${src.id}`, { method: 'POST', body: '{}' })
      await loadArticles(selected?.id)
      alert(`${added} nouvel(s) article(s) importé(s)`)
    } catch (e) {
      alert('Erreur lors du fetch : ' + e.message)
    } finally { setFetching(null) }
  }

  async function markRead(id) {
    await req(`/api/veille/articles/${id}`, { method: 'PATCH', body: JSON.stringify({ lu: true }) })
    setArticles(prev => prev.map(a => a.id === id ? { ...a, lu: true } : a))
  }

  const unread = articles.filter(a => !a.lu).length

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <span className={styles.icon}>🔭</span>
        <div>
          <div className={styles.title}>Veille</div>
          <div className={styles.subtitle}>Sources RSS & actualités concurrentielles</div>
        </div>
        {unread > 0 && <span className={styles.unreadBadge}>{unread} non lu{unread > 1 ? 's' : ''}</span>}
        <button className={styles.btnPrimary} onClick={() => setShowForm(v => !v)} style={{ marginLeft: 'auto' }}>+ Source</button>
      </header>

      {showForm && (
        <form className={styles.form} onSubmit={addSource}>
          <input className={styles.input} placeholder="Nom de la source *" required value={form.nom} onChange={e => setForm(f => ({ ...f, nom: e.target.value }))} />
          <input className={styles.input} placeholder="URL du flux RSS *" required value={form.url} onChange={e => setForm(f => ({ ...f, url: e.target.value }))} />
          <select className={styles.select} value={form.type} onChange={e => setForm(f => ({ ...f, type: e.target.value }))}>
            <option value="rss">📡 RSS</option>
            <option value="web">🌐 Web</option>
          </select>
          <div className={styles.formActions}>
            <button type="submit" className={styles.btnPrimary} disabled={loading}>Ajouter</button>
            <button type="button" className={styles.btnGhost} onClick={() => setShowForm(false)}>Annuler</button>
          </div>
        </form>
      )}

      <div className={styles.layout}>
        {/* Sources */}
        <div className={styles.sourceList}>
          <div className={styles.sectionTitle}>Sources ({sources.length})</div>
          <div
            className={`${styles.sourceItem} ${!selected ? styles.sourceActive : ''}`}
            onClick={() => setSelected(null)}
          >Toutes les sources</div>
          {sources.length === 0 && <div className={styles.empty}>Aucune source configurée.</div>}
          {sources.map(src => (
            <div key={src.id} className={`${styles.sourceItem} ${selected?.id === src.id ? styles.sourceActive : ''}`} onClick={() => setSelected(src)}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div>
                  <div className={styles.sourceName}>{src.nom}</div>
                  <div className={styles.sourceUrl}>{TYPE_LABELS[src.type]} · {src.url.replace(/^https?:\/\//, '').slice(0, 30)}…</div>
                </div>
                <div style={{ display: 'flex', gap: 4 }}>
                  <button className={styles.micro} onClick={e => { e.stopPropagation(); fetchSource(src) }} disabled={fetching === src.id}>
                    {fetching === src.id ? '⟳' : '↻'}
                  </button>
                  <button className={styles.micro} style={{ color: '#ef4444' }} onClick={e => { e.stopPropagation(); deleteSource(src.id) }}>✕</button>
                </div>
              </div>
            </div>
          ))}
        </div>

        {/* Articles */}
        <div className={styles.articleList}>
          <div className={styles.sectionTitle}>
            {selected ? `Articles — ${selected.nom}` : 'Tous les articles'} ({articles.length})
          </div>
          {articles.length === 0 && <div className={styles.empty}>Aucun article.{sources.length > 0 ? ' Cliquez ↻ pour importer.' : ''}</div>}
          {articles.map(a => (
            <div key={a.id} className={`${styles.article} ${a.lu ? styles.articleRead : ''}`}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 }}>
                <a href={a.url} target="_blank" rel="noopener" className={styles.articleTitle} onClick={() => markRead(a.id)}>
                  {!a.lu && <span className={styles.unreadDot} />}
                  {a.titre}
                </a>
                <span className={styles.articleDate}>{a.publishedAt ? new Date(a.publishedAt).toLocaleDateString('fr-FR') : ''}</span>
              </div>
              {a.resume && <div className={styles.articleResume}>{a.resume}</div>}
              {!a.lu && <button className={styles.microLink} onClick={() => markRead(a.id)}>Marquer lu</button>}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

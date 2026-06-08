import { useState, useEffect, useRef, useCallback } from 'react'
import { token } from '../../services/api'
import styles from './KB.module.css'

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

function parseTags(raw) { try { return JSON.parse(raw || '[]') } catch { return [] } }

export default function KBView() {
  const [articles, setArticles] = useState([])
  const [stats, setStats]       = useState(null)
  const [selected, setSelected] = useState(null)
  const [editing, setEditing]   = useState(false)
  const [showNew, setShowNew]   = useState(false)
  const [query, setQuery]       = useState('')
  const [loading, setLoading]   = useState(false)
  const [form, setForm]         = useState({ titre: '', contenu: '', tags: '', isPinned: false })
  const [editForm, setEditForm] = useState(null)
  const searchRef = useRef(null)

  const load = useCallback(async (q = '') => {
    setLoading(true)
    const { articles: list, stats: s } = await req(`/api/kb/articles${q ? `?q=${encodeURIComponent(q)}` : ''}`).catch(() => ({ articles: [], stats: null }))
    setArticles(list ?? [])
    setStats(s)
    setLoading(false)
  }, [])

  useEffect(() => { load() }, [load])

  useEffect(() => {
    const t = setTimeout(() => load(query), 300)
    return () => clearTimeout(t)
  }, [query, load])

  async function create(e) {
    e.preventDefault()
    const tags = form.tags.split(',').map(t => t.trim()).filter(Boolean)
    const a = await req('/api/kb/articles', { method: 'POST', body: JSON.stringify({ ...form, tags }) })
    setArticles(prev => [a, ...prev])
    setSelected(a)
    setShowNew(false)
    setForm({ titre: '', contenu: '', tags: '', isPinned: false })
    load(query)
  }

  async function save() {
    if (!editForm || !selected) return
    const tags = typeof editForm.tags === 'string'
      ? editForm.tags.split(',').map(t => t.trim()).filter(Boolean)
      : editForm.tags
    const a = await req(`/api/kb/articles/${selected.id}`, { method: 'PATCH', body: JSON.stringify({ ...editForm, tags }) })
    setSelected({ ...a, tags: parseTags(a.tags) })
    setArticles(prev => prev.map(x => x.id === a.id ? { ...a, tags: parseTags(a.tags) } : x))
    setEditing(false)
  }

  async function toggle(article, field) {
    const a = await req(`/api/kb/articles/${article.id}`, { method: 'PATCH', body: JSON.stringify({ [field]: !article[field] }) })
    setArticles(prev => prev.map(x => x.id === a.id ? { ...a, tags: parseTags(a.tags) } : x))
    if (selected?.id === a.id) setSelected({ ...a, tags: parseTags(a.tags) })
  }

  async function remove(id) {
    if (!confirm('Supprimer cet article ?')) return
    await req(`/api/kb/articles/${id}`, { method: 'DELETE' })
    setArticles(prev => prev.filter(a => a.id !== id))
    if (selected?.id === id) setSelected(null)
    load(query)
  }

  function startEdit(a) {
    setEditForm({ titre: a.titre, contenu: a.contenu, tags: parseTags(a.tags).join(', '), isPinned: a.isPinned, isPublic: a.isPublic })
    setEditing(true)
  }

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <span className={styles.icon}>📚</span>
        <div>
          <div className={styles.title}>Knowledge Base</div>
          <div className={styles.subtitle}>Wiki interne — procédures, décisions, guides</div>
        </div>
        <div className={styles.headerRight}>
          <input ref={searchRef} className={styles.search} placeholder="Rechercher…" value={query} onChange={e => setQuery(e.target.value)} />
          <button className={styles.btnPrimary} onClick={() => setShowNew(true)}>+ Article</button>
        </div>
      </header>

      {stats && (
        <div className={styles.statsRow}>
          <span className={styles.statChip}>{stats.total} articles</span>
          <span className={styles.statChip} style={{ color: '#10b981' }}>{stats.publics} publics</span>
          <span className={styles.statChip} style={{ color: '#f59e0b' }}>{stats.epingles} épinglés</span>
        </div>
      )}

      {showNew && (
        <form className={styles.newForm} onSubmit={create}>
          <input className={styles.input} placeholder="Titre *" required value={form.titre} onChange={e => setForm(f => ({ ...f, titre: e.target.value }))} />
          <input className={styles.input} placeholder="Tags (virgule séparés)" value={form.tags} onChange={e => setForm(f => ({ ...f, tags: e.target.value }))} />
          <textarea className={styles.textarea} placeholder="Contenu (Markdown)" value={form.contenu} onChange={e => setForm(f => ({ ...f, contenu: e.target.value }))} />
          <label className={styles.checkRow}>
            <input type="checkbox" checked={form.isPinned} onChange={e => setForm(f => ({ ...f, isPinned: e.target.checked }))} />
            Épingler
          </label>
          <div className={styles.formActions}>
            <button type="submit" className={styles.btnPrimary}>Créer</button>
            <button type="button" className={styles.btnGhost} onClick={() => setShowNew(false)}>Annuler</button>
          </div>
        </form>
      )}

      <div className={styles.layout}>
        {/* Liste */}
        <div className={styles.list}>
          {loading && <div className={styles.empty}>Chargement…</div>}
          {!loading && articles.length === 0 && <div className={styles.empty}>{query ? `Aucun résultat pour "${query}"` : 'Aucun article'}</div>}
          {articles.map(a => (
            <div key={a.id} className={`${styles.item} ${selected?.id === a.id ? styles.itemActive : ''}`} onClick={() => { setSelected({ ...a, tags: parseTags(a.tags) }); setEditing(false) }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <span className={styles.itemTitle}>{a.isPinned ? '📌 ' : ''}{a.titre}</span>
                <span style={{ fontSize: 10, color: '#6b6b80' }}>{new Date(a.updatedAt).toLocaleDateString('fr-FR')}</span>
              </div>
              {parseTags(a.tags).length > 0 && (
                <div className={styles.tagsRow}>
                  {parseTags(a.tags).slice(0, 3).map(tag => <span key={tag} className={styles.tag}>{tag}</span>)}
                </div>
              )}
            </div>
          ))}
        </div>

        {/* Détail / Éditeur */}
        {selected && (
          <div className={styles.detail}>
            {editing && editForm ? (
              <div className={styles.editorForm}>
                <input className={styles.input} value={editForm.titre} onChange={e => setEditForm(f => ({ ...f, titre: e.target.value }))} />
                <input className={styles.input} placeholder="Tags" value={editForm.tags} onChange={e => setEditForm(f => ({ ...f, tags: e.target.value }))} />
                <textarea className={styles.textarea} style={{ minHeight: 300 }} value={editForm.contenu} onChange={e => setEditForm(f => ({ ...f, contenu: e.target.value }))} />
                <div className={styles.formActions}>
                  <button className={styles.btnPrimary} onClick={save}>Sauvegarder</button>
                  <button className={styles.btnGhost} onClick={() => setEditing(false)}>Annuler</button>
                </div>
              </div>
            ) : (
              <>
                <div className={styles.detailHeader}>
                  <h2 className={styles.detailTitle}>{selected.isPinned ? '📌 ' : ''}{selected.titre}</h2>
                  <div style={{ display: 'flex', gap: 6 }}>
                    <button className={styles.btnSecondary} onClick={() => startEdit(selected)}>✎ Modifier</button>
                    <button className={styles.micro} onClick={() => toggle(selected, 'isPinned')} title="Épingler">{selected.isPinned ? '📌' : '📍'}</button>
                    <button className={styles.micro} onClick={() => toggle(selected, 'isPublic')} title="Public">{selected.isPublic ? '🌐' : '🔒'}</button>
                    <button className={styles.micro} style={{ color: '#ef4444' }} onClick={() => remove(selected.id)}>✕</button>
                  </div>
                </div>
                {(selected.tags ?? []).length > 0 && (
                  <div className={styles.tagsRow}>
                    {selected.tags.map(tag => <span key={tag} className={styles.tag}>{tag}</span>)}
                  </div>
                )}
                <div className={styles.meta}>
                  {selected.isPublic ? '🌐 Public' : '🔒 Privé'} · Mis à jour le {new Date(selected.updatedAt).toLocaleDateString('fr-FR')}
                </div>
                <div className={styles.content}>{selected.contenu || <em style={{ color: '#6b6b80' }}>Aucun contenu. Cliquez sur Modifier pour ajouter.</em>}</div>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

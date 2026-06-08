import { useState, useEffect, useRef } from 'react'
import { mempalaceApi } from '../../services/api'

const IPCRA = [
  { key: 'input',     label: 'Input',     icon: '📥', color: '#6366f1', desc: 'Captures brutes, idées à traiter' },
  { key: 'projet',    label: 'Projet',    icon: '🎯', color: '#10b981', desc: 'Projets actifs avec un objectif' },
  { key: 'casquette', label: 'Casquette', icon: '🎩', color: '#f59e0b', desc: 'Rôles et responsabilités portés' },
  { key: 'ressource', label: 'Ressource', icon: '📚', color: '#3b82f6', desc: 'Références et connaissances réutilisables' },
  { key: 'archive',   label: 'Archive',   icon: '🗄️', color: '#6b7280', desc: 'Éléments terminés ou inactifs' },
]

export default function MemPalaceView() {
  const [mpToken, setMpToken]         = useState(() => localStorage.getItem('mp_token'))
  const [taxonomy, setTaxonomy]       = useState({})
  const [totalCount, setTotalCount]   = useState(0)
  const [activeWing, setActiveWing]   = useState('input')
  const [drawers, setDrawers]         = useState([])
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState(null)
  const [newContent, setNewContent]   = useState('')
  const [newRoom, setNewRoom]         = useState('general')
  const [loading, setLoading]         = useState(false)
  const [loginForm, setLoginForm]     = useState({ username: '', password: '' })
  const [loginError, setLoginError]   = useState('')
  const debounceRef                   = useRef(null)

  useEffect(() => {
    if (!mpToken) return
    Promise.all([mempalaceApi.status(), mempalaceApi.taxonomy()])
      .then(([s, t]) => {
        if (!s) { handleDisconnect(); return }
        setTotalCount(s.total || 0)
        setTaxonomy(t || {})
      })
      .catch(() => handleDisconnect())
  }, [mpToken])

  useEffect(() => {
    if (!mpToken) return
    setSearchResults(null)
    setSearchQuery('')
    loadDrawers(activeWing)
  }, [activeWing, mpToken])

  async function loadDrawers(wing) {
    setLoading(true)
    const res = await mempalaceApi.drawers(wing)
    setLoading(false)
    setDrawers(Array.isArray(res) ? res : [])
  }

  function onSearchChange(e) {
    const q = e.target.value
    setSearchQuery(q)
    clearTimeout(debounceRef.current)
    if (!q.trim()) { setSearchResults(null); return }
    debounceRef.current = setTimeout(async () => {
      const res = await mempalaceApi.search(q, activeWing, 10)
      setSearchResults(res?.results || [])
    }, 300)
  }

  async function handleAddDrawer() {
    if (!newContent.trim()) return
    const res = await mempalaceApi.addDrawer(newContent, activeWing, newRoom || 'general')
    if (res) {
      setNewContent('')
      await loadDrawers(activeWing)
      const t = await mempalaceApi.taxonomy()
      if (t) setTaxonomy(t)
    }
  }

  async function handleDeleteDrawer(id) {
    if (!id) return
    await mempalaceApi.deleteDrawer(id)
    loadDrawers(activeWing)
  }

  async function handleLogin() {
    setLoginError('')
    const res = await mempalaceApi.login(loginForm.username, loginForm.password)
    if (res?.access_token) {
      localStorage.setItem('mp_token', res.access_token)
      setMpToken(res.access_token)
    } else {
      setLoginError('Identifiants incorrects')
    }
  }

  function handleDisconnect() {
    localStorage.removeItem('mp_token')
    setMpToken(null)
    setTaxonomy({})
    setDrawers([])
    setTotalCount(0)
  }

  function wingCount(key) {
    const rooms = taxonomy[key]
    if (!rooms) return 0
    return Object.values(rooms).reduce((a, b) => a + b, 0)
  }

  function getItemId(item) {
    return item.id || item.metadata?.id
  }

  const activeCat  = IPCRA.find(c => c.key === activeWing)
  const displayList = searchResults ?? drawers

  // ── Login screen ────────────────────────────────────────────
  if (!mpToken) {
    return (
      <div style={s.page}>
        <div style={s.connectCard}>
          <div style={s.connectIcon}>🧠</div>
          <h2 style={s.connectTitle}>MemPalace</h2>
          <p style={s.connectSub}>Connectez-vous à votre palace pour accéder à votre mémoire IPCRA</p>
          <input
            style={s.input}
            type="text"
            placeholder="Nom d'utilisateur"
            value={loginForm.username}
            onChange={e => setLoginForm(f => ({ ...f, username: e.target.value }))}
            onKeyDown={e => e.key === 'Enter' && handleLogin()}
          />
          <input
            style={s.input}
            type="password"
            placeholder="Mot de passe"
            value={loginForm.password}
            onChange={e => setLoginForm(f => ({ ...f, password: e.target.value }))}
            onKeyDown={e => e.key === 'Enter' && handleLogin()}
          />
          {loginError && <p style={s.error}>{loginError}</p>}
          <button style={s.loginBtn} onClick={handleLogin}>Se connecter</button>
          <p style={s.connectHint}>
            Palace : <code>{localStorage.getItem('mp_url') || 'http://localhost:8100'}</code>
          </p>
        </div>
      </div>
    )
  }

  // ── Main view ────────────────────────────────────────────────
  return (
    <div style={s.page}>

      {/* Header */}
      <div style={s.header}>
        <div style={s.headerLeft}>
          <span style={s.headerIcon}>🧠</span>
          <h1 style={s.headerTitle}>MemPalace</h1>
          <span style={s.badge}>{totalCount} drawers</span>
        </div>
        <button style={s.disconnectBtn} onClick={handleDisconnect}>Déconnecter</button>
      </div>

      {/* Search */}
      <div style={s.searchRow}>
        <input
          style={s.searchInput}
          type="text"
          placeholder={`Recherche sémantique dans ${activeCat?.label}…`}
          value={searchQuery}
          onChange={onSearchChange}
        />
        {searchResults && (
          <button style={s.clearBtn} onClick={() => { setSearchResults(null); setSearchQuery('') }}>✕</button>
        )}
      </div>

      {/* IPCRA tabs */}
      <div style={s.tabs}>
        {IPCRA.map(cat => {
          const cnt    = wingCount(cat.key)
          const active = activeWing === cat.key
          return (
            <button
              key={cat.key}
              style={{
                ...s.tab,
                ...(active ? { borderBottomColor: cat.color, color: cat.color, fontWeight: 700 } : {}),
              }}
              onClick={() => setActiveWing(cat.key)}
            >
              {cat.icon} {cat.label}
              {cnt > 0 && (
                <span style={{ ...s.tabBadge, background: active ? cat.color : 'var(--bg)' }}>
                  {cnt}
                </span>
              )}
            </button>
          )
        })}
      </div>

      {/* Category hint */}
      <div style={{ ...s.catHint, borderLeftColor: activeCat?.color }}>
        {activeCat?.desc}
      </div>

      {/* Add drawer */}
      <div style={s.addBox}>
        <textarea
          style={s.addTextarea}
          placeholder={`Ajouter dans ${activeCat?.label}… (Cmd+Entrée pour valider)`}
          value={newContent}
          onChange={e => setNewContent(e.target.value)}
          rows={3}
          onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleAddDrawer() }}
        />
        <div style={s.addControls}>
          <input
            style={s.roomInput}
            type="text"
            placeholder="Salle (ex: idees)"
            value={newRoom}
            onChange={e => setNewRoom(e.target.value)}
          />
          <button
            style={{ ...s.addBtn, background: activeCat?.color, opacity: newContent.trim() ? 1 : 0.4 }}
            onClick={handleAddDrawer}
            disabled={!newContent.trim()}
          >
            + Ajouter
          </button>
        </div>
      </div>

      {/* Drawer list */}
      <div style={s.list}>
        {loading && <div style={s.empty}>Chargement…</div>}
        {!loading && displayList.length === 0 && (
          <div style={s.empty}>
            {searchResults !== null ? 'Aucun résultat' : `Aucun drawer dans ${activeCat?.label}`}
          </div>
        )}
        {!loading && displayList.map((item, i) => {
          const id = getItemId(item)
          return (
            <div key={id || i} style={s.card}>
              <div style={s.cardTop}>
                <div style={s.chips}>
                  {item.metadata?.room && item.metadata.room !== 'general' && (
                    <span style={s.chip}>{item.metadata.room}</span>
                  )}
                  {item.score !== undefined && (
                    <span style={{ ...s.chip, background: '#10b981', color: '#fff' }}>
                      {Math.round(item.score * 100)}%
                    </span>
                  )}
                  {item.metadata?.added_at && (
                    <span style={s.chipDate}>
                      {new Date(item.metadata.added_at).toLocaleDateString('fr-FR')}
                    </span>
                  )}
                </div>
                {id && (
                  <button style={s.deleteBtn} onClick={() => handleDeleteDrawer(id)} title="Supprimer">✕</button>
                )}
              </div>
              <p style={s.cardContent}>{item.content}</p>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Styles (inline — cohérents avec les CSS variables Forge) ──
const s = {
  page: {
    flex: 1,
    overflowY: 'auto',
    padding: '28px 32px',
    background: 'var(--bg)',
    color: 'var(--text)',
    display: 'flex',
    flexDirection: 'column',
    gap: '16px',
    maxWidth: '860px',
    margin: '0 auto',
    width: '100%',
    boxSizing: 'border-box',
  },
  connectCard: {
    background: 'var(--bg-panel)',
    border: '1px solid var(--border)',
    borderRadius: '14px',
    padding: '40px',
    maxWidth: '400px',
    margin: '80px auto 0',
    display: 'flex',
    flexDirection: 'column',
    gap: '12px',
    alignItems: 'center',
  },
  connectIcon: { fontSize: '48px' },
  connectTitle: { margin: 0, fontSize: '22px', fontWeight: 700 },
  connectSub: { margin: 0, color: 'var(--text-muted)', fontSize: '14px', textAlign: 'center', lineHeight: 1.5 },
  input: {
    width: '100%',
    padding: '10px 12px',
    background: 'var(--bg)',
    border: '1px solid var(--border)',
    borderRadius: '8px',
    color: 'var(--text)',
    fontSize: '14px',
    boxSizing: 'border-box',
    outline: 'none',
  },
  error: { color: '#ef4444', fontSize: '13px', margin: 0 },
  loginBtn: {
    width: '100%',
    padding: '10px',
    background: '#6366f1',
    color: '#fff',
    border: 'none',
    borderRadius: '8px',
    cursor: 'pointer',
    fontSize: '14px',
    fontWeight: 600,
  },
  connectHint: { fontSize: '12px', color: 'var(--text-muted)', margin: 0 },
  header: { display: 'flex', alignItems: 'center', justifyContent: 'space-between' },
  headerLeft: { display: 'flex', alignItems: 'center', gap: '10px' },
  headerIcon: { fontSize: '28px' },
  headerTitle: { margin: 0, fontSize: '22px', fontWeight: 700 },
  badge: {
    background: 'var(--bg-panel)',
    border: '1px solid var(--border)',
    borderRadius: '20px',
    padding: '2px 10px',
    fontSize: '12px',
    color: 'var(--text-muted)',
  },
  disconnectBtn: {
    padding: '6px 12px',
    background: 'transparent',
    border: '1px solid var(--border)',
    borderRadius: '6px',
    color: 'var(--text-muted)',
    cursor: 'pointer',
    fontSize: '12px',
  },
  searchRow: { display: 'flex', gap: '8px', alignItems: 'center' },
  searchInput: {
    flex: 1,
    padding: '10px 14px',
    background: 'var(--bg-panel)',
    border: '1px solid var(--border)',
    borderRadius: '8px',
    color: 'var(--text)',
    fontSize: '14px',
    outline: 'none',
  },
  clearBtn: {
    padding: '8px 12px',
    background: 'transparent',
    border: '1px solid var(--border)',
    borderRadius: '8px',
    color: 'var(--text-muted)',
    cursor: 'pointer',
  },
  tabs: {
    display: 'flex',
    gap: '2px',
    borderBottom: '1px solid var(--border)',
  },
  tab: {
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
    padding: '9px 14px',
    background: 'transparent',
    border: 'none',
    borderBottom: '2px solid transparent',
    color: 'var(--text-muted)',
    cursor: 'pointer',
    fontSize: '13px',
    fontWeight: 500,
    transition: 'color 0.15s',
    marginBottom: '-1px',
  },
  tabBadge: {
    borderRadius: '10px',
    padding: '1px 7px',
    fontSize: '11px',
    color: '#fff',
    border: '1px solid var(--border)',
  },
  catHint: {
    padding: '8px 12px',
    borderLeft: '3px solid var(--border)',
    color: 'var(--text-muted)',
    fontSize: '13px',
    background: 'var(--bg-panel)',
    borderRadius: '0 6px 6px 0',
    lineHeight: 1.5,
  },
  addBox: {
    display: 'flex',
    flexDirection: 'column',
    gap: '8px',
    background: 'var(--bg-panel)',
    border: '1px solid var(--border)',
    borderRadius: '10px',
    padding: '14px',
  },
  addTextarea: {
    width: '100%',
    padding: '10px',
    background: 'var(--bg)',
    border: '1px solid var(--border)',
    borderRadius: '8px',
    color: 'var(--text)',
    fontSize: '14px',
    resize: 'vertical',
    fontFamily: 'inherit',
    boxSizing: 'border-box',
    outline: 'none',
    lineHeight: 1.5,
  },
  addControls: { display: 'flex', gap: '8px', alignItems: 'center' },
  roomInput: {
    flex: 1,
    padding: '8px 12px',
    background: 'var(--bg)',
    border: '1px solid var(--border)',
    borderRadius: '6px',
    color: 'var(--text)',
    fontSize: '13px',
    outline: 'none',
  },
  addBtn: {
    padding: '8px 18px',
    border: 'none',
    borderRadius: '6px',
    color: '#fff',
    cursor: 'pointer',
    fontSize: '13px',
    fontWeight: 600,
  },
  list: { display: 'flex', flexDirection: 'column', gap: '10px' },
  empty: { color: 'var(--text-muted)', fontSize: '14px', padding: '24px 0', textAlign: 'center' },
  card: {
    background: 'var(--bg-panel)',
    border: '1px solid var(--border)',
    borderRadius: '8px',
    padding: '14px',
  },
  cardTop: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: '8px',
  },
  chips: { display: 'flex', gap: '6px', alignItems: 'center', flexWrap: 'wrap' },
  chip: {
    background: 'var(--bg)',
    border: '1px solid var(--border)',
    borderRadius: '4px',
    padding: '1px 7px',
    fontSize: '11px',
    color: 'var(--text-muted)',
  },
  chipDate: { fontSize: '11px', color: 'var(--text-muted)' },
  deleteBtn: {
    background: 'transparent',
    border: 'none',
    color: 'var(--text-muted)',
    cursor: 'pointer',
    fontSize: '12px',
    padding: '3px 7px',
    borderRadius: '4px',
  },
  cardContent: {
    margin: 0,
    fontSize: '14px',
    color: 'var(--text)',
    lineHeight: 1.6,
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-word',
    overflow: 'hidden',
    display: '-webkit-box',
    WebkitLineClamp: 6,
    WebkitBoxOrient: 'vertical',
  },
}

import { useState, useEffect } from 'react'
import { token } from '../../../services/api'
import styles from './Panel.module.css'

const DOZZLE_URL = import.meta.env.VITE_DOZZLE_URL || 'http://localhost:9998'

async function req(path, opts = {}) {
  const t = token.get()
  const res = await fetch(path, {
    ...opts,
    headers: { 'Content-Type': 'application/json', ...(t ? { Authorization: `Bearer ${t}` } : {}), ...opts.headers },
  })
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || 'Erreur')
  return res.json()
}

const COLUMNS = [
  { key: 'backlog',   label: 'Backlog',   color: '#4b5563' },
  { key: 'todo',      label: 'Todo',      color: '#6366f1' },
  { key: 'en_cours',  label: 'En cours',  color: '#f59e0b' },
  { key: 'review',    label: 'Review',    color: '#3b82f6' },
  { key: 'done',      label: 'Done',      color: '#10b981' },
]

const PRIORITE_COLORS = { haute: '#ef4444', normale: '#6366f1', basse: '#6b7280' }
const TYPE_LABELS = { bug: '🐛', feature: '✨', chore: '🔧', doc: '📄', refactor: '♻️' }

const EMPTY_FORM = { titre: '', description: '', type: 'feature', priorite: 'normale', assigneA: '' }

export default function DevTeamPanel({ poleId }) {
  const [tasks, setTasks]   = useState([])
  const [form, setForm]     = useState(EMPTY_FORM)
  const [showForm, setShow] = useState(false)
  const [loading, setLoad]  = useState(false)
  const [error, setError]   = useState(null)

  useEffect(() => { load() }, [poleId])

  async function load() {
    try {
      const data = await req('/api/dev-team')
      setTasks(data.filter(t => !poleId || t.poleId === poleId || !t.poleId))
    } catch (e) { setError(e.message) }
  }

  async function create(e) {
    e.preventDefault()
    if (!form.titre.trim()) return
    setLoad(true)
    try {
      const task = await req('/api/dev-team', {
        method: 'POST',
        body: JSON.stringify({ ...form, poleId, statut: 'backlog' }),
      })
      setTasks(prev => [task, ...prev])
      setForm(EMPTY_FORM)
      setShow(false)
    } catch (e) { setError(e.message) }
    finally { setLoad(false) }
  }

  async function moveTask(id, newStatut) {
    try {
      const updated = await req(`/api/dev-team/${id}`, {
        method: 'PATCH',
        body: JSON.stringify({ statut: newStatut }),
      })
      setTasks(prev => prev.map(t => t.id === id ? updated : t))
    } catch (e) { setError(e.message) }
  }

  async function deleteTask(id) {
    try {
      await req(`/api/dev-team/${id}`, { method: 'DELETE' })
      setTasks(prev => prev.filter(t => t.id !== id))
    } catch (e) { setError(e.message) }
  }

  const byStatut = Object.fromEntries(COLUMNS.map(c => [c.key, tasks.filter(t => t.statut === c.key)]))
  const colIdx = (key) => COLUMNS.findIndex(c => c.key === key)

  return (
    <div className={styles.panel}>
      <div className={styles.toolbar}>
        <button className={styles.btnPrimary} onClick={() => setShow(v => !v)}>
          {showForm ? '✕ Annuler' : '+ Nouvelle tâche'}
        </button>
        <span style={{ color: '#6b6b80', fontSize: 12 }}>{tasks.length} tâche{tasks.length !== 1 ? 's' : ''}</span>
        <button
          onClick={() => window.open(DOZZLE_URL, '_blank')}
          title="Logs containers (Dozzle)"
          style={{ marginLeft: 'auto', background: '#1e1e3a', border: '1px solid #2a2a3e', borderRadius: 6, color: '#a0a0c0', cursor: 'pointer', padding: '4px 10px', fontSize: 13 }}
        >🪵 Logs</button>
      </div>

      {error && <div style={{ color: '#ef4444', fontSize: 13 }}>{error}</div>}

      {showForm && (
        <form onSubmit={create} style={s.form}>
          <input
            style={s.input} placeholder="Titre de la tâche *" required
            value={form.titre} onChange={e => setForm(f => ({ ...f, titre: e.target.value }))}
          />
          <div style={{ display: 'flex', gap: 8 }}>
            <select style={s.select} value={form.type} onChange={e => setForm(f => ({ ...f, type: e.target.value }))}>
              {Object.entries(TYPE_LABELS).map(([k, v]) => <option key={k} value={k}>{v} {k}</option>)}
            </select>
            <select style={s.select} value={form.priorite} onChange={e => setForm(f => ({ ...f, priorite: e.target.value }))}>
              <option value="haute">🔴 Haute</option>
              <option value="normale">🔵 Normale</option>
              <option value="basse">⚫ Basse</option>
            </select>
            <input
              style={{ ...s.input, flex: 1 }} placeholder="Assigné à"
              value={form.assigneA} onChange={e => setForm(f => ({ ...f, assigneA: e.target.value }))}
            />
          </div>
          <textarea
            style={{ ...s.input, resize: 'vertical', minHeight: 60 }} placeholder="Description (optionnel)"
            value={form.description} onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
          />
          <button type="submit" style={s.btnSubmit} disabled={loading}>
            {loading ? '…' : 'Créer'}
          </button>
        </form>
      )}

      <div style={s.board}>
        {COLUMNS.map(col => (
          <div key={col.key} style={s.column}>
            <div style={s.colHeader}>
              <span style={{ ...s.colDot, background: col.color }} />
              <span style={s.colLabel}>{col.label}</span>
              <span style={s.colCount}>{byStatut[col.key].length}</span>
            </div>
            <div style={s.cardList}>
              {byStatut[col.key].map(task => (
                <div key={task.id} style={s.card}>
                  <div style={s.cardTop}>
                    <span style={s.typeIcon}>{TYPE_LABELS[task.type] || '📌'}</span>
                    <span style={{ ...s.badge, background: PRIORITE_COLORS[task.priorite] }}>
                      {task.priorite}
                    </span>
                  </div>
                  <div style={s.cardTitle}>{task.titre}</div>
                  {task.assigneA && <div style={s.assignee}>👤 {task.assigneA}</div>}
                  <div style={s.actions}>
                    {colIdx(task.statut) > 0 && (
                      <button style={s.moveBtn} title="Reculer"
                        onClick={() => moveTask(task.id, COLUMNS[colIdx(task.statut) - 1].key)}>
                        ←
                      </button>
                    )}
                    {colIdx(task.statut) < COLUMNS.length - 1 && (
                      <button style={s.moveBtn} title="Avancer"
                        onClick={() => moveTask(task.id, COLUMNS[colIdx(task.statut) + 1].key)}>
                        →
                      </button>
                    )}
                    <button style={{ ...s.moveBtn, color: '#ef4444', marginLeft: 'auto' }}
                      title="Supprimer" onClick={() => deleteTask(task.id)}>
                      🗑
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

const s = {
  form: {
    display: 'flex', flexDirection: 'column', gap: 8,
    background: '#13132b', border: '1px solid #2a2a3e',
    borderRadius: 10, padding: 16,
  },
  input: {
    background: '#0e0e22', border: '1px solid #2a2a3e', borderRadius: 6,
    color: '#e0e0ff', padding: '8px 12px', fontSize: 13, width: '100%', boxSizing: 'border-box',
  },
  select: {
    background: '#0e0e22', border: '1px solid #2a2a3e', borderRadius: 6,
    color: '#e0e0ff', padding: '8px 10px', fontSize: 13,
  },
  btnSubmit: {
    background: '#6366f1', color: '#fff', border: 'none', borderRadius: 6,
    padding: '8px 20px', cursor: 'pointer', fontWeight: 600, alignSelf: 'flex-end',
  },
  board: {
    display: 'grid',
    gridTemplateColumns: 'repeat(5, 1fr)',
    gap: 12, overflowX: 'auto',
  },
  column: {
    background: '#0e0e22', border: '1px solid #1e1e3a',
    borderRadius: 10, padding: 12, minWidth: 160,
    display: 'flex', flexDirection: 'column', gap: 8,
  },
  colHeader: {
    display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4,
  },
  colDot: { width: 8, height: 8, borderRadius: '50%', flexShrink: 0 },
  colLabel: { fontWeight: 600, fontSize: 13, color: '#e0e0ff' },
  colCount: {
    marginLeft: 'auto', background: '#1e1e3a', borderRadius: 10,
    padding: '1px 7px', fontSize: 11, color: '#6b6b80',
  },
  cardList: { display: 'flex', flexDirection: 'column', gap: 8 },
  card: {
    background: '#13132b', border: '1px solid #2a2a3e',
    borderRadius: 8, padding: '10px 12px',
    display: 'flex', flexDirection: 'column', gap: 6,
  },
  cardTop: { display: 'flex', alignItems: 'center', gap: 6 },
  typeIcon: { fontSize: 14 },
  badge: {
    fontSize: 10, padding: '2px 6px', borderRadius: 4,
    color: '#fff', fontWeight: 600, textTransform: 'uppercase',
  },
  cardTitle: { fontSize: 13, color: '#e0e0ff', lineHeight: 1.4 },
  assignee: { fontSize: 11, color: '#6b6b80' },
  actions: { display: 'flex', gap: 4, marginTop: 2 },
  moveBtn: {
    background: '#1e1e3a', border: '1px solid #2a2a3e', borderRadius: 4,
    color: '#a0a0c0', cursor: 'pointer', padding: '2px 8px', fontSize: 13,
  },
}

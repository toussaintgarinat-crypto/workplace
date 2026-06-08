import { useState, useEffect } from 'react'
import { api } from '../../services/api'
import styles from './DevTeam.module.css'

const COLONNES = [
  { key: 'backlog', label: '📋 Backlog' },
  { key: 'todo', label: '📌 À faire' },
  { key: 'en_cours', label: '⚡ En cours' },
  { key: 'review', label: '🔍 Review' },
  { key: 'done', label: '✅ Done' },
]
const TYPES = ['bug', 'feature', 'chore', 'doc', 'refactor']
const PRIOS = ['haute', 'normale', 'basse']
const TYPE_COLORS = { bug: '#ef4444', feature: '#10b981', chore: '#6b6b80', doc: '#3b82f6', refactor: '#f59e0b' }

export default function DevTeamView() {
  const [tasks, setTasks] = useState([])
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState({ titre: '', description: '', type: 'feature', priorite: 'normale', statut: 'backlog', assigneA: '' })
  const [saving, setSaving] = useState(false)
  const [filter, setFilter] = useState('')

  useEffect(() => { loadTasks() }, [])

  async function loadTasks() {
    const rows = await api.get('/api/dev-team').catch(() => [])
    setTasks(Array.isArray(rows) ? rows : [])
  }

  async function submit(e) {
    e.preventDefault()
    setSaving(true)
    try {
      await api.post('/api/dev-team', form)
      await loadTasks()
      setForm({ titre: '', description: '', type: 'feature', priorite: 'normale', statut: 'backlog', assigneA: '' })
      setShowForm(false)
    } finally { setSaving(false) }
  }

  async function moveTask(id, statut) {
    await api.patch(`/api/dev-team/${id}`, { statut })
    setTasks(ts => ts.map(t => t.id === id ? { ...t, statut } : t))
  }

  async function deleteTask(id) {
    await api.delete(`/api/dev-team/${id}`)
    setTasks(ts => ts.filter(t => t.id !== id))
  }

  const filtered = filter ? tasks.filter(t => t.type === filter) : tasks

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <h1 className={styles.title}>💻 Dev Team Kanban</h1>
        <div className={styles.actions}>
          <div className={styles.filterGroup}>
            <button className={`${styles.filterBtn} ${filter === '' ? styles.active : ''}`} onClick={() => setFilter('')}>Tous</button>
            {TYPES.map(t => (
              <button key={t} className={`${styles.filterBtn} ${filter === t ? styles.active : ''}`} onClick={() => setFilter(t)}
                style={{ '--col': TYPE_COLORS[t] }}>
                {t}
              </button>
            ))}
          </div>
          <button className={styles.btnPrimary} onClick={() => setShowForm(v => !v)}>+ Tâche</button>
        </div>
      </div>

      {showForm && (
        <form className={styles.form} onSubmit={submit}>
          <div className={styles.formRow}>
            <input className={styles.input} placeholder="Titre de la tâche *" required value={form.titre}
              onChange={e => setForm(f => ({ ...f, titre: e.target.value }))} />
            <select className={styles.select} value={form.type} onChange={e => setForm(f => ({ ...f, type: e.target.value }))}>
              {TYPES.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
            <select className={styles.select} value={form.priorite} onChange={e => setForm(f => ({ ...f, priorite: e.target.value }))}>
              {PRIOS.map(p => <option key={p} value={p}>{p}</option>)}
            </select>
            <select className={styles.select} value={form.statut} onChange={e => setForm(f => ({ ...f, statut: e.target.value }))}>
              {COLONNES.map(c => <option key={c.key} value={c.key}>{c.label}</option>)}
            </select>
          </div>
          <input className={styles.input} placeholder="Assigné à (optionnel)" value={form.assigneA}
            onChange={e => setForm(f => ({ ...f, assigneA: e.target.value }))} />
          <textarea className={styles.textarea} placeholder="Description..." rows={2} value={form.description}
            onChange={e => setForm(f => ({ ...f, description: e.target.value }))} />
          <div className={styles.formActions}>
            <button type="submit" className={styles.btnPrimary} disabled={saving}>{saving ? '...' : 'Créer'}</button>
            <button type="button" className={styles.btnGhost} onClick={() => setShowForm(false)}>Annuler</button>
          </div>
        </form>
      )}

      <div className={styles.kanban}>
        {COLONNES.map(col => {
          const colTasks = filtered.filter(t => t.statut === col.key)
          return (
            <div key={col.key} className={styles.column}>
              <div className={styles.colHeader}>
                {col.label}
                <span className={styles.badge}>{colTasks.length}</span>
              </div>
              {colTasks.map(task => (
                <div key={task.id} className={styles.card}>
                  <div className={styles.cardTop}>
                    <span className={styles.typeBadge} style={{ background: TYPE_COLORS[task.type] + '22', color: TYPE_COLORS[task.type] }}>
                      {task.type}
                    </span>
                    <span className={styles.prioBadge} style={{ color: task.priorite === 'haute' ? '#ef4444' : task.priorite === 'normale' ? '#f59e0b' : '#6b6b80' }}>
                      {task.priorite === 'haute' ? '🔴' : task.priorite === 'normale' ? '🟡' : '🟢'}
                    </span>
                  </div>
                  <div className={styles.cardTitle}>{task.titre}</div>
                  {task.assigneA && <div className={styles.cardAssignee}>👤 {task.assigneA}</div>}
                  <div className={styles.cardActions}>
                    {COLONNES.filter(c => c.key !== col.key).slice(0, 2).map(target => (
                      <button key={target.key} className={styles.moveBtn} onClick={() => moveTask(task.id, target.key)}>
                        → {target.label.split(' ')[1]}
                      </button>
                    ))}
                    <button className={styles.deleteBtn} onClick={() => deleteTask(task.id)}>✕</button>
                  </div>
                </div>
              ))}
              {colTasks.length === 0 && <p className={styles.colEmpty}>—</p>}
            </div>
          )
        })}
      </div>
    </div>
  )
}

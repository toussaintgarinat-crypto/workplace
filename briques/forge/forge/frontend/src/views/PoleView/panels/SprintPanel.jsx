import { useState, useEffect } from 'react'
import { token } from '../../../services/api'
import styles from './Panel.module.css'

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

const STATUT_COLORS = { todo: '#4b5563', en_cours: '#f59e0b', done: '#10b981' }
const PRIORITE_COLORS = { haute: '#ef4444', normale: '#6366f1', basse: '#6b7280' }

export default function SprintPanel({ poleId }) {
  const [sprints, setSprints]   = useState([])
  const [tasks, setTasks]       = useState([])
  const [activeSprint, setActive] = useState(null)
  const [form, setForm]         = useState({ nom: '', objectif: '' })
  const [taskForm, setTaskForm] = useState({ titre: '', priorite: 'normale' })
  const [showSprint, setShowSprint] = useState(false)
  const [showTask, setShowTask]     = useState(false)
  const [loading, setLoading]       = useState(false)

  useEffect(() => {
    req(`/api/poles/${poleId}/sprints`).then(data => {
      setSprints(data)
      if (data.length > 0 && !activeSprint) setActive(data[0].id)
    }).catch(() => {})
  }, [poleId])

  useEffect(() => {
    if (!activeSprint) return
    req(`/api/poles/${poleId}/tasks?sprintId=${activeSprint}`).then(setTasks).catch(() => {})
  }, [activeSprint, poleId])

  async function createSprint(e) {
    e.preventDefault()
    setLoading(true)
    try {
      const s = await req(`/api/poles/${poleId}/sprints`, { method: 'POST', body: JSON.stringify(form) })
      setSprints(prev => [s, ...prev])
      setActive(s.id)
      setForm({ nom: '', objectif: '' })
      setShowSprint(false)
    } finally { setLoading(false) }
  }

  async function createTask(e) {
    e.preventDefault()
    if (!activeSprint) return
    setLoading(true)
    try {
      const t = await req(`/api/poles/${poleId}/tasks`, {
        method: 'POST',
        body: JSON.stringify({ ...taskForm, sprintId: activeSprint })
      })
      setTasks(prev => [t, ...prev])
      setTaskForm({ titre: '', priorite: 'normale' })
      setShowTask(false)
    } finally { setLoading(false) }
  }

  async function updateTask(id, updates) {
    const t = await req(`/api/tasks/${id}`, { method: 'PATCH', body: JSON.stringify(updates) })
    setTasks(prev => prev.map(x => x.id === id ? t : x))
  }

  async function deleteTask(id) {
    await req(`/api/tasks/${id}`, { method: 'DELETE' })
    setTasks(prev => prev.filter(x => x.id !== id))
  }

  const currentSprint = sprints.find(s => s.id === activeSprint)
  const todo   = tasks.filter(t => t.statut === 'todo')
  const enCours = tasks.filter(t => t.statut === 'en_cours')
  const done   = tasks.filter(t => t.statut === 'done')

  return (
    <div className={styles.panel}>
      {/* Sprint selector */}
      <div className={styles.toolbar}>
        <select className={styles.select} value={activeSprint || ''} onChange={e => setActive(e.target.value)}>
          {sprints.length === 0 && <option value="">Aucun sprint</option>}
          {sprints.map(s => <option key={s.id} value={s.id}>{s.nom} ({s.statut})</option>)}
        </select>
        <button className={styles.btnPrimary} onClick={() => setShowSprint(true)}>+ Sprint</button>
        {activeSprint && <button className={styles.btnSecondary} onClick={() => setShowTask(true)}>+ Tâche</button>}
      </div>

      {/* Sprint form */}
      {showSprint && (
        <form className={styles.form} onSubmit={createSprint}>
          <input className={styles.input} placeholder="Nom du sprint" required value={form.nom}
            onChange={e => setForm(f => ({ ...f, nom: e.target.value }))} />
          <input className={styles.input} placeholder="Objectif (optionnel)" value={form.objectif}
            onChange={e => setForm(f => ({ ...f, objectif: e.target.value }))} />
          <div className={styles.formActions}>
            <button type="submit" className={styles.btnPrimary} disabled={loading}>Créer</button>
            <button type="button" className={styles.btnGhost} onClick={() => setShowSprint(false)}>Annuler</button>
          </div>
        </form>
      )}

      {/* Task form */}
      {showTask && (
        <form className={styles.form} onSubmit={createTask}>
          <input className={styles.input} placeholder="Titre de la tâche" required value={taskForm.titre}
            onChange={e => setTaskForm(f => ({ ...f, titre: e.target.value }))} />
          <select className={styles.select} value={taskForm.priorite}
            onChange={e => setTaskForm(f => ({ ...f, priorite: e.target.value }))}>
            <option value="haute">🔴 Haute</option>
            <option value="normale">🔵 Normale</option>
            <option value="basse">⚪ Basse</option>
          </select>
          <div className={styles.formActions}>
            <button type="submit" className={styles.btnPrimary} disabled={loading}>Créer</button>
            <button type="button" className={styles.btnGhost} onClick={() => setShowTask(false)}>Annuler</button>
          </div>
        </form>
      )}

      {/* Kanban */}
      {activeSprint ? (
        <div className={styles.kanban}>
          {[['todo', 'À faire', todo], ['en_cours', 'En cours', enCours], ['done', 'Terminé', done]].map(([statut, label, list]) => (
            <div key={statut} className={styles.column}>
              <div className={styles.colHeader}>
                <span style={{ color: STATUT_COLORS[statut] }}>●</span> {label}
                <span className={styles.badge}>{list.length}</span>
              </div>
              {list.map(task => (
                <div key={task.id} className={styles.card}>
                  <div className={styles.cardTitle}>{task.titre}</div>
                  <div className={styles.cardMeta}>
                    <span style={{ color: PRIORITE_COLORS[task.priorite], fontSize: 11 }}>▲ {task.priorite}</span>
                  </div>
                  <div className={styles.cardActions}>
                    {statut !== 'todo'     && <button className={styles.micro} onClick={() => updateTask(task.id, { statut: 'todo' })}>←</button>}
                    {statut !== 'en_cours' && <button className={styles.micro} onClick={() => updateTask(task.id, { statut: 'en_cours' })}>→</button>}
                    {statut !== 'done'     && <button className={styles.micro} onClick={() => updateTask(task.id, { statut: 'done' })}>✓</button>}
                    <button className={styles.micro} style={{ color: '#ef4444' }} onClick={() => deleteTask(task.id)}>✕</button>
                  </div>
                </div>
              ))}
            </div>
          ))}
        </div>
      ) : (
        <p className={styles.empty}>Crée un sprint pour commencer.</p>
      )}
    </div>
  )
}

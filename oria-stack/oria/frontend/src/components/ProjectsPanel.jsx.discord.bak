import { useState, useEffect } from 'react'
import { api } from '../services/api.js'

export default function ProjectsPanel({ world, moi, onWorldMisAJour }) {
  const [projects, setProjects]   = useState([])
  const [creating, setCreating]   = useState(false)
  const [newName, setNewName]     = useState('')
  const [newDesc, setNewDesc]     = useState('')
  const [loading, setLoading]     = useState(false)
  const [expanded, setExpanded]   = useState({})
  const [filter, setFilter]       = useState('all') // all | active | closed

  const estProprietaire = world?.owner_id === moi?.id

  useEffect(() => {
    if (world?.id) loadProjects()
  }, [world?.id])

  async function loadProjects() {
    setLoading(true)
    const data = await api.get(`/worlds/${world.id}/projects`)
    if (Array.isArray(data)) setProjects(data)
    setLoading(false)
  }

  async function createProject() {
    if (!newName.trim()) return
    const p = await api.post('/projects', {
      world_id: world.id,
      name: newName.trim(),
      description: newDesc.trim(),
    })
    if (p) {
      setProjects(prev => [p, ...prev])
      setNewName('')
      setNewDesc('')
      setCreating(false)
    }
  }

  async function closeProject(p) {
    if (!confirm(`Fermer le projet « ${p.name} » ? Toutes ses rooms passeront en lecture seule.`)) return
    const updated = await api.post(`/projects/${p.id}/close`)
    if (updated) {
      setProjects(prev => prev.map(x => x.id === p.id ? updated : x))
      onWorldMisAJour()
    }
  }

  async function reopenProject(p) {
    const updated = await api.post(`/projects/${p.id}/reopen`)
    if (updated) {
      setProjects(prev => prev.map(x => x.id === p.id ? updated : x))
      onWorldMisAJour()
    }
  }

  async function deleteProject(p) {
    if (!confirm(`Supprimer le projet « ${p.name} » ? Les rooms ne seront pas supprimées.`)) return
    await api.del(`/projects/${p.id}`)
    setProjects(prev => prev.filter(x => x.id !== p.id))
  }

  const filtered = projects.filter(p =>
    filter === 'all' ? true : p.status === filter
  )

  if (!world) return (
    <div style={{ padding: 32, color: '#aaa', textAlign: 'center' }}>
      <div style={{ fontSize: 40 }}>📁</div>
      <p>Sélectionne une commune</p>
    </div>
  )

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: '#1e1f22' }}>
      {/* Header */}
      <div style={{
        padding: '16px 20px', borderBottom: '1px solid #2d2e33',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      }}>
        <h2 style={{ margin: 0, fontSize: 16, color: '#fff', fontWeight: 600 }}>
          📁 Projets — {world.nom}
        </h2>
        {estProprietaire && (
          <button
            onClick={() => setCreating(true)}
            style={{
              background: '#5865f2', color: '#fff', border: 'none',
              borderRadius: 6, padding: '6px 14px', cursor: 'pointer', fontSize: 13,
            }}
          >
            + Nouveau projet
          </button>
        )}
      </div>

      {/* Filter tabs */}
      <div style={{ display: 'flex', gap: 4, padding: '10px 20px', borderBottom: '1px solid #2d2e33' }}>
        {[['all', 'Tous'], ['active', '🟢 Actifs'], ['closed', '🔒 Fermés']].map(([v, l]) => (
          <button
            key={v}
            onClick={() => setFilter(v)}
            style={{
              background: filter === v ? '#5865f2' : '#2d2e33',
              color: filter === v ? '#fff' : '#aaa',
              border: 'none', borderRadius: 4, padding: '4px 10px',
              cursor: 'pointer', fontSize: 12,
            }}
          >{l}</button>
        ))}
      </div>

      {/* Create form */}
      {creating && (
        <div style={{
          margin: 16, padding: 16, background: '#2d2e33',
          borderRadius: 8, border: '1px solid #3d3e43',
        }}>
          <input
            value={newName}
            onChange={e => setNewName(e.target.value)}
            placeholder="Nom du projet *"
            autoFocus
            style={inputStyle}
          />
          <textarea
            value={newDesc}
            onChange={e => setNewDesc(e.target.value)}
            placeholder="Description (optionnelle)"
            rows={2}
            style={{ ...inputStyle, resize: 'vertical', marginTop: 8 }}
          />
          <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
            <button onClick={createProject} style={btnPrimary}>Créer</button>
            <button onClick={() => setCreating(false)} style={btnSecondary}>Annuler</button>
          </div>
        </div>
      )}

      {/* List */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '8px 16px' }}>
        {loading && <div style={{ color: '#aaa', padding: 24, textAlign: 'center' }}>Chargement…</div>}
        {!loading && filtered.length === 0 && (
          <div style={{ color: '#aaa', padding: 24, textAlign: 'center' }}>
            <div style={{ fontSize: 36 }}>📂</div>
            <p>{filter === 'closed' ? 'Aucun projet fermé' : 'Aucun projet — crée le premier !'}</p>
          </div>
        )}
        {filtered.map(p => (
          <ProjectCard
            key={p.id}
            project={p}
            expanded={expanded[p.id]}
            onToggle={() => setExpanded(prev => ({ ...prev, [p.id]: !prev[p.id] }))}
            estProprietaire={estProprietaire}
            onClose={() => closeProject(p)}
            onReopen={() => reopenProject(p)}
            onDelete={() => deleteProject(p)}
          />
        ))}
      </div>
    </div>
  )
}

function ProjectCard({ project, expanded, onToggle, estProprietaire, onClose, onReopen, onDelete }) {
  const isClosed = project.status === 'closed'

  return (
    <div style={{
      marginBottom: 10, borderRadius: 8,
      border: `1px solid ${isClosed ? '#3a3a3a' : '#3d3e43'}`,
      background: isClosed ? '#1a1a1a' : '#2d2e33',
      opacity: isClosed ? 0.8 : 1,
    }}>
      {/* Card header */}
      <div
        onClick={onToggle}
        style={{
          padding: '12px 16px', cursor: 'pointer',
          display: 'flex', alignItems: 'center', gap: 10,
        }}
      >
        <span style={{ fontSize: 18 }}>{isClosed ? '🔒' : '📁'}</span>
        <div style={{ flex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ color: '#fff', fontWeight: 600, fontSize: 14 }}>{project.name}</span>
            <span style={{
              fontSize: 11, padding: '2px 7px', borderRadius: 10,
              background: isClosed ? '#3a3a3a' : '#3a4a6a',
              color: isClosed ? '#888' : '#8ab4f8',
            }}>
              {isClosed ? 'Terminé' : 'Actif'}
            </span>
          </div>
          {project.description && (
            <div style={{ color: '#aaa', fontSize: 12, marginTop: 2 }}>{project.description}</div>
          )}
        </div>
        <span style={{ color: '#aaa', fontSize: 12 }}>
          {project.room_count} room{project.room_count !== 1 ? 's' : ''}
        </span>
        <span style={{ color: '#666', fontSize: 12 }}>{expanded ? '▲' : '▼'}</span>
      </div>

      {/* Expanded rooms + actions */}
      {expanded && (
        <div style={{ borderTop: '1px solid #3d3e43', padding: '10px 16px' }}>
          {/* Rooms list */}
          {project.rooms.length === 0 ? (
            <p style={{ color: '#666', fontSize: 12, margin: '0 0 10px' }}>Aucune room assignée</p>
          ) : (
            <div style={{ marginBottom: 10 }}>
              {project.rooms.map(r => (
                <div key={r.id} style={{
                  display: 'flex', alignItems: 'center', gap: 6,
                  padding: '4px 0', color: '#ccc', fontSize: 13,
                }}>
                  <span>{r.emoji || '💬'}</span>
                  <span style={{ flex: 1 }}>{r.nom}</span>
                  {r.status === 'closed' && (
                    <span style={{ fontSize: 11, color: '#888' }}>🔒 fermée</span>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Actions */}
          {estProprietaire && (
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {!isClosed ? (
                <button onClick={onClose} style={btnDanger}>
                  🔒 Fermer le projet
                </button>
              ) : (
                <button onClick={onReopen} style={btnSecondary}>
                  🔓 Rouvrir
                </button>
              )}
              <button onClick={onDelete} style={btnGhost}>
                🗑 Supprimer
              </button>
            </div>
          )}

          {isClosed && project.closed_at && (
            <p style={{ color: '#666', fontSize: 11, margin: '8px 0 0' }}>
              Fermé le {new Date(project.closed_at).toLocaleDateString('fr-FR')}
            </p>
          )}
        </div>
      )}
    </div>
  )
}

const inputStyle = {
  width: '100%', background: '#1e1f22', border: '1px solid #3d3e43',
  borderRadius: 6, padding: '8px 10px', color: '#fff', fontSize: 13,
  boxSizing: 'border-box', outline: 'none',
}
const btnPrimary = {
  background: '#5865f2', color: '#fff', border: 'none',
  borderRadius: 6, padding: '7px 14px', cursor: 'pointer', fontSize: 13,
}
const btnSecondary = {
  background: '#2d2e33', color: '#ccc', border: '1px solid #3d3e43',
  borderRadius: 6, padding: '7px 14px', cursor: 'pointer', fontSize: 13,
}
const btnDanger = {
  background: '#4a1a1a', color: '#ff6b6b', border: '1px solid #6b2a2a',
  borderRadius: 6, padding: '6px 12px', cursor: 'pointer', fontSize: 12,
}
const btnGhost = {
  background: 'transparent', color: '#888', border: '1px solid #3d3e43',
  borderRadius: 6, padding: '6px 12px', cursor: 'pointer', fontSize: 12,
}

import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../services/api.js'

export default function ProjectsPanel({ world, moi, onWorldMisAJour }) {
  const { t } = useTranslation()
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
    if (!confirm(t('projects.confirmClose', { name: p.name }))) return
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
    if (!confirm(t('projects.confirmDelete', { name: p.name }))) return
    await api.del(`/projects/${p.id}`)
    setProjects(prev => prev.filter(x => x.id !== p.id))
  }

  const filtered = projects.filter(p =>
    filter === 'all' ? true : p.status === filter
  )

  if (!world) return (
    <div style={{ padding: 32, color: '#aaa', textAlign: 'center' }}>
      <div style={{ fontSize: 40 }}>📁</div>
      <p>{t('projects.selectWorld')}</p>
    </div>
  )

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: 'var(--ink-850)' }}>
      {/* Header */}
      <div style={{
        padding: '16px 20px', borderBottom: '1px solid #2d2e33',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      }}>
        <h2 style={{ margin: 0, fontSize: 16, color: '#fff', fontWeight: 600 }}>
          {t('projects.title', { world: world.nom })}
        </h2>
        {estProprietaire && (
          <button
            onClick={() => setCreating(true)}
            style={{
              background: 'var(--or-500)', color: '#fff', border: 'none',
              borderRadius: 6, padding: '6px 14px', cursor: 'pointer', fontSize: 13,
            }}
          >
            {t('projects.new')}
          </button>
        )}
      </div>

      {/* Filter tabs */}
      <div style={{ display: 'flex', gap: 4, padding: '10px 20px', borderBottom: '1px solid #2d2e33' }}>
        {[['all', t('projects.all')], ['active', t('projects.active')], ['closed', t('projects.closed')]].map(([v, l]) => (
          <button
            key={v}
            onClick={() => setFilter(v)}
            style={{
              background: filter === v ? 'var(--or-500)' : '#2d2e33',
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
            placeholder={t('projects.namePlaceholder')}
            autoFocus
            style={inputStyle}
          />
          <textarea
            value={newDesc}
            onChange={e => setNewDesc(e.target.value)}
            placeholder={t('projects.descPlaceholder')}
            rows={2}
            style={{ ...inputStyle, resize: 'vertical', marginTop: 8 }}
          />
          <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
            <button onClick={createProject} style={btnPrimary}>{t('projects.create')}</button>
            <button onClick={() => setCreating(false)} style={btnSecondary}>{t('common.cancel')}</button>
          </div>
        </div>
      )}

      {/* List */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '8px 16px' }}>
        {loading && <div style={{ color: '#aaa', padding: 24, textAlign: 'center' }}>{t('projects.loading')}</div>}
        {!loading && filtered.length === 0 && (
          <div style={{ color: '#aaa', padding: 24, textAlign: 'center' }}>
            <div style={{ fontSize: 36 }}>📂</div>
            <p>{filter === 'closed' ? t('projects.emptyClosed') : t('projects.empty')}</p>
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
  const { t, i18n } = useTranslation()
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
              {isClosed ? t('projects.statusDone') : t('projects.statusActive')}
            </span>
          </div>
          {project.description && (
            <div style={{ color: '#aaa', fontSize: 12, marginTop: 2 }}>{project.description}</div>
          )}
        </div>
        <span style={{ color: '#aaa', fontSize: 12 }}>
          {t('projects.rooms', { count: project.room_count })}
        </span>
        <span style={{ color: '#666', fontSize: 12 }}>{expanded ? '▲' : '▼'}</span>
      </div>

      {/* Expanded rooms + actions */}
      {expanded && (
        <div style={{ borderTop: '1px solid #3d3e43', padding: '10px 16px' }}>
          {/* Rooms list */}
          {project.rooms.length === 0 ? (
            <p style={{ color: '#666', fontSize: 12, margin: '0 0 10px' }}>{t('projects.noRoom')}</p>
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
                    <span style={{ fontSize: 11, color: '#888' }}>{t('projects.roomClosed')}</span>
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
                  {t('projects.close')}
                </button>
              ) : (
                <button onClick={onReopen} style={btnSecondary}>
                  {t('projects.reopen')}
                </button>
              )}
              <button onClick={onDelete} style={btnGhost}>
                🗑 {t('common.delete')}
              </button>
            </div>
          )}

          {isClosed && project.closed_at && (
            <p style={{ color: '#666', fontSize: 11, margin: '8px 0 0' }}>
              {t('projects.closedOn', { date: new Date(project.closed_at).toLocaleDateString(i18n.language) })}
            </p>
          )}
        </div>
      )}
    </div>
  )
}

const inputStyle = {
  width: '100%', background: 'var(--ink-850)', border: '1px solid #3d3e43',
  borderRadius: 6, padding: '8px 10px', color: '#fff', fontSize: 13,
  boxSizing: 'border-box', outline: 'none',
}
const btnPrimary = {
  background: 'var(--or-500)', color: '#fff', border: 'none',
  borderRadius: 6, padding: '7px 14px', cursor: 'pointer', fontSize: 13,
}
const btnSecondary = {
  background: '#2d2e33', color: '#ccc', border: '1px solid #3d3e43',
  borderRadius: 6, padding: '7px 14px', cursor: 'pointer', fontSize: 13,
}
const btnDanger = {
  background: '#4a1a1a', color: 'var(--rouge)', border: '1px solid #6b2a2a',
  borderRadius: 6, padding: '6px 12px', cursor: 'pointer', fontSize: 12,
}
const btnGhost = {
  background: 'transparent', color: '#888', border: '1px solid #3d3e43',
  borderRadius: 6, padding: '6px 12px', cursor: 'pointer', fontSize: 12,
}

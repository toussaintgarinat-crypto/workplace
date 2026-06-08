import { useState, useEffect } from 'react'
import { api } from '../../services/api'

const SKILL_MD_TEMPLATE = `# Nom du Skill
> Description courte du skill

## Instructions

Décris ici comment l'assistant doit se comporter avec ce skill.
Quelles sont ses responsabilités spéciales, ses contraintes, ses formats de sortie ?

## Exemples

- "Exemple de requête déclenchant ce skill"
`

export default function SkillsView() {
  const [skills, setSkills]     = useState([])
  const [form, setForm]         = useState({ nom: '', description: '', skillMd: SKILL_MD_TEMPLATE, actif: true })
  const [mode, setMode]         = useState('list')
  const [editId, setEditId]     = useState(null)
  const [error, setError]       = useState('')

  useEffect(() => {
    api.get('/api/skills').then(setSkills).catch(() => {})
  }, [])

  async function saveSkill(e) {
    e.preventDefault()
    setError('')
    try {
      if (editId) {
        const updated = await api.patch(`/api/skills/${editId}`, form)
        setSkills(prev => prev.map(s => s.id === editId ? updated : s))
      } else {
        const created = await api.post('/api/skills', { ...form, tags: [] })
        setSkills(prev => [...prev, created])
      }
      setMode('list')
      setEditId(null)
      setForm({ nom: '', description: '', skillMd: SKILL_MD_TEMPLATE, actif: true })
    } catch (err) {
      setError(err.data?.error || 'Erreur sauvegarde')
    }
  }

  async function toggleSkill(id, actif) {
    const updated = await api.patch(`/api/skills/${id}`, { actif })
    setSkills(prev => prev.map(s => s.id === id ? updated : s))
  }

  async function deleteSkill(id) {
    await api.delete(`/api/skills/${id}`)
    setSkills(prev => prev.filter(s => s.id !== id))
  }

  function startEdit(skill) {
    setEditId(skill.id)
    setForm({ nom: skill.nom, description: skill.description, skillMd: skill.skillMd, actif: skill.actif })
    setMode('edit')
  }

  function startNew() {
    setEditId(null)
    setForm({ nom: '', description: '', skillMd: SKILL_MD_TEMPLATE, actif: true })
    setMode('edit')
  }

  if (mode === 'edit') {
    return (
      <div style={{ padding: '2rem', maxWidth: 900, margin: '0 auto' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '1.5rem' }}>
          <button onClick={() => { setMode('list'); setEditId(null) }} style={{ background: 'none', border: 'none', color: '#94a3b8', cursor: 'pointer', fontSize: '1.1rem' }}>
            ← Retour
          </button>
          <h2 style={{ color: '#e2e8f0', margin: 0 }}>{editId ? 'Modifier le skill' : 'Nouveau skill'}</h2>
        </div>

        <form onSubmit={saveSkill} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          {error && <div style={{ color: '#f87171' }}>{error}</div>}
          <input
            placeholder="Nom du skill"
            value={form.nom}
            onChange={e => setForm(f => ({ ...f, nom: e.target.value }))}
            required
            style={inputStyle}
          />
          <input
            placeholder="Description courte"
            value={form.description}
            onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
            style={inputStyle}
          />
          <label style={{ color: '#94a3b8', fontSize: '0.875rem' }}>SKILL.md</label>
          <textarea
            value={form.skillMd}
            onChange={e => setForm(f => ({ ...f, skillMd: e.target.value }))}
            rows={20}
            required
            style={{ ...inputStyle, fontFamily: 'monospace', fontSize: '0.85rem', resize: 'vertical' }}
          />
          <div style={{ display: 'flex', gap: '0.75rem' }}>
            <button type="submit" style={btnStyle('#6366f1')}>Sauvegarder</button>
            <button type="button" onClick={() => { setMode('list'); setEditId(null) }} style={btnStyle('#475569')}>
              Annuler
            </button>
          </div>
        </form>
      </div>
    )
  }

  return (
    <div style={{ padding: '2rem', maxWidth: 800, margin: '0 auto' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.5rem' }}>
        <div>
          <h1 style={{ color: '#e2e8f0', margin: 0 }}>🧩 Skills</h1>
          <p style={{ color: '#94a3b8', marginTop: '0.5rem', marginBottom: 0 }}>
            Instructions expertes injectées dans le contexte de l'assistant selon les déclencheurs.
          </p>
        </div>
        <button onClick={startNew} style={btnStyle('#6366f1')}>
          + Nouveau skill
        </button>
      </div>

      {skills.length === 0 ? (
        <div style={{ color: '#64748b', textAlign: 'center', padding: '3rem', background: '#1e1e2e', borderRadius: 12 }}>
          Aucun skill configuré. Crée ton premier skill pour enrichir les réponses de Forge.
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
          {skills.map(skill => (
            <div
              key={skill.id}
              style={{
                background: '#1e1e2e', borderRadius: 12, padding: '1.25rem',
                border: `1px solid ${skill.actif ? '#6366f1' : '#2d2d44'}`,
                display: 'flex', alignItems: 'flex-start', gap: '1rem',
              }}
            >
              <div style={{ flex: 1 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                  <span style={{ fontSize: '1.1rem' }}>{skill.actif ? '🟢' : '⚫'}</span>
                  <span style={{ color: '#e2e8f0', fontWeight: 600 }}>{skill.nom}</span>
                  {skill.global && (
                    <span style={{ background: '#0ea5e920', color: '#0ea5e9', padding: '0.1rem 0.5rem', borderRadius: 999, fontSize: '0.75rem' }}>
                      Global
                    </span>
                  )}
                </div>
                {skill.description && (
                  <div style={{ color: '#94a3b8', fontSize: '0.875rem', marginTop: '0.25rem', marginLeft: '2rem' }}>
                    {skill.description}
                  </div>
                )}
              </div>
              <div style={{ display: 'flex', gap: '0.5rem', flexShrink: 0 }}>
                <button onClick={() => toggleSkill(skill.id, !skill.actif)} style={btnStyle(skill.actif ? '#64748b' : '#22c55e', true)}>
                  {skill.actif ? 'Désactiver' : 'Activer'}
                </button>
                <button onClick={() => startEdit(skill)} style={btnStyle('#6366f1', true)}>
                  ✎
                </button>
                <button onClick={() => deleteSkill(skill.id)} style={btnStyle('#ef4444', true)}>
                  🗑
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

const inputStyle = {
  background: '#0f0f1a', border: '1px solid #2d2d44', borderRadius: 8,
  padding: '0.6rem 0.875rem', color: '#e2e8f0', fontSize: '0.9rem', outline: 'none', width: '100%',
}

function btnStyle(color, small = false) {
  return {
    background: color, color: '#fff', border: 'none', borderRadius: 8,
    padding: small ? '0.4rem 0.75rem' : '0.6rem 1.5rem',
    cursor: 'pointer', fontSize: small ? '0.8rem' : '0.9rem', fontWeight: 600,
    whiteSpace: 'nowrap',
  }
}

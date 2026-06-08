import { useState, useEffect } from 'react'
import { api } from '../services/api.js'

// Système IPCRA d'Eliott Meunier — Input, Projet, Casquette, Ressource, Archive
const CATEGORIES = [
  {
    key: 'input',
    label: 'Input',
    icon: '📥',
    color: '#6366f1',
    description: 'Captures brutes, idées, articles à traiter',
    hint: 'Ce qui arrive dans ta vie et qui n\'a pas encore été traité.',
  },
  {
    key: 'projet',
    label: 'Projet',
    icon: '🎯',
    color: '#10b981',
    description: 'Projets actifs avec un objectif et une deadline',
    hint: 'Un projet a un résultat attendu et une date de fin.',
  },
  {
    key: 'casquette',
    label: 'Casquette',
    icon: '🎩',
    color: '#f59e0b',
    description: 'Rôles et responsabilités (chapeaux portés)',
    hint: 'Entrepreneur, développeur, parent… chaque casquette que tu portes.',
  },
  {
    key: 'ressource',
    label: 'Ressource',
    icon: '📚',
    color: '#3b82f6',
    description: 'Références, templates, connaissances réutilisables',
    hint: 'Ce qui est utile maintenant ou plus tard, indépendamment d\'un projet.',
  },
  {
    key: 'archive',
    label: 'Archive',
    icon: '🗄️',
    color: '#6b7280',
    description: 'Éléments terminés ou inactifs',
    hint: 'Projets complétés, ressources obsolètes, inputs traités.',
  },
]

const CATEGORY_MAP = Object.fromEntries(CATEGORIES.map(c => [c.key, c]))

export default function IPCRAPanel({ worldId, agents = [] }) {
  const [items, setItems]           = useState([])
  const [activeTab, setActiveTab]   = useState('input')
  const [selected, setSelected]     = useState(null)
  const [creating, setCreating]     = useState(false)
  const [newForm, setNewForm]       = useState({ titre: '', contenu: '', categorie: 'input', casquette: '', tags: '', agent_id: '' })
  const [editing, setEditing]       = useState(false)
  const [editForm, setEditForm]     = useState({})
  const [aiPrompt, setAiPrompt]     = useState('')
  const [aiAnswer, setAiAnswer]     = useState(null)
  const [aiLoading, setAiLoading]   = useState(false)
  const [traces, setTraces]         = useState([])
  const [saving, setSaving]         = useState(false)

  useEffect(() => { fetchItems() }, [])

  async function fetchItems() {
    const data = await api.get('/ipcra/')
    setItems(Array.isArray(data) ? data : [])
  }

  async function fetchTraces(itemId) {
    const data = await api.get(`/ipcra/${itemId}/traces`)
    setTraces(Array.isArray(data) ? data : [])
  }

  function tabItems(cat) {
    return items.filter(i => i.categorie === cat)
  }

  async function createItem() {
    if (!newForm.titre.trim()) return
    setSaving(true)
    const tags = newForm.tags ? newForm.tags.split(',').map(t => t.trim()).filter(Boolean) : []
    const data = await api.post('/ipcra/', {
      titre: newForm.titre,
      contenu: newForm.contenu,
      categorie: newForm.categorie,
      tags,
      casquette: newForm.casquette || null,
      agent_id: newForm.agent_id || null,
      world_id: worldId || null,
    })
    setSaving(false)
    if (data) {
      setItems(prev => [data, ...prev])
      setCreating(false)
      setNewForm({ titre: '', contenu: '', categorie: 'input', casquette: '', tags: '', agent_id: '' })
      setActiveTab(data.categorie)
      openItem(data)
    }
  }

  async function saveEdit() {
    if (!selected) return
    setSaving(true)
    const tags = typeof editForm.tags === 'string'
      ? editForm.tags.split(',').map(t => t.trim()).filter(Boolean)
      : editForm.tags || []
    const data = await api.put(`/ipcra/${selected.id}`, {
      titre: editForm.titre,
      contenu: editForm.contenu,
      tags,
      casquette: editForm.casquette || null,
      source_url: editForm.source_url || null,
      agent_id: editForm.agent_id || null,
    })
    setSaving(false)
    if (data) {
      setItems(prev => prev.map(i => i.id === data.id ? data : i))
      setSelected(data)
      setEditing(false)
    }
  }

  async function moveItem(itemId, newCategorie) {
    const data = await api.patch(`/ipcra/${itemId}/categorie?categorie=${newCategorie}`, {})
    if (data) {
      setItems(prev => prev.map(i => i.id === data.id ? data : i))
      if (selected?.id === itemId) setSelected(data)
    }
  }

  async function deleteItem(item) {
    if (!confirm(`Supprimer "${item.titre}" ?`)) return
    await api.del(`/ipcra/${item.id}`)
    setItems(prev => prev.filter(i => i.id !== item.id))
    if (selected?.id === item.id) setSelected(null)
  }

  async function askAI() {
    if (!aiPrompt.trim() || !selected) return
    setAiLoading(true)
    setAiAnswer(null)
    const data = await api.post(`/ipcra/${selected.id}/assist`, { prompt: aiPrompt })
    setAiLoading(false)
    if (data) {
      setAiAnswer(data.answer)
      setAiPrompt('')
      fetchTraces(selected.id)
    }
  }

  function openItem(item) {
    setSelected(item)
    setEditing(false)
    setAiAnswer(null)
    setAiPrompt('')
    fetchTraces(item.id)
  }

  function startEdit() {
    setEditForm({
      titre: selected.titre,
      contenu: selected.contenu || '',
      tags: (selected.tags || []).join(', '),
      casquette: selected.casquette || '',
      source_url: selected.source_url || '',
      agent_id: selected.agent_id || '',
    })
    setEditing(true)
  }

  const cat = CATEGORY_MAP[activeTab]

  return (
    <div style={{ display: 'flex', height: '100%', minHeight: 0, gap: 0 }}>

      {/* ── Colonne gauche : tabs + liste ─────────────────────── */}
      <div style={{
        width: selected ? '320px' : '100%',
        flexShrink: 0,
        display: 'flex',
        flexDirection: 'column',
        borderRight: selected ? '1px solid var(--border)' : 'none',
        minHeight: 0,
      }}>

        {/* Tabs catégories */}
        <div style={{
          display: 'flex',
          borderBottom: '1px solid var(--border)',
          background: 'var(--bg-secondary)',
          overflowX: 'auto',
          flexShrink: 0,
        }}>
          {CATEGORIES.map(c => (
            <button
              key={c.key}
              onClick={() => setActiveTab(c.key)}
              style={{
                padding: '10px 14px',
                border: 'none',
                background: activeTab === c.key ? 'var(--bg-primary)' : 'transparent',
                borderBottom: activeTab === c.key ? `2px solid ${c.color}` : '2px solid transparent',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                color: activeTab === c.key ? c.color : 'var(--text-secondary)',
                fontWeight: activeTab === c.key ? 600 : 400,
                whiteSpace: 'nowrap',
                fontSize: '13px',
                transition: 'all 0.15s',
              }}
            >
              {c.icon} {c.label}
              <span style={{
                background: activeTab === c.key ? c.color : 'var(--bg-tertiary)',
                color: activeTab === c.key ? '#fff' : 'var(--text-secondary)',
                borderRadius: '10px',
                padding: '0 6px',
                fontSize: '11px',
                minWidth: '18px',
                textAlign: 'center',
              }}>
                {tabItems(c.key).length}
              </span>
            </button>
          ))}
        </div>

        {/* Header catégorie + bouton créer */}
        <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)', flexShrink: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div>
              <div style={{ fontWeight: 600, color: cat.color }}>{cat.icon} {cat.label}</div>
              <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>{cat.hint}</div>
            </div>
            <button
              onClick={() => { setCreating(true); setNewForm(f => ({ ...f, categorie: activeTab })) }}
              style={{
                padding: '6px 12px', borderRadius: '6px', border: 'none',
                background: cat.color, color: '#fff', cursor: 'pointer',
                fontWeight: 600, fontSize: '13px',
              }}
            >+ Ajouter</button>
          </div>
        </div>

        {/* Liste items */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '8px' }}>
          {tabItems(activeTab).length === 0 ? (
            <div style={{ textAlign: 'center', padding: '40px 20px', color: 'var(--text-secondary)' }}>
              <div style={{ fontSize: '32px', marginBottom: '8px' }}>{cat.icon}</div>
              <div style={{ fontWeight: 600, marginBottom: '4px' }}>{cat.label} vide</div>
              <div style={{ fontSize: '12px' }}>{cat.description}</div>
            </div>
          ) : (
            tabItems(activeTab).map(item => (
              <div
                key={item.id}
                onClick={() => openItem(item)}
                style={{
                  padding: '10px 12px',
                  borderRadius: '8px',
                  cursor: 'pointer',
                  marginBottom: '4px',
                  background: selected?.id === item.id ? 'var(--bg-secondary)' : 'transparent',
                  border: `1px solid ${selected?.id === item.id ? cat.color + '44' : 'transparent'}`,
                  transition: 'all 0.1s',
                }}
              >
                <div style={{ fontWeight: 500, fontSize: '14px', marginBottom: '2px' }}>
                  {item.casquette && <span style={{ marginRight: '4px', color: cat.color }}>🎩</span>}
                  {item.titre}
                </div>
                {item.contenu && (
                  <div style={{
                    fontSize: '12px', color: 'var(--text-secondary)', overflow: 'hidden',
                    display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical',
                  }}>
                    {item.contenu}
                  </div>
                )}
                {item.tags?.length > 0 && (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px', marginTop: '4px' }}>
                    {item.tags.map(t => (
                      <span key={t} style={{
                        fontSize: '10px', padding: '1px 6px', borderRadius: '10px',
                        background: cat.color + '22', color: cat.color,
                      }}>{t}</span>
                    ))}
                  </div>
                )}
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px' }}>
                  {new Date(item.updated_at).toLocaleDateString('fr-FR')}
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      {/* ── Panel droit : détail item ───────────────────────── */}
      {selected && (
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>

          {/* Header item */}
          <div style={{
            padding: '14px 20px',
            borderBottom: '1px solid var(--border)',
            display: 'flex',
            alignItems: 'flex-start',
            gap: '12px',
            flexShrink: 0,
          }}>
            <div style={{ flex: 1 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
                <span style={{
                  fontSize: '11px', padding: '2px 8px', borderRadius: '10px',
                  background: CATEGORY_MAP[selected.categorie]?.color + '22',
                  color: CATEGORY_MAP[selected.categorie]?.color,
                  fontWeight: 600,
                }}>
                  {CATEGORY_MAP[selected.categorie]?.icon} {selected.categorie}
                </span>
                {selected.casquette && (
                  <span style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>
                    🎩 {selected.casquette}
                  </span>
                )}
              </div>
              <div style={{ fontWeight: 700, fontSize: '16px' }}>{selected.titre}</div>
            </div>
            <div style={{ display: 'flex', gap: '6px', flexShrink: 0 }}>
              <button onClick={startEdit} style={btnStyle}>✏️ Modifier</button>
              <button onClick={() => deleteItem(selected)} style={{ ...btnStyle, color: '#ef4444' }}>🗑️</button>
              <button onClick={() => setSelected(null)} style={btnStyle}>✕</button>
            </div>
          </div>

          <div style={{ flex: 1, overflowY: 'auto', padding: '16px 20px' }}>

            {/* Déplacer entre catégories */}
            <div style={{ marginBottom: '16px' }}>
              <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '6px', fontWeight: 500 }}>
                Déplacer vers →
              </div>
              <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                {CATEGORIES.filter(c => c.key !== selected.categorie).map(c => (
                  <button
                    key={c.key}
                    onClick={() => moveItem(selected.id, c.key)}
                    style={{
                      padding: '4px 10px', borderRadius: '6px', border: `1px solid ${c.color}44`,
                      background: 'transparent', color: c.color, cursor: 'pointer', fontSize: '12px',
                    }}
                  >
                    {c.icon} {c.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Contenu / Édition */}
            {editing ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                <input
                  value={editForm.titre}
                  onChange={e => setEditForm(f => ({ ...f, titre: e.target.value }))}
                  placeholder="Titre"
                  style={inputStyle}
                />
                {selected.categorie === 'casquette' && (
                  <input
                    value={editForm.casquette}
                    onChange={e => setEditForm(f => ({ ...f, casquette: e.target.value }))}
                    placeholder="Nom du rôle (ex: Entrepreneur, Parent…)"
                    style={inputStyle}
                  />
                )}
                <textarea
                  value={editForm.contenu}
                  onChange={e => setEditForm(f => ({ ...f, contenu: e.target.value }))}
                  placeholder="Contenu…"
                  rows={10}
                  style={{ ...inputStyle, resize: 'vertical', fontFamily: 'inherit' }}
                />
                <input
                  value={editForm.tags}
                  onChange={e => setEditForm(f => ({ ...f, tags: e.target.value }))}
                  placeholder="Tags séparés par des virgules"
                  style={inputStyle}
                />
                <input
                  value={editForm.source_url}
                  onChange={e => setEditForm(f => ({ ...f, source_url: e.target.value }))}
                  placeholder="URL source (optionnel)"
                  style={inputStyle}
                />
                <select
                  value={editForm.agent_id}
                  onChange={e => setEditForm(f => ({ ...f, agent_id: e.target.value }))}
                  style={inputStyle}
                >
                  <option value="">Aucun agent IA</option>
                  {agents.map(a => <option key={a.id} value={a.id}>{a.nom}</option>)}
                </select>
                <div style={{ display: 'flex', gap: '8px' }}>
                  <button onClick={saveEdit} disabled={saving} style={primaryBtnStyle}>
                    {saving ? '…' : '✓ Sauvegarder'}
                  </button>
                  <button onClick={() => setEditing(false)} style={btnStyle}>Annuler</button>
                </div>
              </div>
            ) : (
              <div>
                {selected.contenu ? (
                  <div style={{ fontSize: '14px', lineHeight: '1.7', whiteSpace: 'pre-wrap', marginBottom: '16px' }}>
                    {selected.contenu}
                  </div>
                ) : (
                  <div style={{ color: 'var(--text-secondary)', fontSize: '13px', fontStyle: 'italic', marginBottom: '16px' }}>
                    Pas encore de contenu — clique sur Modifier pour ajouter des notes.
                  </div>
                )}
                {selected.source_url && (
                  <a href={selected.source_url} target="_blank" rel="noreferrer"
                    style={{ fontSize: '12px', color: 'var(--accent)', display: 'block', marginBottom: '12px' }}>
                    🔗 {selected.source_url}
                  </a>
                )}
              </div>
            )}

            {/* ── Assistance IA ── */}
            {!editing && (
              <div style={{ marginTop: '20px', paddingTop: '20px', borderTop: '1px solid var(--border)' }}>
                <div style={{ fontWeight: 600, marginBottom: '10px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  🤖 Assistance IA
                  {!selected.agent_id && (
                    <span style={{ fontSize: '11px', color: 'var(--text-secondary)', fontWeight: 400 }}>
                      (assigne un agent pour activer)
                    </span>
                  )}
                </div>
                <div style={{ display: 'flex', gap: '8px' }}>
                  <input
                    value={aiPrompt}
                    onChange={e => setAiPrompt(e.target.value)}
                    onKeyDown={e => e.key === 'Enter' && askAI()}
                    placeholder="Pose une question sur cet élément…"
                    style={{ ...inputStyle, flex: 1 }}
                  />
                  <button onClick={askAI} disabled={aiLoading || !aiPrompt.trim()} style={primaryBtnStyle}>
                    {aiLoading ? '…' : '→'}
                  </button>
                </div>
                {aiAnswer && (
                  <div style={{
                    marginTop: '10px', padding: '12px', borderRadius: '8px',
                    background: 'var(--bg-secondary)', fontSize: '13px', lineHeight: '1.6',
                    whiteSpace: 'pre-wrap',
                  }}>
                    {aiAnswer}
                  </div>
                )}
                {traces.length > 0 && (
                  <details style={{ marginTop: '12px' }}>
                    <summary style={{ cursor: 'pointer', fontSize: '12px', color: 'var(--text-secondary)' }}>
                      Historique IA ({traces.length})
                    </summary>
                    <div style={{ marginTop: '8px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                      {traces.slice(-5).map(t => (
                        <div key={t.id} style={{
                          padding: '8px', borderRadius: '6px', background: 'var(--bg-secondary)', fontSize: '12px',
                        }}>
                          <div style={{ color: 'var(--text-secondary)', marginBottom: '4px' }}>Q: {t.prompt}</div>
                          <div>{t.answer?.slice(0, 200)}{t.answer?.length > 200 ? '…' : ''}</div>
                        </div>
                      ))}
                    </div>
                  </details>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── Modal créer item ────────────────────────────────── */}
      {creating && (
        <div
          style={{
            position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
            display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
          }}
          onClick={e => e.target === e.currentTarget && setCreating(false)}
        >
          <div style={{
            background: 'var(--bg-primary)', borderRadius: '12px', padding: '24px',
            width: '480px', maxWidth: '95vw', display: 'flex', flexDirection: 'column', gap: '12px',
          }}>
            <div style={{ fontWeight: 700, fontSize: '16px' }}>
              {CATEGORY_MAP[newForm.categorie]?.icon} Nouvel élément IPCRA
            </div>

            <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
              {CATEGORIES.map(c => (
                <button
                  key={c.key}
                  onClick={() => setNewForm(f => ({ ...f, categorie: c.key }))}
                  style={{
                    padding: '5px 10px', borderRadius: '6px', border: `1px solid ${c.color}`,
                    background: newForm.categorie === c.key ? c.color : 'transparent',
                    color: newForm.categorie === c.key ? '#fff' : c.color,
                    cursor: 'pointer', fontSize: '12px', fontWeight: 500,
                  }}
                >
                  {c.icon} {c.label}
                </button>
              ))}
            </div>

            <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
              {CATEGORY_MAP[newForm.categorie]?.hint}
            </div>

            <input
              value={newForm.titre}
              onChange={e => setNewForm(f => ({ ...f, titre: e.target.value }))}
              onKeyDown={e => e.key === 'Enter' && createItem()}
              placeholder="Titre *"
              autoFocus
              style={inputStyle}
            />

            {newForm.categorie === 'casquette' && (
              <input
                value={newForm.casquette}
                onChange={e => setNewForm(f => ({ ...f, casquette: e.target.value }))}
                placeholder="Nom du rôle (ex: Entrepreneur, Développeur…)"
                style={inputStyle}
              />
            )}

            <textarea
              value={newForm.contenu}
              onChange={e => setNewForm(f => ({ ...f, contenu: e.target.value }))}
              placeholder="Contenu (optionnel)"
              rows={4}
              style={{ ...inputStyle, resize: 'vertical', fontFamily: 'inherit' }}
            />

            <input
              value={newForm.tags}
              onChange={e => setNewForm(f => ({ ...f, tags: e.target.value }))}
              placeholder="Tags (séparés par des virgules)"
              style={inputStyle}
            />

            <select
              value={newForm.agent_id}
              onChange={e => setNewForm(f => ({ ...f, agent_id: e.target.value }))}
              style={inputStyle}
            >
              <option value="">Aucun agent IA</option>
              {agents.map(a => <option key={a.id} value={a.id}>{a.nom}</option>)}
            </select>

            <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
              <button onClick={() => setCreating(false)} style={btnStyle}>Annuler</button>
              <button
                onClick={createItem}
                disabled={!newForm.titre.trim() || saving}
                style={{ ...primaryBtnStyle, background: CATEGORY_MAP[newForm.categorie]?.color }}
              >
                {saving ? '…' : `Créer ${CATEGORY_MAP[newForm.categorie]?.label}`}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

const btnStyle = {
  padding: '6px 10px', borderRadius: '6px', border: '1px solid var(--border)',
  background: 'transparent', cursor: 'pointer', fontSize: '13px', color: 'var(--text-primary)',
}
const primaryBtnStyle = {
  padding: '7px 14px', borderRadius: '6px', border: 'none',
  background: 'var(--accent)', color: '#fff', cursor: 'pointer', fontSize: '13px', fontWeight: 600,
}
const inputStyle = {
  padding: '8px 12px', borderRadius: '6px', border: '1px solid var(--border)',
  background: 'var(--bg-secondary)', color: 'var(--text-primary)',
  fontSize: '13px', width: '100%', boxSizing: 'border-box',
}

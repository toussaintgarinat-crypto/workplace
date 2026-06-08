import { useState, useEffect } from 'react'
import { api } from '../services/api.js'

const DEFAULT_AGENT = {
  nom: '', avatar_emoji: '🤖', description: '', system_prompt: 'Tu es un assistant IA utile et bienveillant.',
  map_x: 5, map_y: 5, forge_url: 'http://localhost:3001',
  forge_provider: 'ollama', forge_model: '',
  can_read_docs: true, use_memory: true, use_ipcra: false,
  wake_word: '',
}

const PROVIDERS = ['ollama', 'anthropic', 'openai', 'groq', 'gemini', 'mistral', 'deepseek', 'lmstudio', 'openrouter']

export default function AgentManager({ world, moi, onAgentsChange }) {
  const [agents, setAgents]     = useState([])
  const [loading, setLoading]   = useState(true)
  const [form, setForm]         = useState(null)    // null = liste, objet = form édition
  const [saving, setSaving]     = useState(false)

  const isOwner = world?.owner_id === moi?.id

  useEffect(() => { if (world) fetchAgents() }, [world?.id])

  async function fetchAgents() {
    setLoading(true)
    const data = await api.get(`/agents/world/${world.id}`)
    setAgents(Array.isArray(data) ? data : [])
    setLoading(false)
  }

  async function save() {
    setSaving(true)
    let result
    if (form.id) {
      result = await api.patch(`/agents/${form.id}`, form)
    } else {
      result = await api.post('/agents/', { ...form, world_id: world.id })
    }
    setSaving(false)
    if (result) { setForm(null); fetchAgents(); onAgentsChange?.() }
  }

  async function toggle(agent) {
    await api.patch(`/agents/${agent.id}`, { is_active: !agent.is_active })
    fetchAgents()
  }

  async function remove(agent) {
    if (!confirm(`Supprimer l'agent "${agent.nom}" ?`)) return
    await api.del(`/agents/${agent.id}`)
    fetchAgents()
  }

  function f(k, v) {
    setForm(prev => ({ ...prev, [k]: v }))
  }

  if (!isOwner) return (
    <div className="agent-manager-readonly">
      <h3>🤖 Agents de ce monde</h3>
      {agents.map(a => (
        <div key={a.id} className="agent-card-ro">
          <span>{a.avatar_emoji}</span>
          <div><strong>{a.nom}</strong><p>{a.description}</p></div>
        </div>
      ))}
      {agents.length === 0 && <p className="empty-hint">Aucun agent dans ce monde.</p>}
    </div>
  )

  if (form !== null) return (
    <div className="agent-form-page">
      <div className="agent-form-header">
        <button className="btn-back" onClick={() => setForm(null)}>← Retour</button>
        <h2>{form.id ? 'Modifier l\'agent' : 'Nouvel agent IA'}</h2>
      </div>

      <div className="agent-form">
        <div className="form-row">
          <label>Emoji avatar</label>
          <input type="text" value={form.avatar_emoji} onChange={e => f('avatar_emoji', e.target.value)} className="emoji-input"/>
        </div>
        <div className="form-row">
          <label>Nom *</label>
          <input type="text" value={form.nom} onChange={e => f('nom', e.target.value)} placeholder="Ex: Atlas"/>
        </div>
        <div className="form-row">
          <label>Description</label>
          <input type="text" value={form.description} onChange={e => f('description', e.target.value)} placeholder="Ex: Expert en stratégie"/>
        </div>
        <div className="form-row">
          <label>System prompt</label>
          <textarea rows={5} value={form.system_prompt} onChange={e => f('system_prompt', e.target.value)}/>
        </div>

        <div className="form-section-title">Position sur la carte</div>
        <div className="form-row-inline">
          <div className="form-row">
            <label>X</label>
            <input type="number" min={0} max={23} value={form.map_x} onChange={e => f('map_x', parseFloat(e.target.value))}/>
          </div>
          <div className="form-row">
            <label>Y</label>
            <input type="number" min={0} max={17} value={form.map_y} onChange={e => f('map_y', parseFloat(e.target.value))}/>
          </div>
        </div>

        <div className="form-section-title">Connexion Forge</div>
        <div className="form-row">
          <label>URL Forge</label>
          <input type="text" value={form.forge_url} onChange={e => f('forge_url', e.target.value)}/>
        </div>
        <div className="form-row-inline">
          <div className="form-row">
            <label>Provider</label>
            <select value={form.forge_provider} onChange={e => f('forge_provider', e.target.value)}>
              {PROVIDERS.map(p => <option key={p} value={p}>{p}</option>)}
            </select>
          </div>
          <div className="form-row">
            <label>Modèle (optionnel)</label>
            <input type="text" value={form.forge_model} onChange={e => f('forge_model', e.target.value)} placeholder="Laisse vide = défaut Forge"/>
          </div>
        </div>

        <div className="form-section-title">Activation vocale</div>
        <div className="form-row">
          <label>Mot d'activation (wake word)</label>
          <input
            type="text"
            value={form.wake_word || ''}
            onChange={e => f('wake_word', e.target.value)}
            placeholder={`Par défaut : "${form.nom || 'prénom de l\'agent'}"`}
          />
          <span className="form-hint">👂 L'assistant s'active quand il entend ce mot. Laisse vide pour utiliser le prénom.</span>
        </div>

        <div className="form-section-title">Capacités</div>
        <div className="form-checkboxes">
          <label className="checkbox-label">
            <input type="checkbox" checked={form.can_read_docs} onChange={e => f('can_read_docs', e.target.checked)}/>
            📁 Accès aux dossiers de l'utilisateur
          </label>
          <label className="checkbox-label">
            <input type="checkbox" checked={form.use_memory} onChange={e => f('use_memory', e.target.checked)}/>
            🧠 Utiliser la mémoire MemPalace
          </label>
          <label className="checkbox-label">
            <input type="checkbox" checked={form.use_ipcra} onChange={e => f('use_ipcra', e.target.checked)}/>
            🎯 Mode IPCRA disponible
          </label>
        </div>

        <div className="form-actions">
          <button className="btn-cancel" onClick={() => setForm(null)}>Annuler</button>
          <button className="btn-save" onClick={save} disabled={saving || !form.nom.trim()}>
            {saving ? '⏳ Sauvegarde…' : '💾 Sauvegarder'}
          </button>
        </div>
      </div>
    </div>
  )

  return (
    <div className="agent-manager">
      <div className="agent-manager-header">
        <h2>🤖 Agents IA</h2>
        <button className="btn-new-agent" onClick={() => setForm({ ...DEFAULT_AGENT })}>
          ＋ Nouvel agent
        </button>
      </div>

      <p className="agent-manager-info">
        Les agents vivent sur la carte de ton monde. Les visiteurs peuvent les approcher
        et leur parler — ils sont connectés à Forge et ont accès aux dossiers de chaque utilisateur.
      </p>

      {loading ? (
        <div className="loading-spinner"><div className="spinner"/></div>
      ) : agents.length === 0 ? (
        <div className="agents-empty">
          <span>🤖</span>
          <p>Aucun agent dans ce monde.</p>
          <small>Crée ton premier agent pour l'ajouter à la carte.</small>
        </div>
      ) : (
        <div className="agents-list">
          {agents.map(a => (
            <div key={a.id} className={`agent-card ${!a.is_active ? 'inactive' : ''}`}>
              <div className="agent-card-avatar">{a.avatar_emoji}</div>
              <div className="agent-card-info">
                <div className="agent-card-nom">{a.nom}</div>
                <div className="agent-card-desc">{a.description || '—'}</div>
                <div className="agent-card-badges">
                  <span className="badge-forge">{a.forge_provider}</span>
                  {a.forge_model && <span className="badge-model">{a.forge_model}</span>}
                  {a.can_read_docs && <span className="badge-cap">📁</span>}
                  {a.use_memory   && <span className="badge-cap">🧠</span>}
                  {a.use_ipcra    && <span className="badge-cap">🎯</span>}
                </div>
                <div className="agent-card-pos">📍 x:{a.map_x} y:{a.map_y}</div>
              </div>
              <div className="agent-card-actions">
                <button onClick={() => setForm({ ...a })} title="Modifier">✏️</button>
                <button onClick={() => toggle(a)} title={a.is_active ? 'Désactiver' : 'Activer'}>
                  {a.is_active ? '⏸' : '▶️'}
                </button>
                <button onClick={() => remove(a)} title="Supprimer" className="danger">🗑</button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

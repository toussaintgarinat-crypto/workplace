import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
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
  const { t } = useTranslation()
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
    if (!confirm(t('agent.confirmDelete', { nom: agent.nom }))) return
    await api.del(`/agents/${agent.id}`)
    fetchAgents()
  }

  function f(k, v) {
    setForm(prev => ({ ...prev, [k]: v }))
  }

  if (!isOwner) return (
    <div className="agent-manager-readonly">
      <h3>{t('agent.roTitle')}</h3>
      {agents.map(a => (
        <div key={a.id} className="agent-card-ro">
          <span>{a.avatar_emoji}</span>
          <div><strong>{a.nom}</strong><p>{a.description}</p></div>
        </div>
      ))}
      {agents.length === 0 && <p className="empty-hint">{t('agent.emptyRo')}</p>}
    </div>
  )

  if (form !== null) return (
    <div className="agent-form-page">
      <div className="agent-form-header">
        <button className="btn-back" onClick={() => setForm(null)}>{t('common.back')}</button>
        <h2>{form.id ? t('agent.editTitle') : t('agent.newTitle')}</h2>
      </div>

      <div className="agent-form">
        <div className="form-row">
          <label>{t('agent.emojiLabel')}</label>
          <input type="text" value={form.avatar_emoji} onChange={e => f('avatar_emoji', e.target.value)} className="emoji-input"/>
        </div>
        <div className="form-row">
          <label>{t('agent.nameLabel')}</label>
          <input type="text" value={form.nom} onChange={e => f('nom', e.target.value)} placeholder={t('agent.namePlaceholder')}/>
        </div>
        <div className="form-row">
          <label>{t('common.description')}</label>
          <input type="text" value={form.description} onChange={e => f('description', e.target.value)} placeholder={t('agent.descPlaceholder')}/>
        </div>
        <div className="form-row">
          <label>{t('agent.systemPrompt')}</label>
          <textarea rows={5} value={form.system_prompt} onChange={e => f('system_prompt', e.target.value)}/>
        </div>

        <div className="form-section-title">{t('agent.mapPos')}</div>
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

        <div className="form-section-title">{t('agent.forgeConn')}</div>
        <div className="form-row">
          <label>{t('agent.forgeUrl')}</label>
          <input type="text" value={form.forge_url} onChange={e => f('forge_url', e.target.value)}/>
        </div>
        <div className="form-row-inline">
          <div className="form-row">
            <label>{t('agent.provider')}</label>
            <select value={form.forge_provider} onChange={e => f('forge_provider', e.target.value)}>
              {PROVIDERS.map(p => <option key={p} value={p}>{p}</option>)}
            </select>
          </div>
          <div className="form-row">
            <label>{t('agent.modelLabel')}</label>
            <input type="text" value={form.forge_model} onChange={e => f('forge_model', e.target.value)} placeholder={t('agent.modelPlaceholder')}/>
          </div>
        </div>

        <div className="form-section-title">{t('agent.voiceActivation')}</div>
        <div className="form-row">
          <label>{t('agent.wakeWord')}</label>
          <input
            type="text"
            value={form.wake_word || ''}
            onChange={e => f('wake_word', e.target.value)}
            placeholder={t('agent.wakeWordPlaceholder', { nom: form.nom || t('agent.wakeWordDefault') })}
          />
          <span className="form-hint">{t('agent.wakeWordHint')}</span>
        </div>

        <div className="form-section-title">{t('agent.capabilities')}</div>
        <div className="form-checkboxes">
          <label className="checkbox-label">
            <input type="checkbox" checked={form.can_read_docs} onChange={e => f('can_read_docs', e.target.checked)}/>
            {t('agent.capDocs')}
          </label>
          <label className="checkbox-label">
            <input type="checkbox" checked={form.use_memory} onChange={e => f('use_memory', e.target.checked)}/>
            {t('agent.capMemory')}
          </label>
          <label className="checkbox-label">
            <input type="checkbox" checked={form.use_ipcra} onChange={e => f('use_ipcra', e.target.checked)}/>
            {t('agent.capIpcra')}
          </label>
        </div>

        <div className="form-actions">
          <button className="btn-cancel" onClick={() => setForm(null)}>{t('common.cancel')}</button>
          <button className="btn-save" onClick={save} disabled={saving || !form.nom.trim()}>
            {saving ? t('agent.saving') : t('agent.save')}
          </button>
        </div>
      </div>
    </div>
  )

  return (
    <div className="agent-manager">
      <div className="agent-manager-header">
        <h2>{t('agent.title')}</h2>
        <button className="btn-new-agent" onClick={() => setForm({ ...DEFAULT_AGENT })}>
          {t('agent.newAgent')}
        </button>
      </div>

      <p className="agent-manager-info">
        {t('agent.info')}
      </p>

      {loading ? (
        <div className="loading-spinner"><div className="spinner"/></div>
      ) : agents.length === 0 ? (
        <div className="agents-empty">
          <span>🤖</span>
          <p>{t('agent.emptyTitle')}</p>
          <small>{t('agent.emptyHint')}</small>
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
                <button onClick={() => setForm({ ...a })} title={t('common.edit')}>✏️</button>
                <button onClick={() => toggle(a)} title={a.is_active ? t('agent.deactivate') : t('agent.activate')}>
                  {a.is_active ? '⏸' : '▶️'}
                </button>
                <button onClick={() => remove(a)} title={t('common.delete')} className="danger">🗑</button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

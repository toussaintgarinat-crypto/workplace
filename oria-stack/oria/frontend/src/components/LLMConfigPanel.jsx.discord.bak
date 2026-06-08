import { useState, useEffect } from 'react'
import { api, authHeaders } from '../services/api.js'

const PROVIDER_LABELS = {
  anthropic: 'Anthropic',
  openai: 'OpenAI-compatible',
}

export default function LLMConfigPanel({ world, moi, onFermer }) {
  const [presets, setPresets]       = useState([])
  const [config, setConfig]         = useState(null)
  const [form, setForm]             = useState({ provider: 'anthropic', base_url: '', api_key: '', model: '' })
  const [chargement, setChargement] = useState(true)
  const [sauvegarde, setSauvegarde] = useState(false)
  const [msg, setMsg]               = useState('')
  const [testResult, setTestResult] = useState('')
  const [testing, setTesting]       = useState(false)

  const isAdmin = world?.owner_id === moi?.id

  useEffect(() => {
    Promise.all([
      api.get('/llm-config/presets'),
      api.get(`/llm-config/${world.id}`),
    ]).then(([p, c]) => {
      if (p) setPresets(p)
      if (c) {
        setConfig(c)
        setForm({ provider: c.provider, base_url: c.base_url || '', api_key: c.api_key || '', model: c.model || '' })
      }
      setChargement(false)
    })
  }, [world.id])

  function appliquerPreset(preset) {
    setForm(f => ({ ...f, provider: preset.provider, base_url: preset.base_url, model: preset.model }))
    setMsg('')
    setTestResult('')
  }

  async function sauvegarder(e) {
    e.preventDefault()
    setSauvegarde(true)
    const r = await api.put(`/llm-config/${world.id}`, form)
    setSauvegarde(false)
    setMsg(r?.ok ? '✅ Configuration sauvegardée' : '❌ Erreur lors de la sauvegarde')
  }

  async function tester() {
    setTesting(true)
    setTestResult('')
    // Appel à summarize-conseil avec un conseil fictif — on passe par suggest-ticket-response avec données vides
    // En réalité on va appeler l'endpoint générique de test via suggest-ticket-response sur un ticket qui n'existe pas
    // Le plus simple : appeler l'API directement avec un prompt de test
    const r = await fetch(`${import.meta.env.VITE_API_URL || 'http://localhost:8000'}/api/llm-config/${world.id}/test`, {
      method: 'POST',
      credentials: 'include',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
    })
    const d = await r.json().catch(() => null)
    setTesting(false)
    setTestResult(d?.response || d?.detail || '❌ Erreur')
  }

  async function reinitialiser() {
    if (!confirm('Réinitialiser la config sur les variables d\'environnement ?')) return
    const r = await api.del(`/llm-config/${world.id}`)
    if (r?.ok) setMsg('✅ Config réinitialisée')
  }

  if (!isAdmin) {
    return (
      <div className="mairie-panel">
        <div className="mairie-panel-header">
          <div className="mairie-panel-title"><span>🤖</span><h2>Configuration IA</h2></div>
          <div className="mairie-panel-actions"><button className="mairie-btn-close" onClick={onFermer}>✕</button></div>
        </div>
        <div className="mairie-empty">Réservé aux administrateurs.</div>
      </div>
    )
  }

  return (
    <div className="mairie-panel">
      <div className="mairie-panel-header">
        <div className="mairie-panel-title"><span>🤖</span><h2>Configuration IA</h2></div>
        <div className="mairie-panel-actions">
          <button className="mairie-btn-close" onClick={onFermer}>✕</button>
        </div>
      </div>

      <div style={{ padding: '16px 20px', overflowY: 'auto' }}>
        {chargement && <div className="mairie-empty">Chargement…</div>}

        {!chargement && (
          <>
            {/* Presets */}
            <div style={{ marginBottom: 20 }}>
              <p style={{ fontSize: 12, color: '#72767d', margin: '0 0 10px' }}>Providers disponibles</p>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                {presets.map(p => (
                  <button
                    key={p.id}
                    onClick={() => appliquerPreset(p)}
                    style={{
                      padding: '6px 12px', fontSize: 12, borderRadius: 6, cursor: 'pointer',
                      background: form.base_url === p.base_url && form.provider === p.provider && form.model === p.model
                        ? '#5865F2' : '#2b2d31',
                      color: '#dcddde', border: '1px solid #4e5058',
                    }}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Formulaire */}
            <form onSubmit={sauvegarder} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <div>
                <label style={{ fontSize: 12, color: '#b9bbbe', display: 'block', marginBottom: 4 }}>Provider</label>
                <select
                  value={form.provider}
                  onChange={e => setForm(f => ({ ...f, provider: e.target.value }))}
                  style={{ width: '100%', background: '#1e2124', color: '#dcddde', border: '1px solid #4e5058', borderRadius: 6, padding: '8px 10px', fontSize: 13 }}
                >
                  <option value="anthropic">Anthropic (format natif)</option>
                  <option value="openai">OpenAI-compatible (Ollama, LM Studio, Groq, Together, Mistral…)</option>
                </select>
              </div>

              {form.provider === 'openai' && (
                <div>
                  <label style={{ fontSize: 12, color: '#b9bbbe', display: 'block', marginBottom: 4 }}>
                    URL de base de l'API
                    <span style={{ color: '#72767d', fontWeight: 400, marginLeft: 6 }}>ex. http://localhost:11434/v1</span>
                  </label>
                  <input
                    className="modal-input"
                    value={form.base_url}
                    onChange={e => setForm(f => ({ ...f, base_url: e.target.value }))}
                    placeholder="https://api.openai.com/v1"
                    style={{ fontFamily: 'monospace', fontSize: 12 }}
                  />
                </div>
              )}

              <div>
                <label style={{ fontSize: 12, color: '#b9bbbe', display: 'block', marginBottom: 4 }}>
                  Modèle
                  <span style={{ color: '#72767d', fontWeight: 400, marginLeft: 6 }}>ex. llama3, mistral, gpt-4o</span>
                </label>
                <input
                  className="modal-input"
                  value={form.model}
                  onChange={e => setForm(f => ({ ...f, model: e.target.value }))}
                  placeholder="claude-haiku-4-5-20251001"
                  style={{ fontFamily: 'monospace', fontSize: 12 }}
                  required
                />
              </div>

              <div>
                <label style={{ fontSize: 12, color: '#b9bbbe', display: 'block', marginBottom: 4 }}>
                  Clé API
                  <span style={{ color: '#72767d', fontWeight: 400, marginLeft: 6 }}>
                    {form.provider === 'openai' && form.base_url?.includes('localhost') ? 'Optionnelle pour les modèles locaux' : 'Requise'}
                  </span>
                </label>
                <input
                  className="modal-input"
                  type="password"
                  value={form.api_key}
                  onChange={e => setForm(f => ({ ...f, api_key: e.target.value }))}
                  placeholder={config?.api_key === '***' ? '(clé existante — laisser vide pour conserver)' : 'sk-…'}
                  style={{ fontFamily: 'monospace', fontSize: 12 }}
                  autoComplete="off"
                />
              </div>

              {config?.source === 'env' && (
                <div style={{ fontSize: 11, color: '#FAA61A', background: '#2b2d31', padding: '8px 12px', borderRadius: 6, borderLeft: '3px solid #FAA61A' }}>
                  ⚠️ Configuration active depuis les variables d'environnement. Sauvegarder pour surcharger par commune.
                </div>
              )}

              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                <button type="submit" className="mairie-btn-primary" disabled={sauvegarde}>
                  {sauvegarde ? 'Sauvegarde…' : '💾 Sauvegarder'}
                </button>
                <button type="button" className="mairie-btn-pdf" onClick={tester} disabled={testing}>
                  {testing ? '⏳ Test…' : '🔌 Tester la connexion'}
                </button>
                {config?.source === 'db' && (
                  <button type="button" className="mairie-btn-close" onClick={reinitialiser} style={{ fontSize: 12 }}>
                    🔄 Réinitialiser
                  </button>
                )}
              </div>

              {msg && <p style={{ fontSize: 12, color: msg.startsWith('✅') ? '#43B581' : '#F04747', margin: 0 }}>{msg}</p>}

              {testResult && (
                <div style={{ background: '#1e2124', borderRadius: 6, padding: 12, borderLeft: '3px solid #43B581' }}>
                  <p style={{ fontSize: 11, color: '#72767d', margin: '0 0 6px' }}>Réponse du modèle :</p>
                  <p style={{ fontSize: 12, color: '#dcddde', margin: 0, whiteSpace: 'pre-wrap' }}>{testResult}</p>
                </div>
              )}
            </form>

            {/* Aide */}
            <div style={{ marginTop: 24, borderTop: '1px solid #383a40', paddingTop: 16 }}>
              <p style={{ fontSize: 11, color: '#72767d', margin: '0 0 8px' }}>Exemples de configuration</p>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6, fontSize: 11, color: '#72767d', fontFamily: 'monospace' }}>
                <span>Ollama local : provider=openai, url=http://localhost:11434/v1, model=llama3</span>
                <span>LM Studio    : provider=openai, url=http://localhost:1234/v1, model=local-model</span>
                <span>Groq         : provider=openai, url=https://api.groq.com/openai/v1, clé=gsk_…</span>
                <span>Mistral      : provider=openai, url=https://api.mistral.ai/v1, clé=…</span>
                <span>Together.ai  : provider=openai, url=https://api.together.xyz/v1, clé=…</span>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { api, authHeaders } from '../services/api.js'

export default function LLMConfigPanel({ world, moi, onFermer }) {
  const { t } = useTranslation()
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
    setMsg(r?.ok ? t('llmConfig.saved') : t('llmConfig.saveError'))
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
    setTestResult(d?.response || d?.detail || t('llmConfig.testError'))
  }

  async function reinitialiser() {
    if (!confirm(t('llmConfig.confirmReset'))) return
    const r = await api.del(`/llm-config/${world.id}`)
    if (r?.ok) setMsg(t('llmConfig.resetDone'))
  }

  if (!isAdmin) {
    return (
      <div className="mairie-panel">
        <div className="mairie-panel-header">
          <div className="mairie-panel-title"><span>🤖</span><h2>{t('llmConfig.title')}</h2></div>
          <div className="mairie-panel-actions"><button className="mairie-btn-close" onClick={onFermer}>✕</button></div>
        </div>
        <div className="mairie-empty">{t('llmConfig.adminOnly')}</div>
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
        {chargement && <div className="mairie-empty">{t('llmConfig.loading')}</div>}

        {!chargement && (
          <>
            {/* Presets */}
            <div style={{ marginBottom: 20 }}>
              <p style={{ fontSize: 12, color: 'var(--text-mut)', margin: '0 0 10px' }}>{t('llmConfig.providers')}</p>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                {presets.map(p => (
                  <button
                    key={p.id}
                    onClick={() => appliquerPreset(p)}
                    style={{
                      padding: '6px 12px', fontSize: 12, borderRadius: 6, cursor: 'pointer',
                      background: form.base_url === p.base_url && form.provider === p.provider && form.model === p.model
                        ? 'var(--or-500)' : 'var(--ink-850)',
                      color: 'var(--text)', border: '1px solid var(--ink-650)',
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
                <label style={{ fontSize: 12, color: 'var(--text)', display: 'block', marginBottom: 4 }}>{t('llmConfig.provider')}</label>
                <select
                  value={form.provider}
                  onChange={e => setForm(f => ({ ...f, provider: e.target.value }))}
                  style={{ width: '100%', background: 'var(--ink-850)', color: 'var(--text)', border: '1px solid var(--ink-650)', borderRadius: 6, padding: '8px 10px', fontSize: 13 }}
                >
                  <option value="anthropic">{t('llmConfig.providerAnthropic')}</option>
                  <option value="openai">{t('llmConfig.providerOpenai')}</option>
                </select>
              </div>

              {form.provider === 'openai' && (
                <div>
                  <label style={{ fontSize: 12, color: 'var(--text)', display: 'block', marginBottom: 4 }}>
                    {t('llmConfig.baseUrl')}
                    <span style={{ color: 'var(--text-mut)', fontWeight: 400, marginLeft: 6 }}>{t('llmConfig.baseUrlHint')}</span>
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
                <label style={{ fontSize: 12, color: 'var(--text)', display: 'block', marginBottom: 4 }}>
                  {t('llmConfig.model')}
                  <span style={{ color: 'var(--text-mut)', fontWeight: 400, marginLeft: 6 }}>{t('llmConfig.modelHint')}</span>
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
                <label style={{ fontSize: 12, color: 'var(--text)', display: 'block', marginBottom: 4 }}>
                  {t('llmConfig.apiKey')}
                  <span style={{ color: 'var(--text-mut)', fontWeight: 400, marginLeft: 6 }}>
                    {form.provider === 'openai' && form.base_url?.includes('localhost') ? t('llmConfig.apiKeyOptional') : t('llmConfig.apiKeyRequired')}
                  </span>
                </label>
                <input
                  className="modal-input"
                  type="password"
                  value={form.api_key}
                  onChange={e => setForm(f => ({ ...f, api_key: e.target.value }))}
                  placeholder={config?.api_key === '***' ? t('llmConfig.apiKeyExisting') : 'sk-…'}
                  style={{ fontFamily: 'monospace', fontSize: 12 }}
                  autoComplete="off"
                />
              </div>

              {config?.source === 'env' && (
                <div style={{ fontSize: 11, color: 'var(--or-400)', background: 'var(--ink-850)', padding: '8px 12px', borderRadius: 6, borderLeft: '3px solid var(--or-400)' }}>
                  {t('llmConfig.envWarning')}
                </div>
              )}

              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                <button type="submit" className="mairie-btn-primary" disabled={sauvegarde}>
                  {sauvegarde ? t('llmConfig.saving') : t('llmConfig.save')}
                </button>
                <button type="button" className="mairie-btn-pdf" onClick={tester} disabled={testing}>
                  {testing ? t('llmConfig.testing') : t('llmConfig.test')}
                </button>
                {config?.source === 'db' && (
                  <button type="button" className="mairie-btn-close" onClick={reinitialiser} style={{ fontSize: 12 }}>
                    {t('llmConfig.reset')}
                  </button>
                )}
              </div>

              {msg && <p style={{ fontSize: 12, color: msg.startsWith('✅') ? 'var(--vert)' : 'var(--rouge)', margin: 0 }}>{msg}</p>}

              {testResult && (
                <div style={{ background: 'var(--ink-850)', borderRadius: 6, padding: 12, borderLeft: '3px solid var(--vert)' }}>
                  <p style={{ fontSize: 11, color: 'var(--text-mut)', margin: '0 0 6px' }}>{t('llmConfig.modelResponse')}</p>
                  <p style={{ fontSize: 12, color: 'var(--text)', margin: 0, whiteSpace: 'pre-wrap' }}>{testResult}</p>
                </div>
              )}
            </form>

            {/* Aide */}
            <div style={{ marginTop: 24, borderTop: '1px solid var(--ink-700)', paddingTop: 16 }}>
              <p style={{ fontSize: 11, color: 'var(--text-mut)', margin: '0 0 8px' }}>{t('llmConfig.examplesTitle')}</p>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6, fontSize: 11, color: 'var(--text-mut)', fontFamily: 'monospace' }}>
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

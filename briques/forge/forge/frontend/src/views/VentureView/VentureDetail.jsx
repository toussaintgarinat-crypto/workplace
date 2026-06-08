import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { venturesApi, api, token, llmConfigApi, providerModelsApi } from '../../services/api'
import styles from './Venture.module.css'

const POLE_TYPES = [
  { value: 'finance',   label: 'Finance',    emoji: '📊' },
  { value: 'marketing', label: 'Marketing',   emoji: '🚀' },
  { value: 'sales',     label: 'Sales',       emoji: '🤝' },
  { value: 'ops',       label: 'Opérations',  emoji: '⚙️' },
  { value: 'legal',     label: 'Juridique',   emoji: '🛡️' },
  { value: 'dev',       label: 'Dev',         emoji: '💻' },
  { value: 'custom',    label: 'Autre',       emoji: '🌍' },
]

// ── Gouvernance IA ────────────────────────────────────────────

function GovernanceTab({ ventureId }) {
  const [activeSection, setActiveSection] = useState('mcp')
  const [mcpServers, setMcpServers] = useState([])
  const [skills, setSkills]         = useState([])
  const [mcpForm, setMcpForm]       = useState({ nom: '', url: '', authType: 'none', authToken: '' })
  const [skillForm, setSkillForm]   = useState({ nom: '', description: '', skillMd: '' })
  const [showMcpForm, setShowMcpForm]     = useState(false)
  const [showSkillForm, setShowSkillForm] = useState(false)

  useEffect(() => {
    api.get(`/api/mcp/servers?ventureId=${ventureId}`).then(setMcpServers).catch(() => {})
    api.get(`/api/skills?ventureId=${ventureId}`).then(setSkills).catch(() => {})
  }, [ventureId])

  async function addMcp(e) {
    e.preventDefault()
    const s = await api.post('/api/mcp/servers', { ...mcpForm, ventureId })
    setMcpServers(prev => [...prev, s])
    setMcpForm({ nom: '', url: '', authType: 'none', authToken: '' })
    setShowMcpForm(false)
  }

  async function deleteMcp(id) {
    await api.delete(`/api/mcp/servers/${id}`)
    setMcpServers(prev => prev.filter(s => s.id !== id))
  }

  async function addSkill(e) {
    e.preventDefault()
    const s = await api.post('/api/skills', { ...skillForm, tags: [], actif: true, ventureId })
    setSkills(prev => [...prev, s])
    setSkillForm({ nom: '', description: '', skillMd: '' })
    setShowSkillForm(false)
  }

  async function toggleSkill(id, actif) {
    const updated = await api.patch(`/api/skills/${id}`, { actif: !actif })
    setSkills(prev => prev.map(s => s.id === id ? updated : s))
  }

  async function deleteSkill(id) {
    await api.delete(`/api/skills/${id}`)
    setSkills(prev => prev.filter(s => s.id !== id))
  }

  return (
    <div className={styles.govTab}>
      <div className={styles.govNav}>
        <button className={`${styles.govNavBtn} ${activeSection === 'mcp' ? styles.govNavActive : ''}`} onClick={() => setActiveSection('mcp')}>
          🔌 Serveurs MCP
        </button>
        <button className={`${styles.govNavBtn} ${activeSection === 'skills' ? styles.govNavActive : ''}`} onClick={() => setActiveSection('skills')}>
          🧩 Skills
        </button>
      </div>

      {activeSection === 'mcp' && (
        <div className={styles.govSection}>
          <div className={styles.govSectionHeader}>
            <span className={styles.govSectionTitle}>Serveurs MCP — {ventureId.slice(0, 8)}…</span>
            <button className={styles.btnPrimary} onClick={() => setShowMcpForm(v => !v)}>+ Ajouter</button>
          </div>
          {showMcpForm && (
            <form className={styles.govForm} onSubmit={addMcp}>
              <input className={styles.input} placeholder="Nom *" required value={mcpForm.nom}
                onChange={e => setMcpForm(f => ({ ...f, nom: e.target.value }))} />
              <input className={styles.input} placeholder="URL *" required value={mcpForm.url}
                onChange={e => setMcpForm(f => ({ ...f, url: e.target.value }))} />
              <select className={styles.select} value={mcpForm.authType}
                onChange={e => setMcpForm(f => ({ ...f, authType: e.target.value }))}>
                <option value="none">Pas d'auth</option>
                <option value="bearer">Bearer token</option>
                <option value="basic">Basic auth</option>
              </select>
              {mcpForm.authType !== 'none' && (
                <input className={styles.input} placeholder="Token / mot de passe" value={mcpForm.authToken}
                  onChange={e => setMcpForm(f => ({ ...f, authToken: e.target.value }))} />
              )}
              <div className={styles.formActions}>
                <button type="submit" className={styles.btnPrimary}>Ajouter</button>
                <button type="button" className={styles.btnGhost} onClick={() => setShowMcpForm(false)}>Annuler</button>
              </div>
            </form>
          )}
          {mcpServers.length === 0 && !showMcpForm && (
            <p className={styles.govEmpty}>Aucun serveur MCP pour cette venture.</p>
          )}
          {mcpServers.map(s => (
            <div key={s.id} className={styles.govCard}>
              <div className={styles.govCardInfo}>
                <div className={styles.govCardName}>{s.nom}</div>
                <div className={styles.govCardUrl}>{s.url}</div>
              </div>
              <div className={styles.govCardActions}>
                <span className={`${styles.govBadge} ${s.actif ? styles.govBadgeGreen : styles.govBadgeGray}`}>
                  {s.actif ? 'Actif' : 'Inactif'}
                </span>
                <button className={styles.govDelete} onClick={() => deleteMcp(s.id)}>✕</button>
              </div>
            </div>
          ))}
        </div>
      )}

      {activeSection === 'skills' && (
        <div className={styles.govSection}>
          <div className={styles.govSectionHeader}>
            <span className={styles.govSectionTitle}>Skills de cette venture</span>
            <button className={styles.btnPrimary} onClick={() => setShowSkillForm(v => !v)}>+ Créer</button>
          </div>
          {showSkillForm && (
            <form className={styles.govForm} onSubmit={addSkill}>
              <input className={styles.input} placeholder="Nom *" required value={skillForm.nom}
                onChange={e => setSkillForm(f => ({ ...f, nom: e.target.value }))} />
              <input className={styles.input} placeholder="Description" value={skillForm.description}
                onChange={e => setSkillForm(f => ({ ...f, description: e.target.value }))} />
              <textarea className={styles.textarea} placeholder="Contenu SKILL.md *" required rows={6} value={skillForm.skillMd}
                onChange={e => setSkillForm(f => ({ ...f, skillMd: e.target.value }))} />
              <div className={styles.formActions}>
                <button type="submit" className={styles.btnPrimary}>Créer</button>
                <button type="button" className={styles.btnGhost} onClick={() => setShowSkillForm(false)}>Annuler</button>
              </div>
            </form>
          )}
          {skills.length === 0 && !showSkillForm && (
            <p className={styles.govEmpty}>Aucun skill pour cette venture.</p>
          )}
          {skills.map(s => (
            <div key={s.id} className={styles.govCard}>
              <div className={styles.govCardInfo}>
                <div className={styles.govCardName}>{s.nom}</div>
                {s.description && <div className={styles.govCardUrl}>{s.description}</div>}
              </div>
              <div className={styles.govCardActions}>
                <button className={`${styles.govBadge} ${s.actif ? styles.govBadgeGreen : styles.govBadgeGray}`}
                  onClick={() => toggleSkill(s.id, s.actif)}>
                  {s.actif ? 'Actif' : 'Inactif'}
                </button>
                <button className={styles.govDelete} onClick={() => deleteSkill(s.id)}>✕</button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Morning Brief venture ─────────────────────────────────────

function VentureBrief({ ventureId }) {
  const [brief, setBrief]       = useState(null)
  const [loading, setLoading]   = useState(false)
  const [open, setOpen]         = useState(false)

  async function generate() {
    setLoading(true)
    try {
      const res = await api.post('/api/brief/generate', { ventureId })
      setBrief(res.brief)
      setOpen(true)
    } finally { setLoading(false) }
  }

  return (
    <div className={styles.ventureBrief}>
      <div className={styles.ventureBriefHeader}>
        <span className={styles.ventureBriefTitle}>☀️ Morning Brief</span>
        <button className={styles.btnPrimary} onClick={generate} disabled={loading}>
          {loading ? 'Génération…' : 'Générer'}
        </button>
        {brief && (
          <button className={styles.btnGhost} onClick={() => setOpen(v => !v)}>
            {open ? 'Masquer' : 'Voir'}
          </button>
        )}
      </div>
      {brief && open && (
        <div className={styles.ventureBriefContent}>{brief}</div>
      )}
    </div>
  )
}

// ── Onglet LLM ────────────────────────────────────────────────

const SCOPE_LABELS = { venture: 'Venture (défaut)', pole: 'Pôle', tool: 'Outil', agent: 'Agent' }

function LlmPresetForm({ ventureId, scopeType, scopeId, scopeLabel, existing, onSaved }) {
  const [providers, setProviders]     = useState([])
  const [modelOptions, setModelOptions] = useState([])
  const [form, setForm] = useState({
    provider: existing?.provider ?? 'ollama',
    model: existing?.model ?? '',
    apiKey: existing?.apiKey ?? '',
    baseUrl: existing?.baseUrl ?? '',
    maxTokens: existing?.maxTokens ?? 2048,
    budgetDaily: existing?.budgetDaily ?? '',
    budgetMonthly: existing?.budgetMonthly ?? '',
  })
  const [saving, setSaving] = useState(false)
  const [open, setOpen] = useState(false)

  useEffect(() => {
    llmConfigApi.providers().then(setProviders).catch(() => {})
  }, [])

  useEffect(() => {
    if (!form.provider) return
    providerModelsApi.list(form.provider)
      .then(data => setModelOptions(data.models ?? []))
      .catch(() => {
        const fallback = providers.find(p => p.id === form.provider)?.models ?? []
        setModelOptions(fallback)
      })
  }, [form.provider, providers])

  async function save(e) {
    e.preventDefault()
    setSaving(true)
    try {
      await api.put('/api/llm-config/preset', {
        scopeType, scopeId, ventureId,
        provider: form.provider,
        model: form.model || modelOptions[0] || 'llama3.2',
        apiKey: form.apiKey,
        baseUrl: form.baseUrl,
        maxTokens: Number(form.maxTokens),
        ...(scopeType === 'venture' && form.budgetDaily   ? { budgetDaily:   Number(form.budgetDaily) }   : {}),
        ...(scopeType === 'venture' && form.budgetMonthly ? { budgetMonthly: Number(form.budgetMonthly) } : {}),
      })
      onSaved?.()
      setOpen(false)
    } finally { setSaving(false) }
  }

  return (
    <div className={styles.llmPresetRow}>
      <div className={styles.llmPresetHeader} onClick={() => setOpen(v => !v)}>
        <span className={styles.llmPresetScope}>{SCOPE_LABELS[scopeType] ?? scopeType}</span>
        <span className={styles.llmPresetLabel}>{scopeLabel}</span>
        {existing
          ? <span className={styles.llmPresetBadge}>{existing.provider} / {existing.model}</span>
          : <span className={styles.llmPresetBadgeEmpty}>hérité</span>}
        <span className={styles.llmPresetChevron}>{open ? '▾' : '▸'}</span>
      </div>
      {open && (
        <form className={styles.llmPresetForm} onSubmit={save}>
          <div className={styles.llmRow}>
            <select className={styles.select} value={form.provider}
              onChange={e => setForm(f => ({ ...f, provider: e.target.value, model: '' }))}>
              {providers.map(p => <option key={p.id} value={p.id}>{p.label}</option>)}
            </select>
            {modelOptions.length > 12 ? (
              <>
                <input
                  className={styles.input}
                  style={{ flex: 1 }}
                  placeholder="Rechercher un modèle…"
                  list={`models-${scopeId}`}
                  value={form.model}
                  onChange={e => setForm(f => ({ ...f, model: e.target.value }))}
                />
                <datalist id={`models-${scopeId}`}>
                  {modelOptions.map(m => <option key={m} value={m} />)}
                </datalist>
              </>
            ) : (
              <select className={styles.select} value={form.model}
                onChange={e => setForm(f => ({ ...f, model: e.target.value }))}>
                <option value="">— modèle —</option>
                {modelOptions.map(m => <option key={m} value={m}>{m}</option>)}
              </select>
            )}
          </div>
          <input className={styles.input} placeholder="API Key (optionnel)" value={form.apiKey}
            onChange={e => setForm(f => ({ ...f, apiKey: e.target.value }))} />
          {['ollama', 'lmstudio'].includes(form.provider) && (
            <input className={styles.input} placeholder="Base URL" value={form.baseUrl}
              onChange={e => setForm(f => ({ ...f, baseUrl: e.target.value }))} />
          )}
          <div className={styles.llmRow}>
            <label className={styles.llmLabel}>
              Max tokens
              <input type="number" className={styles.input} value={form.maxTokens} min={256} max={128000}
                onChange={e => setForm(f => ({ ...f, maxTokens: e.target.value }))} />
            </label>
            {scopeType === 'venture' && (
              <>
                <label className={styles.llmLabel}>
                  Budget/jour (USD)
                  <input type="number" className={styles.input} placeholder="ex: 5" value={form.budgetDaily} step="0.01"
                    onChange={e => setForm(f => ({ ...f, budgetDaily: e.target.value }))} />
                </label>
                <label className={styles.llmLabel}>
                  Budget/mois (USD)
                  <input type="number" className={styles.input} placeholder="ex: 50" value={form.budgetMonthly} step="0.01"
                    onChange={e => setForm(f => ({ ...f, budgetMonthly: e.target.value }))} />
                </label>
              </>
            )}
          </div>
          <div className={styles.formActions}>
            <button type="submit" className={styles.btnPrimary} disabled={saving}>{saving ? '…' : 'Enregistrer'}</button>
            <button type="button" className={styles.btnGhost} onClick={() => setOpen(false)}>Annuler</button>
          </div>
        </form>
      )}
    </div>
  )
}

function LlmTab({ ventureId, poles }) {
  const [presets, setPresets] = useState([])

  function reload() {
    api.get(`/api/llm-config/venture/${ventureId}`).then(setPresets).catch(() => {})
  }
  useEffect(reload, [ventureId])

  function presetFor(scopeType, scopeId) {
    return presets.find(p => p.scopeType === scopeType && p.scopeId === scopeId) ?? null
  }

  return (
    <div className={styles.llmTab}>
      <p className={styles.llmHint}>
        La config la plus précise gagne — agent › outil › pôle › venture. La venture sert de défaut global.
      </p>

      <div className={styles.llmSection}>
        <div className={styles.llmSectionTitle}>🚀 Défaut Venture</div>
        <LlmPresetForm
          ventureId={ventureId}
          scopeType="venture"
          scopeId={ventureId}
          scopeLabel="Config par défaut"
          existing={presetFor('venture', ventureId)}
          onSaved={reload}
        />
      </div>

      <div className={styles.llmSection}>
        <div className={styles.llmSectionTitle}>🏛 Overrides par pôle</div>
        {poles.map(pole => (
          <LlmPresetForm
            key={pole.id}
            ventureId={ventureId}
            scopeType="pole"
            scopeId={pole.id}
            scopeLabel={`${pole.emoji} ${pole.nom}`}
            existing={presetFor('pole', pole.id)}
            onSaved={reload}
          />
        ))}
        {poles.length === 0 && <p className={styles.govEmpty}>Aucun pôle dans cette venture.</p>}
      </div>
    </div>
  )
}

// ── Vue principale ─────────────────────────────────────────────

export default function VentureDetail() {
  const { ventureId } = useParams()
  const navigate = useNavigate()
  const [venture, setVenture]   = useState(null)
  const [poles, setPoles]       = useState([])
  const [loading, setLoading]   = useState(true)
  const [activeTab, setActiveTab] = useState('poles')
  const [showForm, setShowForm] = useState(false)
  const [saving, setSaving]     = useState(false)
  const [form, setForm]         = useState({ nom: '', emoji: '🌍', couleur: '#6366f1', type: 'custom', description: '' })

  useEffect(() => {
    Promise.all([
      venturesApi.get(ventureId),
      venturesApi.poles(ventureId),
    ]).then(([v, ps]) => {
      setVenture(v)
      setPoles(Array.isArray(ps) ? ps : [])
    }).catch(() => {}).finally(() => setLoading(false))
  }, [ventureId])

  async function createPole(e) {
    e.preventDefault()
    setSaving(true)
    try {
      const pole = await venturesApi.createPole(ventureId, form)
      setPoles(ps => [...ps, pole])
      setForm({ nom: '', emoji: '🌍', couleur: '#6366f1', type: 'custom', description: '' })
      setShowForm(false)
    } finally { setSaving(false) }
  }

  if (loading) return <div className={styles.page}><p style={{ color: 'var(--text-muted)', padding: 24 }}>Chargement...</p></div>
  if (!venture) return <div className={styles.page}><p style={{ color: 'var(--text-muted)', padding: 24 }}>Venture introuvable.</p></div>

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <button
            onClick={() => navigate('/ventures')}
            style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: 18 }}
          >←</button>
          <span style={{ fontSize: 28 }}>{venture.emoji}</span>
          <div>
            <h1 className={styles.title} style={{ margin: 0 }}>{venture.nom}</h1>
            <span className={styles.typeChip}
              style={{ background: venture.type === 'audit' ? '#f59e0b22' : '#818cf822', color: venture.type === 'audit' ? '#f59e0b' : '#818cf8' }}>
              {venture.type === 'audit' ? '🔍 Mission Audit' : '🏠 Own Venture'}
            </span>
          </div>
        </div>
        {activeTab === 'poles' && (
          <button className={styles.btnPrimary} onClick={() => setShowForm(v => !v)}>+ Nouveau pôle</button>
        )}
      </div>

      {venture.description && (
        <p style={{ color: 'var(--text-muted)', fontSize: 14, marginBottom: 16 }}>{venture.description}</p>
      )}

      <div className={styles.tabsBar}>
        <button className={`${styles.tab} ${activeTab === 'poles' ? styles.tabActive : ''}`} onClick={() => setActiveTab('poles')}>
          🏛 Pôles
        </button>
        <button className={`${styles.tab} ${activeTab === 'governance' ? styles.tabActive : ''}`} onClick={() => setActiveTab('governance')}>
          🧠 Gouvernance IA
        </button>
        <button className={`${styles.tab} ${activeTab === 'llm' ? styles.tabActive : ''}`} onClick={() => setActiveTab('llm')}>
          🤖 LLM
        </button>
      </div>

      {activeTab === 'poles' && (
        <>
          <VentureBrief ventureId={ventureId} />

          {showForm && (
            <form className={styles.form} onSubmit={createPole}>
              <div className={styles.formRow}>
                <input className={styles.inputEmoji} value={form.emoji}
                  onChange={e => setForm(f => ({ ...f, emoji: e.target.value }))} />
                <input className={styles.input} placeholder="Nom du pôle *" required value={form.nom}
                  onChange={e => setForm(f => ({ ...f, nom: e.target.value }))} style={{ flex: 1 }} />
                <select className={styles.select} value={form.type} onChange={e => {
                  const t = POLE_TYPES.find(p => p.value === e.target.value)
                  setForm(f => ({ ...f, type: e.target.value, emoji: t?.emoji ?? f.emoji }))
                }}>
                  {POLE_TYPES.map(t => <option key={t.value} value={t.value}>{t.emoji} {t.label}</option>)}
                </select>
                <input type="color" value={form.couleur}
                  onChange={e => setForm(f => ({ ...f, couleur: e.target.value }))}
                  style={{ width: 36, height: 36, border: 'none', background: 'none', cursor: 'pointer', borderRadius: 6 }} />
              </div>
              <input className={styles.input} placeholder="Description (optionnel)" value={form.description}
                onChange={e => setForm(f => ({ ...f, description: e.target.value }))} />
              <div className={styles.formActions}>
                <button type="submit" className={styles.btnPrimary} disabled={saving}>{saving ? '...' : 'Créer le pôle'}</button>
                <button type="button" className={styles.btnGhost} onClick={() => setShowForm(false)}>Annuler</button>
              </div>
            </form>
          )}

          <div className={styles.grid}>
            {poles.map(pole => (
              <div
                key={pole.id}
                className={styles.ventureCard}
                style={{ borderLeftColor: pole.couleur, cursor: 'pointer' }}
                onClick={() => navigate(`/ventures/${ventureId}/poles/${pole.id}`)}
              >
                <div className={styles.ventureIcon}>{pole.emoji}</div>
                <div className={styles.ventureInfo}>
                  <div className={styles.ventureName}>{pole.nom}</div>
                  {pole.description && <div className={styles.ventureDesc}>{pole.description}</div>}
                  <div className={styles.ventureMeta}>
                    <span className={styles.typeChip} style={{ background: '#818cf822', color: '#818cf8' }}>
                      {POLE_TYPES.find(t => t.value === pole.type)?.label ?? pole.type}
                    </span>
                  </div>
                </div>
                <span style={{ color: 'var(--text-muted)', fontSize: 18 }}>→</span>
              </div>
            ))}
          </div>

          {poles.length === 0 && !showForm && (
            <div className={styles.empty}>
              <p>Aucun pôle dans cette venture.</p>
              <p className={styles.hint}>Créez un premier pôle pour commencer à organiser votre travail.</p>
            </div>
          )}
        </>
      )}

      {activeTab === 'governance' && <GovernanceTab ventureId={ventureId} />}
      {activeTab === 'llm' && <LlmTab ventureId={ventureId} poles={poles} />}
    </div>
  )
}

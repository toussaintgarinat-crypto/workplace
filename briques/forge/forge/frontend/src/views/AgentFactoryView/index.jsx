import { useState, useEffect, useCallback } from 'react'
import { DndContext, closestCenter, PointerSensor, useSensor, useSensors } from '@dnd-kit/core'
import { SortableContext, useSortable, verticalListSortingStrategy, arrayMove } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { token } from '../../services/api'
import styles from './AgentFactory.module.css'

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

const NIVEAU_META = {
  local:  { label: 'Local',  color: '#10b981', desc: 'Ollama / LM Studio' },
  medium: { label: 'Groq',   color: '#f59e0b', desc: 'Groq (llama 70B)' },
  api:    { label: 'API',    color: '#a78bfa', desc: 'Claude / OpenAI' },
}
const STATUT_META = {
  active:   { label: 'Actif',     color: '#10b981' },
  draft:    { label: 'Brouillon', color: '#f59e0b' },
  error:    { label: 'Erreur',    color: '#ef4444' },
  disabled: { label: 'Désactivé', color: '#6b7280' },
}

const BLANK_FORM = { nom: '', description: '', instructions: '', niveau: 'medium', llmPreset: '', personalityId: '' }
const BLANK_PERSO_FORM = { label: '', emoji: '🤖', description: '', systemPrompt: '' }

function SortablePersoItem({ p, isActive, onClick, onEdit, onDelete }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: p.id })
  const style = { transform: CSS.Transform.toString(transform), transition, opacity: isDragging ? 0.5 : 1 }
  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`${styles.agentItem} ${isActive ? styles.agentActive : ''}`}
      onClick={onClick}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span {...attributes} {...listeners} style={{ cursor: 'grab', color: '#4b5563', fontSize: 14, userSelect: 'none' }} title="Réordonner">⠿</span>
          <span className={styles.agentNom}>{p.emoji} {p.label}</span>
        </div>
        {p.isBuiltin ? (
          <span className={styles.badge} style={{ background: '#818cf822', color: '#818cf8' }}>Builtin</span>
        ) : (
          <span className={styles.badge} style={{ background: '#10b98122', color: '#10b981' }}>Custom</span>
        )}
      </div>
      {p.description && <div className={styles.agentDesc}>{p.description}</div>}
    </div>
  )
}

export default function AgentFactoryView() {
  const [tab, setTab]                   = useState('agents')
  const [agents, setAgents]             = useState([])
  const [templates, setTemplates]       = useState([])
  const [stats, setStats]               = useState({})
  const [personalities, setPersonalities] = useState([])
  const [selected, setSelected]         = useState(null)
  const [showForm, setShowForm]         = useState(false)
  const [form, setForm]                 = useState(BLANK_FORM)
  const [filterSt, setFilterSt]         = useState('')
  const [loading, setLoading]           = useState(false)

  // Personnalités state
  const [selectedPerso, setSelectedPerso] = useState(null)
  const [showPersoForm, setShowPersoForm] = useState(false)
  const [persoForm, setPersoForm]         = useState(BLANK_PERSO_FORM)
  const [editingPersoId, setEditingPersoId] = useState(null)
  const [persoLoading, setPersoLoading]   = useState(false)

  const dndSensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }))

  const load = useCallback(async () => {
    const params = new URLSearchParams()
    if (filterSt) params.set('statut', filterSt)
    const { items, stats: s } = await req(`/api/agent-factory?${params}`).catch(() => ({ items: [], stats: {} }))
    setAgents(items ?? [])
    setStats(s ?? {})
  }, [filterSt])

  const loadPersonalities = useCallback(async () => {
    const items = await req('/api/personalities').catch(() => [])
    setPersonalities(items ?? [])
  }, [])

  useEffect(() => { load() }, [load])
  useEffect(() => { loadPersonalities() }, [loadPersonalities])
  useEffect(() => {
    req('/api/agent-factory/templates').then(setTemplates).catch(() => {})
  }, [])

  function useTemplate(tpl) {
    setForm({ nom: tpl.nom, description: tpl.description, instructions: tpl.instructions, niveau: tpl.niveau, llmPreset: '', personalityId: '' })
    setShowForm(true)
    setTab('agents')
  }

  async function create(e) {
    e.preventDefault()
    setLoading(true)
    try {
      const payload = { ...form, personalityId: form.personalityId || undefined }
      const a = await req('/api/agent-factory', { method: 'POST', body: JSON.stringify(payload) })
      setAgents(prev => [a, ...prev])
      setSelected(a)
      setForm(BLANK_FORM)
      setShowForm(false)
    } finally { setLoading(false) }
  }

  async function updateStatut(id, statut) {
    const a = await req(`/api/agent-factory/${id}`, { method: 'PATCH', body: JSON.stringify({ statut }) })
    setAgents(prev => prev.map(x => x.id === id ? a : x))
    if (selected?.id === id) setSelected(a)
  }

  async function remove(id) {
    if (!confirm('Supprimer cet agent ?')) return
    await req(`/api/agent-factory/${id}`, { method: 'DELETE' })
    setAgents(prev => prev.filter(a => a.id !== id))
    if (selected?.id === id) setSelected(null)
  }

  async function assignPersonality(agentId, personalityId) {
    const a = await req(`/api/agent-factory/${agentId}`, {
      method: 'PATCH',
      body: JSON.stringify({ personalityId: personalityId || null }),
    })
    setAgents(prev => prev.map(x => x.id === agentId ? a : x))
    if (selected?.id === agentId) setSelected(a)
  }

  // Personnalités CRUD
  function openCreatePerso() {
    setEditingPersoId(null)
    setPersoForm(BLANK_PERSO_FORM)
    setShowPersoForm(true)
  }

  function openEditPerso(p) {
    setEditingPersoId(p.id)
    setPersoForm({ label: p.label, emoji: p.emoji ?? '🤖', description: p.description ?? '', systemPrompt: p.systemPrompt ?? '' })
    setShowPersoForm(true)
  }

  async function savePerso(e) {
    e.preventDefault()
    setPersoLoading(true)
    try {
      if (editingPersoId) {
        const p = await req(`/api/personalities/${editingPersoId}`, { method: 'PUT', body: JSON.stringify(persoForm) })
        setPersonalities(prev => prev.map(x => x.id === editingPersoId ? p : x))
        if (selectedPerso?.id === editingPersoId) setSelectedPerso(p)
      } else {
        const p = await req('/api/personalities', { method: 'POST', body: JSON.stringify(persoForm) })
        setPersonalities(prev => [...prev, p])
        setSelectedPerso(p)
      }
      setShowPersoForm(false)
    } finally { setPersoLoading(false) }
  }

  async function deletePerso(id) {
    if (!confirm('Supprimer cette personnalité ?')) return
    await req(`/api/personalities/${id}`, { method: 'DELETE' })
    setPersonalities(prev => prev.filter(p => p.id !== id))
    if (selectedPerso?.id === id) setSelectedPerso(null)
  }

  async function handlePersoDragEnd({ active: a, over }) {
    if (!over || a.id === over.id) return
    const oldIdx = personalities.findIndex(p => p.id === a.id)
    const newIdx = personalities.findIndex(p => p.id === over.id)
    const reordered = arrayMove(personalities, oldIdx, newIdx)
    setPersonalities(reordered)
    try {
      await req('/api/personalities/reorder', { method: 'PATCH', body: JSON.stringify({ ids: reordered.map(p => p.id) }) })
    } catch { loadPersonalities() }
  }

  const getPersonalityLabel = (id) => {
    const p = personalities.find(p => p.id === id)
    return p ? `${p.emoji} ${p.label}` : null
  }

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <span className={styles.icon}>🤖</span>
        <div>
          <div className={styles.title}>Agent Factory</div>
          <div className={styles.subtitle}>Créer et gérer des agents autonomes</div>
        </div>
        <div className={styles.headerActions}>
          <div className={styles.statsRow}>
            <span className={styles.chip}>{stats.total ?? 0} agents</span>
            <span className={styles.chip} style={{ color: '#10b981' }}>{stats.actifs ?? 0} actifs</span>
            <span className={styles.chip} style={{ color: '#f59e0b' }}>{stats.drafts ?? 0} brouillons</span>
          </div>
          {tab === 'agents' && (
            <button className={styles.btnPrimary} onClick={() => setShowForm(v => !v)}>+ Agent</button>
          )}
          {tab === 'personalities' && (
            <button className={styles.btnPrimary} onClick={openCreatePerso}>+ Personnalité</button>
          )}
        </div>
      </header>

      {/* Tabs */}
      <div className={styles.tabBar}>
        <button className={`${styles.tabBtn} ${tab === 'agents' ? styles.tabActive : ''}`} onClick={() => setTab('agents')}>
          Mes agents
          {(stats.total ?? 0) > 0 && <span className={styles.tabCount}>{stats.total}</span>}
        </button>
        <button className={`${styles.tabBtn} ${tab === 'templates' ? styles.tabActive : ''}`} onClick={() => setTab('templates')}>
          Templates
          {templates.length > 0 && <span className={styles.tabCount}>{templates.length}</span>}
        </button>
        <button className={`${styles.tabBtn} ${tab === 'personalities' ? styles.tabActive : ''}`} onClick={() => setTab('personalities')}>
          Personnalités
          {personalities.length > 0 && <span className={styles.tabCount}>{personalities.length}</span>}
        </button>
      </div>

      {/* ── Onglet Mes agents ── */}
      {tab === 'agents' && (
        <>
          <div className={styles.filterBar}>
            {['', 'active', 'draft', 'disabled', 'error'].map(s => (
              <button key={s} className={`${styles.filterBtn} ${filterSt === s ? styles.filterActive : ''}`} onClick={() => setFilterSt(s)}>
                {s ? STATUT_META[s]?.label : 'Tous'}
              </button>
            ))}
          </div>

          {showForm && (
            <form className={styles.form} onSubmit={create}>
              <input className={styles.input} placeholder="Nom de l'agent *" required value={form.nom} onChange={e => setForm(f => ({ ...f, nom: e.target.value }))} />
              <input className={styles.input} placeholder="Description courte" value={form.description} onChange={e => setForm(f => ({ ...f, description: e.target.value }))} />
              <textarea className={styles.textarea} placeholder="Instructions supplémentaires (optionnel — la personnalité sélectionnée fournit le comportement de base)" value={form.instructions} onChange={e => setForm(f => ({ ...f, instructions: e.target.value }))} />
              <div style={{ display: 'flex', gap: 8 }}>
                <select className={styles.select} value={form.niveau} onChange={e => setForm(f => ({ ...f, niveau: e.target.value }))}>
                  {Object.entries(NIVEAU_META).map(([k, v]) => <option key={k} value={k}>{v.label} — {v.desc}</option>)}
                </select>
                <select className={styles.select} value={form.personalityId} onChange={e => setForm(f => ({ ...f, personalityId: e.target.value }))}>
                  <option value="">Aucune personnalité</option>
                  {personalities.map(p => (
                    <option key={p.id} value={p.id}>{p.emoji} {p.label}</option>
                  ))}
                </select>
              </div>
              <div className={styles.formActions}>
                <button type="submit" className={styles.btnPrimary} disabled={loading}>Créer</button>
                <button type="button" className={styles.btnGhost} onClick={() => { setShowForm(false); setForm(BLANK_FORM) }}>Annuler</button>
              </div>
            </form>
          )}

          <div className={styles.layout}>
            <div className={styles.list}>
              {agents.length === 0 && (
                <div className={styles.empty}>
                  Aucun agent.{' '}
                  <button className={styles.linkBtn} onClick={() => setTab('templates')}>Partir d'un template →</button>
                </div>
              )}
              {agents.map(a => {
                const niv = NIVEAU_META[a.niveau] ?? NIVEAU_META.medium
                const st  = STATUT_META[a.statut] ?? STATUT_META.draft
                return (
                  <div key={a.id} className={`${styles.agentItem} ${selected?.id === a.id ? styles.agentActive : ''}`} onClick={() => setSelected(a)}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                      <span className={styles.agentNom}>{a.nom}</span>
                      <span className={styles.badge} style={{ background: st.color + '22', color: st.color }}>{st.label}</span>
                    </div>
                    {a.description && <div className={styles.agentDesc}>{a.description}</div>}
                    <div className={styles.agentMeta}>
                      <span style={{ color: niv.color }}>⚡ {niv.label}</span>
                      {a.personalityId && (
                        <span style={{ color: '#818cf8', marginLeft: 8 }}>{getPersonalityLabel(a.personalityId)}</span>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>

            {selected && (() => {
              const niv = NIVEAU_META[selected.niveau] ?? NIVEAU_META.medium
              const st  = STATUT_META[selected.statut] ?? STATUT_META.draft
              return (
                <div className={styles.detail}>
                  <div className={styles.detailHeader}>
                    <div>
                      <h2 className={styles.detailNom}>{selected.nom}</h2>
                      <span className={styles.badge} style={{ background: st.color + '22', color: st.color }}>{st.label}</span>
                    </div>
                    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                      {selected.statut === 'draft'    && <button className={styles.btnSecondary} onClick={() => updateStatut(selected.id, 'active')}>▶ Activer</button>}
                      {selected.statut === 'active'   && <button className={styles.btnSecondary} onClick={() => updateStatut(selected.id, 'disabled')}>⏸ Désactiver</button>}
                      {selected.statut === 'disabled' && <button className={styles.btnSecondary} onClick={() => updateStatut(selected.id, 'active')}>▶ Réactiver</button>}
                      <button className={styles.btnDanger} onClick={() => remove(selected.id)}>✕</button>
                    </div>
                  </div>

                  <div className={styles.infoGrid}>
                    <div className={styles.infoBlock}>
                      <div className={styles.infoLabel}>Niveau LLM</div>
                      <div style={{ color: niv.color, fontWeight: 600 }}>⚡ {niv.label} — {niv.desc}</div>
                    </div>
                    <div className={styles.infoBlock}>
                      <div className={styles.infoLabel}>Créé le</div>
                      <div style={{ color: '#a8a8c0' }}>{new Date(selected.createdAt).toLocaleDateString('fr-FR')}</div>
                    </div>
                  </div>

                  {/* Personnalité picker inline */}
                  <div className={styles.infoBlock}>
                    <div className={styles.infoLabel}>Personnalité</div>
                    <select
                      className={styles.select}
                      style={{ marginTop: 6 }}
                      value={selected.personalityId ?? ''}
                      onChange={e => assignPersonality(selected.id, e.target.value)}
                    >
                      <option value="">Aucune personnalité</option>
                      {personalities.map(p => (
                        <option key={p.id} value={p.id}>{p.emoji} {p.label}</option>
                      ))}
                    </select>
                    {selected.personalityId && (() => {
                      const perso = personalities.find(p => p.id === selected.personalityId)
                      return perso?.description ? (
                        <div style={{ fontSize: 12, color: '#6b6b80', marginTop: 6 }}>{perso.description}</div>
                      ) : null
                    })()}
                  </div>

                  {selected.description && (
                    <div className={styles.infoBlock}>
                      <div className={styles.infoLabel}>Description</div>
                      <div style={{ color: '#a8a8c0', fontSize: 13 }}>{selected.description}</div>
                    </div>
                  )}

                  {selected.instructions && (
                    <div className={styles.infoBlock}>
                      <div className={styles.infoLabel}>Instructions supplémentaires</div>
                      <pre className={styles.instructions}>{selected.instructions}</pre>
                    </div>
                  )}
                </div>
              )
            })()}
          </div>
        </>
      )}

      {/* ── Onglet Templates ── */}
      {tab === 'templates' && (
        <div className={styles.templatesPage}>
          <div className={styles.templatesIntro}>
            Choisissez un template pour créer un agent pré-configuré. Vous pourrez personnaliser tous les champs avant de sauvegarder.
          </div>
          <div className={styles.templatesGrid}>
            {templates.map(tpl => {
              const niv = NIVEAU_META[tpl.niveau] ?? NIVEAU_META.medium
              return (
                <div key={tpl.id} className={styles.tplCard}>
                  <div className={styles.tplTop}>
                    <span className={styles.tplIcon}>{tpl.icon}</span>
                    <span className={styles.tplCategorie}>{tpl.categorie}</span>
                    <span className={styles.tplNiveau} style={{ color: niv.color }}>⚡ {niv.label}</span>
                  </div>
                  <div className={styles.tplNom}>{tpl.nom}</div>
                  <div className={styles.tplDesc}>{tpl.description}</div>
                  <button className={styles.btnUseTemplate} onClick={() => useTemplate(tpl)}>
                    Utiliser ce template →
                  </button>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* ── Onglet Personnalités ── */}
      {tab === 'personalities' && (
        <>
          {showPersoForm && (
            <form className={styles.form} onSubmit={savePerso}>
              <div style={{ display: 'flex', gap: 8 }}>
                <input
                  className={styles.input}
                  style={{ width: 60, flexShrink: 0 }}
                  placeholder="🤖"
                  value={persoForm.emoji}
                  onChange={e => setPersoForm(f => ({ ...f, emoji: e.target.value }))}
                />
                <input
                  className={styles.input}
                  placeholder="Nom de la personnalité *"
                  required
                  value={persoForm.label}
                  onChange={e => setPersoForm(f => ({ ...f, label: e.target.value }))}
                />
              </div>
              <input
                className={styles.input}
                placeholder="Description courte"
                value={persoForm.description}
                onChange={e => setPersoForm(f => ({ ...f, description: e.target.value }))}
              />
              <textarea
                className={styles.textarea}
                style={{ minHeight: 140 }}
                placeholder="System prompt — définit le comportement de l'agent (ex: Tu es un expert financier senior…)"
                value={persoForm.systemPrompt}
                onChange={e => setPersoForm(f => ({ ...f, systemPrompt: e.target.value }))}
              />
              <div className={styles.formActions}>
                <button type="submit" className={styles.btnPrimary} disabled={persoLoading}>
                  {editingPersoId ? 'Sauvegarder' : 'Créer'}
                </button>
                <button type="button" className={styles.btnGhost} onClick={() => { setShowPersoForm(false); setEditingPersoId(null) }}>Annuler</button>
              </div>
            </form>
          )}

          <div className={styles.layout}>
            <div className={styles.list}>
              {personalities.length === 0 && (
                <div className={styles.empty}>Aucune personnalité.</div>
              )}
              <DndContext sensors={dndSensors} collisionDetection={closestCenter} onDragEnd={handlePersoDragEnd}>
                <SortableContext items={personalities.map(p => p.id)} strategy={verticalListSortingStrategy}>
                  {personalities.map(p => (
                    <SortablePersoItem
                      key={p.id}
                      p={p}
                      isActive={selectedPerso?.id === p.id}
                      onClick={() => setSelectedPerso(p)}
                      onEdit={openEditPerso}
                      onDelete={deletePerso}
                    />
                  ))}
                </SortableContext>
              </DndContext>
            </div>

            {selectedPerso && (
              <div className={styles.detail}>
                <div className={styles.detailHeader}>
                  <div>
                    <h2 className={styles.detailNom}>{selectedPerso.emoji} {selectedPerso.label}</h2>
                    {selectedPerso.description && (
                      <div style={{ color: '#6b6b80', fontSize: 13, marginTop: 4 }}>{selectedPerso.description}</div>
                    )}
                  </div>
                  <div style={{ display: 'flex', gap: 6 }}>
                    <button className={styles.btnSecondary} onClick={() => openEditPerso(selectedPerso)}>✏️ Éditer</button>
                    {!selectedPerso.isBuiltin && (
                      <button className={styles.btnDanger} onClick={() => deletePerso(selectedPerso.id)}>✕</button>
                    )}
                  </div>
                </div>

                <div className={styles.infoBlock}>
                  <div className={styles.infoLabel}>System Prompt</div>
                  {selectedPerso.systemPrompt ? (
                    <pre className={styles.instructions}>{selectedPerso.systemPrompt}</pre>
                  ) : (
                    <div style={{ color: '#6b6b80', fontSize: 13, marginTop: 6 }}>Aucun prompt défini — comportement par défaut</div>
                  )}
                </div>

                <div className={styles.infoBlock}>
                  <div className={styles.infoLabel}>Agents utilisant cette personnalité</div>
                  <div style={{ marginTop: 6, display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                    {agents.filter(a => a.personalityId === selectedPerso.id).map(a => (
                      <span key={a.id} className={styles.chip} style={{ color: '#818cf8', borderColor: '#6366f1' }}>{a.nom}</span>
                    ))}
                    {agents.filter(a => a.personalityId === selectedPerso.id).length === 0 && (
                      <span style={{ color: '#6b6b80', fontSize: 13 }}>Aucun agent</span>
                    )}
                  </div>
                </div>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}

import { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import {
  ReactFlow, addEdge, useNodesState, useEdgesState,
  Controls, Background, Handle, Position, MiniMap,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { api } from '../../../services/api.jsx'
import keycloak from '../../../keycloak'

// ── Custom node types ────────────────────────────────────────
function AgentNode({ data, selected }) {
  return (
    <div style={{
      background: '#23272a', border: `2px solid ${selected ? '#fff' : '#5865F2'}`,
      borderRadius: 10, padding: '10px 16px', minWidth: 160, maxWidth: 220, fontSize: 12,
      boxShadow: selected ? '0 0 0 3px rgba(88,101,242,0.35)' : 'none',
    }}>
      <Handle type="target" position={Position.Left} style={{ background: '#5865F2' }} />
      <div style={{ color: '#5865F2', fontWeight: 700, fontSize: 11, marginBottom: 3 }}>⚙️ Agent</div>
      <div style={{ color: '#fff', fontWeight: 600 }}>{data.label}</div>
      {data.agentOwner && <div style={{ color: '#aaa', fontSize: 11, marginTop: 2 }}>{data.agentOwner}</div>}
      <Handle type="source" position={Position.Right} style={{ background: '#5865F2' }} />
    </div>
  )
}

function PromptNode({ data, selected }) {
  return (
    <div style={{
      background: '#23272a', border: `2px solid ${selected ? '#fff' : '#57F287'}`,
      borderRadius: 10, padding: '10px 16px', minWidth: 160, maxWidth: 220, fontSize: 12,
      boxShadow: selected ? '0 0 0 3px rgba(87,242,135,0.25)' : 'none',
    }}>
      <Handle type="target" position={Position.Left} style={{ background: '#57F287' }} />
      <div style={{ color: '#57F287', fontWeight: 700, fontSize: 11, marginBottom: 3 }}>💬 Prompt</div>
      <div style={{ color: '#fff', fontWeight: 600 }}>{data.label}</div>
      <Handle type="source" position={Position.Right} style={{ background: '#57F287' }} />
    </div>
  )
}

const NODE_TYPES = { agentNode: AgentNode, promptNode: PromptNode }

const STATUT_COLOR = { pending: '#4f545c', running: '#5865F2', done: '#57F287', error: '#ED4245' }

const EDGE_STYLE = { stroke: '#5865F2', strokeWidth: 2 }

// ── Helpers ──────────────────────────────────────────────────
function itemsToFlow(items) {
  // Auto-layout if all positions are 0 — topological X-ordering
  const allZero = items.every(t => !t.posX && !t.posY)
  const xByTopo = {}
  if (allZero) {
    const inDeg = {}
    const adj = {}
    for (const t of items) { inDeg[t.id] = 0; adj[t.id] = [] }
    for (const t of items) {
      const deps = JSON.parse(t.dependances || '[]')
      for (const d of deps) { if (adj[d]) { adj[d].push(t.id); inDeg[t.id]++ } }
    }
    const queue = items.filter(t => inDeg[t.id] === 0).map(t => t.id)
    let col = 0
    while (queue.length) {
      const id = queue.shift()
      xByTopo[id] = col++
      for (const nxt of adj[id]) { if (--inDeg[nxt] === 0) queue.push(nxt) }
    }
  }

  let rowIdx = {}
  const nodes = items.map((t, i) => {
    const col = xByTopo[t.id] ?? i
    rowIdx[col] = (rowIdx[col] ?? -1) + 1
    const x = allZero ? 50 + col * 260 : (t.posX || 0)
    const y = allZero ? 80 + rowIdx[col] * 120 : (t.posY || 0)
    return {
      id: t.id,
      type: t.nodeType === 'prompt' ? 'promptNode' : 'agentNode',
      position: { x, y },
      data: {
        label: t.nom, agentOwner: t.agentOwner, criticite: t.criticite,
        nodeType: t.nodeType, promptText: t.promptText, statut: t.statut,
      },
    }
  })

  const edges = items.flatMap(t => {
    const deps = JSON.parse(t.dependances || '[]')
    return deps.filter(d => items.some(i => i.id === d)).map(d => ({
      id: `e-${d}-${t.id}`,
      source: d, target: t.id,
      animated: true, style: EDGE_STYLE,
    }))
  })

  return { nodes, edges }
}

const DOZZLE_URL = import.meta.env.VITE_DOZZLE_URL || 'http://localhost:9998'

// ── Main component ───────────────────────────────────────────
export default function DAGPanel({ poleId }) {
  const [tab, setTab] = useState('editor')

  // Editor state
  const [nodes, setNodes, onNodesChange] = useNodesState([])
  const [edges, setEdges, onEdgesChange] = useEdgesState([])
  const [tasks, setTasks]               = useState([])
  const [selected, setSelected]         = useState(null)
  const [running, setRunning]           = useState(false)
  const [form, setForm]                 = useState({ nom: '', nodeType: 'prompt', agentOwner: '', criticite: 'normale', promptText: '', dependances: [] })
  const pollRef = useRef()

  // Templates state
  const [templates, setTemplates]       = useState([])
  const [savingTpl, setSavingTpl]       = useState(false)
  const [tplForm, setTplForm]           = useState({ nom: '', description: '', icon: '🔄', categorie: '' })

  // Assistant state
  const [messages, setMessages]         = useState([{ role: 'assistant', content: 'Bonjour ! Je peux t\'aider à concevoir ton pipeline. Décris ce que tu veux accomplir, ou demande-moi de générer un pipeline.' }])
  const [chatInput, setChatInput]       = useState('')
  const [chatLoading, setChatLoading]   = useState(false)
  const messagesEndRef = useRef()

  const nodeTypes = useMemo(() => NODE_TYPES, [])

  useEffect(() => { load(); loadTemplates() }, [poleId])
  useEffect(() => { return () => clearInterval(pollRef.current) }, [])
  useEffect(() => { messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])

  async function load() {
    try {
      const items = await api.get(`/api/poles/${poleId}/dag`)
      setTasks(items)
      const { nodes: n, edges: e } = itemsToFlow(items)
      setNodes(n)
      setEdges(e)
    } catch {}
  }

  async function loadTemplates() {
    try {
      const data = await api.get('/api/pipeline-templates')
      setTemplates(data)
    } catch {}
  }

  // ── Node drag end → persist position ────────────────────────
  const onNodeDragStop = useCallback(async (_, node) => {
    try {
      await api.patch(`/api/dag/${node.id}`, { posX: node.position.x, posY: node.position.y })
    } catch {}
  }, [])

  // ── Connect edge → persist dependance ───────────────────────
  const onConnect = useCallback(async (params) => {
    setEdges(eds => addEdge({ ...params, animated: true, style: EDGE_STYLE }, eds))
    try {
      const target = tasks.find(t => t.id === params.target)
      if (!target) return
      const deps = JSON.parse(target.dependances || '[]')
      if (!deps.includes(params.source)) {
        await api.patch(`/api/dag/${params.target}`, { dependances: [...deps, params.source] })
        await load()
      }
    } catch {}
  }, [tasks])

  // ── Node click → select ─────────────────────────────────────
  const onNodeClick = useCallback((_, node) => {
    const task = tasks.find(t => t.id === node.id)
    setSelected(task ?? null)
  }, [tasks])

  // ── Create task ──────────────────────────────────────────────
  async function createTask() {
    if (!form.nom.trim()) return
    try {
      await api.post(`/api/poles/${poleId}/dag`, {
        nom:        form.nom.trim(),
        nodeType:   form.nodeType,
        agentOwner: form.agentOwner || undefined,
        criticite:  form.criticite,
        dependances: form.dependances,
        promptText: form.promptText || undefined,
        posX:       100 + Math.random() * 300,
        posY:       100 + Math.random() * 200,
      })
      setForm({ nom: '', nodeType: 'prompt', agentOwner: '', criticite: 'normale', promptText: '', dependances: [] })
      await load()
    } catch {}
  }

  async function deleteTask(id) {
    try { await api.delete(`/api/dag/${id}`); setSelected(null); await load() } catch {}
  }

  async function resetTask(id) {
    try { await api.patch(`/api/dag/${id}`, { statut: 'pending' }); await load() } catch {}
  }

  function startPolling() {
    clearInterval(pollRef.current)
    pollRef.current = setInterval(async () => {
      try {
        const items = await api.get(`/api/poles/${poleId}/dag`)
        setTasks(items)
        setNodes(nds => nds.map(n => {
          const t = items.find(i => i.id === n.id)
          return t ? { ...n, data: { ...n.data, statut: t.statut } } : n
        }))
        if (items.every(t => t.statut === 'done' || t.statut === 'error')) {
          clearInterval(pollRef.current); setRunning(false)
        }
      } catch {}
    }, 1500)
  }

  async function runDAG() {
    if (running || tasks.length === 0) return
    setRunning(true)
    try { await api.post(`/api/poles/${poleId}/dag/run`, {}); startPolling() }
    catch { setRunning(false) }
  }

  // ── Use template ─────────────────────────────────────────────
  async function useTemplate(tpl) {
    const nodes = JSON.parse(tpl.nodes || '[]')
    const edges = JSON.parse(tpl.edges || '[]')
    try {
      await api.post(`/api/poles/${poleId}/dag/import`, { nodes, edges, clearExisting: true })
      await load()
      setTab('editor')
    } catch {}
  }

  // ── Save as template ─────────────────────────────────────────
  async function saveTemplate() {
    if (!tplForm.nom.trim()) return
    setSavingTpl(true)
    try {
      await api.post('/api/pipeline-templates', {
        ...tplForm,
        nodes: JSON.stringify(nodes.map(n => ({ id: n.id, type: n.type, position: n.position, data: n.data }))),
        edges: JSON.stringify(edges.map(e => ({ id: e.id, source: e.source, target: e.target, animated: true }))),
      })
      setTplForm({ nom: '', description: '', icon: '🔄', categorie: '' })
      await loadTemplates()
    } catch {}
    setSavingTpl(false)
  }

  async function deleteTpl(id) {
    try { await api.delete(`/api/pipeline-templates/${id}`); await loadTemplates() } catch {}
  }

  // ── Assistant chat ───────────────────────────────────────────
  async function sendMessage() {
    if (!chatInput.trim() || chatLoading) return
    const userMsg = { role: 'user', content: chatInput.trim() }
    const history = [...messages, userMsg]
    setMessages(history)
    setChatInput('')
    setChatLoading(true)
    try {
      await keycloak.updateToken(30).catch(() => {})
      const resp = await fetch('/api/pipeline-assistant/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${keycloak.token || ''}` },
        body: JSON.stringify({ messages: history.filter(m => m.role !== 'system') }),
      })
      if (!resp.body) throw new Error()
      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let full = ''
      setMessages(m => [...m, { role: 'assistant', content: '' }])
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        const chunk = decoder.decode(value)
        for (const line of chunk.split('\n')) {
          if (line.startsWith('0:')) {
            try { full += JSON.parse(line.slice(2)) } catch {}
            setMessages(m => {
              const copy = [...m]
              copy[copy.length - 1] = { role: 'assistant', content: full }
              return copy
            })
          }
        }
      }
    } catch {
      setMessages(m => [...m, { role: 'assistant', content: 'Erreur lors de la génération.' }])
    }
    setChatLoading(false)
  }

  // Apply pipeline JSON from assistant message
  async function applyPipelineJson(content) {
    const match = content.match(/```json\s*([\s\S]*?)```/)
    if (!match) return
    try {
      const { nodes: n, edges: e } = JSON.parse(match[1])
      await api.post(`/api/poles/${poleId}/dag/import`, { nodes: n, edges: e, clearExisting: true })
      await load()
      setTab('editor')
    } catch {}
  }

  // ── Render tabs ──────────────────────────────────────────────
  const tabStyle = (t) => ({
    padding: '6px 16px', fontSize: 13, fontWeight: tab === t ? 600 : 400,
    color: tab === t ? '#fff' : '#aaa', background: tab === t ? '#383a40' : 'transparent',
    border: 'none', borderRadius: 6, cursor: 'pointer', transition: 'all 0.15s',
  })

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 140px)', padding: '0.75rem', gap: '0.6rem' }}>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 4, background: '#2b2d31', padding: 4, borderRadius: 8, width: 'fit-content' }}>
        <button style={tabStyle('editor')}    onClick={() => setTab('editor')}>    🕸️ Éditeur</button>
        <button style={tabStyle('templates')} onClick={() => setTab('templates')}> 📦 Templates</button>
        <button style={tabStyle('assistant')} onClick={() => setTab('assistant')}> 🤖 Assistant</button>
      </div>

      {/* ── EDITOR TAB ──────────────────────────────────────── */}
      {tab === 'editor' && (
        <div style={{ display: 'flex', flex: 1, gap: '1rem', minHeight: 0 }}>

          {/* Canvas */}
          <div style={{ flex: 1, background: '#1e2124', borderRadius: 10, overflow: 'hidden' }}>
            <ReactFlow
              nodes={nodes}
              edges={edges}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onConnect={onConnect}
              onNodeClick={onNodeClick}
              onNodeDragStop={onNodeDragStop}
              nodeTypes={nodeTypes}
              fitView
              style={{ background: '#1e2124' }}
              defaultEdgeOptions={{ animated: true, style: EDGE_STYLE }}
            >
              <Controls style={{ background: '#2b2d31', border: '1px solid #4f545c' }} />
              <MiniMap style={{ background: '#2b2d31' }} nodeColor={n => n.type === 'agentNode' ? '#5865F2' : '#57F287'} />
              <Background color="#333" gap={20} />
            </ReactFlow>
          </div>

          {/* Side panel */}
          <div style={{ width: 270, display: 'flex', flexDirection: 'column', gap: '0.6rem', overflowY: 'auto' }}>

            {/* Selected node */}
            {selected && (
              <div style={{ background: '#2b2d31', borderRadius: 8, padding: '0.75rem', fontSize: 13, borderLeft: `3px solid ${STATUT_COLOR[selected.statut] || '#5865F2'}` }}>
                <div style={{ fontWeight: 600, marginBottom: 4 }}>{selected.nom}</div>
                <div style={{ color: STATUT_COLOR[selected.statut], marginBottom: 4 }}>{selected.statut} · {selected.criticite}</div>
                {selected.agentOwner && <div style={{ color: '#aaa', fontSize: 12, marginBottom: 4 }}>Agent : {selected.agentOwner}</div>}
                {selected.promptText && <div style={{ color: '#ccc', fontSize: 11, marginBottom: 8, background: '#1e2124', padding: '4px 6px', borderRadius: 4, maxHeight: 60, overflowY: 'auto' }}>{selected.promptText}</div>}
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                  <button onClick={() => resetTask(selected.id)} style={btnStyle('#4f545c')}>↺ Reset</button>
                  <button onClick={() => deleteTask(selected.id)} style={btnStyle('#ED4245')}>✕ Suppr.</button>
                  {selected.nodeType === 'agent' && selected.agentOwner && (
                    <button
                      onClick={() => window.open(`${DOZZLE_URL}/container/${selected.agentOwner}`, '_blank')}
                      style={btnStyle('#2b5a2e')}
                      title="Voir les logs Docker"
                    >🪵 Logs</button>
                  )}
                </div>
              </div>
            )}

            {/* New node form */}
            <div style={{ background: '#2b2d31', borderRadius: 8, padding: '0.75rem', display: 'flex', flexDirection: 'column', gap: 8, fontSize: 13 }}>
              <div style={{ fontWeight: 600 }}>Nouveau nœud</div>
              <input placeholder="Nom *" value={form.nom} onChange={e => setForm(p => ({ ...p, nom: e.target.value }))} onKeyDown={e => e.key === 'Enter' && createTask()} style={inputStyle} />
              <select value={form.nodeType} onChange={e => setForm(p => ({ ...p, nodeType: e.target.value }))} style={inputStyle}>
                <option value="prompt">💬 Prompt libre</option>
                <option value="agent">⚙️ Agent Forge</option>
              </select>
              {form.nodeType === 'agent' && (
                <input placeholder="Nom de l'agent" value={form.agentOwner} onChange={e => setForm(p => ({ ...p, agentOwner: e.target.value }))} style={inputStyle} />
              )}
              {form.nodeType === 'prompt' && (
                <textarea placeholder="Instructions du prompt" value={form.promptText} onChange={e => setForm(p => ({ ...p, promptText: e.target.value }))} style={{ ...inputStyle, resize: 'vertical', minHeight: 64 }} />
              )}
              <select value={form.criticite} onChange={e => setForm(p => ({ ...p, criticite: e.target.value }))} style={inputStyle}>
                <option value="faible">Faible</option>
                <option value="normale">Normale</option>
                <option value="haute">Haute</option>
                <option value="critique">Critique</option>
              </select>
              {tasks.length > 0 && (
                <>
                  <div style={{ fontSize: 11, color: '#aaa' }}>Dépend de :</div>
                  <div style={{ maxHeight: 80, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 3 }}>
                    {tasks.map(t => (
                      <label key={t.id} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, cursor: 'pointer' }}>
                        <input type="checkbox" checked={form.dependances.includes(t.id)} onChange={e => setForm(p => ({ ...p, dependances: e.target.checked ? [...p.dependances, t.id] : p.dependances.filter(d => d !== t.id) }))} />
                        <span style={{ color: STATUT_COLOR[t.statut] }}>■</span> {t.nom}
                      </label>
                    ))}
                  </div>
                </>
              )}
              <button onClick={createTask} style={btnStyle('#5865F2', true)}>+ Créer le nœud</button>
            </div>

            {/* Run */}
            <button onClick={runDAG} disabled={running || tasks.length === 0} style={{ background: running ? '#4f545c' : '#57F287', color: running ? '#aaa' : '#111', border: 'none', borderRadius: 8, padding: '10px', cursor: running || tasks.length === 0 ? 'default' : 'pointer', fontWeight: 700, fontSize: 14 }}>
              {running ? '⏳ Exécution…' : '▶ Exécuter le DAG'}
            </button>

            {/* Save as template */}
            <div style={{ background: '#2b2d31', borderRadius: 8, padding: '0.75rem', display: 'flex', flexDirection: 'column', gap: 8, fontSize: 13 }}>
              <div style={{ fontWeight: 600 }}>💾 Sauvegarder comme template</div>
              <input placeholder="Nom du template *" value={tplForm.nom} onChange={e => setTplForm(p => ({ ...p, nom: e.target.value }))} style={inputStyle} />
              <input placeholder="Description" value={tplForm.description} onChange={e => setTplForm(p => ({ ...p, description: e.target.value }))} style={inputStyle} />
              <div style={{ display: 'flex', gap: 6 }}>
                <input placeholder="🔄 Icône" value={tplForm.icon} onChange={e => setTplForm(p => ({ ...p, icon: e.target.value }))} style={{ ...inputStyle, width: 60 }} />
                <input placeholder="Catégorie" value={tplForm.categorie} onChange={e => setTplForm(p => ({ ...p, categorie: e.target.value }))} style={{ ...inputStyle, flex: 1 }} />
              </div>
              <button onClick={saveTemplate} disabled={savingTpl || !tplForm.nom.trim() || nodes.length === 0} style={btnStyle('#57F287', true)}>
                {savingTpl ? '…' : '💾 Sauvegarder'}
              </button>
            </div>

            {/* Tasks list */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {tasks.map(t => (
                <div key={t.id} onClick={() => setSelected(t)} style={{ background: selected?.id === t.id ? '#383a40' : '#2b2d31', borderRadius: 6, padding: '6px 10px', cursor: 'pointer', fontSize: 12, borderLeft: `3px solid ${STATUT_COLOR[t.statut]}` }}>
                  <div style={{ fontWeight: 500, color: '#fff' }}>{t.nom}</div>
                  <div style={{ color: '#aaa', display: 'flex', gap: 8, marginTop: 2, alignItems: 'center' }}>
                    <span style={{ color: STATUT_COLOR[t.statut] }}>{t.statut}</span>
                    <span>{t.criticite}</span>
                    <span style={{ color: t.nodeType === 'agent' ? '#5865F2' : '#57F287' }}>{t.nodeType === 'agent' ? '⚙️' : '💬'}</span>
                    {t.nodeType === 'agent' && t.agentOwner && (
                      <button
                        onClick={e => { e.stopPropagation(); window.open(`${DOZZLE_URL}/container/${t.agentOwner}`, '_blank') }}
                        style={{ ...btnStyle('#2b5a2e'), marginLeft: 'auto', fontSize: 10, padding: '2px 6px' }}
                        title="Logs Docker"
                      >🪵</button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* ── TEMPLATES TAB ───────────────────────────────────── */}
      {tab === 'templates' && (
        <div style={{ flex: 1, overflowY: 'auto' }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '1rem' }}>
            {templates.map(tpl => (
              <div key={tpl.id} style={{ background: '#2b2d31', borderRadius: 10, padding: '1rem', display: 'flex', flexDirection: 'column', gap: 8 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                  <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                    <span style={{ fontSize: 28 }}>{tpl.icon}</span>
                    <div>
                      <div style={{ fontWeight: 600, fontSize: 14, color: '#fff' }}>{tpl.nom}</div>
                      {tpl.categorie && <div style={{ fontSize: 11, color: '#5865F2', fontWeight: 500 }}>{tpl.categorie}</div>}
                    </div>
                  </div>
                  {tpl.userId && (
                    <button onClick={() => deleteTpl(tpl.id)} style={{ background: 'none', border: 'none', color: '#ED4245', cursor: 'pointer', fontSize: 16, padding: 0 }}>✕</button>
                  )}
                </div>
                <div style={{ fontSize: 12, color: '#aaa', lineHeight: 1.5 }}>{tpl.description}</div>
                <div style={{ fontSize: 11, color: '#777' }}>
                  {JSON.parse(tpl.nodes || '[]').length} nœuds · {JSON.parse(tpl.edges || '[]').length} arêtes
                </div>
                <button onClick={() => useTemplate(tpl)} style={{ ...btnStyle('#5865F2', true), marginTop: 4 }}>
                  ▶ Utiliser ce template
                </button>
              </div>
            ))}
            {templates.length === 0 && (
              <div style={{ color: '#aaa', fontSize: 13, padding: '2rem' }}>Aucun template disponible.</div>
            )}
          </div>
        </div>
      )}

      {/* ── ASSISTANT TAB ───────────────────────────────────── */}
      {tab === 'assistant' && (
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '0.6rem', minHeight: 0 }}>
          <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 8, background: '#1e2124', borderRadius: 10, padding: '1rem' }}>
            {messages.map((m, i) => (
              <div key={i} style={{ display: 'flex', flexDirection: 'column', alignItems: m.role === 'user' ? 'flex-end' : 'flex-start', gap: 4 }}>
                <div style={{
                  background: m.role === 'user' ? '#5865F2' : '#2b2d31',
                  color: '#fff', borderRadius: 10, padding: '8px 14px',
                  maxWidth: '80%', fontSize: 13, lineHeight: 1.55, whiteSpace: 'pre-wrap',
                }}>
                  {m.content}
                </div>
                {m.role === 'assistant' && m.content.includes('```json') && (
                  <button onClick={() => applyPipelineJson(m.content)} style={{ ...btnStyle('#57F287'), fontSize: 11 }}>
                    ⚡ Appliquer ce pipeline dans l'éditeur
                  </button>
                )}
              </div>
            ))}
            {chatLoading && (
              <div style={{ color: '#aaa', fontSize: 12, fontStyle: 'italic' }}>L'assistant réfléchit…</div>
            )}
            <div ref={messagesEndRef} />
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <input
              value={chatInput}
              onChange={e => setChatInput(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && !e.shiftKey && sendMessage()}
              placeholder="Décris ton pipeline ou demande un conseil…"
              style={{ ...inputStyle, flex: 1 }}
            />
            <button onClick={sendMessage} disabled={chatLoading} style={{ ...btnStyle('#5865F2'), padding: '8px 16px', fontSize: 14 }}>
              ➤
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

const inputStyle = {
  background: '#1e2124', border: '1px solid #4f545c',
  borderRadius: 4, padding: '5px 8px', color: '#fff', fontSize: 13,
  width: '100%', boxSizing: 'border-box',
}

function btnStyle(bg, full = false) {
  return {
    background: bg, color: bg === '#57F287' ? '#111' : '#fff',
    border: 'none', borderRadius: 4, padding: '5px 10px',
    cursor: 'pointer', fontSize: 12,
    ...(full ? { width: '100%' } : {}),
  }
}

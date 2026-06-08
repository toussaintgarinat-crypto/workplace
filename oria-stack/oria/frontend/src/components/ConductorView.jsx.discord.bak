import { useState, useEffect, useRef, useCallback } from 'react'
import { api, authHeaders } from '../services/api.js'

const STATUS_CONFIG = {
  idle:    { color: '#4caf50', label: 'Disponible',  dot: '🟢' },
  working: { color: '#ff9800', label: 'En cours…',   dot: '🟡' },
  error:   { color: '#f44336', label: 'Erreur',      dot: '🔴' },
}

function AgentCard({ agent, onCall }) {
  const [expanded, setExpanded] = useState(false)
  const [msg, setMsg]           = useState('')
  const [loading, setLoading]   = useState(false)
  const cfg = STATUS_CONFIG[agent.status] ?? STATUS_CONFIG.idle

  async function handleCall(e) {
    e.preventDefault()
    if (!msg.trim()) return
    setLoading(true)
    await onCall(agent.id, msg.trim())
    setMsg('')
    setLoading(false)
    setExpanded(false)
  }

  return (
    <div className="conductor-card" data-status={agent.status}>
      <div className="conductor-card-header">
        <span className="conductor-agent-emoji">{agent.avatar_emoji}</span>
        <div className="conductor-agent-info">
          <strong>{agent.name}</strong>
          <span className="conductor-agent-pole">{agent.pole_type}</span>
        </div>
        <div className="conductor-status-badge" style={{ color: cfg.color }}>
          <span className="conductor-dot" style={{ background: cfg.color }} />
          <span>{cfg.label}</span>
        </div>
      </div>

      {agent.status === 'working' && agent.current_task && (
        <div className="conductor-task-line">
          <span className="conductor-task-icon">⚡</span>
          <span className="conductor-task-text">{agent.current_task}</span>
        </div>
      )}
      {agent.status === 'error' && agent.current_task && (
        <div className="conductor-task-line conductor-task-error">
          <span className="conductor-task-icon">⚠️</span>
          <span className="conductor-task-text">{agent.current_task}</span>
        </div>
      )}

      <div className="conductor-card-actions">
        <button
          className="conductor-btn-call"
          onClick={() => setExpanded(v => !v)}
          disabled={agent.status === 'working'}
        >
          💬 Appeler
        </button>
        {agent.room_id && (
          <button
            className="conductor-btn-room"
            onClick={() => {}}
            title="Entrer dans la room"
          >
            🚪 Room
          </button>
        )}
        <a
          className="conductor-btn-forge"
          href={`${agent.forge_url || 'http://localhost:3000'}`}
          target="_blank"
          rel="noreferrer"
          title="Ouvrir Forge"
        >
          🔧 Forge
        </a>
      </div>

      {expanded && (
        <form className="conductor-call-form" onSubmit={handleCall}>
          <input
            autoFocus
            type="text"
            placeholder={`Message pour l'agent ${agent.pole_type}…`}
            value={msg}
            onChange={e => setMsg(e.target.value)}
            disabled={loading}
          />
          <button type="submit" disabled={loading || !msg.trim()}>
            {loading ? '…' : 'Envoyer'}
          </button>
        </form>
      )}
    </div>
  )
}

export default function ConductorView({ moi }) {
  const [agents, setAgents]     = useState([])
  const [connected, setConnected] = useState(false)
  const wsRef = useRef(null)

  async function loadAgents() {
    const data = await api.get('/conductor/agents')
    if (Array.isArray(data)) setAgents(data)
  }

  const connectWS = useCallback(() => {
    const base = (import.meta.env.VITE_API_URL || 'http://localhost:8000')
      .replace(/^http/, 'ws')
    const ws = new WebSocket(`${base}/ws/conductor`)
    wsRef.current = ws

    ws.onopen  = () => setConnected(true)
    ws.onclose = () => {
      setConnected(false)
      setTimeout(connectWS, 3000) // reconnect auto
    }
    ws.onerror = () => ws.close()
    ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data)
        if (msg.type === 'status' && msg.agent) {
          setAgents(prev => prev.map(a => a.id === msg.agent.id ? msg.agent : a))
        }
      } catch {}
    }
  }, [])

  useEffect(() => {
    loadAgents()
    connectWS()
    return () => wsRef.current?.close()
  }, [connectWS])

  async function handleCall(agentId, message) {
    await api.post(`/conductor/agents/${agentId}/call`, { message })
  }

  const countByStatus = agents.reduce((acc, a) => {
    acc[a.status] = (acc[a.status] || 0) + 1
    return acc
  }, {})

  return (
    <div className="conductor-view">
      <div className="conductor-header">
        <h2>🎛 Conductor</h2>
        <p className="conductor-subtitle">Agents résidents pôle — présence temps réel</p>
        <div className="conductor-status-bar">
          <span className="conductor-ws-dot" data-connected={connected} />
          <span>{connected ? 'Connecté' : 'Reconnexion…'}</span>
          <span className="conductor-summary">
            {countByStatus.idle || 0} disponibles · {countByStatus.working || 0} actifs · {countByStatus.error || 0} erreurs
          </span>
        </div>
      </div>

      <div className="conductor-grid">
        {agents.length === 0 ? (
          <div className="conductor-empty">
            <span>🤖</span>
            <p>Aucun agent résident configuré.</p>
          </div>
        ) : (
          agents.map(agent => (
            <AgentCard key={agent.id} agent={agent} onCall={handleCall} />
          ))
        )}
      </div>
    </div>
  )
}

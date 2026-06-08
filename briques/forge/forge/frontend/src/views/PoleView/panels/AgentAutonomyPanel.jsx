import { useState, useEffect } from 'react'
import { api } from '../../../services/api'
import styles from './Panel.module.css'

const NIVEAUX = [
  { key: 'N0', label: 'N0 — Clarification', desc: 'L\'agent demande confirmation avant d\'agir', color: '#ef4444' },
  { key: 'N1', label: 'N1 — Supervisé', desc: 'L\'agent agit, le fondateur valide avant déploiement', color: '#f59e0b' },
  { key: 'N2', label: 'N2 — Auto+Ask', desc: 'L\'agent agit et se corrige, alerte si bloqué', color: '#3b82f6' },
  { key: 'N3', label: 'N3 — Autonome', desc: 'L\'agent exécute librement et logue ses actions', color: '#10b981' },
]

export default function AgentAutonomyPanel({ poleId }) {
  const [agents, setAgents] = useState([])
  const [autonomy, setAutonomy] = useState({})
  const [saving, setSaving] = useState({})

  useEffect(() => {
    api.get('/api/agent-factory').then(r => setAgents(Array.isArray(r) ? r : [])).catch(() => {})
  }, [poleId])

  useEffect(() => {
    agents.forEach(agent => {
      api.get(`/api/agents/${agent.id}/autonomy`).then(rule => {
        setAutonomy(a => ({ ...a, [agent.id]: rule.niveau ?? 'N1' }))
      }).catch(() => {})
    })
  }, [agents])

  async function setNiveau(agentId, niveau) {
    setAutonomy(a => ({ ...a, [agentId]: niveau }))
    setSaving(s => ({ ...s, [agentId]: true }))
    try {
      await api.put(`/api/agents/${agentId}/autonomy`, { niveau })
    } finally { setSaving(s => ({ ...s, [agentId]: false })) }
  }

  return (
    <div className={styles.panel}>
      <div className={styles.stats}>
        {NIVEAUX.map(n => (
          <div key={n.key} className={styles.stat}>
            <div className={styles.statLabel} style={{ color: n.color, fontWeight: 700 }}>{n.key}</div>
            <div className={styles.rowSub}>{n.desc}</div>
          </div>
        ))}
      </div>

      {agents.length === 0 && <p className={styles.empty}>Aucun agent configuré. Créez des agents dans la vue Agents.</p>}

      <div className={styles.list}>
        {agents.map(agent => (
          <div key={agent.id} className={styles.row}>
            <div>
              <div className={styles.rowTitle}>{agent.nom}</div>
              <div className={styles.rowSub}>{agent.description}</div>
            </div>
            <div className={styles.rowRight}>
              {saving[agent.id] && <span style={{ fontSize: 11, color: '#6b6b80' }}>...</span>}
              <div className={styles.filterGroup}>
                {NIVEAUX.map(n => (
                  <button key={n.key} onClick={() => setNiveau(agent.id, n.key)}
                    className={`${styles.filterBtn} ${autonomy[agent.id] === n.key ? styles.active : ''}`}
                    style={autonomy[agent.id] === n.key ? { borderColor: n.color, color: n.color, background: n.color + '22' } : {}}>
                    {n.key}
                  </button>
                ))}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

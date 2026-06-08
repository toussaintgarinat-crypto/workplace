import { useState, useEffect, useCallback, useRef } from 'react'
import { commandBridge, token } from '../../services/api'
import styles from './CommandBridge.module.css'

const WS_URL = import.meta.env.VITE_WS_URL || 'ws://localhost:8600'  // S136 : core strangler

const NIVEAU_STYLE = {
  N0: { color: '#ef4444', bg: 'rgba(239,68,68,0.12)' },
  N1: { color: '#f59e0b', bg: 'rgba(245,158,11,0.12)' },
  N2: { color: '#3b82f6', bg: 'rgba(59,130,246,0.12)' },
  N3: { color: '#10b981', bg: 'rgba(16,185,129,0.12)' },
}

export default function CommandBridgeView() {
  const [overview,   setOverview]   = useState(null)
  const [decisions,  setDecisions]  = useState([])
  const [bbEvents,   setBbEvents]   = useState([])
  const [loading,    setLoading]    = useState(true)
  const [error,      setError]      = useState(null)
  const [brief,      setBrief]      = useState(null)
  const [briefLoading, setBriefLoading] = useState(false)
  const wsRef = useRef(null)

  const load = useCallback(async () => {
    try {
      const [ov, dec] = await Promise.all([
        commandBridge.overview(),
        commandBridge.decisions('en_attente'),
      ])
      setOverview(ov)
      setDecisions(Array.isArray(dec) ? dec : [])
      setError(null)
    } catch {
      setError('Unable to load Command Bridge')
    } finally {
      setLoading(false)
    }
  }, [])

  // Chargement initial + refresh 15s
  useEffect(() => {
    load()
    const iv = setInterval(load, 15_000)
    return () => clearInterval(iv)
  }, [load])

  // Blackboard initial
  useEffect(() => {
    commandBridge.blackboard('N0').then(data => {
      setBbEvents(Array.isArray(data) ? data.slice(0, 20) : [])
    }).catch(() => {})
  }, [])

  // WebSocket blackboard — événements N0 en temps réel avec reconnect
  useEffect(() => {
    let dead = false
    const reconnectRef = { current: null }

    function connect() {
      const t = token.get()
      if (!t || dead) return
      const ws = new WebSocket(`${WS_URL}/api/ws/blackboard?token=${t}`)
      wsRef.current = ws
      ws.onmessage = (e) => {
        try {
          const ev = JSON.parse(e.data)
          if (ev.niveau === 'N0' || ev.type === 'blackboard_event') {
            setBbEvents(prev => [ev, ...prev].slice(0, 20))
            if (ev.type === 'decision_created') load()
          }
        } catch {}
      }
      ws.onclose = (e) => {
        if (!dead && e.code !== 1000) {
          reconnectRef.current = setTimeout(connect, 3000)
        }
      }
    }

    connect()
    return () => {
      dead = true
      clearTimeout(reconnectRef.current)
      wsRef.current?.close(1000)
    }
  }, [load])

  async function approve(id) {
    await commandBridge.approve(id)
    setDecisions(prev => prev.filter(d => d.id !== id))
    setOverview(prev => prev ? {
      ...prev,
      totalDecisions: Math.max(0, prev.totalDecisions - 1),
      poles: prev.poles.map(p =>
        decisions.find(d => d.id === id)?.poleId === p.id
          ? { ...p, nbDecisions: Math.max(0, p.nbDecisions - 1) }
          : p
      ),
    } : prev)
  }

  async function reject(id) {
    await commandBridge.reject(id)
    setDecisions(prev => prev.filter(d => d.id !== id))
  }

  async function generateBrief() {
    setBriefLoading(true)
    try {
      const t = token.get()
      const res = await fetch('/api/brief/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(t ? { Authorization: `Bearer ${t}` } : {}) },
      })
      const data = await res.json()
      setBrief(data.brief)
    } catch {}
    setBriefLoading(false)
  }

  async function togglePause(poleId) {
    const res = await commandBridge.togglePause(poleId)
    setOverview(prev => prev ? {
      ...prev,
      poles: prev.poles.map(p => p.id === poleId ? { ...p, enPause: res.enPause } : p),
    } : prev)
  }

  if (loading) return <div className={styles.center}>Loading Command Bridge...</div>
  if (error)   return <div className={`${styles.center} ${styles.error}`}>{error}</div>

  const polesList    = overview?.poles    ?? []
  const venturesList = overview?.ventures ?? []

  // Grouper pôles et décisions par venture
  const ventureGroups = venturesList.map(v => ({
    venture: v,
    poles: polesList.filter(p => p.ventureId === v.id),
    decisions: decisions.filter(d => polesList.find(p => p.id === d.poleId)?.ventureId === v.id),
  }))
  const orphanPoles     = polesList.filter(p => !p.ventureId)
  const orphanDecisions = decisions.filter(d => !polesList.find(p => p.id === d.poleId)?.ventureId)

  return (
    <div className={styles.page}>
      {/* Header */}
      <header className={styles.header}>
        <div className={styles.headerLeft}>
          <span className={styles.icon}>🎯</span>
          <div>
            <div className={styles.title}>Command Bridge</div>
            <div className={styles.subtitle}>Founder hawk-eye view</div>
          </div>
        </div>
        {decisions.length > 0 && (
          <div className={styles.badge}>
            {decisions.length} decision{decisions.length > 1 ? 's' : ''} pending
          </div>
        )}
      </header>

      <div className={styles.body}>
        {/* Groupes par venture */}
        {ventureGroups.map(({ venture, poles: vPoles, decisions: vDecs }) => (
          <section key={venture.id} className={styles.ventureSection}>
            <div className={styles.ventureSectionTitle} style={{ borderLeftColor: venture.couleur }}>
              <span>{venture.emoji}</span>
              <span>{venture.nom}</span>
              {venture.type === 'audit' && <span className={styles.auditChip}>Audit</span>}
              {vDecs.length > 0 && <span className={styles.badgeRed}>{vDecs.length} décision{vDecs.length > 1 ? 's' : ''}</span>}
            </div>

            {vPoles.length > 0 && (
              <div className={styles.polesGrid}>
                {vPoles.map(pole => (
                  <PoleCard key={pole.id} pole={pole} onToggle={() => togglePause(pole.id)} />
                ))}
              </div>
            )}

            {vDecs.length > 0 && (
              <div className={styles.decisionsBlock}>
                {vDecs.map(d => (
                  <DecisionCard key={d.id} decision={d} onApprove={() => approve(d.id)} onReject={() => reject(d.id)} />
                ))}
              </div>
            )}
          </section>
        ))}

        {/* Pôles sans venture */}
        {orphanPoles.length > 0 && (
          <section className={styles.section}>
            <div className={styles.sectionTitle}>
              Pôles hors venture
              <span className={styles.count}>{orphanPoles.length} pôles</span>
            </div>
            <div className={styles.polesGrid}>
              {orphanPoles.map(pole => (
                <PoleCard key={pole.id} pole={pole} onToggle={() => togglePause(pole.id)} />
              ))}
            </div>
            {orphanDecisions.map(d => (
              <DecisionCard key={d.id} decision={d} onApprove={() => approve(d.id)} onReject={() => reject(d.id)} />
            ))}
          </section>
        )}

        {ventureGroups.length === 0 && orphanPoles.length === 0 && (
          <div className={styles.empty}>No poles yet — create them in Ventures</div>
        )}

        {/* Décisions globales en attente résumé */}
        {decisions.length === 0 && (
          <section className={styles.section}>
            <div className={styles.sectionTitle}>Pending decisions</div>
            <div className={styles.empty}>No decisions pending ✓</div>
          </section>
        )}

        {/* Morning Brief */}
        <section className={styles.section}>
          <div className={styles.sectionTitle}>
            Morning Brief
          </div>
          <div className={styles.briefBox}>
            <button
              className={styles.btnBrief}
              onClick={generateBrief}
              disabled={briefLoading}
            >
              {briefLoading ? '⟳ Génération…' : '☀️ Générer le brief du jour'}
            </button>
            {brief && (
              <div className={styles.briefContent}>{brief}</div>
            )}
          </div>
        </section>

        {/* Flux Blackboard N0 */}
        <section className={styles.section}>
          <div className={styles.sectionTitle}>
            Blackboard — N0 events
            {bbEvents.length > 0 && (
              <span className={styles.badgeRed}>{bbEvents.length}</span>
            )}
          </div>
          {bbEvents.length === 0 ? (
            <div className={styles.empty}>No recent N0 events</div>
          ) : (
            <div className={styles.bbList}>
              {bbEvents.map((ev, i) => (
                <div key={ev.id || i} className={styles.bbEvent}>
                  <span className={styles.bbTime}>
                    {new Date(ev.createdAt || ev.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                  </span>
                  <span className={styles.bbPole}>{ev.poleEmoji} {ev.poleNom}</span>
                  <span className={styles.bbAgent}>{ev.agentNom}</span>
                  <span className={styles.bbPayload}>{ev.payload}</span>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  )
}

function PoleCard({ pole, onToggle }) {
  return (
    <div
      className={styles.poleCard}
      style={{ borderColor: pole.enPause ? 'var(--red)' : pole.couleur, opacity: pole.enPause ? 0.7 : 1 }}
    >
      <div className={styles.poleCardTop}>
        <span className={styles.poleEmoji}>{pole.emoji}</span>
        <span
          className={styles.statusDot}
          style={{ background: pole.enPause ? 'var(--red)' : 'var(--green)' }}
        />
      </div>
      <div className={styles.poleName}>{pole.nom}</div>
      <div className={styles.poleMeta}>
        {pole.nbMembres} agent{pole.nbMembres !== 1 ? 's' : ''}
        {pole.nbDecisions > 0 && (
          <span className={styles.decBadge}>{pole.nbDecisions} N0</span>
        )}
      </div>
      <div className={styles.poleStatus} style={{ color: pole.enPause ? 'var(--red)' : 'var(--green)' }}>
        {pole.enPause ? '⏸ Paused' : '● Active'}
      </div>
      <button
        className={styles.killBtn}
        style={{
          background: pole.enPause ? 'rgba(16,185,129,0.1)' : 'rgba(239,68,68,0.1)',
          color:      pole.enPause ? 'var(--green)' : 'var(--red)',
        }}
        onClick={onToggle}
      >
        {pole.enPause ? '▶ Resume' : '⏸ Pause'}
      </button>
    </div>
  )
}

function DecisionCard({ decision, onApprove, onReject }) {
  const niv = NIVEAU_STYLE[decision.niveau] || NIVEAU_STYLE.N0
  return (
    <div
      className={styles.decisionCard}
      style={{ borderLeft: decision.urgence === 'haute' ? '3px solid var(--red)' : undefined }}
    >
      <div className={styles.decisionMeta}>
        <span className={styles.decisionPole}>{decision.poleNom}</span>
        <span className={styles.niveauBadge} style={{ background: niv.bg, color: niv.color }}>
          {decision.niveau}
        </span>
      </div>
      <div className={styles.decisionAgent}>{decision.agentNom}</div>
      <div className={styles.decisionAction}>{decision.action}</div>
      <div className={styles.decisionFooter}>
        {decision.urgence === 'haute' && (
          <span className={styles.urgenceBadge}>🚨 Urgent</span>
        )}
        <div className={styles.decisionBtns}>
          <button className={styles.btnApprove} onClick={onApprove}>✓ Approve</button>
          <button className={styles.btnReject}  onClick={onReject}>✕ Reject</button>
        </div>
      </div>
    </div>
  )
}

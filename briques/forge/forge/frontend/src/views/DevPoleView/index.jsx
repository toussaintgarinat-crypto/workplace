import { useState, useEffect } from 'react'
import { api } from '../../services/api'
import styles from './DevPole.module.css'

const STATUS_LABELS = {
  pending:   { label: 'En attente',  color: '#f59e0b', icon: '⏳' },
  analyzing: { label: 'Analyse IA',  color: '#3b82f6', icon: '🔍' },
  analyzed:  { label: 'Analysé',     color: '#8b5cf6', icon: '✅' },
  building:  { label: 'En cours',    color: '#6366f1', icon: '🔨' },
  deployed:  { label: 'Déployé',     color: '#10b981', icon: '🚀' },
  rejected:  { label: 'Rejeté',      color: '#ef4444', icon: '❌' },
}

const PRIORITY_COLORS = {
  low: '#64748b', medium: '#f59e0b', high: '#f97316', critical: '#ef4444',
}

export default function DevPoleView({ poleId }) {
  const [requests, setRequests]     = useState([])
  const [selected, setSelected]     = useState(null)
  const [filter, setFilter]         = useState('all')
  const [analyzing, setAnalyzing]   = useState(false)
  const [deploying, setDeploying]   = useState(false)
  const [deployForm, setDeployForm] = useState({ trigger: '', action: '' })
  const [showDeploy, setShowDeploy] = useState(false)
  const [updating, setUpdating]     = useState(false)

  useEffect(() => {
    api.get('/api/dev/requests').then(setRequests).catch(() => {})
  }, [])

  const filtered = filter === 'all'
    ? requests
    : requests.filter(r => r.status === filter)

  async function analyze(id) {
    setAnalyzing(true)
    try {
      const res = await api.post(`/api/dev/requests/${id}/analyze`, {})
      setRequests(rs => rs.map(r => r.id === id ? { ...r, ...res } : r))
      setSelected(s => s?.id === id ? { ...s, ...res } : s)
    } finally { setAnalyzing(false) }
  }

  async function updateStatus(id, status, extra = {}) {
    setUpdating(true)
    try {
      const res = await api.patch(`/api/dev/requests/${id}`, { status, ...extra })
      setRequests(rs => rs.map(r => r.id === id ? res : r))
      setSelected(s => s?.id === id ? res : s)
    } finally { setUpdating(false) }
  }

  async function deploy(id) {
    setDeploying(true)
    try {
      const res = await api.post(`/api/dev/requests/${id}/deploy`, deployForm)
      setRequests(rs => rs.map(r => r.id === id ? res.request : r))
      setSelected(res.request)
      setShowDeploy(false)
    } finally { setDeploying(false) }
  }

  const counts = Object.fromEntries(
    Object.keys(STATUS_LABELS).map(s => [s, requests.filter(r => r.status === s).length])
  )

  const sel = selected
  const selStatus = sel ? STATUS_LABELS[sel.status] ?? STATUS_LABELS.pending : null

  return (
    <div className={styles.page}>
      <div className={styles.topbar}>
        <div>
          <h2 className={styles.title}>💻 Pôle Dev — Inbox Automatisation</h2>
          <p className={styles.sub}>Demandes reçues de tous les pôles</p>
        </div>
        <div className={styles.stats}>
          {Object.entries(STATUS_LABELS).map(([k, v]) => counts[k] > 0 && (
            <div key={k} className={styles.statChip}
              style={{ background: v.color + '18', color: v.color }}
              onClick={() => setFilter(filter === k ? 'all' : k)}
            >
              {v.icon} {counts[k]}
            </div>
          ))}
        </div>
      </div>

      <div className={styles.filters}>
        {['all', 'pending', 'analyzed', 'building', 'deployed', 'rejected'].map(f => (
          <button key={f}
            className={`${styles.filterBtn} ${filter === f ? styles.filterActive : ''}`}
            onClick={() => setFilter(f)}
          >
            {f === 'all' ? `Tout (${requests.length})` : `${STATUS_LABELS[f]?.label ?? f} (${counts[f] ?? 0})`}
          </button>
        ))}
      </div>

      <div className={styles.split}>
        {/* ── Liste demandes ─────────────────────────────────── */}
        <div className={styles.list}>
          {filtered.length === 0 && (
            <div className={styles.empty}>
              {filter === 'all'
                ? 'Aucune demande reçue. Les pôles enverront leurs tâches répétitives ici.'
                : 'Aucune demande dans ce statut.'}
            </div>
          )}
          {filtered.map(r => {
            const s = STATUS_LABELS[r.status] ?? STATUS_LABELS.pending
            return (
              <div key={r.id}
                className={`${styles.card} ${selected?.id === r.id ? styles.cardActive : ''}`}
                onClick={() => { setSelected(r); setShowDeploy(false) }}
              >
                <div className={styles.cardTop}>
                  <span className={styles.poleChip}>
                    {r.sourcePoleEmoji} {r.sourcePoleName}
                  </span>
                  <span className={styles.statusDot} style={{ background: s.color }} title={s.label} />
                </div>
                <div className={styles.cardTitle}>{r.title}</div>
                <div className={styles.cardMeta}>
                  <span style={{ color: PRIORITY_COLORS[r.priority] }}>● {r.priority}</span>
                  <span className={styles.dot}>·</span>
                  <span>{r.frequency}</span>
                  <span className={styles.dot}>·</span>
                  <span>{new Date(r.createdAt).toLocaleDateString('fr-FR')}</span>
                </div>
              </div>
            )
          })}
        </div>

        {/* ── Détail ─────────────────────────────────────────── */}
        <div className={styles.detail}>
          {!sel && (
            <div className={styles.detailEmpty}>
              <div className={styles.detailEmptyIcon}>🤖</div>
              <p>Sélectionnez une demande pour l'analyser et déployer l'automatisation</p>
            </div>
          )}
          {sel && (
            <>
              <div className={styles.detailHead}>
                <div>
                  <div className={styles.detailPole}>
                    {sel.sourcePoleEmoji} {sel.sourcePoleName}
                  </div>
                  <h3 className={styles.detailTitle}>{sel.title}</h3>
                </div>
                <span className={styles.badge}
                  style={{ background: selStatus.color + '22', color: selStatus.color }}>
                  {selStatus.icon} {selStatus.label}
                </span>
              </div>

              <div className={styles.metaRow}>
                <span style={{ color: PRIORITY_COLORS[sel.priority] }}>⚡ {sel.priority}</span>
                <span>🔄 {sel.frequency}</span>
                <span>📅 {new Date(sel.createdAt).toLocaleDateString('fr-FR')}</span>
              </div>

              <div className={styles.section}>
                <div className={styles.sLabel}>Description</div>
                <p className={styles.sBody}>{sel.description}</p>
              </div>

              {sel.analysis && (
                <div className={styles.section}>
                  <div className={styles.sLabel}>🔍 Analyse IA</div>
                  <p className={styles.sBody}>{sel.analysis}</p>
                </div>
              )}

              {sel.proposedSolution && (
                <div className={styles.section}>
                  <div className={styles.sLabel}>💡 Solution proposée</div>
                  <p className={styles.sBody}>{sel.proposedSolution}</p>
                </div>
              )}

              {/* ── Actions ─────────────────────────────────── */}
              <div className={styles.actions}>
                {(sel.status === 'pending') && (
                  <button className={styles.btnAnalyze} onClick={() => analyze(sel.id)} disabled={analyzing}>
                    {analyzing ? '🔍 Analyse en cours…' : '🔍 Analyser avec IA'}
                  </button>
                )}

                {sel.status === 'analyzed' && (
                  <>
                    <button className={styles.btnBuild}
                      onClick={() => updateStatus(sel.id, 'building')} disabled={updating}>
                      🔨 Prendre en charge
                    </button>
                    <button className={styles.btnReject}
                      onClick={() => updateStatus(sel.id, 'rejected', { rejectionReason: 'Non faisable ou hors périmètre' })}
                      disabled={updating}>
                      Rejeter
                    </button>
                  </>
                )}

                {sel.status === 'building' && (
                  <button className={styles.btnDeploy}
                    onClick={() => setShowDeploy(v => !v)}>
                    🚀 Déployer l'automatisation
                  </button>
                )}

                {sel.status === 'deployed' && (
                  <div className={styles.deployedBanner}>
                    ✅ Automatisation active — déployée sur le pôle {sel.sourcePoleName}
                  </div>
                )}
              </div>

              {showDeploy && (
                <div className={styles.deployForm}>
                  <div className={styles.sLabel}>Déploiement</div>
                  <input className={styles.input}
                    placeholder="Déclencheur (ex: chaque lundi 08:00, on_new_crm_contact…)"
                    value={deployForm.trigger}
                    onChange={e => setDeployForm(f => ({ ...f, trigger: e.target.value }))}
                  />
                  <textarea className={styles.textarea} rows={3}
                    placeholder="Action à exécuter (ex: générer rapport hebdo, envoyer email résumé…)"
                    value={deployForm.action}
                    onChange={e => setDeployForm(f => ({ ...f, action: e.target.value }))}
                  />
                  <button className={styles.btnDeploy}
                    onClick={() => deploy(sel.id)} disabled={deploying || !deployForm.trigger || !deployForm.action}>
                    {deploying ? '…' : '🚀 Confirmer le déploiement'}
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}

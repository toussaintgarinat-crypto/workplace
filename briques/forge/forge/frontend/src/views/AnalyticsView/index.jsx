import { useState, useEffect } from 'react'
import { api } from '../../services/api'
import styles from './Analytics.module.css'

export default function AnalyticsView() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get('/api/analytics').then(d => { setData(d); setLoading(false) }).catch(() => setLoading(false))
  }, [])

  if (loading) return <div className={styles.loading}>Chargement des analytics...</div>
  if (!data) return <div className={styles.loading}>Erreur de chargement.</div>

  const stats = [
    { label: 'Pôles actifs', value: data.poles, icon: '🏢', color: '#818cf8' },
    { label: 'Sessions (30j)', value: data.sessions30j, icon: '💬', color: '#10b981' },
    { label: 'Messages', value: data.messages, icon: '📨', color: '#3b82f6' },
    { label: 'Leads CRM', value: data.crm.total, icon: '🤝', color: '#f59e0b' },
    { label: 'Leads gagnés', value: data.crm.gagnes, icon: '🏆', color: '#10b981' },
    { label: 'Incidents ouverts', value: data.incidentsOuverts, icon: '🚨', color: data.incidentsOuverts > 0 ? '#ef4444' : '#6b6b80' },
    { label: 'Articles KB', value: data.kb, icon: '📚', color: '#818cf8' },
    { label: 'Sprints', value: data.sprints, icon: '🎯', color: '#3b82f6' },
  ]

  return (
    <div className={styles.page}>
      <h1 className={styles.title}>📈 Analytics — Vue Fondateur</h1>
      <p className={styles.sub}>Métriques des 30 derniers jours</p>

      <div className={styles.statsGrid}>
        {stats.map(s => (
          <div key={s.label} className={styles.statCard}>
            <div className={styles.statIcon}>{s.icon}</div>
            <div className={styles.statValue} style={{ color: s.color }}>{s.value ?? 0}</div>
            <div className={styles.statLabel}>{s.label}</div>
          </div>
        ))}
      </div>

      <div className={styles.row}>
        <div className={styles.card}>
          <h2 className={styles.cardTitle}>💰 Finance (30j)</h2>
          <div className={styles.financeRow}>
            <div><div className={styles.fLabel}>Recettes</div><div className={styles.fValue} style={{ color: '#10b981' }}>+{(data.budget.recettes ?? 0).toLocaleString()} €</div></div>
            <div><div className={styles.fLabel}>Dépenses</div><div className={styles.fValue} style={{ color: '#ef4444' }}>-{(data.budget.depenses ?? 0).toLocaleString()} €</div></div>
            <div><div className={styles.fLabel}>Solde</div><div className={styles.fValue} style={{ color: (data.budget.solde ?? 0) >= 0 ? '#10b981' : '#ef4444' }}>{(data.budget.solde ?? 0) >= 0 ? '+' : ''}{(data.budget.solde ?? 0).toLocaleString()} €</div></div>
          </div>
        </div>
        <div className={styles.card}>
          <h2 className={styles.cardTitle}>🔔 Événements récents</h2>
          <div className={styles.eventList}>
            {(data.recentEvents ?? []).length === 0 && <p className={styles.empty}>Aucun événement récent.</p>}
            {(data.recentEvents ?? []).slice(0, 5).map(e => (
              <div key={e.id} className={styles.eventRow}>
                <span className={styles.eventPole}>{e.poleEmoji} {e.poleNom}</span>
                <span className={styles.eventType}>{e.type}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

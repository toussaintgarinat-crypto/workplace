import { useState, useEffect } from 'react'
import { api } from '../../services/api'
import styles from './SLO.module.css'

const COULEUR_SCORE = s => s >= 90 ? '#10b981' : s >= 70 ? '#f59e0b' : '#ef4444'

export default function SLOView() {
  const [data, setData] = useState({ modules: [], healthScore: 100 })

  useEffect(() => {
    api.get('/api/slo').then(setData).catch(() => {})
  }, [])

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <h1 className={styles.title}>📊 SLO Dashboard</h1>
        <div className={styles.globalScore}>
          <div className={styles.scoreLabel}>Health Score Global</div>
          <div className={styles.scoreValue} style={{ color: COULEUR_SCORE(data.healthScore) }}>
            {data.healthScore}
            <span className={styles.scoreUnit}>/100</span>
          </div>
        </div>
      </div>

      {data.modules.length === 0 && (
        <div className={styles.empty}>
          <p>Aucun module configuré.</p>
          <p className={styles.hint}>Les métriques SLO apparaîtront ici automatiquement au fur et à mesure de l'utilisation.</p>
        </div>
      )}

      <div className={styles.grid}>
        {data.modules.map(m => (
          <div key={m.id} className={styles.moduleCard}>
            <div className={styles.moduleHeader}>
              <span className={styles.moduleName}>{m.module}</span>
              <div className={styles.scoreChip} style={{
                background: COULEUR_SCORE(m.healthScore) + '22',
                color: COULEUR_SCORE(m.healthScore),
              }}>
                {m.healthScore}/100
              </div>
            </div>
            <div className={styles.sloBar}>
              <div className={styles.sloFill} style={{
                width: `${m.sloCurrent ?? 100}%`,
                background: COULEUR_SCORE(m.healthScore),
              }} />
            </div>
            <div className={styles.moduleMeta}>
              <span>SLO : {m.sloCurrent?.toFixed(2)}% / {m.sloTarget?.toFixed(2)}%</span>
              <span style={{ color: m.erreurs24h > 0 ? '#ef4444' : '#6b6b80' }}>
                {m.erreurs24h} erreurs 24h
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

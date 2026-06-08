import { useState, useEffect } from 'react'
import { api } from '../../services/api'
import styles from './Governor.module.css'

export default function GovernorView() {
  const [config, setConfig] = useState({ budgetJournalier: 100000, budgetMensuel: 2000000, alerteSeuil: 80, blocageSeuil: 95, actif: true })
  const [usage, setUsage] = useState({ rows: [], totalTokens: 0, totalCout: 0 })
  const [editConfig, setEditConfig] = useState(false)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    api.get('/api/governor/config').then(setConfig).catch(() => {})
    const depuis = new Date(Date.now() - 30 * 24 * 60 * 60 * 1000).toISOString()
    api.get(`/api/governor/usage?depuis=${depuis}`).then(setUsage).catch(() => {})
  }, [])

  async function saveConfig() {
    setSaving(true)
    try {
      const updated = await api.put('/api/governor/config', config)
      setConfig(updated)
      setEditConfig(false)
    } finally { setSaving(false) }
  }

  const pctJournalier = Math.min(100, Math.round((usage.totalTokens / config.budgetJournalier) * 100))

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <h1 className={styles.title}>⚙️ Governor — Budget Tokens</h1>
        <button className={styles.btnPrimary} onClick={() => setEditConfig(v => !v)}>
          {editConfig ? 'Annuler' : '✏️ Configurer'}
        </button>
      </div>

      {editConfig && (
        <div className={styles.configForm}>
          <h3 className={styles.formTitle}>Configuration des seuils</h3>
          <div className={styles.formGrid}>
            <label className={styles.fieldLabel}>
              Budget journalier (tokens)
              <input className={styles.input} type="number" value={config.budgetJournalier}
                onChange={e => setConfig(c => ({ ...c, budgetJournalier: parseInt(e.target.value) }))} />
            </label>
            <label className={styles.fieldLabel}>
              Budget mensuel (tokens)
              <input className={styles.input} type="number" value={config.budgetMensuel}
                onChange={e => setConfig(c => ({ ...c, budgetMensuel: parseInt(e.target.value) }))} />
            </label>
            <label className={styles.fieldLabel}>
              Seuil alerte (%)
              <input className={styles.input} type="number" min="0" max="100" value={config.alerteSeuil}
                onChange={e => setConfig(c => ({ ...c, alerteSeuil: parseInt(e.target.value) }))} />
            </label>
            <label className={styles.fieldLabel}>
              Seuil blocage (%)
              <input className={styles.input} type="number" min="0" max="100" value={config.blocageSeuil}
                onChange={e => setConfig(c => ({ ...c, blocageSeuil: parseInt(e.target.value) }))} />
            </label>
          </div>
          <div className={styles.formActions}>
            <button className={styles.btnPrimary} disabled={saving} onClick={saveConfig}>
              {saving ? 'Sauvegarde...' : 'Sauvegarder'}
            </button>
          </div>
        </div>
      )}

      <div className={styles.stats}>
        <div className={styles.statCard}>
          <div className={styles.statLabel}>Tokens utilisés (30j)</div>
          <div className={styles.statValue}>{usage.totalTokens.toLocaleString()}</div>
        </div>
        <div className={styles.statCard}>
          <div className={styles.statLabel}>Coût estimé (30j)</div>
          <div className={styles.statValue}>${usage.totalCout.toFixed(4)}</div>
        </div>
        <div className={styles.statCard}>
          <div className={styles.statLabel}>Budget mensuel</div>
          <div className={styles.statValue}>{config.budgetMensuel.toLocaleString()} tok</div>
        </div>
        <div className={styles.statCard}>
          <div className={styles.statLabel}>Statut</div>
          <div className={styles.statValue} style={{ color: config.actif ? '#10b981' : '#ef4444' }}>
            {config.actif ? '✅ Actif' : '⛔ Inactif'}
          </div>
        </div>
      </div>

      <div className={styles.progressSection}>
        <div className={styles.progressLabel}>
          <span>Consommation journalière</span>
          <span style={{ color: pctJournalier >= config.blocageSeuil ? '#ef4444' : pctJournalier >= config.alerteSeuil ? '#f59e0b' : '#10b981' }}>
            {pctJournalier}%
          </span>
        </div>
        <div className={styles.progressBar}>
          <div className={styles.progressFill} style={{
            width: `${pctJournalier}%`,
            background: pctJournalier >= config.blocageSeuil ? '#ef4444' : pctJournalier >= config.alerteSeuil ? '#f59e0b' : '#10b981'
          }} />
        </div>
        <div className={styles.progressTicks}>
          <span>0</span>
          <span style={{ color: '#f59e0b' }}>Alerte: {config.alerteSeuil}%</span>
          <span style={{ color: '#ef4444' }}>Blocage: {config.blocageSeuil}%</span>
        </div>
      </div>

      <div className={styles.section}>
        <h2 className={styles.sectionTitle}>Historique d'usage</h2>
        <div className={styles.usageList}>
          {usage.rows.length === 0 && <p className={styles.empty}>Aucun usage enregistré.</p>}
          {usage.rows.slice(0, 50).map(r => (
            <div key={r.id} className={styles.usageRow}>
              <div>
                <div className={styles.rowTitle}>{r.provider} / {r.model}</div>
                <div className={styles.rowSub}>{new Date(r.createdAt).toLocaleString('fr-FR')}</div>
              </div>
              <div className={styles.rowRight}>
                <span className={styles.chip}>{(r.tokensIn + r.tokensOut).toLocaleString()} tok</span>
                <span style={{ color: '#6b6b80', fontSize: 12 }}>${r.coutUsd?.toFixed(4)}</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

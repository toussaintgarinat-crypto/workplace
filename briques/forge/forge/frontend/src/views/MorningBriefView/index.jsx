import { useState, useEffect } from 'react'
import { api } from '../../services/api'
import styles from './MorningBrief.module.css'

export default function MorningBriefView() {
  const [briefs, setBriefs] = useState([])
  const [config, setConfig] = useState({ enabled: true, heureUtc: '07:00', joursSemaine: [1,2,3,4,5] })
  const [selected, setSelected] = useState(null)
  const [generating, setGenerating] = useState(false)
  const [showConfig, setShowConfig] = useState(false)

  useEffect(() => {
    api.get('/api/briefs').then(r => { setBriefs(Array.isArray(r) ? r : []); if (r.length > 0) setSelected(r[0]) }).catch(() => {})
    api.get('/api/brief/config').then(setConfig).catch(() => {})
  }, [])

  async function generate() {
    setGenerating(true)
    try {
      const brief = await api.post('/api/briefs/generate', {})
      setBriefs(bs => [brief, ...bs])
      setSelected(brief)
    } finally { setGenerating(false) }
  }

  async function saveConfig() {
    await api.put('/api/brief/config', config)
    setShowConfig(false)
  }

  async function markRead(id) {
    await api.patch(`/api/briefs/${id}/lu`, {})
    setBriefs(bs => bs.map(b => b.id === id ? { ...b, lu: true } : b))
  }

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <h1 className={styles.title}>☀️ Morning Brief</h1>
        <div className={styles.actions}>
          <button className={styles.btnSecondary} onClick={() => setShowConfig(v => !v)}>⚙️ Config</button>
          <button className={styles.btnPrimary} onClick={generate} disabled={generating}>
            {generating ? 'Génération...' : '+ Générer brief'}
          </button>
        </div>
      </div>

      {showConfig && (
        <div className={styles.configCard}>
          <h3 className={styles.configTitle}>Configuration du brief automatique</h3>
          <div className={styles.configRow}>
            <label className={styles.fieldLabel}>
              Heure (UTC)
              <input className={styles.input} type="time" value={config.heureUtc}
                onChange={e => setConfig(c => ({ ...c, heureUtc: e.target.value }))} />
            </label>
            <label className={styles.fieldLabel}>
              <input type="checkbox" checked={config.enabled}
                onChange={e => setConfig(c => ({ ...c, enabled: e.target.checked }))} />
              Brief automatique activé
            </label>
          </div>
          <button className={styles.btnPrimary} onClick={saveConfig}>Sauvegarder</button>
        </div>
      )}

      <div className={styles.layout}>
        <div className={styles.sidebar}>
          {briefs.length === 0 && <p className={styles.empty}>Aucun brief.</p>}
          {briefs.map(b => (
            <div key={b.id} className={`${styles.briefItem} ${selected?.id === b.id ? styles.active : ''}`}
              onClick={() => { setSelected(b); if (!b.lu) markRead(b.id) }}>
              <div className={styles.briefTitle}>{b.titre}</div>
              <div className={styles.briefMeta}>
                <span className={styles.typeChip}>{b.type}</span>
                {!b.lu && <span className={styles.newDot} />}
              </div>
            </div>
          ))}
        </div>
        <div className={styles.content}>
          {selected ? (
            <>
              <h2 className={styles.contentTitle}>{selected.titre}</h2>
              <p className={styles.contentDate}>{new Date(selected.createdAt).toLocaleString('fr-FR')}</p>
              <div className={styles.contentBody}>
                {selected.contenu.split('\n').map((line, i) => (
                  <p key={i} className={line.startsWith('#') ? styles.heading : styles.para}>{line}</p>
                ))}
              </div>
            </>
          ) : (
            <div className={styles.emptyContent}>
              <p>Sélectionnez un brief ou générez-en un nouveau.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

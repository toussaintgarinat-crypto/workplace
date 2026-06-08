import { useState, useEffect } from 'react'
import { api } from '../../../services/api'
import styles from './Panel.module.css'

export default function RapportPanel({ poleId }) {
  const [rapports, setRapports] = useState([])
  const [selected, setSelected] = useState(null)
  const [generating, setGenerating] = useState(false)
  const [type, setType] = useState('weekly')

  useEffect(() => { load() }, [])

  async function load() {
    const data = await api.get('/api/rapports').catch(() => [])
    const list = Array.isArray(data) ? data : []
    setRapports(list)
    if (list.length > 0) setSelected(list[0])
  }

  async function generate() {
    setGenerating(true)
    try {
      const r = await api.post('/api/rapports/generate', { type })
      setRapports(rs => [r, ...rs])
      setSelected(r)
    } finally { setGenerating(false) }
  }

  async function remove(id) {
    await api.delete(`/api/rapports/${id}`)
    setRapports(rs => rs.filter(r => r.id !== id))
    if (selected?.id === id) setSelected(null)
  }

  return (
    <div className={styles.panel}>
      <div className={styles.toolbar}>
        <select className={styles.select} value={type} onChange={e => setType(e.target.value)} style={{ flex: 'unset', width: 'auto' }}>
          <option value="weekly">Hebdomadaire</option>
          <option value="monthly">Mensuel</option>
          <option value="custom">Personnalisé</option>
        </select>
        <button className={styles.btnPrimary} onClick={generate} disabled={generating}>
          {generating ? 'Génération...' : '+ Générer'}
        </button>
      </div>

      {rapports.length === 0 && <p className={styles.empty}>Aucun rapport généré.</p>}

      <div style={{ display: 'flex', gap: 12, minHeight: 200 }}>
        {rapports.length > 0 && (
          <div style={{ width: 200, flexShrink: 0, display: 'flex', flexDirection: 'column', gap: 4 }}>
            {rapports.map(r => (
              <div key={r.id} className={`${styles.row} ${selected?.id === r.id ? styles.form : ''}`}
                style={{ cursor: 'pointer', padding: '8px 12px' }} onClick={() => setSelected(r)}>
                <div>
                  <div className={styles.rowTitle} style={{ fontSize: 12 }}>{r.titre.slice(0, 40)}</div>
                  <div className={styles.rowSub}>{new Date(r.createdAt).toLocaleDateString('fr-FR')}</div>
                </div>
                <button className={styles.micro} style={{ color: '#ef4444' }} onClick={ev => { ev.stopPropagation(); remove(r.id) }}>✕</button>
              </div>
            ))}
          </div>
        )}
        {selected && (
          <div style={{ flex: 1, background: '#13131a', border: '1px solid #1e1e2e', borderRadius: 8, padding: 16, overflowY: 'auto' }}>
            <div className={styles.rowTitle} style={{ fontSize: 15, marginBottom: 12 }}>{selected.titre}</div>
            <div style={{ fontSize: 13, color: '#a8a8c0', lineHeight: 1.7, whiteSpace: 'pre-wrap' }}>
              {selected.contenu}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

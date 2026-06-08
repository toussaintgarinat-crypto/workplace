import { useState } from 'react'
import { api } from '../../../services/api'
import styles from './Panel.module.css'

const TYPES = ['article', 'post_linkedin', 'tweet', 'email', 'landing_page', 'newsletter']
const LONGUEURS = ['court', 'moyen', 'long']

export default function ContentAgentPanel({ poleId }) {
  const [form, setForm] = useState({ sujet: '', type: 'article', ton: 'professionnel', longueur: 'moyen' })
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)

  async function generate(e) {
    e.preventDefault()
    setLoading(true)
    try {
      const data = await api.post('/api/content-agent/generate', form)
      setResult(data)
    } finally { setLoading(false) }
  }

  return (
    <div className={styles.panel}>
      <form className={styles.form} onSubmit={generate}>
        <input className={styles.input} placeholder="Sujet du contenu *" required value={form.sujet}
          onChange={e => setForm(f => ({ ...f, sujet: e.target.value }))} />
        <div style={{ display: 'flex', gap: 8 }}>
          <select className={styles.select} value={form.type} onChange={e => setForm(f => ({ ...f, type: e.target.value }))}>
            {TYPES.map(t => <option key={t} value={t}>{t}</option>)}
          </select>
          <select className={styles.select} value={form.longueur} onChange={e => setForm(f => ({ ...f, longueur: e.target.value }))}>
            {LONGUEURS.map(l => <option key={l} value={l}>{l}</option>)}
          </select>
        </div>
        <input className={styles.input} placeholder="Ton (ex: professionnel, décontracté, inspirant...)" value={form.ton}
          onChange={e => setForm(f => ({ ...f, ton: e.target.value }))} />
        <button type="submit" className={styles.btnPrimary} disabled={loading}>
          {loading ? 'Génération...' : '✍️ Générer le contenu'}
        </button>
      </form>

      {result && (
        <div className={styles.form}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
            <span className={styles.rowTitle}>{result.type} — {result.sujet}</span>
            <button className={styles.micro} onClick={() => navigator.clipboard?.writeText(result.contenu)}>📋 Copier</button>
          </div>
          <div style={{ fontSize: 13, color: '#a8a8c0', lineHeight: 1.7, whiteSpace: 'pre-wrap', maxHeight: 400, overflowY: 'auto' }}>
            {result.contenu}
          </div>
        </div>
      )}
    </div>
  )
}

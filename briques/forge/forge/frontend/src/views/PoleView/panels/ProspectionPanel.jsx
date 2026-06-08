import { useState } from 'react'
import { api } from '../../../services/api'
import styles from './Panel.module.css'

export default function ProspectionPanel({ poleId }) {
  const [form, setForm] = useState({ entreprise: '', secteur: '', url: '', contact: '' })
  const [result, setResult] = useState(null)
  const [email, setEmail] = useState(null)
  const [loading, setLoading] = useState(false)
  const [emailLoading, setEmailLoading] = useState(false)
  const [tab, setTab] = useState('analyse')

  async function analyze(e) {
    e.preventDefault()
    setLoading(true)
    try {
      const data = await api.post('/api/prospection/analyze', form)
      setResult(data)
    } finally { setLoading(false) }
  }

  async function generateEmail(e) {
    e.preventDefault()
    setEmailLoading(true)
    try {
      const data = await api.post('/api/prospection/email', { entreprise: form.entreprise, contact: form.contact })
      setEmail(data.email)
    } finally { setEmailLoading(false) }
  }

  return (
    <div className={styles.panel}>
      <div className={styles.toolbar}>
        <div className={styles.filterGroup}>
          <button className={`${styles.filterBtn} ${tab === 'analyse' ? styles.active : ''}`} onClick={() => setTab('analyse')}>🎯 Analyse</button>
          <button className={`${styles.filterBtn} ${tab === 'email' ? styles.active : ''}`} onClick={() => setTab('email')}>📧 Email</button>
        </div>
      </div>

      <form className={styles.form} onSubmit={tab === 'analyse' ? analyze : generateEmail}>
        <input className={styles.input} placeholder="Entreprise cible *" required value={form.entreprise}
          onChange={e => setForm(f => ({ ...f, entreprise: e.target.value }))} />
        <div style={{ display: 'flex', gap: 8 }}>
          <input className={styles.input} placeholder="Secteur" value={form.secteur}
            onChange={e => setForm(f => ({ ...f, secteur: e.target.value }))} />
          <input className={styles.input} placeholder="Contact" value={form.contact}
            onChange={e => setForm(f => ({ ...f, contact: e.target.value }))} />
        </div>
        {tab === 'analyse' && (
          <input className={styles.input} type="url" placeholder="Site web (optionnel)" value={form.url}
            onChange={e => setForm(f => ({ ...f, url: e.target.value }))} />
        )}
        <button type="submit" className={styles.btnPrimary} disabled={loading || emailLoading}>
          {tab === 'analyse' ? (loading ? 'Analyse...' : '🎯 Analyser la cible') : (emailLoading ? 'Génération...' : '📧 Générer l\'email')}
        </button>
      </form>

      {tab === 'analyse' && result && (
        <div className={styles.form}>
          <div className={styles.rowTitle}>Analyse — {result.entreprise}</div>
          <div style={{ fontSize: 13, color: '#a8a8c0', lineHeight: 1.7, whiteSpace: 'pre-wrap', maxHeight: 400, overflowY: 'auto' }}>
            {result.analyse}
          </div>
        </div>
      )}

      {tab === 'email' && email && (
        <div className={styles.form}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
            <span className={styles.rowTitle}>Email de prospection</span>
            <button className={styles.micro} onClick={() => navigator.clipboard?.writeText(email)}>📋 Copier</button>
          </div>
          <div style={{ fontSize: 13, color: '#a8a8c0', lineHeight: 1.7, whiteSpace: 'pre-wrap' }}>{email}</div>
        </div>
      )}
    </div>
  )
}

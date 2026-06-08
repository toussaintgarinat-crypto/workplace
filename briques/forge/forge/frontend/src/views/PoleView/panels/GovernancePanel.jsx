import { useState, useEffect } from 'react'
import { api } from '../../../services/api'
import styles from './Panel.module.css'

function McpSection({ poleId }) {
  const [servers, setServers]   = useState([])
  const [form, setForm]         = useState({ nom: '', url: '', authType: 'none', authToken: '' })
  const [showForm, setShowForm] = useState(false)

  useEffect(() => {
    api.get(`/api/mcp/servers?poleId=${poleId}`).then(setServers).catch(() => {})
  }, [poleId])

  async function add(e) {
    e.preventDefault()
    const s = await api.post('/api/mcp/servers', { ...form, poleId })
    setServers(p => [...p, s])
    setForm({ nom: '', url: '', authType: 'none', authToken: '' })
    setShowForm(false)
  }

  async function del(id) {
    await api.delete(`/api/mcp/servers/${id}`)
    setServers(p => p.filter(s => s.id !== id))
  }

  return (
    <div className={styles.govSection}>
      <div className={styles.govHeader}>
        <span className={styles.govTitle}>🔌 Serveurs MCP</span>
        <button className={styles.btnPrimary} onClick={() => setShowForm(v => !v)}>+ Ajouter</button>
      </div>
      {showForm && (
        <form className={styles.govForm} onSubmit={add}>
          <input className={styles.input} placeholder="Nom *" required value={form.nom}
            onChange={e => setForm(f => ({ ...f, nom: e.target.value }))} />
          <input className={styles.input} placeholder="URL *" required value={form.url}
            onChange={e => setForm(f => ({ ...f, url: e.target.value }))} />
          <select className={styles.select} value={form.authType}
            onChange={e => setForm(f => ({ ...f, authType: e.target.value }))}>
            <option value="none">Pas d'auth</option>
            <option value="bearer">Bearer token</option>
            <option value="basic">Basic auth</option>
          </select>
          {form.authType !== 'none' && (
            <input className={styles.input} placeholder="Token" value={form.authToken}
              onChange={e => setForm(f => ({ ...f, authToken: e.target.value }))} />
          )}
          <div className={styles.formActions}>
            <button type="submit" className={styles.btnPrimary}>Ajouter</button>
            <button type="button" className={styles.btnGhost} onClick={() => setShowForm(false)}>Annuler</button>
          </div>
        </form>
      )}
      {servers.length === 0 && !showForm && <p className={styles.empty}>Aucun serveur MCP pour ce pôle.</p>}
      {servers.map(s => (
        <div key={s.id} className={styles.govCard}>
          <div className={styles.govCardInfo}>
            <div className={styles.govCardName}>{s.nom}</div>
            <div className={styles.govCardUrl}>{s.url}</div>
          </div>
          <span className={`${styles.govBadge} ${s.actif ? styles.govBadgeGreen : styles.govBadgeGray}`}>
            {s.actif ? 'Actif' : 'Inactif'}
          </span>
          <button className={styles.govDelete} onClick={() => del(s.id)}>✕</button>
        </div>
      ))}
    </div>
  )
}

function SkillsSection({ poleId }) {
  const [skills, setSkills]     = useState([])
  const [form, setForm]         = useState({ nom: '', description: '', skillMd: '' })
  const [showForm, setShowForm] = useState(false)

  useEffect(() => {
    api.get(`/api/skills?poleId=${poleId}`).then(setSkills).catch(() => {})
  }, [poleId])

  async function add(e) {
    e.preventDefault()
    const s = await api.post('/api/skills', { ...form, tags: [], actif: true, poleId })
    setSkills(p => [...p, s])
    setForm({ nom: '', description: '', skillMd: '' })
    setShowForm(false)
  }

  async function toggle(id, actif) {
    const updated = await api.patch(`/api/skills/${id}`, { actif: !actif })
    setSkills(p => p.map(s => s.id === id ? updated : s))
  }

  async function del(id) {
    await api.delete(`/api/skills/${id}`)
    setSkills(p => p.filter(s => s.id !== id))
  }

  return (
    <div className={styles.govSection}>
      <div className={styles.govHeader}>
        <span className={styles.govTitle}>🧩 Skills</span>
        <button className={styles.btnPrimary} onClick={() => setShowForm(v => !v)}>+ Créer</button>
      </div>
      {showForm && (
        <form className={styles.govForm} onSubmit={add}>
          <input className={styles.input} placeholder="Nom *" required value={form.nom}
            onChange={e => setForm(f => ({ ...f, nom: e.target.value }))} />
          <input className={styles.input} placeholder="Description" value={form.description}
            onChange={e => setForm(f => ({ ...f, description: e.target.value }))} />
          <textarea className={styles.textarea} placeholder="Contenu SKILL.md *" required rows={6} value={form.skillMd}
            onChange={e => setForm(f => ({ ...f, skillMd: e.target.value }))} />
          <div className={styles.formActions}>
            <button type="submit" className={styles.btnPrimary}>Créer</button>
            <button type="button" className={styles.btnGhost} onClick={() => setShowForm(false)}>Annuler</button>
          </div>
        </form>
      )}
      {skills.length === 0 && !showForm && <p className={styles.empty}>Aucun skill pour ce pôle.</p>}
      {skills.map(s => (
        <div key={s.id} className={styles.govCard}>
          <div className={styles.govCardInfo}>
            <div className={styles.govCardName}>{s.nom}</div>
            {s.description && <div className={styles.govCardUrl}>{s.description}</div>}
          </div>
          <button className={`${styles.govBadge} ${s.actif ? styles.govBadgeGreen : styles.govBadgeGray}`}
            onClick={() => toggle(s.id, s.actif)}>
            {s.actif ? 'Actif' : 'Inactif'}
          </button>
          <button className={styles.govDelete} onClick={() => del(s.id)}>✕</button>
        </div>
      ))}
    </div>
  )
}

export default function GovernancePanel({ poleId }) {
  const [section, setSection] = useState('mcp')

  return (
    <div className={styles.panel}>
      <div className={styles.toolbar}>
        <button className={`${styles.filterBtn} ${section === 'mcp' ? styles.filterActive : ''}`}
          onClick={() => setSection('mcp')}>🔌 MCP</button>
        <button className={`${styles.filterBtn} ${section === 'skills' ? styles.filterActive : ''}`}
          onClick={() => setSection('skills')}>🧩 Skills</button>
      </div>
      {section === 'mcp'    && <McpSection    poleId={poleId} />}
      {section === 'skills' && <SkillsSection poleId={poleId} />}
    </div>
  )
}

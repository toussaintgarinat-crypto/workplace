import { useState, useEffect } from 'react'
import { token } from '../../services/api'
import styles from './GitPackView.module.css'

const BASE = ''
async function req(path, opts = {}) {
  const t = token.get()
  const res = await fetch(`${BASE}${path}`, {
    ...opts,
    headers: { 'Content-Type': 'application/json', ...(t ? { Authorization: `Bearer ${t}` } : {}), ...opts.headers }
  })
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || 'Erreur')
  return res.json()
}

const STATUS_COLORS = {
  pending: '#6b7280',
  running: '#f59e0b',
  done:    '#10b981',
  error:   '#ef4444',
}

const STATUS_LABELS = {
  pending: 'En attente',
  running: 'Analyse…',
  done:    'Terminé',
  error:   'Erreur',
}

const PLATFORMS = [
  { value: 'macos',   label: '🍎 macOS' },
  { value: 'windows', label: '🪟 Windows' },
  { value: 'linux',   label: '🐧 Linux' },
]

export default function GitPackView() {
  const [jobs, setJobs]       = useState([])
  const [selected, setSelect] = useState(null)
  const [form, setForm]       = useState({ githubUrl: '', platform: 'macos' })
  const [loading, setLoading] = useState(false)
  const [err, setErr]         = useState(null)

  useEffect(() => {
    loadJobs()
    const iv = setInterval(loadJobs, 6000)
    return () => clearInterval(iv)
  }, [])

  async function loadJobs() {
    try {
      const data = await req('/api/gitpack/jobs')
      setJobs(data)
      setSelect(prev => prev ? (data.find(j => j.id === prev.id) ?? prev) : prev)
    } catch {}
  }

  async function submit(e) {
    e.preventDefault()
    setLoading(true)
    setErr(null)
    try {
      const job = await req('/api/gitpack/analyze', { method: 'POST', body: JSON.stringify(form) })
      setJobs(prev => [job, ...prev])
      setSelect(job)
      setForm({ githubUrl: '', platform: 'macos' })
    } catch (e) {
      setErr(e.message)
    } finally {
      setLoading(false)
    }
  }

  async function remove(id) {
    await req(`/api/gitpack/jobs/${id}`, { method: 'DELETE' })
    setJobs(prev => prev.filter(j => j.id !== id))
    if (selected?.id === id) setSelect(null)
  }

  function parseLogs(raw) {
    try { return JSON.parse(raw || '[]') } catch { return [] }
  }

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <span className={styles.icon}>📦</span>
        <div>
          <div className={styles.title}>GitPack</div>
          <div className={styles.subtitle}>GitHub repo → analyse IA + packaging</div>
        </div>
      </header>

      <div className={styles.body}>
        {/* Formulaire */}
        <section className={styles.card}>
          <div className={styles.cardTitle}>Analyser un dépôt GitHub</div>
          <form className={styles.form} onSubmit={submit}>
            <input
              className={styles.input}
              placeholder="URL du dépôt (ex: https://github.com/user/repo)"
              required
              value={form.githubUrl}
              onChange={e => setForm(f => ({ ...f, githubUrl: e.target.value }))}
            />
            <div className={styles.platformRow}>
              {PLATFORMS.map(p => (
                <button
                  key={p.value}
                  type="button"
                  className={`${styles.platformBtn} ${form.platform === p.value ? styles.platformActive : ''}`}
                  onClick={() => setForm(f => ({ ...f, platform: p.value }))}
                >
                  {p.label}
                </button>
              ))}
            </div>
            {err && <div className={styles.error}>{err}</div>}
            <button type="submit" className={styles.btnPrimary} disabled={loading}>
              {loading ? 'Envoi…' : '🚀 Analyser'}
            </button>
          </form>
        </section>

        {/* Liste des jobs + Détail */}
        <div className={styles.layout}>
          <div className={styles.jobList}>
            <div className={styles.sectionTitle}>Jobs ({jobs.length})</div>
            {jobs.length === 0 && <div className={styles.empty}>Aucun job. Lance une analyse ci-dessus.</div>}
            {jobs.map(job => (
              <div
                key={job.id}
                className={`${styles.jobItem} ${selected?.id === job.id ? styles.jobActive : ''}`}
                onClick={() => setSelect(job)}
              >
                <div className={styles.jobTop}>
                  <span
                    className={styles.statusDot}
                    style={{ background: STATUS_COLORS[job.statut] ?? '#6b7280' }}
                    title={STATUS_LABELS[job.statut]}
                  />
                  <span className={styles.jobRepo}>
                    {job.githubUrl.replace('https://github.com/', '')}
                  </span>
                  <button
                    className={styles.micro}
                    style={{ color: '#ef4444', marginLeft: 'auto' }}
                    onClick={e => { e.stopPropagation(); remove(job.id) }}
                  >✕</button>
                </div>
                <div className={styles.jobMeta}>
                  {STATUS_LABELS[job.statut]} · {job.platform}
                  {job.language && ` · ${job.language}`}
                </div>
              </div>
            ))}
          </div>

          {selected && (
            <div className={styles.detail}>
              <div className={styles.detailHeader}>
                <div className={styles.detailRepo}>{selected.githubUrl}</div>
                <span
                  className={styles.badge}
                  style={{ background: (STATUS_COLORS[selected.statut] ?? '#6b7280') + '22', color: STATUS_COLORS[selected.statut] ?? '#6b7280' }}
                >
                  {STATUS_LABELS[selected.statut]}
                </span>
              </div>

              <div className={styles.metaRow}>
                {selected.platform && <span className={styles.metaTag}>{PLATFORMS.find(p => p.value === selected.platform)?.label ?? selected.platform}</span>}
                {selected.language && <span className={styles.metaTag}>Lang: {selected.language}</span>}
                {selected.framework && <span className={styles.metaTag}>Framework: {selected.framework}</span>}
              </div>

              {selected.statut === 'running' && (
                <div className={styles.analyzing}>
                  <span className={styles.spinner}>⟳</span> Analyse IA en cours…
                </div>
              )}

              {selected.error && (
                <div className={styles.errorBox}>{selected.error}</div>
              )}

              {selected.logs && parseLogs(selected.logs).length > 0 && (
                <div className={styles.resultat}>
                  <div className={styles.resultatTitle}>Résultat de l'analyse</div>
                  <div className={styles.logBox}>
                    {parseLogs(selected.logs).map((line, i) => (
                      <div key={i} className={styles.logLine}>{line}</div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

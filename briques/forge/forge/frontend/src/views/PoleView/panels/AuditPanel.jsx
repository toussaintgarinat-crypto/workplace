import { useState, useEffect, useRef, useCallback } from 'react'
import { token } from '../../../services/api'
import styles from './Panel.module.css'

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

const STATUT_COLORS  = { brouillon: '#6b7280', actif: '#f59e0b', termine: '#10b981' }
const STATUT_LABELS  = { brouillon: 'Brouillon', actif: 'Actif', termine: 'Terminé' }
const SEV_COLORS     = { critique: '#ef4444', moyen: '#f59e0b', faible: '#6b7280' }
const PRIO_COLORS    = { haute: '#ef4444', moyenne: '#f59e0b', faible: '#10b981' }
const STATUT_R_ICONS = { ouvert: '○', en_cours: '◑', resolu: '●' }

const TEXT_EXTS = new Set([
  'txt','md','csv','json','log','ts','js','jsx','tsx','py','go','java','rs','cpp','c','h',
  'yaml','yml','xml','html','htm','css','sql','sh','env','toml','ini','cfg',
])

function canReadAsText(filename) {
  const ext = filename.split('.').pop()?.toLowerCase() || ''
  return TEXT_EXTS.has(ext)
}

const DEPLOY_STEPS = ['Génération fichiers', 'Connexion SSH', 'Upload', 'Docker compose', 'Seed DB', 'Terminé']
const STATUS_COLORS = { deploying: '#f59e0b', ready: '#10b981', error: '#ef4444' }

export default function AuditPanel({ poleId }) {
  const [missions, setMissions]     = useState([])
  const [selected, setSelected]     = useState(null)
  const [docs, setDocs]             = useState([])
  const [rapport, setRapport]       = useState(null)
  const [form, setForm]             = useState({ titre: '', description: '' })
  const [showForm, setShow]         = useState(false)
  const [loading, setLoading]       = useState(false)
  const [generating, setGenerating] = useState(false)
  const [genError, setGenError]     = useState('')
  const [dragging, setDragging]     = useState(false)
  const [uploadErr, setUploadErr]   = useState('')
  const [tab, setTab]               = useState('docs') // 'docs' | 'rapport'
  const fileRef = useRef(null)

  // ── Deploy state ──────────────────────────────────────────
  const [showDeploy, setShowDeploy]       = useState(false)
  const [deployForm, setDeployForm]       = useState({
    serverMode: 'custom', serverId: '', serverIp: '', sshKey: '', sshUser: 'root',
    domainMode: 'manual', domain: '',
    adminEmail: '', adminPassword: '',
  })
  const [servers, setServers]             = useState([])
  const [deploying, setDeploying]         = useState(false)
  const [deployStep, setDeployStep]       = useState(0)
  const [deployLog, setDeployLog]         = useState([])
  const [deployErr, setDeployErr]         = useState('')
  const [deployDone, setDeployDone]       = useState(null) // { instanceId, domain }
  const [deployments, setDeployments]     = useState([])

  useEffect(() => {
    req(`/api/poles/${poleId}/audit`).then(data => {
      setMissions(data)
      if (data.length > 0 && !selected) setSelected(data[0].id)
    }).catch(() => {})
  }, [poleId])

  useEffect(() => {
    if (!selected) { setDocs([]); setRapport(null); setDeployments([]); return }
    req(`/api/audit/${selected}/documents`).then(setDocs).catch(() => {})
    req(`/api/audit/${selected}/rapport`).then(setRapport).catch(() => {})
    req(`/api/audit/${selected}/deployments`).then(setDeployments).catch(() => {})
  }, [selected])

  useEffect(() => {
    req('/api/servers').then(setServers).catch(() => {})
  }, [])

  async function createMission(e) {
    e.preventDefault()
    setLoading(true)
    try {
      const m = await req(`/api/poles/${poleId}/audit`, { method: 'POST', body: JSON.stringify(form) })
      setMissions(prev => [m, ...prev])
      setSelected(m.id)
      setForm({ titre: '', description: '' })
      setShow(false)
    } finally { setLoading(false) }
  }

  async function updateStatut(id, statut) {
    const updated = await req(`/api/audit/${id}`, { method: 'PATCH', body: JSON.stringify({ statut }) })
    setMissions(prev => prev.map(m => m.id === id ? updated : m))
  }

  async function deleteMission(id) {
    await req(`/api/audit/${id}`, { method: 'DELETE' })
    setMissions(prev => prev.filter(m => m.id !== id))
    if (selected === id) setSelected(null)
  }

  async function removePole(missionId, pid) {
    await req(`/api/audit/${missionId}/poles/${pid}`, { method: 'DELETE' })
    setMissions(prev => prev.map(m =>
      m.id === missionId ? { ...m, poles: m.poles.filter(p => p.id !== pid) } : m
    ))
  }

  async function deleteDoc(id) {
    await req(`/api/audit/documents/${id}`, { method: 'DELETE' })
    setDocs(prev => prev.filter(d => d.id !== id))
  }

  async function uploadFiles(files) {
    setUploadErr('')
    for (const file of files) {
      if (!canReadAsText(file.name)) {
        setUploadErr(`"${file.name}" : format non pris en charge inline. Utilisez le workspace pour les PDF/Word.`)
        continue
      }
      try {
        const contenu = await file.text()
        const ext = file.name.split('.').pop()?.toLowerCase() || 'txt'
        const doc = await req(`/api/audit/${selected}/documents`, {
          method: 'POST',
          body: JSON.stringify({ nom: file.name, type: ext, contenu }),
        })
        setDocs(prev => [doc, ...prev])
      } catch (err) {
        setUploadErr(`Erreur upload "${file.name}" : ${err.message}`)
      }
    }
  }

  function onFileChange(e) {
    if (e.target.files?.length) uploadFiles(Array.from(e.target.files))
    e.target.value = ''
  }

  function onDrop(e) {
    e.preventDefault()
    setDragging(false)
    if (e.dataTransfer.files?.length) uploadFiles(Array.from(e.dataTransfer.files))
  }

  async function generateReport() {
    setGenerating(true)
    setGenError('')
    try {
      const data = await req(`/api/audit/${selected}/generate-report`, { method: 'POST' })
      setRapport(data)
      setTab('rapport')
    } catch (err) {
      setGenError(err.message)
    } finally { setGenerating(false) }
  }

  function copyMarkdown() {
    if (rapport?.rapport?.contenu) navigator.clipboard.writeText(rapport.rapport.contenu)
  }

  function openDeploy() {
    setDeployErr('')
    setDeployLog([])
    setDeployStep(0)
    setDeployDone(null)
    setDeploying(false)
    setShowDeploy(true)
  }

  // S124 — Lit le flux SSE de progression d'un déploiement (endpoint séparé,
  // reconnectable). Utilisé au lancement ET pour ré-attacher un déploiement
  // déjà en cours (modal rouvert). Le job tourne côté serveur indépendamment.
  async function consumeDeployStream(instanceId, onDone) {
    const t = token.get()
    const res = await fetch(`/api/audit/instances/${instanceId}/stream`, {
      headers: { ...(t ? { Authorization: `Bearer ${t}` } : {}) },
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.error || 'Suivi du déploiement impossible')
    }

    const reader = res.body.getReader()
    const dec    = new TextDecoder()
    let buf = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buf += dec.decode(value, { stream: true })
      const lines = buf.split('\n')
      buf = lines.pop()
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        const data = JSON.parse(line.slice(6))
        if (data.error) throw new Error(data.error)
        if (data.done) {
          setDeployDone({ instanceId: data.instanceId, domain: data.domain })
          onDone?.(data)
        } else if (data.msg) {
          setDeployStep(data.step)
          setDeployLog(prev => [...prev, data.msg])
        }
      }
    }
  }

  const markReady = (data) => setDeployments(prev => prev.map(d =>
    d.id === data.instanceId ? { ...d, status: 'ready', domain: data.domain } : d))

  async function startDeploy(e) {
    e.preventDefault()
    setDeploying(true)
    setDeployErr('')
    setDeployLog([])
    setDeployStep(0)
    setDeployDone(null)

    const t = token.get()
    const body = {
      serverMode:   deployForm.serverMode,
      serverId:     deployForm.serverMode === 'parc' ? deployForm.serverId : undefined,
      serverIp:     deployForm.serverMode === 'custom' ? deployForm.serverIp : undefined,
      sshKey:       deployForm.serverMode === 'custom' ? deployForm.sshKey : undefined,
      sshUser:      deployForm.sshUser,
      domainMode:   deployForm.domainMode,
      domain:       deployForm.domain,
      adminEmail:   deployForm.adminEmail,
      adminPassword: deployForm.adminPassword,
    }

    try {
      // Le POST lance le job de fond et répond immédiatement avec l'instanceId.
      // Le déploiement continue côté serveur même si on ferme l'onglet.
      const res = await fetch(`/api/audit/${selected}/deploy`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(t ? { Authorization: `Bearer ${t}` } : {}) },
        body: JSON.stringify(body),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.error || 'Erreur serveur')
      }
      const { instanceId } = await res.json()

      // Affiche l'instance « en cours » tout de suite.
      setDeployments(prev => [...prev, {
        id: instanceId, domain: body.domain || '', serverIp: body.serverIp || '',
        domainMode: deployForm.domainMode, status: 'deploying',
        adminEmail: deployForm.adminEmail, createdAt: new Date().toISOString(),
      }])

      await consumeDeployStream(instanceId, markReady)
    } catch (err) {
      setDeployErr(err.message)
    } finally {
      setDeploying(false)
    }
  }

  // Ré-attache le suivi d'un déploiement déjà en cours (clic depuis la liste).
  async function reattachDeploy(instanceId) {
    setShowDeploy(true)
    setDeploying(true)
    setDeployErr('')
    setDeployLog([])
    setDeployStep(0)
    setDeployDone(null)
    try {
      await consumeDeployStream(instanceId, markReady)
    } catch (err) {
      setDeployErr(err.message)
    } finally {
      setDeploying(false)
    }
  }

  const currentMission = missions.find(m => m.id === selected)

  return (
    <div className={styles.panel}>
      <div className={styles.toolbar}>
        <select className={styles.select} value={selected || ''} onChange={e => setSelected(e.target.value)}>
          {missions.length === 0 && <option value="">Aucune mission</option>}
          {missions.map(m => <option key={m.id} value={m.id}>{m.titre}</option>)}
        </select>
        <button className={styles.btnPrimary} onClick={() => setShow(true)}>+ Mission</button>
      </div>

      {showForm && (
        <form className={styles.form} onSubmit={createMission}>
          <input className={styles.input} placeholder="Titre de la mission *" required value={form.titre}
            onChange={e => setForm(f => ({ ...f, titre: e.target.value }))} />
          <textarea className={styles.textarea} placeholder="Description" value={form.description}
            onChange={e => setForm(f => ({ ...f, description: e.target.value }))} />
          <div className={styles.formActions}>
            <button type="submit" className={styles.btnPrimary} disabled={loading}>Créer</button>
            <button type="button" className={styles.btnGhost} onClick={() => setShow(false)}>Annuler</button>
          </div>
        </form>
      )}

      {currentMission && (
        <div className={styles.missionDetail}>
          <div className={styles.missionHeader}>
            <div>
              <h3 className={styles.missionTitle}>{currentMission.titre}</h3>
              {currentMission.description && <p className={styles.missionDesc}>{currentMission.description}</p>}
            </div>
            <div className={styles.missionActions}>
              <span className={styles.statutBadge}
                style={{ background: STATUT_COLORS[currentMission.statut] + '22', color: STATUT_COLORS[currentMission.statut] }}>
                {STATUT_LABELS[currentMission.statut]}
              </span>
              {currentMission.statut === 'brouillon' && (
                <button className={styles.btnSecondary} onClick={() => updateStatut(currentMission.id, 'actif')}>Activer</button>
              )}
              {currentMission.statut === 'actif' && (
                <button className={styles.btnSecondary} onClick={() => updateStatut(currentMission.id, 'termine')}>Terminer</button>
              )}
              <button className={styles.micro} style={{ color: '#ef4444' }} onClick={() => deleteMission(currentMission.id)}>✕</button>
            </div>
          </div>

          {currentMission.poles?.length > 0 && (
            <div className={styles.polesSection}>
              <h4 className={styles.docsTitle}>Pôles couverts ({currentMission.poles.length})</h4>
              <div className={styles.polesTags}>
                {currentMission.poles.map(p => (
                  <span key={p.id} className={styles.poleTag} style={{ borderColor: p.couleur }}>
                    {p.emoji} {p.nom}
                    <button className={styles.poleTagRemove} onClick={() => removePole(currentMission.id, p.id)} title="Retirer ce pôle">✕</button>
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Tabs */}
          <div className={styles.tabBar} style={{ display: 'flex', gap: 4, margin: '12px 0 8px' }}>
            <button
              className={tab === 'docs' ? styles.btnPrimary : styles.btnGhost}
              style={{ fontSize: 12, padding: '4px 10px' }}
              onClick={() => setTab('docs')}
            >
              Documents ({docs.length})
            </button>
            <button
              className={tab === 'rapport' ? styles.btnPrimary : styles.btnGhost}
              style={{ fontSize: 12, padding: '4px 10px' }}
              onClick={() => setTab('rapport')}
            >
              {rapport ? 'Rapport ✓' : 'Rapport'}
            </button>
          </div>

          {/* Tab: Documents */}
          {tab === 'docs' && (
            <div className={styles.docsSection}>
              {/* Drop zone */}
              <div
                onDragOver={e => { e.preventDefault(); setDragging(true) }}
                onDragLeave={() => setDragging(false)}
                onDrop={onDrop}
                onClick={() => fileRef.current?.click()}
                style={{
                  border: `2px dashed ${dragging ? '#6366f1' : '#374151'}`,
                  borderRadius: 8,
                  padding: '12px 16px',
                  textAlign: 'center',
                  cursor: 'pointer',
                  marginBottom: 10,
                  fontSize: 12,
                  color: dragging ? '#6366f1' : '#9ca3af',
                  transition: 'all 0.15s',
                }}
              >
                {dragging ? 'Déposez ici' : '📎 Glissez des fichiers texte ou cliquez pour sélectionner'}
                <input ref={fileRef} type="file" multiple style={{ display: 'none' }} onChange={onFileChange} />
              </div>
              {uploadErr && <p style={{ color: '#ef4444', fontSize: 12, margin: '4px 0 8px' }}>{uploadErr}</p>}
              <p style={{ fontSize: 11, color: '#6b7280', margin: '0 0 10px' }}>
                Formats supportés inline : .txt .md .csv .json .js .ts .py .yaml .html…<br />
                Pour les PDF/Word : uploadez via le workspace (Document Intelligence).
              </p>

              {docs.length === 0 && <p className={styles.empty}>Aucun document.</p>}
              {docs.map(doc => (
                <div key={doc.id} className={styles.docCard}>
                  <div className={styles.rowTitle}>📄 {doc.nom}</div>
                  {doc.analyse && <div className={styles.analyse}>{doc.analyse.slice(0, 200)}…</div>}
                  <button className={styles.micro} style={{ color: '#ef4444' }} onClick={() => deleteDoc(doc.id)}>✕</button>
                </div>
              ))}

              <div style={{ marginTop: 12 }}>
                <button
                  className={styles.btnPrimary}
                  disabled={docs.length === 0 || generating}
                  onClick={generateReport}
                  style={{ width: '100%' }}
                >
                  {generating ? '⏳ Génération en cours…' : '✨ Générer le rapport IA'}
                </button>
                {genError && <p style={{ color: '#ef4444', fontSize: 12, marginTop: 6 }}>{genError}</p>}
              </div>
            </div>
          )}

          {/* Tab: Rapport */}
          {tab === 'rapport' && (
            <div className={styles.docsSection}>
              {!rapport && (
                <div style={{ textAlign: 'center', padding: 24 }}>
                  <p className={styles.empty} style={{ marginBottom: 12 }}>
                    Aucun rapport généré. Ajoutez des documents et cliquez sur "Générer le rapport IA".
                  </p>
                  <button
                    className={styles.btnPrimary}
                    disabled={docs.length === 0 || generating}
                    onClick={generateReport}
                  >
                    {generating ? '⏳ Génération en cours…' : '✨ Générer le rapport IA'}
                  </button>
                  {genError && <p style={{ color: '#ef4444', fontSize: 12, marginTop: 6 }}>{genError}</p>}
                </div>
              )}

              {rapport && (
                <>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                    <span style={{ fontSize: 11, color: '#6b7280' }}>
                      Généré le {new Date(rapport.rapport.createdAt).toLocaleString('fr-FR')}
                    </span>
                    <div style={{ display: 'flex', gap: 6 }}>
                      <button className={styles.btnGhost} style={{ fontSize: 11 }} onClick={copyMarkdown}>
                        📋 Copier MD
                      </button>
                      <button
                        className={styles.btnSecondary}
                        style={{ fontSize: 11 }}
                        disabled={docs.length === 0 || generating}
                        onClick={generateReport}
                      >
                        {generating ? '⏳…' : '↺ Regénérer'}
                      </button>
                      <button
                        className={styles.btnPrimary}
                        style={{ fontSize: 11 }}
                        onClick={openDeploy}
                      >
                        🚀 Déployer chez le client
                      </button>
                    </div>
                  </div>

                  {/* Résumé exécutif */}
                  <section style={{ marginBottom: 18 }}>
                    <h4 style={{ fontSize: 13, fontWeight: 600, marginBottom: 6, color: '#e5e7eb' }}>📋 Résumé exécutif</h4>
                    <div style={{ fontSize: 12, lineHeight: 1.6, color: '#d1d5db', whiteSpace: 'pre-wrap', background: '#1f2937', padding: '10px 12px', borderRadius: 6 }}>
                      {rapport.rapport.contenu.match(/## 📋 Résumé exécutif\n\n([\s\S]*?)\n\n##/)?.[1] || ''}
                    </div>
                  </section>

                  {/* Findings */}
                  {rapport.findings?.length > 0 && (
                    <section style={{ marginBottom: 18 }}>
                      <h4 style={{ fontSize: 13, fontWeight: 600, marginBottom: 8, color: '#e5e7eb' }}>
                        🔍 Constats ({rapport.findings.length})
                      </h4>
                      {Object.entries(
                        rapport.findings.reduce((acc, f) => {
                          if (!acc[f.categorie]) acc[f.categorie] = []
                          acc[f.categorie].push(f)
                          return acc
                        }, {})
                      ).map(([cat, items]) => (
                        <div key={cat} style={{ marginBottom: 10 }}>
                          <div style={{ fontSize: 11, fontWeight: 600, color: '#9ca3af', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.05em' }}>{cat}</div>
                          {items.map(f => (
                            <div key={f.id} style={{
                              display: 'flex', gap: 8, alignItems: 'flex-start',
                              padding: '6px 10px', borderRadius: 6, marginBottom: 4,
                              background: SEV_COLORS[f.severite] + '11',
                              borderLeft: `3px solid ${SEV_COLORS[f.severite]}`,
                            }}>
                              <span style={{
                                fontSize: 10, fontWeight: 700, padding: '2px 6px', borderRadius: 4,
                                background: SEV_COLORS[f.severite] + '33', color: SEV_COLORS[f.severite],
                                whiteSpace: 'nowrap', marginTop: 1,
                              }}>{f.severite.toUpperCase()}</span>
                              <div>
                                <div style={{ fontSize: 12, color: '#e5e7eb' }}>{f.description}</div>
                                {f.source && <div style={{ fontSize: 11, color: '#6b7280', marginTop: 2 }}>Source : {f.source}</div>}
                              </div>
                            </div>
                          ))}
                        </div>
                      ))}
                    </section>
                  )}

                  {/* Recommandations */}
                  {rapport.recommandations?.length > 0 && (
                    <section>
                      <h4 style={{ fontSize: 13, fontWeight: 600, marginBottom: 8, color: '#e5e7eb' }}>
                        ✅ Recommandations ({rapport.recommandations.length})
                      </h4>
                      {rapport.recommandations.map((r, i) => (
                        <div key={r.id} style={{
                          display: 'flex', gap: 8, alignItems: 'flex-start',
                          padding: '6px 10px', borderRadius: 6, marginBottom: 4,
                          background: '#1f2937',
                          borderLeft: `3px solid ${PRIO_COLORS[r.priorite]}`,
                        }}>
                          <span style={{
                            fontSize: 10, fontWeight: 700, padding: '2px 6px', borderRadius: 4,
                            background: PRIO_COLORS[r.priorite] + '33', color: PRIO_COLORS[r.priorite],
                            whiteSpace: 'nowrap', marginTop: 1,
                          }}>{r.priorite.toUpperCase()}</span>
                          <div style={{ flex: 1 }}>
                            <div style={{ fontSize: 12, color: '#e5e7eb' }}>{r.action}</div>
                          </div>
                          <span style={{ fontSize: 12, color: '#6b7280' }} title={r.statut}>{STATUT_R_ICONS[r.statut]}</span>
                        </div>
                      ))}
                    </section>
                  )}
                </>
              )}
            </div>
          )}
        </div>
      )}

      {missions.length === 0 && !showForm && (
        <p className={styles.empty}>Crée une mission d'audit pour commencer.</p>
      )}

      {/* ── Instances déployées ──────────────────────────────── */}
      {deployments.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <h4 style={{ fontSize: 12, fontWeight: 600, color: '#9ca3af', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            Instances déployées ({deployments.length})
          </h4>
          {deployments.map(d => (
            <div key={d.id} style={{
              background: '#1f2937', borderRadius: 6, padding: '8px 12px', marginBottom: 6,
              borderLeft: `3px solid ${STATUS_COLORS[d.status] || '#6b7280'}`,
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            }}>
              <div>
                <div style={{ fontSize: 12, color: '#e5e7eb', fontWeight: 500 }}>
                  {d.domain || d.serverIp}
                </div>
                <div style={{ fontSize: 11, color: '#6b7280', marginTop: 2 }}>
                  {d.adminEmail} · {new Date(d.createdAt).toLocaleDateString('fr-FR')}
                </div>
              </div>
              <span style={{
                fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 4,
                background: (STATUS_COLORS[d.status] || '#6b7280') + '22',
                color: STATUS_COLORS[d.status] || '#6b7280',
              }}>
                {d.status === 'deploying' ? 'en cours' : d.status === 'ready' ? 'actif' : 'erreur'}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* ── Modal déploiement ────────────────────────────────── */}
      {showDeploy && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 999,
        }}>
          <div style={{
            background: '#111827', borderRadius: 10, padding: 24, width: '100%', maxWidth: 520,
            border: '1px solid #374151', maxHeight: '90vh', overflowY: 'auto',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
              <h3 style={{ fontSize: 15, fontWeight: 700, color: '#e5e7eb', margin: 0 }}>🚀 Déployer chez le client</h3>
              <button className={styles.micro} onClick={() => !deploying && setShowDeploy(false)} style={{ color: '#9ca3af' }}>✕</button>
            </div>

            {/* Progression */}
            {deploying && (
              <div style={{ marginBottom: 16 }}>
                <div style={{ display: 'flex', gap: 4, marginBottom: 10 }}>
                  {DEPLOY_STEPS.map((s, i) => (
                    <div key={s} style={{
                      flex: 1, height: 4, borderRadius: 2,
                      background: i < deployStep ? '#6366f1' : i === deployStep - 1 ? '#818cf8' : '#374151',
                      transition: 'background 0.3s',
                    }} />
                  ))}
                </div>
                <div style={{ fontSize: 12, color: '#a5b4fc', marginBottom: 8 }}>
                  {DEPLOY_STEPS[deployStep - 1] || 'Préparation…'}
                </div>
                <div style={{
                  background: '#0f172a', borderRadius: 6, padding: '8px 10px',
                  fontFamily: 'monospace', fontSize: 11, color: '#6b7280',
                  maxHeight: 120, overflowY: 'auto',
                }}>
                  {deployLog.map((l, i) => <div key={i}>{l}</div>)}
                </div>
              </div>
            )}

            {/* Succès */}
            {deployDone && (
              <div style={{ background: '#064e3b', borderRadius: 6, padding: '10px 14px', marginBottom: 16 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: '#10b981', marginBottom: 4 }}>✅ Déploiement réussi !</div>
                {deployDone.domain && (
                  <div style={{ fontSize: 12, color: '#6ee7b7' }}>
                    Accès : <strong>https://{deployDone.domain}</strong>
                  </div>
                )}
                <div style={{ fontSize: 11, color: '#6b7280', marginTop: 4 }}>
                  Le client peut se connecter avec les identifiants fournis.
                </div>
              </div>
            )}

            {deployErr && <p style={{ color: '#ef4444', fontSize: 12, marginBottom: 12 }}>{deployErr}</p>}

            {!deploying && !deployDone && (
              <form onSubmit={startDeploy}>
                {/* Mode serveur */}
                <div style={{ marginBottom: 14 }}>
                  <div style={{ fontSize: 12, color: '#9ca3af', marginBottom: 6 }}>Serveur cible</div>
                  <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
                    {['parc', 'custom'].map(m => (
                      <button key={m} type="button"
                        className={deployForm.serverMode === m ? styles.btnPrimary : styles.btnGhost}
                        style={{ fontSize: 11, flex: 1 }}
                        onClick={() => setDeployForm(f => ({ ...f, serverMode: m }))}
                      >
                        {m === 'parc' ? '🖥️ Mon parc' : '🔌 Serveur client'}
                      </button>
                    ))}
                  </div>

                  {deployForm.serverMode === 'parc' ? (
                    <select className={styles.select} value={deployForm.serverId}
                      onChange={e => setDeployForm(f => ({ ...f, serverId: e.target.value }))} required>
                      <option value="">-- Choisir un serveur --</option>
                      {servers.filter(s => s.status === 'libre').map(s => (
                        <option key={s.id} value={s.id}>{s.label} — {s.ip} {s.region ? `(${s.region})` : ''}</option>
                      ))}
                    </select>
                  ) : (
                    <>
                      <input className={styles.input} placeholder="IP du serveur (ex: 1.2.3.4)" required
                        value={deployForm.serverIp} onChange={e => setDeployForm(f => ({ ...f, serverIp: e.target.value }))} />
                      <input className={styles.input} placeholder="Utilisateur SSH (défaut: root)"
                        value={deployForm.sshUser} onChange={e => setDeployForm(f => ({ ...f, sshUser: e.target.value }))}
                        style={{ marginTop: 6 }} />
                      <textarea className={styles.textarea} placeholder="Clé SSH privée (-----BEGIN...)" required
                        value={deployForm.sshKey} onChange={e => setDeployForm(f => ({ ...f, sshKey: e.target.value }))}
                        style={{ marginTop: 6, fontFamily: 'monospace', fontSize: 11, minHeight: 80 }} />
                    </>
                  )}
                </div>

                {/* Mode domaine */}
                <div style={{ marginBottom: 14 }}>
                  <div style={{ fontSize: 12, color: '#9ca3af', marginBottom: 6 }}>Domaine</div>
                  <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
                    {['manual', 'cloudflare'].map(m => (
                      <button key={m} type="button"
                        className={deployForm.domainMode === m ? styles.btnPrimary : styles.btnGhost}
                        style={{ fontSize: 11, flex: 1 }}
                        onClick={() => setDeployForm(f => ({ ...f, domainMode: m }))}
                      >
                        {m === 'manual' ? '✋ Manuel' : '☁️ Cloudflare auto'}
                      </button>
                    ))}
                  </div>
                  <input className={styles.input}
                    placeholder={deployForm.domainMode === 'cloudflare' ? 'Sous-domaine (ex: client-xyz)' : 'Domaine (optionnel, ex: client.mondomaine.com)'}
                    value={deployForm.domain}
                    onChange={e => setDeployForm(f => ({ ...f, domain: e.target.value }))}
                    required={deployForm.domainMode === 'cloudflare'}
                  />
                  {deployForm.domainMode === 'manual' && (
                    <p style={{ fontSize: 11, color: '#6b7280', margin: '4px 0 0' }}>
                      Après déploiement, pointez votre DNS vers l'IP du serveur.
                    </p>
                  )}
                </div>

                {/* Compte admin client */}
                <div style={{ marginBottom: 16 }}>
                  <div style={{ fontSize: 12, color: '#9ca3af', marginBottom: 6 }}>Compte admin client</div>
                  <input className={styles.input} type="email" placeholder="Email admin client *" required
                    value={deployForm.adminEmail} onChange={e => setDeployForm(f => ({ ...f, adminEmail: e.target.value }))} />
                  <input className={styles.input} type="password" placeholder="Mot de passe initial (min. 8 car.) *" required minLength={8}
                    value={deployForm.adminPassword} onChange={e => setDeployForm(f => ({ ...f, adminPassword: e.target.value }))}
                    style={{ marginTop: 6 }} />
                </div>

                <div className={styles.formActions}>
                  <button type="submit" className={styles.btnPrimary}>🚀 Lancer le déploiement</button>
                  <button type="button" className={styles.btnGhost} onClick={() => setShowDeploy(false)}>Annuler</button>
                </div>
              </form>
            )}

            {(deploying || deployDone) && (
              <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 12 }}>
                <button className={styles.btnGhost} disabled={deploying} onClick={() => setShowDeploy(false)}>
                  {deploying ? 'Déploiement en cours…' : 'Fermer'}
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

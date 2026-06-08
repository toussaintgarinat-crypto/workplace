import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, venturesApi } from '../../services/api'
import styles from './Venture.module.css'

export default function VentureView() {
  const navigate = useNavigate()
  const [ventures, setVentures] = useState([])
  const [showForm, setShowForm] = useState(false)
  const [form, setForm]         = useState({ nom: '', description: '', emoji: '🚀', couleur: '#6366f1', type: 'own' })
  const [saving, setSaving]     = useState(false)

  // État suppression
  const [deleteTarget, setDeleteTarget] = useState(null) // { id, nom, email }
  const [deleteStep, setDeleteStep]     = useState(null) // 'confirm1' | 'confirm2'
  const [deleteCode, setDeleteCode]     = useState('')
  const [deleteError, setDeleteError]   = useState('')
  const [deletingReq, setDeletingReq]   = useState(false)

  useEffect(() => {
    api.get('/api/ventures').then(r => setVentures(Array.isArray(r) ? r : [])).catch(() => {})
  }, [])

  async function submit(e) {
    e.preventDefault()
    setSaving(true)
    try {
      const v = await api.post('/api/ventures', form)
      setVentures(vs => [v, ...vs])
      setForm({ nom: '', description: '', emoji: '🚀', couleur: '#6366f1', type: 'own' })
      setShowForm(false)
    } finally { setSaving(false) }
  }

  async function archive(id) {
    await api.patch(`/api/ventures/${id}`, { statut: 'archive' })
    setVentures(vs => vs.map(v => v.id === id ? { ...v, statut: 'archive' } : v))
  }

  // Étape 1 — première confirmation
  function startDelete(venture, e) {
    e.stopPropagation()
    setDeleteTarget(venture)
    setDeleteStep('confirm1')
    setDeleteCode('')
    setDeleteError('')
  }

  // Étape 2 — envoyer l'email
  async function sendDeleteEmail() {
    setDeletingReq(true)
    setDeleteError('')
    try {
      const res = await venturesApi.deleteRequest(deleteTarget.id)
      setDeleteTarget(t => ({ ...t, email: res.email }))
      setDeleteStep('confirm2')
    } catch (err) {
      setDeleteError(err?.data?.error || 'Erreur lors de l\'envoi de l\'email.')
    } finally {
      setDeletingReq(false)
    }
  }

  // Étape 3 — confirmer avec le code
  async function confirmDelete() {
    if (deleteCode.length !== 6) return
    setDeletingReq(true)
    setDeleteError('')
    try {
      await venturesApi.delete(deleteTarget.id, deleteCode)
      setVentures(vs => vs.filter(v => v.id !== deleteTarget.id))
      closeDeleteModal()
    } catch (err) {
      setDeleteError(err?.data?.error || 'Code invalide ou expiré.')
    } finally {
      setDeletingReq(false)
    }
  }

  function closeDeleteModal() {
    setDeleteTarget(null)
    setDeleteStep(null)
    setDeleteCode('')
    setDeleteError('')
  }

  const actives   = ventures.filter(v => v.statut !== 'archive')
  const archivees = ventures.filter(v => v.statut === 'archive')

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <h1 className={styles.title}>🚀 Ventures</h1>
        <button className={styles.btnPrimary} onClick={() => setShowForm(v => !v)}>+ Nouvelle venture</button>
      </div>

      {showForm && (
        <form className={styles.form} onSubmit={submit}>
          <div className={styles.formRow}>
            <input className={styles.inputEmoji} value={form.emoji}
              onChange={e => setForm(f => ({ ...f, emoji: e.target.value }))} />
            <input className={styles.input} placeholder="Nom de la venture *" required value={form.nom}
              onChange={e => setForm(f => ({ ...f, nom: e.target.value }))} style={{ flex: 1 }} />
            <select className={styles.select} value={form.type} onChange={e => setForm(f => ({ ...f, type: e.target.value }))}>
              <option value="own">🏠 Own Venture</option>
              <option value="audit">🔍 Mission Audit</option>
            </select>
          </div>
          <input className={styles.input} placeholder="Description (optionnel)" value={form.description}
            onChange={e => setForm(f => ({ ...f, description: e.target.value }))} />
          <div className={styles.formActions}>
            <button type="submit" className={styles.btnPrimary} disabled={saving}>{saving ? '...' : 'Créer'}</button>
            <button type="button" className={styles.btnGhost} onClick={() => setShowForm(false)}>Annuler</button>
          </div>
        </form>
      )}

      <div className={styles.grid}>
        {actives.map(v => (
          <div key={v.id} className={styles.ventureCard} style={{ borderLeftColor: v.couleur }}
            onClick={() => navigate(`/ventures/${v.id}`)}>
            <div className={styles.ventureIcon}>{v.emoji}</div>
            <div className={styles.ventureInfo}>
              <div className={styles.ventureName}>{v.nom}</div>
              {v.description && <div className={styles.ventureDesc}>{v.description}</div>}
              <div className={styles.ventureMeta}>
                <span className={styles.typeChip} style={{ background: v.type === 'audit' ? '#f59e0b22' : '#818cf822', color: v.type === 'audit' ? '#f59e0b' : '#818cf8' }}>
                  {v.type === 'audit' ? '🔍 Audit' : '🏠 Own'}
                </span>
                <span className={styles.statut}>{v.statut}</span>
              </div>
            </div>
            <div className={styles.ventureActions} onClick={e => e.stopPropagation()}>
              <button className={styles.archiveBtn} onClick={e => { e.stopPropagation(); archive(v.id) }} title="Archiver">📦</button>
              <button className={styles.deleteBtn}  onClick={e => startDelete(v, e)} title="Supprimer">🗑️</button>
            </div>
          </div>
        ))}
      </div>

      {archivees.length > 0 && (
        <details className={styles.archivesSection}>
          <summary className={styles.archivesSummary}>📦 Archives ({archivees.length})</summary>
          <div className={styles.grid} style={{ marginTop: 12 }}>
            {archivees.map(v => (
              <div key={v.id} className={`${styles.ventureCard} ${styles.archived}`}>
                <div className={styles.ventureIcon}>{v.emoji}</div>
                <div className={styles.ventureInfo}>
                  <div className={styles.ventureName}>{v.nom}</div>
                </div>
                <div className={styles.ventureActions} onClick={e => e.stopPropagation()}>
                  <button className={styles.deleteBtn} onClick={e => startDelete(v, e)} title="Supprimer définitivement">🗑️</button>
                </div>
              </div>
            ))}
          </div>
        </details>
      )}

      {ventures.length === 0 && !showForm && (
        <div className={styles.empty}>
          <p>Aucune venture créée.</p>
          <p className={styles.hint}>Les ventures vous permettent de gérer plusieurs projets ou missions d'audit séparément.</p>
        </div>
      )}

      {/* Modal de suppression */}
      {deleteStep && deleteTarget && (
        <div className={styles.modalOverlay} onClick={closeDeleteModal}>
          <div className={styles.modal} onClick={e => e.stopPropagation()}>
            {deleteStep === 'confirm1' && (
              <>
                <div className={styles.modalIcon}>⚠️</div>
                <h3 className={styles.modalTitle}>Supprimer la venture ?</h3>
                <p className={styles.modalText}>
                  Vous êtes sur le point de supprimer <strong>{deleteTarget.nom}</strong>.<br/>
                  Cette action est <strong>irréversible</strong> et supprimera tous les pôles, conversations et données associés.
                </p>
                {deleteError && <p className={styles.modalError}>{deleteError}</p>}
                <div className={styles.modalActions}>
                  <button className={styles.btnDanger} onClick={sendDeleteEmail} disabled={deletingReq}>
                    {deletingReq ? 'Envoi...' : 'Envoyer le code par email'}
                  </button>
                  <button className={styles.btnGhost} onClick={closeDeleteModal}>Annuler</button>
                </div>
              </>
            )}

            {deleteStep === 'confirm2' && (
              <>
                <div className={styles.modalIcon}>📧</div>
                <h3 className={styles.modalTitle}>Confirmer la suppression</h3>
                <p className={styles.modalText}>
                  Un code à 6 chiffres a été envoyé à <strong>{deleteTarget.email}</strong>.<br/>
                  Saisissez-le ci-dessous pour confirmer la suppression de <strong>{deleteTarget.nom}</strong>.
                </p>
                <input
                  className={styles.codeInput}
                  type="text"
                  inputMode="numeric"
                  maxLength={6}
                  placeholder="000000"
                  value={deleteCode}
                  onChange={e => setDeleteCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                  autoFocus
                />
                {deleteError && <p className={styles.modalError}>{deleteError}</p>}
                <div className={styles.modalActions}>
                  <button className={styles.btnDanger} onClick={confirmDelete}
                    disabled={deletingReq || deleteCode.length !== 6}>
                    {deletingReq ? 'Suppression...' : 'Supprimer définitivement'}
                  </button>
                  <button className={styles.btnGhost} onClick={closeDeleteModal}>Annuler</button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

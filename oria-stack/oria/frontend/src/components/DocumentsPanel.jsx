import { useState, useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { api, authHeaders } from '../services/api.js'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

const ICONES_MIME = {
  'application/pdf':  '📄',
  'image/':           '🖼️',
  'video/':           '🎬',
  'audio/':           '🎵',
  'text/':            '📝',
  'application/zip':  '📦',
  'application/x-zip': '📦',
}

function icone(mime) {
  for (const [prefix, ic] of Object.entries(ICONES_MIME)) {
    if (mime?.startsWith(prefix)) return ic
  }
  return '📎'
}

function taille(bytes, t) {
  if (bytes < 1024) return `${bytes} ${t('documents.unitB')}`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} ${t('documents.unitKB')}`
  return `${(bytes / (1024 * 1024)).toFixed(1)} ${t('documents.unitMB')}`
}

/**
 * Panel de gestion de documents pour un scope (world | building).
 * @param {string} scope   — 'world' | 'building'
 * @param {string} scopeId — ID du monde ou du bâtiment
 * @param {string} scopeNom
 * @param {object} moi     — utilisateur connecté
 * @param {function} onFermer
 */
export default function DocumentsPanel({ scope, scopeId, scopeNom, moi, onFermer }) {
  const { t } = useTranslation()
  const [fichiers, setFichiers] = useState([])
  const [chargement, setChargement] = useState(false)
  const fileRef = useRef(null)

  useEffect(() => { charger() }, [scopeId])

  async function charger() {
    const data = await api.get(`/files/${scope}/${scopeId}`)
    if (Array.isArray(data)) setFichiers(data)
  }

  async function uploader(e) {
    const file = e.target.files[0]
    if (!file) return
    setChargement(true)
    const form = new FormData()
    form.append('file', file)
    const res = await fetch(`${API_URL}/api/files/upload/${scope}/${scopeId}`, {
      method: 'POST',
      credentials: 'include',
      headers: authHeaders(),
      body: form,
    })
    setChargement(false)
    if (res.ok) charger()
    e.target.value = ''
  }

  async function supprimer(id) {
    await api.del(`/files/${id}`)
    setFichiers(prev => prev.filter(f => f.id !== id))
  }

  const label = scope === 'world' ? '🌍' : '🏠'

  return (
    <div className="documents-panel">
      <div className="documents-panel-header">
        <span className="documents-panel-titre">{label} {scopeNom}{t('documents.titleSuffix')}</span>
        <button className="btn-quitter-room" onClick={onFermer}>✕</button>
      </div>

      <div className="documents-panel-toolbar">
        <button
          className="btn-upload-doc"
          onClick={() => fileRef.current?.click()}
          disabled={chargement}
          title={t('documents.addTitle')}
        >
          {chargement ? '⏳' : '＋'} {t('documents.add')}
        </button>
        <input ref={fileRef} type="file" style={{ display: 'none' }} onChange={uploader} />
      </div>

      <div className="documents-liste">
        {fichiers.length === 0 && (
          <div className="documents-vide">
            <span>📂</span>
            <p>{t('documents.empty')}</p>
            <p className="documents-vide-hint">{scope === 'world' ? t('documents.emptyHintWorld') : t('documents.emptyHintBuilding')}</p>
          </div>
        )}
        {fichiers.map(f => (
          <div key={f.id} className="document-item">
            <span className="document-icone">{icone(f.type_mime)}</span>
            <div className="document-info">
              <a
                href={`${API_URL}/api/files/download/${f.id}`}
                target="_blank"
                rel="noreferrer"
                className="document-nom"
                title={f.nom}
              >
                {f.nom}
              </a>
              <span className="document-meta">
                {taille(f.taille, t)} · {f.uploader_nom} · {f.created_at?.slice(0, 10)}
              </span>
            </div>
            {f.uploaded_by === moi.id && (
              <button
                className="btn-suppr-doc"
                onClick={() => supprimer(f.id)}
                title={t('common.delete')}
              >✕</button>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

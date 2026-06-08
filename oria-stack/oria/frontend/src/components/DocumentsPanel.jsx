import { useState, useEffect, useRef } from 'react'
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

function taille(bytes) {
  if (bytes < 1024) return `${bytes} o`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} Ko`
  return `${(bytes / (1024 * 1024)).toFixed(1)} Mo`
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
        <span className="documents-panel-titre">{label} {scopeNom} — Documents</span>
        <button className="btn-quitter-room" onClick={onFermer}>✕</button>
      </div>

      <div className="documents-panel-toolbar">
        <button
          className="btn-upload-doc"
          onClick={() => fileRef.current?.click()}
          disabled={chargement}
          title="Ajouter un document"
        >
          {chargement ? '⏳' : '＋'} Ajouter
        </button>
        <input ref={fileRef} type="file" style={{ display: 'none' }} onChange={uploader} />
      </div>

      <div className="documents-liste">
        {fichiers.length === 0 && (
          <div className="documents-vide">
            <span>📂</span>
            <p>Aucun document</p>
            <p className="documents-vide-hint">Ajoute des fichiers partagés pour ce {scope === 'world' ? 'commune' : 'service'}</p>
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
                {taille(f.taille)} · {f.uploader_nom} · {f.created_at?.slice(0, 10)}
              </span>
            </div>
            {f.uploaded_by === moi.id && (
              <button
                className="btn-suppr-doc"
                onClick={() => supprimer(f.id)}
                title="Supprimer"
              >✕</button>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

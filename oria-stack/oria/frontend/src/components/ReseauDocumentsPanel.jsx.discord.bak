import { useState, useEffect } from 'react'
import { api } from '../services/api.js'

const MIME_ICON = (mime = '') => {
  if (mime.includes('pdf'))   return '📄'
  if (mime.includes('image')) return '🖼️'
  if (mime.includes('audio')) return '🎵'
  if (mime.includes('word') || mime.includes('document')) return '📝'
  return '📎'
}

export default function ReseauDocumentsPanel({ world, moi, onFermer }) {
  const [data,        setData]        = useState(null)
  const [mesDocs,     setMesDocs]     = useState([])
  const [onglet,      setOnglet]      = useState('deliberations')
  const [chargement,  setChargement]  = useState(true)
  const [toggling,    setToggling]    = useState(null) // doc_id en cours de toggle

  useEffect(() => {
    if (world?.id) {
      charger()
      chargerMesDocs()
    }
  }, [world?.id])

  async function charger() {
    setChargement(true)
    const d = await api.get(`/reseau/documents?world_id=${world.id}`)
    setChargement(false)
    if (d) setData(d)
  }

  async function chargerMesDocs() {
    const d = await api.get(`/reseau/documents/mes-docs?world_id=${world.id}`)
    if (d) setMesDocs(d)
  }

  async function togglePartage(doc) {
    setToggling(doc.id)
    const res = await api.post('/reseau/documents/partager', {
      doc_id:  doc.id,
      partage: !doc.partage_reseau,
    })
    setToggling(null)
    if (res) {
      setMesDocs(prev =>
        prev.map(d => d.id === doc.id ? { ...d, partage_reseau: res.partage_reseau } : d)
      )
      charger()
    }
  }

  const ONGLETS = [
    { key: 'deliberations', label: '📜 Délibérations', items: data?.deliberations || [] },
    { key: 'arretes',       label: '📑 Arrêtés',       items: data?.arretes       || [] },
    { key: 'autres',        label: '📁 Autres',         items: data?.autres        || [] },
    { key: 'mes-docs',      label: '🔗 Mes partages',  items: mesDocs              },
  ]

  const ongletActif = ONGLETS.find(o => o.key === onglet)

  return (
    <div className="mairie-panel">
      <div className="mairie-panel-header">
        <div className="mairie-panel-title"><span>🏘</span><h2>Documents intercommunaux</h2></div>
        <div className="mairie-panel-actions">
          <button className="mairie-btn-close" onClick={onFermer}>✕</button>
        </div>
      </div>

      {/* Communes liées */}
      {data && data.communes.length > 0 && (
        <div style={{ padding: '8px 16px 0', display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
          <span style={{ fontSize: 11, color: '#72767d' }}>Communes :</span>
          {data.communes.map(c => (
            <span key={c.id} style={{
              fontSize: 12, background: '#2b2d31', borderRadius: 12,
              padding: '2px 10px', color: '#dcddde',
            }}>
              {c.emoji} {c.nom}
            </span>
          ))}
        </div>
      )}

      {/* État vide — aucun world lié */}
      {data && data.communes.length === 0 && onglet !== 'mes-docs' && (
        <div className="mairie-empty" style={{ padding: 40 }}>
          <p>Aucune commune liée au réseau intercommunal.</p>
          <p style={{ fontSize: 12, color: '#72767d', marginTop: 8 }}>
            Connectez des communes via la vue Intercommunalité.
          </p>
        </div>
      )}

      {/* Onglets */}
      <div className="mairie-filters" style={{ marginTop: 10 }}>
        {ONGLETS.map(o => (
          <button
            key={o.key}
            className={`mairie-filter-btn ${onglet === o.key ? 'actif' : ''}`}
            onClick={() => setOnglet(o.key)}
          >
            {o.label}
            {o.key !== 'mes-docs' && ` (${o.items.length})`}
            {o.key === 'mes-docs' && (
              <span style={{
                marginLeft: 4, fontSize: 10,
                color: mesDocs.filter(d => d.partage_reseau).length > 0 ? '#43B581' : '#72767d',
              }}>
                {mesDocs.filter(d => d.partage_reseau).length}/{mesDocs.length}
              </span>
            )}
          </button>
        ))}
      </div>

      <div className="mairie-list">
        {chargement && onglet !== 'mes-docs' && (
          <div className="mairie-empty">Chargement…</div>
        )}

        {/* Docs reçus du réseau */}
        {onglet !== 'mes-docs' && !chargement && ongletActif.items.length === 0 && (
          <div className="mairie-empty">
            Aucun document partagé dans cette catégorie.<br />
            <span style={{ fontSize: 12, color: '#72767d' }}>
              Les communes partenaires peuvent partager leurs documents depuis leurs panneaux respectifs.
            </span>
          </div>
        )}

        {onglet !== 'mes-docs' && ongletActif.items.map(doc => (
          <div key={doc.id} className="mairie-card">
            <div className="mairie-card-header">
              <span style={{ fontWeight: 600, fontSize: 13 }}>
                {doc.commune?.emoji} {doc.commune?.nom}
              </span>
              <span style={{ fontSize: 11, color: '#72767d' }}>
                {MIME_ICON(doc.type_mime)} {doc.type_mime?.split('/')[1]?.toUpperCase() || 'FICHIER'}
              </span>
            </div>
            <div className="mairie-card-titre">{doc.nom}</div>
            <div className="mairie-card-meta">
              <span>📅 {new Date(doc.created_at).toLocaleDateString('fr-FR')}</span>
              <span style={{ color: '#72767d', fontSize: 11 }}>{doc.nom_original}</span>
            </div>
          </div>
        ))}

        {/* Mes docs — gestion partage */}
        {onglet === 'mes-docs' && mesDocs.length === 0 && (
          <div className="mairie-empty">
            Aucun document dans ce world.<br />
            <span style={{ fontSize: 12, color: '#72767d' }}>
              Uploadez des documents via le panneau Documents pour les partager.
            </span>
          </div>
        )}

        {onglet === 'mes-docs' && mesDocs.map(doc => (
          <div key={doc.id} className="mairie-card" style={{
            display: 'flex', alignItems: 'center', gap: 10,
          }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="mairie-card-titre" style={{ marginBottom: 2 }}>
                {MIME_ICON(doc.type_mime)} {doc.nom}
              </div>
              <div className="mairie-card-meta">
                <span>📅 {new Date(doc.created_at).toLocaleDateString('fr-FR')}</span>
              </div>
            </div>
            <button
              onClick={() => togglePartage(doc)}
              disabled={toggling === doc.id}
              style={{
                flexShrink: 0,
                padding: '5px 12px',
                borderRadius: 6,
                border: 'none',
                cursor: toggling === doc.id ? 'wait' : 'pointer',
                fontSize: 12,
                fontWeight: 600,
                background: doc.partage_reseau ? '#43B581' : '#2b2d31',
                color:      doc.partage_reseau ? '#fff'    : '#72767d',
                transition: 'background 0.15s',
              }}
            >
              {toggling === doc.id ? '…' : doc.partage_reseau ? '✓ Partagé' : 'Partager'}
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}

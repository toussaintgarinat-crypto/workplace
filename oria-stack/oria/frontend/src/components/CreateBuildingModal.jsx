import { useState } from 'react'
import { api } from '../services/api.js'

const TYPES = [
  { id: 'maison',   emoji: '🏛', label: 'Mairie centrale',   desc: 'Siège principal, accueil, administration générale' },
  { id: 'site',     emoji: '🏢', label: 'Direction',          desc: 'Service thématique : Finances, RH, Urbanisme...' },
  { id: 'immeuble', emoji: '🏘', label: 'Antenne',            desc: 'Antenne de quartier ou service déconcentré' },
]

export default function CreateBuildingModal({ worldId, quartierId, onCree, onFermer }) {
  const [type, setType]   = useState('maison')
  const [nom, setNom]     = useState('')
  const [desc, setDesc]   = useState('')
  const [loading, setLoading] = useState(false)

  async function creer(e) {
    e.preventDefault()
    if (!nom.trim()) return
    setLoading(true)
    await api.post('/buildings/', { world_id: worldId, nom, type, description: desc, quartier_id: quartierId || '' })
    setLoading(false)
    onCree()
  }

  const placeholder = type === 'maison' ? 'Mairie principale' : type === 'site' ? 'Direction des finances' : 'Antenne nord'

  return (
    <div className="modal-overlay" onClick={onFermer}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <h2 className="modal-titre">Ajouter un service municipal</h2>
        <label>Type de service</label>
        <div className="type-picker">
          {TYPES.map(t => (
            <button key={t.id} type="button"
              className={`type-btn ${type === t.id ? 'actif' : ''}`}
              onClick={() => setType(t.id)}
            >
              <span className="type-emoji">{t.emoji}</span>
              <span className="type-label">{t.label}</span>
              <span className="type-desc">{t.desc}</span>
            </button>
          ))}
        </div>
        <form onSubmit={creer}>
          <label>Nom</label>
          <input value={nom} onChange={e => setNom(e.target.value)}
            placeholder={placeholder} autoFocus />
          <label>Description <span className="optionnel">(optionnel)</span></label>
          <input value={desc} onChange={e => setDesc(e.target.value)} placeholder="Mission de ce service..." />
          <div className="modal-actions">
            <button type="button" className="btn-annuler" onClick={onFermer}>Annuler</button>
            <button type="submit" className="btn-creer" disabled={loading}>
              {loading ? '...' : 'Créer →'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

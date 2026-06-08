import { useState } from 'react'
import { api } from '../services/api.js'

const EMOJIS   = ['🏛','🏙','🌆','🏘','⚜️','🗺','📋','🎖','🏟','🌇','🏫','🗼']
const COULEURS = ['#003189','#1a6fc4','#0d47a1','#1565c0','#57F287','#FEE75C','#E63946','#6c757d']

export default function CreateWorldModal({ onCree, onFermer }) {
  const [nom, setNom]         = useState('')
  const [desc, setDesc]       = useState('')
  const [emoji, setEmoji]     = useState('🏛')
  const [couleur, setCouleur] = useState('#003189')
  const [chargement, setChargement] = useState(false)

  async function creer(e) {
    e.preventDefault()
    if (!nom.trim()) return
    setChargement(true)
    const data = await api.post('/worlds/', { nom, description: desc, emoji, couleur })
    setChargement(false)
    onCree(data)
  }

  return (
    <div className="modal-overlay" onClick={onFermer}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <h2 className="modal-titre">Créer une commune</h2>
        <form onSubmit={creer}>
          <label>Emblème</label>
          <div className="emoji-picker">
            {EMOJIS.map(e => (
              <button key={e} type="button" className={`emoji-btn ${emoji === e ? 'actif' : ''}`}
                onClick={() => setEmoji(e)}>{e}</button>
            ))}
          </div>
          <label>Couleur</label>
          <div className="couleur-picker">
            {COULEURS.map(c => (
              <button key={c} type="button"
                className={`couleur-btn ${couleur === c ? 'actif' : ''}`}
                style={{ background: c }}
                onClick={() => setCouleur(c)}
              />
            ))}
          </div>
          <label>Nom de la commune</label>
          <input value={nom} onChange={e => setNom(e.target.value)}
            placeholder="Mairie de Paris, Commune de Lyon..." autoFocus />
          <label>Description <span className="optionnel">(optionnel)</span></label>
          <input value={desc} onChange={e => setDesc(e.target.value)}
            placeholder="Décrivez votre commune..." />
          <div className="modal-actions">
            <button type="button" className="btn-annuler" onClick={onFermer}>Annuler</button>
            <button type="submit" className="btn-creer" disabled={chargement}>
              {chargement ? '...' : 'Créer →'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

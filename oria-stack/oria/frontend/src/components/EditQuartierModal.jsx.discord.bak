import { useState } from 'react'
import { api } from '../services/api.js'

const EMOJIS   = ['🏘','🏙','🌆','🏛','🌇','🏗','🌃','🌉','🏬','🏭','🏦','🏯']
const COULEURS = ['#5865F2','#E67E22','#3498DB','#9B59B6','#2ECC71','#E74C3C','#1ABC9C','#F39C12']

export default function EditQuartierModal({ quartier, onSave, onFermer }) {
  const [nom, setNom]         = useState(quartier.nom)
  const [desc, setDesc]       = useState(quartier.description || '')
  const [emoji, setEmoji]     = useState(quartier.emoji)
  const [couleur, setCouleur] = useState(quartier.couleur)
  const [loading, setLoading] = useState(false)

  async function sauvegarder(e) {
    e.preventDefault()
    setLoading(true)
    await api.patch(`/quartiers/${quartier.id}`, { nom, description: desc, emoji, couleur })
    setLoading(false)
    onSave()
  }

  return (
    <div className="modal-overlay" onClick={onFermer}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <h2 className="modal-titre">Modifier le quartier</h2>
        <form onSubmit={sauvegarder}>
          <label>Emoji</label>
          <div className="emoji-picker">
            {EMOJIS.map(e => (
              <button key={e} type="button"
                className={`emoji-btn ${emoji === e ? 'actif' : ''}`}
                onClick={() => setEmoji(e)}>{e}</button>
            ))}
          </div>
          <label>Couleur</label>
          <div className="couleur-picker">
            {COULEURS.map(c => (
              <button key={c} type="button"
                className={`couleur-btn ${couleur === c ? 'actif' : ''}`}
                style={{ background: c }} onClick={() => setCouleur(c)} />
            ))}
          </div>
          <label>Nom</label>
          <input value={nom} onChange={e => setNom(e.target.value)} autoFocus required />
          <label>Description <span className="optionnel">(optionnel)</span></label>
          <input value={desc} onChange={e => setDesc(e.target.value)} />
          <div className="modal-actions">
            <button type="button" className="btn-annuler" onClick={onFermer}>Annuler</button>
            <button type="submit" className="btn-creer" disabled={loading}>
              {loading ? '...' : 'Sauvegarder'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

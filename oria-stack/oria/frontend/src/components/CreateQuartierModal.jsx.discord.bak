import { useState } from 'react'
import { api } from '../services/api.js'

const EMOJIS   = ['🏘','🏙','🌆','🏛','🌇','🏗','🌃','🌉','🏬','🏭','🏦','🏯']
const COULEURS = ['#5865F2','#E67E22','#3498DB','#9B59B6','#2ECC71','#E74C3C','#1ABC9C','#F39C12']

export default function CreateQuartierModal({ worldId, onCree, onFermer }) {
  const [nom, setNom]         = useState('')
  const [desc, setDesc]       = useState('')
  const [emoji, setEmoji]     = useState('🏘')
  const [couleur, setCouleur] = useState('#5865F2')
  const [loading, setLoading] = useState(false)

  async function creer(e) {
    e.preventDefault()
    if (!nom.trim()) return
    setLoading(true)
    const data = await api.post('/quartiers/', { world_id: worldId, nom, description: desc, emoji, couleur })
    setLoading(false)
    onCree(data)
  }

  return (
    <div className="modal-overlay" onClick={onFermer}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <h2 className="modal-titre">Créer un quartier</h2>

        <form onSubmit={creer}>
          <label>Emoji</label>
          <div className="emoji-picker">
            {EMOJIS.map(e => (
              <button key={e} type="button"
                className={`emoji-btn ${emoji === e ? 'actif' : ''}`}
                onClick={() => setEmoji(e)}>{e}
              </button>
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

          <label>Nom du quartier</label>
          <input value={nom} onChange={e => setNom(e.target.value)}
            placeholder="Holding A, Résidentiel, Tech..." autoFocus required />

          <label>Description <span className="optionnel">(optionnel)</span></label>
          <input value={desc} onChange={e => setDesc(e.target.value)}
            placeholder="À quoi sert ce quartier ?" />

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

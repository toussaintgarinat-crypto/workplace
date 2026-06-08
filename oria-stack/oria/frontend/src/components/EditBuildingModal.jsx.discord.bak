import { useState } from 'react'
import { api } from '../services/api.js'

const COULEURS = ['#5865F2','#57F287','#FEE75C','#EB459E','#ED4245','#E67E22','#3498DB','#9B59B6']

export default function EditBuildingModal({ building, onSave, onFermer }) {
  const [nom, setNom]         = useState(building.nom)
  const [desc, setDesc]       = useState(building.description || '')
  const [couleur, setCouleur] = useState(building.couleur)
  const [loading, setLoading] = useState(false)

  async function sauvegarder(e) {
    e.preventDefault()
    if (!nom.trim()) return
    setLoading(true)
    await api.patch(`/buildings/${building.id}`, { nom, description: desc, couleur })
    setLoading(false)
    onSave()
  }

  return (
    <div className="modal-overlay" onClick={onFermer}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <h2 className="modal-titre">Modifier l'espace</h2>
        <form onSubmit={sauvegarder}>
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

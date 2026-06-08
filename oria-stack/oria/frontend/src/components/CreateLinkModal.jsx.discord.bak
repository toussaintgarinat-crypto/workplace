import { useState } from 'react'
import { api } from '../services/api.js'

const TYPES = [
  { id: 'filiale',     label: 'Commune membre',    color: '#5865F2', desc: 'A possède B' },
  { id: 'partenaire',  label: 'Partenaire',         color: '#57F287', desc: 'Collaboration' },
  { id: 'client',      label: 'Contractant',        color: '#FEE75C', desc: 'A est client de B' },
  { id: 'fournisseur', label: 'Prestataire',        color: '#EB459E', desc: 'A est fournisseur de B' },
  { id: 'association', label: 'EPCI / Groupement',  color: '#ED4245', desc: 'Lien associatif' },
]

export default function CreateLinkModal({ mondes, onSave, onFermer }) {
  const [fromId, setFromId]       = useState('')
  const [toId, setToId]           = useState('')
  const [type, setType]           = useState('filiale')
  const [pct, setPct]             = useState('')
  const [loading, setLoading]     = useState(false)
  const [erreur, setErreur]       = useState('')

  async function creer(e) {
    e.preventDefault()
    if (!fromId || !toId) { setErreur('Sélectionne les deux communes.'); return }
    if (fromId === toId) { setErreur('Les deux communes doivent être différentes.'); return }
    setLoading(true)
    setErreur('')
    const body = { from_world_id: parseInt(fromId), to_world_id: parseInt(toId), type }
    if (pct) body.pourcentage = parseFloat(pct)
    const res = await api.post('/network/', body)
    setLoading(false)
    if (res?.id || res?.from_world_id) {
      onSave()
    } else {
      setErreur(res?.detail || 'Erreur lors de la création du lien.')
    }
  }

  return (
    <div className="modal-overlay" onClick={onFermer}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <h2 className="modal-titre">🕸 Créer un lien</h2>
        <form onSubmit={creer}>
          <label>Commune source (A)</label>
          <select value={fromId} onChange={e => setFromId(e.target.value)} required>
            <option value="">-- Choisir --</option>
            {mondes.map(m => <option key={m.id} value={m.id}>{m.emoji} {m.nom}</option>)}
          </select>

          <label>Type de relation</label>
          <div className="type-picker">
            {TYPES.map(t => (
              <button key={t.id} type="button"
                className={`type-btn ${type === t.id ? 'actif' : ''}`}
                style={type === t.id ? { borderColor: t.color } : {}}
                onClick={() => setType(t.id)}>
                <span className="type-label" style={{ color: t.color }}>{t.label}</span>
                <span className="type-desc">{t.desc}</span>
              </button>
            ))}
          </div>

          <label>Commune cible (B)</label>
          <select value={toId} onChange={e => setToId(e.target.value)} required>
            <option value="">-- Choisir --</option>
            {mondes.filter(m => m.id !== parseInt(fromId)).map(m => (
              <option key={m.id} value={m.id}>{m.emoji} {m.nom}</option>
            ))}
          </select>

          <label>Pourcentage <span className="optionnel">(optionnel)</span></label>
          <input
            type="number" min="0" max="100" step="0.01"
            value={pct} onChange={e => setPct(e.target.value)}
            placeholder="ex: 51"
          />

          {erreur && <p className="form-erreur">{erreur}</p>}

          <div className="modal-actions">
            <button type="button" className="btn-annuler" onClick={onFermer}>Annuler</button>
            <button type="submit" className="btn-creer" disabled={loading}>
              {loading ? '...' : 'Créer le lien'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

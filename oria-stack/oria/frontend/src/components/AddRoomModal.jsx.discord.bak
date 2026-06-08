import { useState, useEffect } from 'react'
import { api } from '../services/api.js'

const TYPES = [
  { id: 'texte',  emoji: '💬', label: 'Texte',  desc: 'Chat écrit en temps réel' },
  { id: 'vocal',  emoji: '🔊', label: 'Vocal',  desc: 'Appel voix/vidéo' },
  { id: 'mixte',  emoji: '⚡', label: 'Mixte',  desc: 'Chat + voix dans la même pièce' },
]

const EMOJIS = ['💬','🔊','⚡','🏠','💼','🍳','🛋','📋','📊','🎮','🎨','🔬','📡','🌡','💡','🔧','📁','🎯','🌿','🚪']

export default function AddRoomModal({ building, worldId, onCree, onFermer }) {
  const [nom, setNom]                 = useState('')
  const [type, setType]               = useState('mixte')
  const [emoji, setEmoji]             = useState('💬')
  const [etage, setEtage]             = useState(0)
  const [acces, setAcces]             = useState('libre')
  const [abonnements, setAbonnements] = useState([])       // tiers dispo
  const [requis, setRequis]           = useState([])       // ids sélectionnés
  const [loading, setLoading]         = useState(false)

  const etagesExistants = building.type === 'immeuble'
    ? [...new Set((building.rooms || []).map(r => r.etage))].sort()
    : null

  useEffect(() => {
    if (worldId) {
      api.get(`/worlds/${worldId}/abonnements`).then(data => {
        if (Array.isArray(data)) setAbonnements(data)
      })
    }
  }, [worldId])

  function toggleRequis(id) {
    setRequis(p => p.includes(id) ? p.filter(x => x !== id) : [...p, id])
  }

  async function creer(e) {
    e.preventDefault()
    if (!nom.trim()) return
    setLoading(true)
    await api.post('/buildings/rooms', {
      building_id: building.id,
      nom: nom.trim(),
      type,
      emoji,
      etage: building.type === 'immeuble' ? etage : 0,
      acces_restreint: acces,
      abonnements_requis_ids: acces !== 'libre' ? requis : [],
    })
    setLoading(false)
    onCree()
  }

  return (
    <div className="modal-overlay" onClick={onFermer}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <h2 className="modal-titre">
          Ajouter une pièce
          <span className="modal-sous-titre"> dans {building.emoji} {building.nom}</span>
        </h2>

        <form onSubmit={creer}>
          <label>Type de pièce</label>
          <div className="type-picker">
            {TYPES.map(t => (
              <button key={t.id} type="button"
                className={`type-btn ${type === t.id ? 'actif' : ''}`}
                onClick={() => { setType(t.id); setEmoji(t.emoji) }}
              >
                <span className="type-emoji">{t.emoji}</span>
                <span className="type-label">{t.label}</span>
                <span className="type-desc">{t.desc}</span>
              </button>
            ))}
          </div>

          <label>Icône</label>
          <div className="emoji-picker">
            {EMOJIS.map(e => (
              <button key={e} type="button"
                className={`emoji-btn ${emoji === e ? 'actif' : ''}`}
                onClick={() => setEmoji(e)}>{e}
              </button>
            ))}
          </div>

          <label>Nom de la pièce</label>
          <input value={nom} onChange={e => setNom(e.target.value)}
            placeholder="Domotique, Archives, Studio..." autoFocus required />

          {building.type === 'immeuble' && (
            <>
              <label>Étage</label>
              <select className="input-select" value={etage}
                onChange={e => setEtage(Number(e.target.value))}>
                {(etagesExistants?.length ? etagesExistants : [0]).map(n => (
                  <option key={n} value={n}>{n === 0 ? 'RDC' : `Étage ${n}`}</option>
                ))}
                <option value={(etagesExistants?.at(-1) ?? 0) + 1}>
                  Nouvel étage ({(etagesExistants?.at(-1) ?? 0) + 1})
                </option>
              </select>
            </>
          )}

          {/* Restriction d'accès */}
          <label style={{ marginTop: 12 }}>Restriction d'accès</label>
          <div className="type-picker" style={{ gridTemplateColumns: 'repeat(3, 1fr)' }}>
            {[
              { id: 'libre',   icon: '🔓', label: 'Libre',   desc: 'Tout le monde' },
              { id: 'cadenas', icon: '🔒', label: 'Cadenas', desc: 'Visible mais bloqué' },
              { id: 'cache',   icon: '👁️',  label: 'Caché',   desc: 'Invisible sans abonnement' },
            ].map(opt => (
              <button key={opt.id} type="button"
                className={`type-btn ${acces === opt.id ? 'actif' : ''}`}
                onClick={() => setAcces(opt.id)}>
                <span className="type-emoji">{opt.icon}</span>
                <span className="type-label">{opt.label}</span>
                <span className="type-desc">{opt.desc}</span>
              </button>
            ))}
          </div>

          {acces !== 'libre' && (
            <>
              <label style={{ marginTop: 10 }}>
                Abonnements requis
                <span style={{ color: '#72767d', fontWeight: 400 }}> (au moins un)</span>
              </label>
              {abonnements.length === 0 ? (
                <p style={{ color: '#72767d', fontSize: 13 }}>
                  Aucun tier d'abonnement défini. Créez-en via le bouton 💳 dans la barre du world.
                </p>
              ) : (
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                  {abonnements.map(a => {
                    const sel = requis.includes(a.id)
                    return (
                      <button key={a.id} type="button"
                        onClick={() => toggleRequis(a.id)}
                        style={{
                          padding: '5px 12px', borderRadius: 20, border: 'none', cursor: 'pointer',
                          background: sel ? a.couleur : '#2b2d31',
                          color: sel ? 'white' : '#b5bac1',
                          fontWeight: sel ? 600 : 400, fontSize: 13,
                          outline: sel ? `2px solid ${a.couleur}` : 'none',
                          outlineOffset: 1,
                        }}
                      >{a.nom}</button>
                    )
                  })}
                </div>
              )}
            </>
          )}

          <div className="modal-actions">
            <button type="button" className="btn-annuler" onClick={onFermer}>Annuler</button>
            <button type="submit" className="btn-creer" disabled={loading}>
              {loading ? '...' : 'Ajouter →'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

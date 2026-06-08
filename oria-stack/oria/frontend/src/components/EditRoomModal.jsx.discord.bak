import { useState, useEffect } from 'react'
import { api } from '../services/api.js'

const TYPES = [
  { id: 'texte', emoji: '💬', label: 'Texte',  desc: 'Chat écrit' },
  { id: 'vocal', emoji: '🔊', label: 'Vocal',  desc: 'Voix/vidéo' },
  { id: 'mixte', emoji: '⚡', label: 'Mixte',  desc: 'Chat + voix' },
]
const EMOJIS = ['💬','🔊','⚡','🏠','💼','🍳','🛋','📋','📊','🎮','🎨','🔬','📡','🌡','💡','🔧','📁','🎯','🌿','🚪']

export default function EditRoomModal({ room, worldId, onSave, onFermer }) {
  const [nom, setNom]                 = useState(room.nom)
  const [type, setType]               = useState(room.type)
  const [emoji, setEmoji]             = useState(room.emoji)
  const [acces, setAcces]             = useState(room.acces_restreint || 'libre')
  const [abonnements, setAbonnements] = useState([])
  const [requis, setRequis]           = useState(
    (room.abonnements_requis || []).map(a => a.id)
  )
  const [estPayante, setEstPayante]   = useState(room.est_payante || false)
  const [prixAcces, setPrixAcces]     = useState(room.prix_acces || '')
  const [deviseAcces, setDeviseAcces] = useState(room.devise_acces || 'EUR')
  const [typePaiement, setTypePaiement] = useState(room.type_paiement || 'unique')
  const [loading, setLoading]         = useState(false)

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

  async function sauvegarder(e) {
    e.preventDefault()
    setLoading(true)
    await api.patch(`/buildings/rooms/${room.id}`, {
      nom, type, emoji,
      acces_restreint: acces,
      abonnements_requis_ids: acces !== 'libre' ? requis : [],
      est_payante: estPayante,
      prix_acces: estPayante && prixAcces ? parseFloat(prixAcces) : null,
      devise_acces: deviseAcces,
      type_paiement: typePaiement,
    })
    setLoading(false)
    onSave()
  }

  return (
    <div className="modal-overlay" onClick={onFermer}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <h2 className="modal-titre">Modifier la pièce</h2>
        <form onSubmit={sauvegarder}>
          <label>Type</label>
          <div className="type-picker">
            {TYPES.map(t => (
              <button key={t.id} type="button"
                className={`type-btn ${type === t.id ? 'actif' : ''}`}
                onClick={() => setType(t.id)}>
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
                onClick={() => setEmoji(e)}>{e}</button>
            ))}
          </div>

          <label>Nom</label>
          <input value={nom} onChange={e => setNom(e.target.value)} autoFocus required />

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
                  Aucun tier d'abonnement défini pour ce world.
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

          {/* Room payante */}
          <label style={{ marginTop: 14 }}>Accès payant</label>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
            <button
              type="button"
              onClick={() => setEstPayante(p => !p)}
              style={{
                padding: '6px 14px', borderRadius: 20, border: 'none', cursor: 'pointer',
                background: estPayante ? '#57F287' : '#2b2d31',
                color: estPayante ? '#000' : '#b5bac1',
                fontWeight: 600, fontSize: 13,
              }}
            >
              {estPayante ? '💰 Activé' : '🔓 Désactivé'}
            </button>
            <span style={{ color: '#72767d', fontSize: 12 }}>
              Les membres devront payer pour accéder à cette room
            </span>
          </div>

          {estPayante && (
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
              <div style={{ flex: 1, minWidth: 120 }}>
                <label style={{ fontSize: 12 }}>Prix</label>
                <input
                  type="number" min="0" step="0.01"
                  value={prixAcces}
                  onChange={e => setPrixAcces(e.target.value)}
                  placeholder="Ex: 9.99"
                  style={{ width: '100%' }}
                />
              </div>
              <div style={{ minWidth: 80 }}>
                <label style={{ fontSize: 12 }}>Devise</label>
                <select
                  value={deviseAcces}
                  onChange={e => setDeviseAcces(e.target.value)}
                  style={{ width: '100%', background: '#1e1f22', color: '#dcddde',
                           border: '1px solid #3d3f45', borderRadius: 6, padding: '8px 6px' }}
                >
                  <option value="EUR">EUR €</option>
                  <option value="USD">USD $</option>
                  <option value="GBP">GBP £</option>
                </select>
              </div>
              <div style={{ flex: 2, minWidth: 140 }}>
                <label style={{ fontSize: 12 }}>Type de paiement</label>
                <div style={{ display: 'flex', gap: 6 }}>
                  {[
                    { id: 'unique',      label: '💳 Achat unique' },
                    { id: 'abonnement',  label: '🔄 Mensuel' },
                  ].map(opt => (
                    <button
                      key={opt.id} type="button"
                      onClick={() => setTypePaiement(opt.id)}
                      style={{
                        flex: 1, padding: '6px 8px', borderRadius: 8, border: 'none',
                        cursor: 'pointer', fontSize: 12,
                        background: typePaiement === opt.id ? '#5865f2' : '#2b2d31',
                        color: typePaiement === opt.id ? 'white' : '#b5bac1',
                        fontWeight: typePaiement === opt.id ? 600 : 400,
                      }}
                    >{opt.label}</button>
                  ))}
                </div>
              </div>
            </div>
          )}

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

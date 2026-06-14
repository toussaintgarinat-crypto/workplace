import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../services/api.js'

const TYPES = [
  { id: 'texte',  emoji: '💬' },
  { id: 'vocal',  emoji: '🔊' },
  { id: 'mixte',  emoji: '⚡' },
]

const EMOJIS = ['💬','🔊','⚡','🏠','💼','🍳','🛋','📋','📊','🎮','🎨','🔬','📡','🌡','💡','🔧','📁','🎯','🌿','🚪']

export default function AddRoomModal({ building, worldId, onCree, onFermer }) {
  const { t } = useTranslation()
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
          {t('addRoom.title')}
          <span className="modal-sous-titre">{t('addRoom.subtitle', { building: `${building.emoji} ${building.nom}` })}</span>
        </h2>

        <form onSubmit={creer}>
          <label>{t('addRoom.typeLabel')}</label>
          <div className="type-picker">
            {TYPES.map(ty => (
              <button key={ty.id} type="button"
                className={`type-btn ${type === ty.id ? 'actif' : ''}`}
                onClick={() => { setType(ty.id); setEmoji(ty.emoji) }}
              >
                <span className="type-emoji">{ty.emoji}</span>
                <span className="type-label">{t(`addRoom.${ty.id}Label`)}</span>
                <span className="type-desc">{t(`addRoom.${ty.id}Desc`)}</span>
              </button>
            ))}
          </div>

          <label>{t('addRoom.iconLabel')}</label>
          <div className="emoji-picker">
            {EMOJIS.map(e => (
              <button key={e} type="button"
                className={`emoji-btn ${emoji === e ? 'actif' : ''}`}
                onClick={() => setEmoji(e)}>{e}
              </button>
            ))}
          </div>

          <label>{t('addRoom.nameLabel')}</label>
          <input value={nom} onChange={e => setNom(e.target.value)}
            placeholder={t('addRoom.namePlaceholder')} autoFocus required />

          {building.type === 'immeuble' && (
            <>
              <label>{t('addRoom.floorLabel')}</label>
              <select className="input-select" value={etage}
                onChange={e => setEtage(Number(e.target.value))}>
                {(etagesExistants?.length ? etagesExistants : [0]).map(n => (
                  <option key={n} value={n}>{n === 0 ? t('addRoom.floorGround') : t('addRoom.floorN', { n })}</option>
                ))}
                <option value={(etagesExistants?.at(-1) ?? 0) + 1}>
                  {t('addRoom.newFloor', { n: (etagesExistants?.at(-1) ?? 0) + 1 })}
                </option>
              </select>
            </>
          )}

          {/* Restriction d'accès */}
          <label style={{ marginTop: 12 }}>{t('addRoom.accessLabel')}</label>
          <div className="type-picker" style={{ gridTemplateColumns: 'repeat(3, 1fr)' }}>
            {[
              { id: 'libre',   icon: '🔓' },
              { id: 'cadenas', icon: '🔒' },
              { id: 'cache',   icon: '👁️' },
            ].map(opt => (
              <button key={opt.id} type="button"
                className={`type-btn ${acces === opt.id ? 'actif' : ''}`}
                onClick={() => setAcces(opt.id)}>
                <span className="type-emoji">{opt.icon}</span>
                <span className="type-label">{t(`addRoom.${opt.id}Label`)}</span>
                <span className="type-desc">{t(`addRoom.${opt.id}Desc`)}</span>
              </button>
            ))}
          </div>

          {acces !== 'libre' && (
            <>
              <label style={{ marginTop: 10 }}>
                {t('addRoom.subsLabel')}
                <span style={{ color: 'var(--text-mut)', fontWeight: 400 }}>{t('addRoom.subsHint')}</span>
              </label>
              {abonnements.length === 0 ? (
                <p style={{ color: 'var(--text-mut)', fontSize: 13 }}>
                  {t('addRoom.noSubs')}
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
                          background: sel ? a.couleur : 'var(--ink-850)',
                          color: sel ? 'white' : 'var(--text)',
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
            <button type="button" className="btn-annuler" onClick={onFermer}>{t('common.cancel')}</button>
            <button type="submit" className="btn-creer" disabled={loading}>
              {loading ? t('common.working') : t('addRoom.submit')}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

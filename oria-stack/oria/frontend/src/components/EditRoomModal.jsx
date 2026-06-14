import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../services/api.js'

const TYPES = [
  { id: 'texte', emoji: '💬' },
  { id: 'vocal', emoji: '🔊' },
  { id: 'mixte', emoji: '⚡' },
]
const EMOJIS = ['💬','🔊','⚡','🏠','💼','🍳','🛋','📋','📊','🎮','🎨','🔬','📡','🌡','💡','🔧','📁','🎯','🌿','🚪']

export default function EditRoomModal({ room, worldId, onSave, onFermer }) {
  const { t } = useTranslation()
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
        <h2 className="modal-titre">{t('editRoom.title')}</h2>
        <form onSubmit={sauvegarder}>
          <label>{t('editRoom.typeLabel')}</label>
          <div className="type-picker">
            {TYPES.map(ty => (
              <button key={ty.id} type="button"
                className={`type-btn ${type === ty.id ? 'actif' : ''}`}
                onClick={() => setType(ty.id)}>
                <span className="type-emoji">{ty.emoji}</span>
                <span className="type-label">{t(`editRoom.${ty.id}Label`)}</span>
                <span className="type-desc">{t(`editRoom.${ty.id}Desc`)}</span>
              </button>
            ))}
          </div>

          <label>{t('editRoom.iconLabel')}</label>
          <div className="emoji-picker">
            {EMOJIS.map(e => (
              <button key={e} type="button"
                className={`emoji-btn ${emoji === e ? 'actif' : ''}`}
                onClick={() => setEmoji(e)}>{e}</button>
            ))}
          </div>

          <label>{t('common.name')}</label>
          <input value={nom} onChange={e => setNom(e.target.value)} autoFocus required />

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
                  {t('editRoom.noSubs')}
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

          {/* Room payante */}
          <label style={{ marginTop: 14 }}>{t('editRoom.payAccess')}</label>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
            <button
              type="button"
              onClick={() => setEstPayante(p => !p)}
              style={{
                padding: '6px 14px', borderRadius: 20, border: 'none', cursor: 'pointer',
                background: estPayante ? 'var(--vert)' : 'var(--ink-850)',
                color: estPayante ? '#000' : 'var(--text)',
                fontWeight: 600, fontSize: 13,
              }}
            >
              {estPayante ? t('editRoom.payOn') : t('editRoom.payOff')}
            </button>
            <span style={{ color: 'var(--text-mut)', fontSize: 12 }}>
              {t('editRoom.payHint')}
            </span>
          </div>

          {estPayante && (
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
              <div style={{ flex: 1, minWidth: 120 }}>
                <label style={{ fontSize: 12 }}>{t('editRoom.priceLabel')}</label>
                <input
                  type="number" min="0" step="0.01"
                  value={prixAcces}
                  onChange={e => setPrixAcces(e.target.value)}
                  placeholder={t('editRoom.pricePlaceholder')}
                  style={{ width: '100%' }}
                />
              </div>
              <div style={{ minWidth: 80 }}>
                <label style={{ fontSize: 12 }}>{t('editRoom.currencyLabel')}</label>
                <select
                  value={deviseAcces}
                  onChange={e => setDeviseAcces(e.target.value)}
                  style={{ width: '100%', background: 'var(--ink-850)', color: 'var(--text)',
                           border: '1px solid #3d3f45', borderRadius: 6, padding: '8px 6px' }}
                >
                  <option value="EUR">EUR €</option>
                  <option value="USD">USD $</option>
                  <option value="GBP">GBP £</option>
                </select>
              </div>
              <div style={{ flex: 2, minWidth: 140 }}>
                <label style={{ fontSize: 12 }}>{t('editRoom.payTypeLabel')}</label>
                <div style={{ display: 'flex', gap: 6 }}>
                  {[
                    { id: 'unique',      label: t('editRoom.payOnce') },
                    { id: 'abonnement',  label: t('editRoom.payMonthly') },
                  ].map(opt => (
                    <button
                      key={opt.id} type="button"
                      onClick={() => setTypePaiement(opt.id)}
                      style={{
                        flex: 1, padding: '6px 8px', borderRadius: 8, border: 'none',
                        cursor: 'pointer', fontSize: 12,
                        background: typePaiement === opt.id ? 'var(--or-500)' : 'var(--ink-850)',
                        color: typePaiement === opt.id ? 'white' : 'var(--text)',
                        fontWeight: typePaiement === opt.id ? 600 : 400,
                      }}
                    >{opt.label}</button>
                  ))}
                </div>
              </div>
            </div>
          )}

          <div className="modal-actions">
            <button type="button" className="btn-annuler" onClick={onFermer}>{t('common.cancel')}</button>
            <button type="submit" className="btn-creer" disabled={loading}>
              {loading ? t('common.working') : t('common.save')}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../services/api.js'

const TYPES = [
  { id: 'maison',   emoji: '🏛' },
  { id: 'site',     emoji: '🏢' },
  { id: 'immeuble', emoji: '🏘' },
]

export default function CreateBuildingModal({ worldId, quartierId, onCree, onFermer }) {
  const { t } = useTranslation()
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

  const placeholder = t(`createBuilding.${type}Placeholder`)

  return (
    <div className="modal-overlay" onClick={onFermer}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <h2 className="modal-titre">{t('createBuilding.title')}</h2>
        <label>{t('createBuilding.typeLabel')}</label>
        <div className="type-picker">
          {TYPES.map(ty => (
            <button key={ty.id} type="button"
              className={`type-btn ${type === ty.id ? 'actif' : ''}`}
              onClick={() => setType(ty.id)}
            >
              <span className="type-emoji">{ty.emoji}</span>
              <span className="type-label">{t(`createBuilding.${ty.id}Label`)}</span>
              <span className="type-desc">{t(`createBuilding.${ty.id}Desc`)}</span>
            </button>
          ))}
        </div>
        <form onSubmit={creer}>
          <label>{t('common.name')}</label>
          <input value={nom} onChange={e => setNom(e.target.value)}
            placeholder={placeholder} autoFocus />
          <label>{t('common.description')} <span className="optionnel">{t('common.optional')}</span></label>
          <input value={desc} onChange={e => setDesc(e.target.value)} placeholder={t('createBuilding.descPlaceholder')} />
          <div className="modal-actions">
            <button type="button" className="btn-annuler" onClick={onFermer}>{t('common.cancel')}</button>
            <button type="submit" className="btn-creer" disabled={loading}>
              {loading ? t('common.working') : t('common.createArrow')}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

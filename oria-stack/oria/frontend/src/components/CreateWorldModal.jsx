import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../services/api.js'

const EMOJIS   = ['🏛','🏙','🌆','🏘','⚜️','🗺','📋','🎖','🏟','🌇','🏫','🗼']
const COULEURS = ['var(--or-600)','var(--or-600)','#0d47a1','#1565c0','var(--vert)','#FEE75C','#E63946','#6c757d']

export default function CreateWorldModal({ onCree, onFermer }) {
  const { t } = useTranslation()
  const [nom, setNom]         = useState('')
  const [desc, setDesc]       = useState('')
  const [emoji, setEmoji]     = useState('🏛')
  const [couleur, setCouleur] = useState('var(--or-600)')
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
        <h2 className="modal-titre">{t('createWorld.title')}</h2>
        <form onSubmit={creer}>
          <label>{t('createWorld.emblem')}</label>
          <div className="emoji-picker">
            {EMOJIS.map(e => (
              <button key={e} type="button" className={`emoji-btn ${emoji === e ? 'actif' : ''}`}
                onClick={() => setEmoji(e)}>{e}</button>
            ))}
          </div>
          <label>{t('common.color')}</label>
          <div className="couleur-picker">
            {COULEURS.map(c => (
              <button key={c} type="button"
                className={`couleur-btn ${couleur === c ? 'actif' : ''}`}
                style={{ background: c }}
                onClick={() => setCouleur(c)}
              />
            ))}
          </div>
          <label>{t('createWorld.nameLabel')}</label>
          <input value={nom} onChange={e => setNom(e.target.value)}
            placeholder={t('createWorld.namePlaceholder')} autoFocus />
          <label>{t('common.description')} <span className="optionnel">{t('common.optional')}</span></label>
          <input value={desc} onChange={e => setDesc(e.target.value)}
            placeholder={t('createWorld.descPlaceholder')} />
          <div className="modal-actions">
            <button type="button" className="btn-annuler" onClick={onFermer}>{t('common.cancel')}</button>
            <button type="submit" className="btn-creer" disabled={chargement}>
              {chargement ? t('common.working') : t('common.createArrow')}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

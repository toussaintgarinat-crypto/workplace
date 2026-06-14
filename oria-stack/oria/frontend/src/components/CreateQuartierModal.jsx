import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../services/api.js'

const EMOJIS   = ['🏘','🏙','🌆','🏛','🌇','🏗','🌃','🌉','🏬','🏭','🏦','🏯']
const COULEURS = ['var(--or-500)','#E67E22','#3498DB','#9B59B6','#2ECC71','#E74C3C','#1ABC9C','#F39C12']

export default function CreateQuartierModal({ worldId, onCree, onFermer }) {
  const { t } = useTranslation()
  const [nom, setNom]         = useState('')
  const [desc, setDesc]       = useState('')
  const [emoji, setEmoji]     = useState('🏘')
  const [couleur, setCouleur] = useState('var(--or-500)')
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
        <h2 className="modal-titre">{t('createQuartier.title')}</h2>

        <form onSubmit={creer}>
          <label>{t('common.emoji')}</label>
          <div className="emoji-picker">
            {EMOJIS.map(e => (
              <button key={e} type="button"
                className={`emoji-btn ${emoji === e ? 'actif' : ''}`}
                onClick={() => setEmoji(e)}>{e}
              </button>
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

          <label>{t('createQuartier.nameLabel')}</label>
          <input value={nom} onChange={e => setNom(e.target.value)}
            placeholder={t('createQuartier.namePlaceholder')} autoFocus required />

          <label>{t('common.description')} <span className="optionnel">{t('common.optional')}</span></label>
          <input value={desc} onChange={e => setDesc(e.target.value)}
            placeholder={t('createQuartier.descPlaceholder')} />

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

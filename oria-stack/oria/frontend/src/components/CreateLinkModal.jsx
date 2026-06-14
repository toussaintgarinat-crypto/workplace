import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../services/api.js'

const TYPES = [
  { id: 'filiale',     color: 'var(--or-500)' },
  { id: 'partenaire',  color: 'var(--vert)' },
  { id: 'client',      color: '#FEE75C' },
  { id: 'fournisseur', color: '#EB459E' },
  { id: 'association', color: 'var(--rouge)' },
]

export default function CreateLinkModal({ mondes, onSave, onFermer }) {
  const { t } = useTranslation()
  const [fromId, setFromId]       = useState('')
  const [toId, setToId]           = useState('')
  const [type, setType]           = useState('filiale')
  const [pct, setPct]             = useState('')
  const [loading, setLoading]     = useState(false)
  const [erreur, setErreur]       = useState('')

  async function creer(e) {
    e.preventDefault()
    if (!fromId || !toId) { setErreur(t('createLink.errSelectBoth')); return }
    if (fromId === toId) { setErreur(t('createLink.errDifferent')); return }
    setLoading(true)
    setErreur('')
    const body = { from_world_id: parseInt(fromId), to_world_id: parseInt(toId), type }
    if (pct) body.pourcentage = parseFloat(pct)
    const res = await api.post('/network/', body)
    setLoading(false)
    if (res?.id || res?.from_world_id) {
      onSave()
    } else {
      setErreur(res?.detail || t('createLink.errCreate'))
    }
  }

  return (
    <div className="modal-overlay" onClick={onFermer}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <h2 className="modal-titre">{t('createLink.title')}</h2>
        <form onSubmit={creer}>
          <label>{t('createLink.sourceLabel')}</label>
          <select value={fromId} onChange={e => setFromId(e.target.value)} required>
            <option value="">{t('common.choose')}</option>
            {mondes.map(m => <option key={m.id} value={m.id}>{m.emoji} {m.nom}</option>)}
          </select>

          <label>{t('createLink.typeLabel')}</label>
          <div className="type-picker">
            {TYPES.map(ty => (
              <button key={ty.id} type="button"
                className={`type-btn ${type === ty.id ? 'actif' : ''}`}
                style={type === ty.id ? { borderColor: ty.color } : {}}
                onClick={() => setType(ty.id)}>
                <span className="type-label" style={{ color: ty.color }}>{t(`createLink.${ty.id}Label`)}</span>
                <span className="type-desc">{t(`createLink.${ty.id}Desc`)}</span>
              </button>
            ))}
          </div>

          <label>{t('createLink.targetLabel')}</label>
          <select value={toId} onChange={e => setToId(e.target.value)} required>
            <option value="">{t('common.choose')}</option>
            {mondes.filter(m => m.id !== parseInt(fromId)).map(m => (
              <option key={m.id} value={m.id}>{m.emoji} {m.nom}</option>
            ))}
          </select>

          <label>{t('createLink.pctLabel')} <span className="optionnel">{t('common.optional')}</span></label>
          <input
            type="number" min="0" max="100" step="0.01"
            value={pct} onChange={e => setPct(e.target.value)}
            placeholder={t('createLink.pctPlaceholder')}
          />

          {erreur && <p className="form-erreur">{erreur}</p>}

          <div className="modal-actions">
            <button type="button" className="btn-annuler" onClick={onFermer}>{t('common.cancel')}</button>
            <button type="submit" className="btn-creer" disabled={loading}>
              {loading ? t('common.working') : t('createLink.submit')}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../services/api.js'

const COULEURS = ['#6366f1','#ec4899','#f59e0b','#10b981','#3b82f6','#ef4444','#8b5cf6','#14b8a6']

export default function AbonnementsModal({ world, onFermer }) {
  const { t } = useTranslation()
  const [abonnements, setAbonnements] = useState([])
  const [form, setForm]               = useState({ nom: '', description: '', couleur: '#6366f1', prix: 0, devise: 'EUR' })
  const [loading, setLoading]         = useState(false)

  useEffect(() => { charger() }, [world.id])

  async function charger() {
    const data = await api.get(`/worlds/${world.id}/abonnements`)
    if (Array.isArray(data)) setAbonnements(data)
  }

  async function creer(e) {
    e.preventDefault()
    if (!form.nom.trim()) return
    setLoading(true)
    const res = await api.post(`/worlds/${world.id}/abonnements`, { ...form, prix: Number(form.prix) })
    setLoading(false)
    if (res) {
      setAbonnements(p => [...p, res])
      setForm({ nom: '', description: '', couleur: '#6366f1', prix: 0, devise: 'EUR' })
    }
  }

  async function supprimer(id) {
    if (!confirm(t('abonnements.confirmDelete'))) return
    await api.del(`/worlds/${world.id}/abonnements/${id}`)
    setAbonnements(p => p.filter(a => a.id !== id))
  }

  return (
    <div className="modal-overlay" onClick={onFermer}>
      <div className="modal" style={{ maxWidth: 520 }} onClick={e => e.stopPropagation()}>
        <h2 className="modal-titre">
          {t('abonnements.title')}
          <span className="modal-sous-titre">{t('abonnements.subtitle', { world: world.nom })}</span>
        </h2>

        {/* Liste des tiers existants */}
        {abonnements.length > 0 && (
          <div style={{ marginBottom: 20 }}>
            <label>{t('abonnements.activeTiers')}</label>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {abonnements.map(a => (
                <div key={a.id} style={{
                  display: 'flex', alignItems: 'center', gap: 10,
                  background: 'var(--ink-850)', borderRadius: 8, padding: '8px 12px',
                  borderLeft: `4px solid ${a.couleur}`,
                }}>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontWeight: 600, color: '#e3e5e8' }}>{a.nom}</div>
                    {a.description && <div style={{ fontSize: 12, color: 'var(--text-mut)' }}>{a.description}</div>}
                    <div style={{ fontSize: 12, color: 'var(--text-mut)', marginTop: 2 }}>
                      {a.prix > 0 ? t('abonnements.perMonth', { prix: a.prix, devise: a.devise }) : t('abonnements.free')}
                      {a.has_stripe && ' • ✅ Stripe'}
                    </div>
                  </div>
                  <button
                    onClick={() => supprimer(a.id)}
                    style={{ background: 'none', border: 'none', color: 'var(--text-mut)', cursor: 'pointer', fontSize: 16 }}
                    title={t('common.delete')}
                  >✕</button>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Formulaire création */}
        <form onSubmit={creer}>
          <label>{t('abonnements.newTier')}</label>
          <input
            value={form.nom}
            onChange={e => setForm(p => ({ ...p, nom: e.target.value }))}
            placeholder={t('abonnements.namePlaceholder')}
            required
          />

          <label>{t('common.description')}</label>
          <input
            value={form.description}
            onChange={e => setForm(p => ({ ...p, description: e.target.value }))}
            placeholder={t('abonnements.descPlaceholder')}
          />

          <label>{t('common.color')}</label>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', margin: '6px 0' }}>
            {COULEURS.map(c => (
              <button
                key={c} type="button"
                onClick={() => setForm(p => ({ ...p, couleur: c }))}
                style={{
                  width: 28, height: 28, borderRadius: '50%', background: c, border: 'none',
                  cursor: 'pointer',
                  outline: form.couleur === c ? '3px solid white' : 'none',
                  outlineOffset: 2,
                }}
              />
            ))}
          </div>

          <div style={{ display: 'flex', gap: 10 }}>
            <div style={{ flex: 1 }}>
              <label>{t('abonnements.priceLabel')}</label>
              <input
                type="number" min="0" step="0.01"
                value={form.prix}
                onChange={e => setForm(p => ({ ...p, prix: e.target.value }))}
              />
            </div>
            <div style={{ width: 90 }}>
              <label>{t('editRoom.currencyLabel')}</label>
              <select
                className="input-select"
                value={form.devise}
                onChange={e => setForm(p => ({ ...p, devise: e.target.value }))}
              >
                <option value="EUR">EUR</option>
                <option value="USD">USD</option>
                <option value="GBP">GBP</option>
              </select>
            </div>
          </div>

          {Number(form.prix) > 0 && (
            <p style={{ fontSize: 12, color: 'var(--text-mut)', margin: '4px 0' }}>
              {t('abonnements.stripeHint')}
            </p>
          )}

          <div className="modal-actions">
            <button type="button" className="btn-annuler" onClick={onFermer}>{t('common.close')}</button>
            <button type="submit" className="btn-creer" disabled={loading}>
              {loading ? t('common.working') : t('common.createArrow')}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

import { useState, useEffect } from 'react'
import { api } from '../../services/api'
import styles from './Stripe.module.css'

const PLAN_ICONS = { free: '🆓', starter: '🚀', pro: '💎', enterprise: '🏢' }

export default function StripeView() {
  const [plans, setPlans] = useState({})
  const [current, setCurrent] = useState({ plan: 'free', statut: 'actif' })
  const [payments, setPayments] = useState([])

  useEffect(() => {
    api.get('/api/stripe/plans').then(setPlans).catch(() => {})
    api.get('/api/stripe/abonnement').then(a => { if (a) setCurrent(a) }).catch(() => {})
    api.get('/api/stripe/payments').then(r => setPayments(Array.isArray(r) ? r : [])).catch(() => {})
  }, [])

  async function checkout(plan) {
    const { checkoutUrl } = await api.post('/api/stripe/checkout', { plan })
    window.open(checkoutUrl, '_blank')
  }

  return (
    <div className={styles.page}>
      <h1 className={styles.title}>💳 Abonnements</h1>

      <div className={styles.currentPlan}>
        <div className={styles.currentLabel}>Plan actuel</div>
        <div className={styles.currentValue}>{PLAN_ICONS[current.plan]} {current.plan?.toUpperCase()}</div>
        <div className={styles.currentStatus} style={{ color: current.statut === 'actif' ? '#10b981' : '#f59e0b' }}>
          {current.statut}
        </div>
      </div>

      <div className={styles.plansGrid}>
        {Object.entries(plans).map(([key, plan]) => (
          <div key={key} className={`${styles.planCard} ${current.plan === key ? styles.active : ''}`}>
            <div className={styles.planHeader}>
              <span className={styles.planIcon}>{PLAN_ICONS[key]}</span>
              <div>
                <div className={styles.planName}>{key.charAt(0).toUpperCase() + key.slice(1)}</div>
                <div className={styles.planPrice}>{plan.prix === 0 ? 'Gratuit' : `${plan.prix}€/mois`}</div>
              </div>
              {current.plan === key && <span className={styles.currentChip}>Actuel</span>}
            </div>
            <ul className={styles.features}>
              {plan.features.map(f => <li key={f} className={styles.feature}>✓ {f}</li>)}
            </ul>
            {key !== 'free' && current.plan !== key && (
              <button className={styles.btnPrimary} onClick={() => checkout(key)}>
                Passer au {key}
              </button>
            )}
          </div>
        ))}
      </div>

      {payments.length > 0 && (
        <div className={styles.section}>
          <h2 className={styles.sectionTitle}>Historique des paiements</h2>
          <div className={styles.paymentList}>
            {payments.map(p => (
              <div key={p.id} className={styles.paymentRow}>
                <span>{new Date(p.createdAt).toLocaleDateString('fr-FR')}</span>
                <span>{(p.montant / 100).toFixed(2)} €</span>
                <span className={styles.paymentStatus} style={{ color: p.statut === 'complete' ? '#10b981' : '#f59e0b' }}>
                  {p.statut}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

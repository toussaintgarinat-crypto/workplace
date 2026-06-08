import { useState, useEffect, useRef } from 'react'
import { api } from '../services/api.js'

const CHOIX_LABELS = { pour: '✅ Pour', contre: '❌ Contre', abstention: '🔵 Abstention' }
const CHOIX_COLORS = { pour: '#43B581', contre: '#F04747', abstention: '#4A90D9' }

export default function VotePanel({ conseil, world, moi, onFermer }) {
  const [votes, setVotes] = useState([])
  const [question, setQuestion] = useState('')
  const [loading, setLoading] = useState(false)
  const pollRef = useRef(null)
  const isAdmin = world?.owner_id === moi?.id

  useEffect(() => {
    charger()
    // Polling toutes les 3s pour temps réel
    pollRef.current = setInterval(charger, 3000)
    return () => clearInterval(pollRef.current)
  }, [conseil?.id])

  async function charger() {
    const data = await api.get(`/votes/conseil/${conseil.id}`)
    if (data) setVotes(data)
  }

  async function lancerVote(e) {
    e.preventDefault()
    if (!question.trim()) return
    setLoading(true)
    await api.post('/votes/', { conseil_id: conseil.id, world_id: world.id, question: question.trim() })
    setQuestion('')
    setLoading(false)
    charger()
  }

  async function voter(voteId, choix) {
    await api.post(`/votes/${voteId}/voter?choix=${choix}`, {})
    charger()
  }

  async function fermerVote(voteId) {
    await api.patch(`/votes/${voteId}/fermer`, {})
    charger()
  }

  async function supprimerVote(voteId) {
    if (!confirm('Supprimer ce vote ?')) return
    await api.del(`/votes/${voteId}`)
    charger()
  }

  return (
    <div className="mairie-panel">
      <div className="mairie-panel-header">
        <div className="mairie-panel-title">
          <span>🗳️</span>
          <h2>Votes — {conseil.date_conseil}</h2>
        </div>
        <div className="mairie-panel-actions">
          <button className="mairie-btn-close" onClick={onFermer}>✕</button>
        </div>
      </div>

      {isAdmin && (
        <form onSubmit={lancerVote} className="vote-new-form">
          <input
            value={question}
            onChange={e => setQuestion(e.target.value)}
            placeholder="Question soumise au vote..."
            className="vote-question-input"
          />
          <button type="submit" className="mairie-btn-primary" disabled={loading || !question.trim()}>
            🗳️ Lancer le vote
          </button>
        </form>
      )}

      <div className="mairie-list">
        {votes.length === 0 && <div className="mairie-empty">Aucun vote lancé</div>}
        {votes.map(v => {
          const total = v.total_votants || 0
          const monBulletin = v.bulletins?.find(b => b.user_nom === moi?.nom)
          return (
            <div key={v.id} className={`vote-card ${v.statut === 'ferme' ? 'vote-ferme' : 'vote-ouvert'}`}>
              <div className="vote-card-header">
                <span className="vote-question">{v.question}</span>
                <span className={`vote-statut-badge ${v.statut}`}>
                  {v.statut === 'ouvert' ? '🟢 Ouvert' : '🔴 Fermé'}
                </span>
              </div>

              {/* Résultats */}
              <div className="vote-resultats">
                {Object.entries(v.resultats).map(([choix, nb]) => {
                  const pct = total > 0 ? Math.round((nb / total) * 100) : 0
                  return (
                    <div key={choix} className="vote-resultat-row">
                      <span className="vote-choix-label" style={{ color: CHOIX_COLORS[choix] }}>{CHOIX_LABELS[choix]}</span>
                      <div className="vote-bar-bg">
                        <div className="vote-bar-fill" style={{ width: `${pct}%`, background: CHOIX_COLORS[choix] }} />
                      </div>
                      <span className="vote-count">{nb} ({pct}%)</span>
                    </div>
                  )
                })}
                <div className="vote-total">{total} votant{total > 1 ? 's' : ''}</div>
              </div>

              {/* Actions voter */}
              {v.statut === 'ouvert' && (
                <div className="vote-actions">
                  {monBulletin ? (
                    <div className="vote-mon-choix">
                      Mon vote : <strong style={{ color: CHOIX_COLORS[monBulletin.choix] }}>{CHOIX_LABELS[monBulletin.choix]}</strong>
                      <span className="vote-change-hint"> (cliquer pour changer)</span>
                    </div>
                  ) : null}
                  <div className="vote-btns">
                    {Object.entries(CHOIX_LABELS).map(([choix, label]) => (
                      <button
                        key={choix}
                        className={`vote-btn ${monBulletin?.choix === choix ? 'vote-btn-actif' : ''}`}
                        style={{ '--color': CHOIX_COLORS[choix] }}
                        onClick={() => voter(v.id, choix)}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {isAdmin && (
                <div className="vote-admin-btns">
                  {v.statut === 'ouvert' && (
                    <button className="mairie-btn-primary" onClick={() => fermerVote(v.id)} style={{ fontSize: 12 }}>
                      🔴 Clore le vote
                    </button>
                  )}
                  <button onClick={() => supprimerVote(v.id)} style={{ background: 'none', border: 'none', color: '#72767d', cursor: 'pointer', fontSize: 13 }}>🗑</button>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

import { useState, useEffect } from 'react'
import { api } from '../services/api.js'
import { useMatrixPresence } from '../hooks/useMatrixPresence.js'

const ROLE_LABELS = { proprietaire: '👑 ', admin: '🛡 ', membre: '' }

export default function MembersPanel({ world, moi, onFermer, onOuvrirDM, dmUnreadByMxid }) {
  const [membres, setMembres]         = useState([])
  const [abonnements, setAbonnements] = useState([])
  const [gererMembre, setGererMembre] = useState(null) // membre dont on gère les abonnements

  const estProprietaire = world?.owner_id === moi?.id

  useEffect(() => {
    chargerMembres()
    if (estProprietaire) chargerAbonnements()
  }, [world.id])

  async function chargerMembres() {
    const data = await api.get(`/worlds/${world.id}/membres`)
    if (Array.isArray(data)) setMembres(data)
  }

  async function chargerAbonnements() {
    const data = await api.get(`/worlds/${world.id}/abonnements`)
    if (Array.isArray(data)) setAbonnements(data)
  }

  const presence  = useMatrixPresence(membres)
  const enLigne   = membres.filter(m => presence[m.user_id]?.presence === 'online')
  const horsLigne = membres.filter(m => !enLigne.includes(m))

  return (
    <div className="members-panel">
      <div className="members-panel-header">
        <span>Agents &amp; Élus — {membres.length}</span>
        <button className="btn-quitter-room" onClick={onFermer}>✕</button>
      </div>
      <div className="members-list">
        {enLigne.length > 0 && (
          <>
            <p className="members-section-label">En ligne — {enLigne.length}</p>
            {enLigne.map(m => (
              <MemberRow key={m.user_id} m={m} enligne presence={presence[m.user_id]} moi={moi}
                onDM={onOuvrirDM} dmUnread={dmUnreadByMxid?.[m.matrix_user_id] || 0}
                estProprietaire={estProprietaire} onGererAbonnements={() => setGererMembre(m)} />
            ))}
          </>
        )}
        {horsLigne.length > 0 && (
          <>
            <p className="members-section-label">Hors ligne — {horsLigne.length}</p>
            {horsLigne.map(m => (
              <MemberRow key={m.user_id} m={m} enligne={false} moi={moi}
                onDM={onOuvrirDM} dmUnread={dmUnreadByMxid?.[m.matrix_user_id] || 0}
                estProprietaire={estProprietaire} onGererAbonnements={() => setGererMembre(m)} />
            ))}
          </>
        )}
      </div>

      {gererMembre && (
        <GererAbonnementsModal
          world={world}
          membre={gererMembre}
          abonnements={abonnements}
          onFermer={() => setGererMembre(null)}
        />
      )}
    </div>
  )
}

function MemberRow({ m, enligne, presence, moi, onDM, dmUnread, estProprietaire, onGererAbonnements }) {
  const isMoi = m.user_id === moi.id
  return (
    <div className={`member-item ${enligne ? '' : 'offline'}`}>
      <div className="member-avatar-wrap">
        <span className="member-avatar">{m.avatar_emoji}</span>
        <span className={`member-dot ${enligne ? 'online' : ''}`} />
      </div>
      <div className="member-info">
        <span className="member-nom">
          {ROLE_LABELS[m.role]}
          {m.nom}
          {isMoi && <span style={{ color: '#72767d', fontSize: 11 }}> (moi)</span>}
        </span>
        {presence?.room_id && <span className="member-location">Dans une pièce</span>}
      </div>
      <div style={{ display: 'flex', gap: 4 }}>
        {estProprietaire && !isMoi && (
          <button
            className="btn-dm"
            onClick={onGererAbonnements}
            title="Gérer les abonnements"
            style={{ fontSize: 14 }}
          >🔑</button>
        )}
        {!isMoi && onDM && (
          <button className="btn-dm" onClick={() => onDM(m)} title="Message privé" style={{ position: 'relative' }}>
            ✉
            {dmUnread > 0 && (
              <span className="unread-badge" style={{ position: 'absolute', top: -4, right: -4 }}>
                {dmUnread > 99 ? '99+' : dmUnread}
              </span>
            )}
          </button>
        )}
      </div>
    </div>
  )
}

function GererAbonnementsModal({ world, membre, abonnements, onFermer }) {
  const [membresAbonnements, setMembresAbonnements] = useState([])
  const [loading, setLoading] = useState(false)

  useEffect(() => { charger() }, [membre.user_id])

  async function charger() {
    const data = await api.get(`/worlds/${world.id}/membres/${membre.user_id}/abonnements`)
    if (Array.isArray(data)) setMembresAbonnements(data)
  }

  const abonnesIds = new Set(membresAbonnements.map(ma => ma.abonnement.id))

  async function assigner(abonnement_id) {
    setLoading(true)
    await api.post(`/worlds/${world.id}/membres/${membre.user_id}/abonnements`, { abonnement_id })
    await charger()
    setLoading(false)
  }

  async function retirer(abonnement_id) {
    setLoading(true)
    await api.del(`/worlds/${world.id}/membres/${membre.user_id}/abonnements/${abonnement_id}`)
    await charger()
    setLoading(false)
  }

  return (
    <div className="modal-overlay" onClick={onFermer}>
      <div className="modal" style={{ maxWidth: 420 }} onClick={e => e.stopPropagation()}>
        <h2 className="modal-titre">
          Abonnements de {membre.avatar_emoji} {membre.nom}
        </h2>

        {abonnements.length === 0 ? (
          <p style={{ color: '#72767d', fontSize: 14 }}>
            Aucun tier d'abonnement défini pour ce world.
          </p>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {abonnements.map(a => {
              const actif = abonnesIds.has(a.id)
              return (
                <div key={a.id} style={{
                  display: 'flex', alignItems: 'center', gap: 10,
                  background: '#2b2d31', borderRadius: 8, padding: '8px 12px',
                  borderLeft: `4px solid ${a.couleur}`,
                }}>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontWeight: 600, color: '#e3e5e8' }}>{a.nom}</div>
                    <div style={{ fontSize: 12, color: '#72767d' }}>
                      {a.prix > 0 ? `${a.prix} ${a.devise}/mois` : 'Gratuit'}
                    </div>
                  </div>
                  {actif ? (
                    <button
                      onClick={() => retirer(a.id)}
                      disabled={loading}
                      style={{
                        background: '#ed4245', color: 'white', border: 'none',
                        borderRadius: 6, padding: '4px 10px', cursor: 'pointer', fontSize: 13,
                      }}
                    >Retirer</button>
                  ) : (
                    <button
                      onClick={() => assigner(a.id)}
                      disabled={loading}
                      style={{
                        background: '#5865f2', color: 'white', border: 'none',
                        borderRadius: 6, padding: '4px 10px', cursor: 'pointer', fontSize: 13,
                      }}
                    >Assigner</button>
                  )}
                </div>
              )
            })}
          </div>
        )}

        <div className="modal-actions" style={{ marginTop: 16 }}>
          <button className="btn-creer" onClick={onFermer}>Fermer</button>
        </div>
      </div>
    </div>
  )
}

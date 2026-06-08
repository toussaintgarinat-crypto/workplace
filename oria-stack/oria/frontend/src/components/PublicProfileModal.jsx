import { useState, useEffect } from 'react'
import { api } from '../services/api.js'
import FollowButton from './FollowButton.jsx'

export default function PublicProfileModal({ userId, nom, avatarEmoji, moi, onFermer, onOuvrirWorld }) {
  const [profile, setProfile] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get(`/social/profile/${userId}`).then(data => {
      if (data) setProfile(data)
      setLoading(false)
    })
  }, [userId])

  function onOverlayClick(e) {
    if (e.target === e.currentTarget) onFermer()
  }

  const displayAvatar = profile?.avatar_emoji || avatarEmoji || '👤'
  const displayNom    = profile?.nom || nom || '…'

  return (
    <div className="modal-overlay" onClick={onOverlayClick}>
      <div className="modal profile-modal">
        <button className="modal-close" onClick={onFermer}>✕</button>

        {loading ? (
          <div className="profile-loading"><div className="spinner" /></div>
        ) : (
          <>
            <div className="profile-header">
              <span className="profile-avatar">{displayAvatar}</span>
              <div className="profile-info">
                <span className="profile-nom">{displayNom}</span>
                {profile?.bio && <span className="profile-bio">{profile.bio}</span>}
              </div>
              <FollowButton userId={userId} moiId={moi?.id} />
            </div>

            {profile?.worlds?.length > 0 ? (
              <div className="profile-worlds">
                <h4>Mondes publics</h4>
                <div className="profile-worlds-list">
                  {profile.worlds.map(w => (
                    <div
                      key={w.id}
                      className="profile-world-card"
                      onClick={() => { onFermer(); onOuvrirWorld?.(w.id) }}
                    >
                      <span className="profile-world-banner" style={{ background: w.couleur }}>
                        {w.emoji}
                      </span>
                      <div className="profile-world-body">
                        <span className="profile-world-nom">{w.nom}</span>
                        {w.description && <span className="profile-world-desc">{w.description}</span>}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <p className="profile-no-worlds">Aucun monde public pour l'instant.</p>
            )}
          </>
        )}
      </div>
    </div>
  )
}

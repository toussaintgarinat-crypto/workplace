import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../services/api.js'
import FollowButton from './FollowButton.jsx'
import PublicProfileModal from './PublicProfileModal.jsx'

export default function ActivityFeed({ moi, onOuvrirWorld }) {
  const { t } = useTranslation()
  const [onglet, setOnglet]       = useState('feed')
  const [feed, setFeed]           = useState([])
  const [following, setFollowing] = useState([])
  const [followers, setFollowers] = useState([])
  const [loading, setLoading]     = useState(true)
  const [profile, setProfile]     = useState(null) // { userId, nom, avatarEmoji }

  useEffect(() => {
    fetchFeed()
    fetchFollowing()
    fetchFollowers()
  }, [])

  async function fetchFeed() {
    setLoading(true)
    const data = await api.get('/social/feed')
    setFeed(Array.isArray(data) ? data : [])
    setLoading(false)
  }

  async function fetchFollowing() {
    const data = await api.get('/social/following')
    setFollowing(Array.isArray(data) ? data : [])
  }

  async function fetchFollowers() {
    const data = await api.get('/social/followers')
    setFollowers(Array.isArray(data) ? data : [])
  }

  function openProfile(userId, nom, avatarEmoji) {
    setProfile({ userId, nom, avatarEmoji })
  }

  return (
    <div className="activity-feed">
      <div className="feed-header">
        <h2>{t('feed.title')}</h2>
        <div className="feed-tabs">
          <button className={`feed-tab${onglet === 'feed' ? ' actif' : ''}`} onClick={() => setOnglet('feed')}>
            {t('feed.tabFeed')}
          </button>
          <button className={`feed-tab${onglet === 'following' ? ' actif' : ''}`} onClick={() => setOnglet('following')}>
            {t('feed.tabFollowing')} {following.length > 0 && <span className="feed-tab-count">{following.length}</span>}
          </button>
          <button className={`feed-tab${onglet === 'followers' ? ' actif' : ''}`} onClick={() => setOnglet('followers')}>
            {t('feed.tabFollowers')} {followers.length > 0 && <span className="feed-tab-count">{followers.length}</span>}
          </button>
        </div>
      </div>

      {onglet === 'feed' && (
        loading ? (
          <div className="feed-loading"><div className="spinner" /><p>{t('feed.loading')}</p></div>
        ) : feed.length === 0 ? (
          <div className="feed-empty">
            <span>🌱</span>
            <p>{t('feed.emptyFeed')}</p>
            <small>{t('feed.emptyFeedHint')}</small>
          </div>
        ) : (
          <div className="feed-items">
            {feed.map((item, i) => (
              <FeedCard
                key={i}
                item={item}
                onOuvrirWorld={onOuvrirWorld}
                onOpenProfile={openProfile}
              />
            ))}
          </div>
        )
      )}

      {onglet === 'following' && (
        <div className="social-list">
          {following.length === 0 ? (
            <div className="feed-empty">
              <span>👥</span>
              <p>{t('feed.emptyFollowing')}</p>
              <small>{t('feed.emptyFollowingHint')}</small>
            </div>
          ) : (
            following.map(u => (
              <UserRow
                key={u.id}
                user={u}
                moiId={moi?.id}
                initialFollowing={true}
                onOpenProfile={openProfile}
              />
            ))
          )}
        </div>
      )}

      {onglet === 'followers' && (
        <div className="social-list">
          {followers.length === 0 ? (
            <div className="feed-empty">
              <span>👤</span>
              <p>{t('feed.emptyFollowers')}</p>
            </div>
          ) : (
            followers.map(u => (
              <UserRow
                key={u.id}
                user={u}
                moiId={moi?.id}
                onOpenProfile={openProfile}
              />
            ))
          )}
        </div>
      )}

      {profile && (
        <PublicProfileModal
          userId={profile.userId}
          nom={profile.nom}
          avatarEmoji={profile.avatarEmoji}
          moi={moi}
          onFermer={() => setProfile(null)}
          onOuvrirWorld={id => { setProfile(null); onOuvrirWorld?.(id) }}
        />
      )}
    </div>
  )
}

function FeedCard({ item, onOuvrirWorld, onOpenProfile }) {
  const { t, i18n } = useTranslation()
  return (
    <div className="feed-card" onClick={() => onOuvrirWorld?.(item.world_id)}>
      <div className="feed-card-banner" style={{ background: item.world_couleur }}>
        <span className="feed-card-emoji">{item.world_emoji}</span>
      </div>
      <div className="feed-card-body">
        <div className="feed-card-owner">
          <button
            className="feed-owner-avatar-btn"
            onClick={e => { e.stopPropagation(); onOpenProfile(item.owner_id, item.owner_nom, item.owner_avatar) }}
            title={t('feed.viewProfile', { nom: item.owner_nom })}
          >
            {item.owner_avatar}
          </button>
          <span className="feed-card-owner-nom">{item.owner_nom}</span>
          <span className="feed-card-date">{new Date(item.created_at).toLocaleDateString(i18n.language)}</span>
        </div>
        <h4 className="feed-card-nom">{item.world_nom}</h4>
        {item.world_desc && <p className="feed-card-desc">{item.world_desc}</p>}
      </div>
    </div>
  )
}

function UserRow({ user, moiId, initialFollowing, onOpenProfile }) {
  return (
    <div className="user-row" onClick={() => onOpenProfile(user.id, user.nom, user.avatar_emoji)}>
      <span className="user-row-avatar">{user.avatar_emoji}</span>
      <div className="user-row-info">
        <span className="user-row-nom">{user.nom}</span>
        {user.bio && <span className="user-row-bio">{user.bio}</span>}
      </div>
      <FollowButton userId={user.id} moiId={moiId} initialFollowing={initialFollowing} />
    </div>
  )
}

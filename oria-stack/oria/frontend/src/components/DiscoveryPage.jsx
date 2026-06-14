import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../services/api.js'

const TAGS_SUGGESTIONS = ['IA', 'créatif', 'éducation', 'travail', 'art', 'tech', 'communauté', 'jeux', 'musique', 'science']

export default function DiscoveryPage({ moi, onJoinWorld }) {
  const { t } = useTranslation()
  const [worlds, setWorlds]           = useState([])
  const [loading, setLoading]         = useState(true)
  const [search, setSearch]           = useState('')
  const [activeTag, setActiveTag]     = useState(null)
  const [joinLoading, setJoinLoading] = useState(null)
  const [followLoading, setFollowLoading] = useState(null)
  const [followingSet, setFollowingSet]   = useState(new Set())
  const [toast, setToast]             = useState(null)

  useEffect(() => { fetchWorlds() }, [search, activeTag])
  useEffect(() => { fetchFollowing() }, [])

  async function fetchWorlds() {
    setLoading(true)
    const params = new URLSearchParams()
    if (search) params.set('q', search)
    if (activeTag) params.set('tag', activeTag)
    const data = await api.get(`/discover/worlds?${params}`)
    setWorlds(Array.isArray(data) ? data : [])
    setLoading(false)
  }

  async function fetchFollowing() {
    const data = await api.get('/social/following')
    if (Array.isArray(data)) setFollowingSet(new Set(data.map(u => u.id)))
  }

  async function joinWorld(worldId) {
    setJoinLoading(worldId)
    const data = await api.post(`/worlds/${worldId}/rejoindre`, { user_id: moi.id })
    setJoinLoading(null)
    if (data) {
      showToast(t('discovery.joined'))
      onJoinWorld?.()
    }
  }

  async function toggleFollow(ownerId) {
    setFollowLoading(ownerId)
    const isFollowing = followingSet.has(ownerId)
    if (isFollowing) {
      await api.del(`/social/follow/${ownerId}`)
      setFollowingSet(prev => { const s = new Set(prev); s.delete(ownerId); return s })
    } else {
      await api.post(`/social/follow/${ownerId}`)
      setFollowingSet(prev => new Set([...prev, ownerId]))
      showToast(t('discovery.followed'))
    }
    setFollowLoading(null)
  }

  function showToast(msg) {
    setToast(msg)
    setTimeout(() => setToast(null), 3000)
  }

  return (
    <div className="discovery-page">
      {toast && <div className="toast-notif">{toast}</div>}

      {/* Hero */}
      <div className="discovery-hero">
        <h1>{t('discovery.heroTitle')}</h1>
        <p>{t('discovery.heroSubtitle')}</p>
        <div className="discovery-search-bar">
          <input
            type="text"
            placeholder={t('discovery.searchPlaceholder')}
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
          <span className="search-icon">🔍</span>
        </div>
      </div>

      {/* Tags filtres */}
      <div className="discovery-tags">
        <button
          className={`tag-pill ${!activeTag ? 'active' : ''}`}
          onClick={() => setActiveTag(null)}
        >{t('discovery.all')}</button>
        {TAGS_SUGGESTIONS.map(tag => (
          <button
            key={tag}
            className={`tag-pill ${activeTag === tag ? 'active' : ''}`}
            onClick={() => setActiveTag(tag === activeTag ? null : tag)}
          >{tag}</button>
        ))}
      </div>

      {/* Grille worlds */}
      {loading ? (
        <div className="discovery-loading">
          <div className="spinner"/>
          <p>{t('discovery.loading')}</p>
        </div>
      ) : worlds.length === 0 ? (
        <div className="discovery-empty">
          <span>🌌</span>
          <p>{search ? t('discovery.emptyTitleSearch', { q: search }) : t('discovery.emptyTitle')}</p>
          <small>{t('discovery.emptyHint')}</small>
        </div>
      ) : (
        <div className="discovery-grid">
          {worlds.map(w => (
            <WorldCard
              key={w.id}
              world={w}
              moi={moi}
              onJoin={() => joinWorld(w.id)}
              loading={joinLoading === w.id}
              isFollowing={followingSet.has(w.owner_id)}
              onToggleFollow={() => toggleFollow(w.owner_id)}
              followLoading={followLoading === w.owner_id}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function WorldCard({ world, moi, onJoin, loading, isFollowing, onToggleFollow, followLoading }) {
  const { t } = useTranslation()
  const isOwner = moi?.id === world.owner_id

  return (
    <div className="world-card-discovery">
      {/* Bandeau couleur */}
      <div className="wc-banner" style={{ background: world.couleur }}>
        <span className="wc-emoji">{world.emoji}</span>
        {world.agent_count > 0 && (
          <span className="wc-ai-badge">{t('discovery.agentCount', { count: world.agent_count })}</span>
        )}
      </div>

      <div className="wc-body">
        <h3 className="wc-nom">{world.nom}</h3>
        <p className="wc-desc">{world.description || t('discovery.noDesc')}</p>

        {/* Tags */}
        {world.tags?.length > 0 && (
          <div className="wc-tags">
            {world.tags.slice(0, 4).map(t => (
              <span key={t} className="wc-tag">{t}</span>
            ))}
          </div>
        )}

        {/* Stats */}
        <div className="wc-stats">
          <span>👥 {world.member_count}</span>
          <span>👁 {world.view_count}</span>
          <span>🤖 {world.agent_count}</span>
        </div>

        {/* Auteur + Follow */}
        <div className="wc-owner">
          <span className="wc-owner-avatar">{world.owner_avatar}</span>
          <span>{world.owner_nom}</span>
          {!isOwner && (
            <button
              className={`btn-follow-owner ${isFollowing ? 'following' : ''}`}
              onClick={e => { e.stopPropagation(); onToggleFollow() }}
              disabled={followLoading}
              title={isFollowing ? t('discovery.unfollow') : t('discovery.follow')}
            >
              {followLoading ? '⏳' : isFollowing ? t('discovery.following') : t('discovery.followBtn')}
            </button>
          )}
        </div>

        {/* Action rejoindre */}
        {!isOwner && (
          <button
            className="btn-join-world"
            onClick={onJoin}
            disabled={loading}
          >
            {loading ? t('discovery.joining') : t('discovery.join')}
          </button>
        )}
        {isOwner && (
          <div className="wc-owner-badge">{t('discovery.yourWorld')}</div>
        )}
      </div>
    </div>
  )
}

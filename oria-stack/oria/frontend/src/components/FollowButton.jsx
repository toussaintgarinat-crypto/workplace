import { useState, useEffect } from 'react'
import { api } from '../services/api.js'

export default function FollowButton({ userId, moiId, initialFollowing }) {
  const [following, setFollowing] = useState(initialFollowing ?? null)
  const [loading, setLoading]     = useState(initialFollowing === undefined || initialFollowing === null)

  useEffect(() => {
    if (initialFollowing !== undefined && initialFollowing !== null) {
      setFollowing(initialFollowing)
      setLoading(false)
      return
    }
    api.get(`/social/check/${userId}`).then(data => {
      if (data !== null) setFollowing(data.following)
      setLoading(false)
    })
  }, [userId])

  if (userId === moiId) return null

  async function toggle(e) {
    e.stopPropagation()
    setLoading(true)
    if (following) {
      await api.del(`/social/follow/${userId}`)
      setFollowing(false)
    } else {
      await api.post(`/social/follow/${userId}`, {})
      setFollowing(true)
    }
    setLoading(false)
  }

  if (loading && following === null) return <span className="follow-btn-loading">…</span>

  return (
    <button
      className={`btn-follow-owner${following ? ' following' : ''}`}
      onClick={toggle}
      disabled={loading}
    >
      {loading ? '…' : following ? '✓ Suivi' : '+ Suivre'}
    </button>
  )
}

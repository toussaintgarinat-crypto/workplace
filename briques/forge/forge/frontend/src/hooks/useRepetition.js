import { useCallback } from 'react'
import { api } from '../services/api'

export function useRepetition(poleId) {
  const logEvent = useCallback(async (actionKey, actionLabel) => {
    if (!poleId) return null
    try {
      return await api.post('/api/repetition/event', { poleId, actionKey, actionLabel })
    } catch {
      return null
    }
  }, [poleId])

  return { logEvent }
}

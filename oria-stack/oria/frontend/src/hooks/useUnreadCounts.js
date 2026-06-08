/**
 * Hook — compteur de messages non lus par Matrix room.
 * N'incrémente pas si la room est déjà ouverte (activeMatrixRoomIds).
 *
 * @param {Set<string>} activeMatrixRoomIds — matrix_room_id des rooms actuellement ouvertes
 * @returns {{ counts: Object, markAsRead: Function }}
 */
import { useState, useEffect, useCallback, useRef } from 'react'
import { getMatrixClient } from '../services/matrixClient.js'

export function useUnreadCounts(activeMatrixRoomIds) {
  const [counts, setCounts] = useState({}) // { matrixRoomId: number }
  const activeRef = useRef(activeMatrixRoomIds)

  // Garder la ref à jour sans re-register l'écouteur
  useEffect(() => { activeRef.current = activeMatrixRoomIds }, [activeMatrixRoomIds])

  useEffect(() => {
    const client = getMatrixClient()
    if (!client) return

    function onTimeline(event, room, toStartOfTimeline) {
      if (!room || toStartOfTimeline) return
      if (event.getType() !== 'm.room.message') return
      if (event.getSender() === client.getUserId()) return  // ignorer nos propres messages
      if (activeRef.current?.has(room.roomId)) return       // room déjà ouverte

      setCounts(prev => ({
        ...prev,
        [room.roomId]: (prev[room.roomId] || 0) + 1,
      }))
    }

    client.on('Room.timeline', onTimeline)
    return () => client.off('Room.timeline', onTimeline)
  }, []) // une seule inscription, activeRef gère le reste

  const markAsRead = useCallback((matrixRoomId) => {
    if (!matrixRoomId) return
    setCounts(prev => {
      if (!prev[matrixRoomId]) return prev
      const next = { ...prev }
      delete next[matrixRoomId]
      return next
    })
  }, [])

  return { counts, markAsRead }
}

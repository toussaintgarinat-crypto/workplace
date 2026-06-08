/**
 * Hook — compteur de messages DM non lus par MXID de l'expéditeur.
 * Utilise m.direct (account data Matrix) pour identifier les DM rooms.
 *
 * @param {string|null} activeDMMxid — MXID du destinataire actuellement ouvert (null si aucun)
 * @returns {{ total: number, byMxid: Object, markDMAsRead: Function }}
 */
import { useState, useEffect, useCallback, useRef } from 'react'
import { getMatrixClient } from '../services/matrixClient.js'

export function useUnreadDMCounts(activeDMMxid) {
  const [byMxid, setByMxid] = useState({}) // { mxid: count }
  const activeRef = useRef(activeDMMxid)

  useEffect(() => { activeRef.current = activeDMMxid }, [activeDMMxid])

  useEffect(() => {
    const client = getMatrixClient()
    if (!client) return

    // Construit { roomId → mxid } à partir de m.direct
    function buildDMRoomMap() {
      const dmData = client.getAccountData('m.direct')?.getContent() || {}
      const map = {}
      for (const [mxid, roomIds] of Object.entries(dmData)) {
        for (const roomId of roomIds) {
          map[roomId] = mxid
        }
      }
      return map
    }

    function onTimeline(event, room, toStartOfTimeline) {
      if (!room || toStartOfTimeline) return
      if (event.getType() !== 'm.room.message') return
      if (event.getSender() === client.getUserId()) return

      const dmMap = buildDMRoomMap()
      const senderMxid = dmMap[room.roomId]
      if (!senderMxid) return                         // pas une DM room
      if (senderMxid === activeRef.current) return    // DM actuellement ouvert

      setByMxid(prev => ({
        ...prev,
        [senderMxid]: (prev[senderMxid] || 0) + 1,
      }))
    }

    client.on('Room.timeline', onTimeline)
    return () => client.off('Room.timeline', onTimeline)
  }, [])

  const markDMAsRead = useCallback((mxid) => {
    if (!mxid) return
    setByMxid(prev => {
      if (!prev[mxid]) return prev
      const next = { ...prev }
      delete next[mxid]
      return next
    })
  }, [])

  const total = Object.values(byMxid).reduce((a, b) => a + b, 0)

  return { total, byMxid, markDMAsRead }
}

/**
 * Hook — présence online/offline via Matrix.
 * Remplace le WebSocket /api/presence/ws/{world_id}/{user_id} de MembersPanel.
 *
 * Reçoit la liste des membres (avec matrix_user_id) et
 * retourne un objet { [user_id]: 'online'|'offline' }
 */
import { useState, useEffect } from 'react'
import { getMatrixClient } from '../services/matrixClient.js'

export function useMatrixPresence(membres) {
  // presence: { [user_id_oria]: { presence: 'online'|'offline', room_id: null } }
  const [presence, setPresence] = useState({})
  const client = getMatrixClient()

  useEffect(() => {
    if (!client || !membres?.length) return

    // Index MXID → user_id Oria pour le mapping inverse
    const mxidToUserId = {}
    membres.forEach(m => {
      if (m.matrix_user_id) mxidToUserId[m.matrix_user_id] = m.user_id
    })

    // Lire la présence initiale de chaque membre depuis le cache client
    const initial = {}
    membres.forEach(m => {
      if (!m.matrix_user_id) return
      const user = client.getUser(m.matrix_user_id)
      initial[m.user_id] = {
        presence: user?.presence === 'online' ? 'online' : 'offline',
        room_id: null,
      }
    })
    setPresence(initial)

    // Écouter les changements de présence en temps réel
    function onPresence(event, user) {
      const userId = mxidToUserId[user.userId]
      if (!userId) return
      setPresence(prev => ({
        ...prev,
        [userId]: {
          presence: user.presence === 'online' ? 'online' : 'offline',
          room_id: null,
        },
      }))
    }

    client.on('User.presence', onPresence)
    return () => client.off('User.presence', onPresence)
  }, [client, membres])

  return presence
}

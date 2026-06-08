/**
 * Hook — messages directs via Matrix.
 * Remplace le WebSocket /api/dm/ws/{user_id} de DMPanel.
 *
 * Crée la DM room Matrix si elle n'existe pas encore,
 * ou récupère la room existante depuis account data (m.direct).
 */
import { useState, useEffect, useCallback } from 'react'
import { getMatrixClient } from '../services/matrixClient.js'

export function useMatrixDM(destinataireMxid) {
  const [messages, setMessages]     = useState([])
  const [matrixRoomId, setRoomId]   = useState(null)
  const [chargement, setChargement] = useState(true)
  const client = getMatrixClient()

  useEffect(() => {
    if (!client || !destinataireMxid) return
    let annulee = false

    async function initDMRoom() {
      setChargement(true)

      // Chercher une DM room existante dans m.direct
      const dmData = client.getAccountData('m.direct')?.getContent() || {}
      const roomsExistantes = dmData[destinataireMxid] || []
      let roomId = roomsExistantes.find(id => client.getRoom(id))

      if (!roomId) {
        // Créer une nouvelle DM room
        try {
          const res = await client.createRoom({
            preset: 'trusted_private_chat',
            is_direct: true,
            invite: [destinataireMxid],
            creation_content: { 'm.federate': false },
          })
          roomId = res.room_id

          // Mémoriser dans account data
          const updated = { ...dmData, [destinataireMxid]: [...roomsExistantes, roomId] }
          await client.setAccountData('m.direct', updated)
        } catch (e) {
          console.error('Erreur création DM room Matrix:', e)
          setChargement(false)
          return
        }
      }

      if (annulee) return
      setRoomId(roomId)

      // Charger l'historique
      const room = client.getRoom(roomId)
      if (room) {
        const events = room.getLiveTimeline().getEvents()
        setMessages(events.filter(e => e.getType() === 'm.room.message').map(dmEventToMessage))
      }
      setChargement(false)
    }

    initDMRoom()

    return () => { annulee = true }
  }, [destinataireMxid, client])

  // Écouter les nouveaux messages dans la DM room
  useEffect(() => {
    if (!client || !matrixRoomId) return

    function onTimeline(event, room) {
      if (!room || room.roomId !== matrixRoomId) return
      if (event.getType() === 'm.room.message') {
        setMessages(prev => [...prev, dmEventToMessage(event)])
      }
    }

    client.on('Room.timeline', onTimeline)
    return () => client.off('Room.timeline', onTimeline)
  }, [client, matrixRoomId])

  /** Envoie un message DM. */
  const envoyer = useCallback(async (contenu, moi) => {
    if (!client || !matrixRoomId || !contenu.trim()) return
    await client.sendEvent(matrixRoomId, 'm.room.message', {
      msgtype: 'm.text',
      body: contenu.trim(),
      'io.oria.nom':   moi?.nom          || '',
      'io.oria.emoji': moi?.avatar_emoji || '👤',
    })
  }, [client, matrixRoomId])

  return { messages, envoyer, chargement, disponible: !!client && !!matrixRoomId }
}

function dmEventToMessage(event) {
  const content = event.getContent()
  const sender  = event.getSender()
  const isMxid  = sender?.startsWith('@oria_')
  return {
    id:           event.getId(),
    from_user_id: sender,
    from_nom:     content['io.oria.nom']   || (isMxid ? sender.split(':')[0].replace('@oria_', '') : sender),
    from_emoji:   content['io.oria.emoji'] || '👤',
    contenu:      content.body            || '',
    created_at:   new Date(event.getTs()).toISOString(),
  }
}

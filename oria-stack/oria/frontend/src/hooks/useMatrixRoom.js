/**
 * Hook — messages temps réel d'une Matrix Room.
 * Remplace le WebSocket /api/messages/ws/{room_id} de RoomView.
 *
 * Si matrix_room_id est null (ancienne room pas encore migrée),
 * retourne des fonctions vides et laisse RoomView utiliser l'ancien WS.
 */
import { useState, useEffect, useCallback } from 'react'
import { getMatrixClient } from '../services/matrixClient.js'

export function useMatrixRoom(matrixRoomId) {
  const [messages, setMessages] = useState([])
  const client = getMatrixClient()

  useEffect(() => {
    if (!client || !matrixRoomId) return

    // Charger l'historique déjà en mémoire (sync initial)
    const room = client.getRoom(matrixRoomId)
    if (room) {
      const events = room.getLiveTimeline().getEvents()
      const msgs = events
        .filter(e => e.getType() === 'm.room.message')
        .map(matrixEventToMessage)
      setMessages(msgs)
    }

    // Écouter les nouveaux événements en temps réel
    function onTimeline(event, room, toStartOfTimeline) {
      if (!room || room.roomId !== matrixRoomId) return
      if (toStartOfTimeline) return // historique paginé, on ignore

      const type = event.getType()
      if (type === 'm.room.message') {
        setMessages(prev => [...prev, matrixEventToMessage(event)])
      } else if (type === 'm.room.redaction') {
        // Suppression d'un message
        setMessages(prev => prev.filter(m => m.id !== event.event.redacts))
      } else if (type === 'm.reaction') {
        // Réaction — mise à jour du message correspondant
        const targetId = event.getRelation()?.event_id
        if (targetId) {
          setMessages(prev => prev.map(m =>
            m.id === targetId ? { ...m, _reactionsUpdated: Date.now() } : m
          ))
        }
      }
    }

    client.on('Room.timeline', onTimeline)
    return () => client.off('Room.timeline', onTimeline)
  }, [matrixRoomId, client])

  /** Envoie un message texte dans la room Matrix. */
  const envoyer = useCallback(async (contenu) => {
    if (!client || !matrixRoomId || !contenu.trim()) return
    await client.sendTextMessage(matrixRoomId, contenu.trim())
  }, [client, matrixRoomId])

  /** Ajoute/retire une réaction (emoji) sur un message Matrix. */
  const reagir = useCallback(async (eventId, emoji) => {
    if (!client || !matrixRoomId) return
    // Cherche si l'utilisateur a déjà réagi avec cet emoji
    const room = client.getRoom(matrixRoomId)
    const myUserId = client.getUserId()
    const existing = room?.getUnfilteredTimelineSet()
      .getTimelineForEvent(eventId)
      ?.getEvents()
      .find(e =>
        e.getType() === 'm.reaction' &&
        e.getSender() === myUserId &&
        e.getRelation()?.key === emoji &&
        e.getRelation()?.event_id === eventId
      )

    if (existing) {
      // Retirer la réaction
      await client.redactEvent(matrixRoomId, existing.getId())
    } else {
      // Ajouter la réaction
      await client.sendEvent(matrixRoomId, 'm.reaction', {
        'm.relates_to': { rel_type: 'm.annotation', event_id: eventId, key: emoji },
      })
    }
  }, [client, matrixRoomId])

  /** Supprime un message Matrix (redaction). */
  const supprimer = useCallback(async (eventId) => {
    if (!client || !matrixRoomId) return
    await client.redactEvent(matrixRoomId, eventId)
  }, [client, matrixRoomId])

  return { messages, envoyer, reagir, supprimer, disponible: !!client && !!matrixRoomId }
}

/** Convertit un événement Matrix en objet message compatible avec l'UI Oria. */
function matrixEventToMessage(event) {
  const content = event.getContent()
  const sender  = event.getSender() // "@oria_<uuid>:oria.local"
  return {
    id:           event.getId(),
    author_id:    sender,
    author_nom:   content['io.oria.nom']    || sender.split(':')[0].replace('@oria_', ''),
    author_emoji: content['io.oria.emoji']  || '👤',
    contenu:      content.body             || '',
    created_at:   new Date(event.getTs()).toISOString(),
    reactions:    {},  // calculé séparément via les événements m.reaction
    _matrixEvent: event,
  }
}

import { useEffect, useRef, useCallback } from 'react'
import { token } from '../services/api'

const WS_URL = import.meta.env.VITE_WS_URL || (() => {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}`
})()

/**
 * Hook WebSocket pour une session de conversation.
 * Supporte le mode standard et le mode ReAct (react_step events).
 */
export function useWebSocket(sessionId, {
  onChunk,
  onDone,
  onThinking,
  onError,
  onReactStep,
  onActualModel,
} = {}) {
  const wsRef        = useRef(null)
  const reconnectRef = useRef(null)
  const handlersRef  = useRef({})

  handlersRef.current = { onChunk, onDone, onThinking, onError, onReactStep, onActualModel }

  const connect = useCallback(() => {
    if (!sessionId) return
    const t = token.get()
    if (!t) return

    const ws = new WebSocket(`${WS_URL}/api/ws/${sessionId}?token=${t}`)
    wsRef.current = ws

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        const h = handlersRef.current
        switch (msg.type) {
          case 'chunk':      h.onChunk?.(msg.content);         break
          case 'done':       h.onDone?.(msg.content, msg.steps); break
          case 'thinking':   h.onThinking?.();                  break
          case 'error':      h.onError?.(msg.message);          break
          case 'react_step':   h.onReactStep?.(msg.step);                    break
          case 'actual_model': h.onActualModel?.(msg.model, msg.provider);   break
        }
      } catch {}
    }

    ws.onclose = (e) => {
      if (e.code !== 1000) {
        reconnectRef.current = setTimeout(connect, 2000)
      }
    }

    ws.onerror = () => {
      handlersRef.current.onError?.('WebSocket connection error')
    }
  }, [sessionId])

  useEffect(() => {
    connect()
    return () => {
      clearTimeout(reconnectRef.current)
      wsRef.current?.close(1000)
    }
  }, [connect])

  const send = useCallback((content, provider, model, reactMode = false) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ content, provider, model, reactMode }))
      return true
    }
    return false
  }, [])

  return { send }
}

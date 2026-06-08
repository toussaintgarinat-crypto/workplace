import { useState, useRef, useEffect, useCallback } from 'react'
import { api, authHeaders } from '../services/api.js'

const BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'

export default function AgentChatPanel({ agent, moi, onClose }) {
  const [messages, setMessages] = useState([
    {
      role: 'agent',
      content: `Bonjour ! Je suis **${agent.nom}**. ${agent.description ? agent.description + ' ' : ''}Comment puis-je t'aider ?`,
      timestamp: new Date().toISOString(),
    }
  ])
  const [input, setInput]               = useState('')
  const [loading, setLoading]           = useState(false)
  const [sessionId]                     = useState(`oria-${moi?.id}-${agent.id}-${Date.now()}`)
  const [mode, setMode]                 = useState('chat')
  const [isListening, setIsListening]   = useState(false)
  const [voiceEnabled, setVoiceEnabled] = useState(false)
  const [isSpeaking, setIsSpeaking]     = useState(false)
  const [alwaysListening, setAlwaysListening] = useState(false)
  const [isActivated, setIsActivated]   = useState(false)

  const bottomRef           = useRef(null)
  const recognitionRef      = useRef(null)
  const wakeRecognitionRef  = useRef(null)
  const alwaysListeningRef  = useRef(false)
  const loadingRef          = useRef(false)

  // Le mot d'activation : wake_word configuré ou nom de l'agent par défaut
  const wakeWord = ((agent.wake_word && agent.wake_word.trim()) || agent.nom || '').toLowerCase()

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  useEffect(() => {
    loadingRef.current = loading
  }, [loading])

  // Nettoyage à la fermeture
  useEffect(() => {
    return () => {
      window.speechSynthesis?.cancel()
      recognitionRef.current?.stop()
      wakeRecognitionRef.current?.stop()
    }
  }, [])

  // Sync ref pour les callbacks async du wake word
  useEffect(() => {
    alwaysListeningRef.current = alwaysListening
    if (!alwaysListening) {
      wakeRecognitionRef.current?.stop()
      wakeRecognitionRef.current = null
    }
  }, [alwaysListening])

  // ── TTS ──────────────────────────────────────────────────────────

  function speak(text) {
    if (!window.speechSynthesis) return
    window.speechSynthesis.cancel()
    const plain = text.replace(/<[^>]+>/g, '').replace(/\*+/g, '').trim()
    if (!plain) return
    const utt = new SpeechSynthesisUtterance(plain)
    utt.lang = 'fr-FR'
    utt.rate = 1.05
    const voices = window.speechSynthesis.getVoices()
    const fr = voices.find(v => v.lang.startsWith('fr'))
    if (fr) utt.voice = fr
    utt.onstart = () => setIsSpeaking(true)
    utt.onend = () => {
      setIsSpeaking(false)
      // Après la réponse, reprendre l'écoute wake word si mode actif
      if (alwaysListeningRef.current) {
        setTimeout(() => startWakeWordListening(), 400)
      }
    }
    utt.onerror = () => setIsSpeaking(false)
    window.speechSynthesis.speak(utt)
  }

  function toggleVoice() {
    if (voiceEnabled) window.speechSynthesis?.cancel()
    setVoiceEnabled(v => !v)
    setIsSpeaking(false)
  }

  // ── STT manuel (bouton microphone hold) ──────────────────────────

  function startListening() {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!SR) return
    const rec = new SR()
    rec.lang = 'fr-FR'
    rec.interimResults = false
    rec.onresult = e => {
      const text = e.results[0][0].transcript
      setInput(prev => prev ? prev + ' ' + text : text)
    }
    rec.onend = () => setIsListening(false)
    rec.onerror = () => setIsListening(false)
    recognitionRef.current = rec
    rec.start()
    setIsListening(true)
  }

  function stopListening() {
    recognitionRef.current?.stop()
    setIsListening(false)
  }

  // ── Wake word — écoute continue en arrière-plan ───────────────────

  const startWakeWordListening = useCallback(() => {
    if (!alwaysListeningRef.current) return
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!SR || !wakeWord) return

    const rec = new SR()
    rec.lang = 'fr-FR'
    rec.continuous = true
    rec.interimResults = true

    rec.onresult = e => {
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const transcript = e.results[i][0].transcript.toLowerCase()
        if (transcript.includes(wakeWord)) {
          rec.stop()
          activateFromWakeWord()
          break
        }
      }
    }

    rec.onend = () => {
      // Auto-restart si on est toujours en mode écoute et pas en train de traiter
      if (alwaysListeningRef.current && !loadingRef.current) {
        setTimeout(() => startWakeWordListening(), 300)
      }
    }

    rec.onerror = e => {
      if (e.error === 'no-speech' && alwaysListeningRef.current) {
        setTimeout(() => startWakeWordListening(), 500)
      }
    }

    wakeRecognitionRef.current = rec
    try { rec.start() } catch {}
  }, [wakeWord])

  function activateFromWakeWord() {
    setIsActivated(true)
    // Active le TTS automatiquement en mode wake word
    setVoiceEnabled(true)

    // Légère pause pour le feedback visuel, puis écoute la commande
    setTimeout(() => captureCommand(), 600)
  }

  function captureCommand() {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!SR) return

    const rec = new SR()
    rec.lang = 'fr-FR'
    rec.continuous = false
    rec.interimResults = false

    rec.onresult = e => {
      const command = e.results[0][0].transcript.trim()
      if (command) {
        setIsActivated(false)
        autoSendMessage(command)
      }
    }

    rec.onend = () => {
      setIsActivated(false)
      // Si aucune commande captée, reprendre l'écoute
      if (alwaysListeningRef.current && !loadingRef.current) {
        setTimeout(() => startWakeWordListening(), 400)
      }
    }

    rec.onerror = () => {
      setIsActivated(false)
      if (alwaysListeningRef.current) {
        setTimeout(() => startWakeWordListening(), 500)
      }
    }

    recognitionRef.current = rec
    try { rec.start() } catch {}
  }

  function toggleAlwaysListening() {
    if (alwaysListening) {
      setAlwaysListening(false)
      setIsActivated(false)
    } else {
      setAlwaysListening(true)
      setVoiceEnabled(true)
      // Démarrage différé pour laisser le temps à la ref de se mettre à jour
      setTimeout(() => {
        alwaysListeningRef.current = true
        startWakeWordListening()
      }, 100)
    }
  }

  // ── Envoi message (commun texte + voix) ──────────────────────────

  async function autoSendMessage(text) {
    if (!text || loadingRef.current) return
    setMessages(prev => [...prev, {
      role: 'user',
      content: text,
      timestamp: new Date().toISOString(),
    }])
    await sendToAgent(text)
  }

  async function sendMessage(e) {
    e.preventDefault()
    const text = input.trim()
    if (!text || loading) return
    setInput('')
    setMessages(prev => [...prev, {
      role: 'user',
      content: text,
      timestamp: new Date().toISOString(),
    }])
    await sendToAgent(text)
  }

  async function sendToAgent(text) {
    setLoading(true)
    try {
      const res = await fetch(`${BASE}/api/agents/${agent.id}/chat`, {
        method: 'POST',
        credentials: 'include',
        headers: authHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({ message: text, session_id: sessionId }),
      })

      if (res.ok && res.headers.get('content-type')?.includes('event-stream')) {
        const reader = res.body.getReader()
        const decoder = new TextDecoder()
        let answer = ''
        let msgId = null

        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          const chunk = decoder.decode(value)
          const lines = chunk.split('\n')
          for (const line of lines) {
            if (!line.startsWith('data:')) continue
            try {
              const data = JSON.parse(line.slice(5))
              if (data.type === 'answer' || data.content) {
                answer += (data.content || data.answer || '')
                setMessages(prev => {
                  if (msgId === null) {
                    msgId = Date.now()
                    return [...prev, { role: 'agent', content: answer, timestamp: new Date().toISOString(), id: msgId }]
                  }
                  return prev.map(m => m.id === msgId ? { ...m, content: answer } : m)
                })
              }
            } catch {}
          }
        }
        if (!answer) throw new Error('empty')
        // Lit la réponse si voix active (le callback onend de speak relancera le wake word)
        if (voiceEnabled || alwaysListeningRef.current) speak(answer)
        else if (alwaysListeningRef.current) setTimeout(() => startWakeWordListening(), 400)
      } else {
        throw new Error('no-stream')
      }
    } catch {
      const data = await api.post(`/agents/${agent.id}/chat/simple`, {
        message: text,
        session_id: sessionId,
      })
      const answer = data?.answer || '[Aucune réponse]'
      setMessages(prev => [...prev, {
        role: 'agent',
        content: answer,
        timestamp: new Date().toISOString(),
      }])
      if (voiceEnabled || alwaysListeningRef.current) speak(answer)
      else if (alwaysListeningRef.current) setTimeout(() => startWakeWordListening(), 400)
    } finally {
      setLoading(false)
    }
  }

  // ── Rendu ─────────────────────────────────────────────────────────

  function renderContent(text) {
    return text
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(.+?)\*/g, '<em>$1</em>')
      .replace(/`(.+?)`/g, '<code>$1</code>')
      .replace(/\n/g, '<br/>')
  }

  const hasSpeechRecognition = !!(window.SpeechRecognition || window.webkitSpeechRecognition)

  return (
    <div className="agent-chat-overlay">
      <div className="agent-chat-panel">
        {/* Header */}
        <div className="agent-chat-header">
          <div className="agent-chat-identity">
            <span className="agent-chat-avatar">{agent.avatar_emoji}</span>
            <div>
              <div className="agent-chat-nom">{agent.nom}</div>
              <div className="agent-chat-desc">{agent.description || 'Agent IA'}</div>
            </div>
          </div>
          <div className="agent-chat-actions">
            <div className="agent-chat-tabs">
              <button
                className={`tab-btn ${mode === 'chat' ? 'active' : ''}`}
                onClick={() => setMode('chat')}
              >💬 Chat</button>
              {agent.use_ipcra && (
                <button
                  className={`tab-btn ${mode === 'ipcra' ? 'active' : ''}`}
                  onClick={() => setMode('ipcra')}
                >🎯 IPCRA</button>
              )}
              <button
                className={`tab-btn ${voiceEnabled ? 'active' : ''}`}
                onClick={toggleVoice}
                title={voiceEnabled ? 'Désactiver la lecture vocale' : 'Activer la lecture vocale'}
              >
                {isSpeaking ? '🔊' : '🔈'}
              </button>
              {hasSpeechRecognition && wakeWord && (
                <button
                  className={`tab-btn ${alwaysListening ? 'active wake-pulse' : ''}`}
                  onClick={toggleAlwaysListening}
                  title={alwaysListening ? `En écoute — dis "${wakeWord}"` : `Activer l'écoute permanente (dire "${wakeWord}")`}
                >
                  {isActivated ? '⚡' : '👂'}
                </button>
              )}
            </div>
            <button className="agent-chat-close" onClick={onClose}>✕</button>
          </div>
        </div>

        {/* Indicateur wake word */}
        {alwaysListening && (
          <div className={`wake-indicator ${isActivated ? 'activated' : ''}`}>
            {isActivated
              ? '⚡ Activé — parle maintenant…'
              : `👂 En écoute · dis "${wakeWord}"`}
          </div>
        )}

        {/* Capacités badges */}
        <div className="agent-capabilities">
          {agent.can_read_docs && <span className="cap-badge">📁 Dossiers</span>}
          {agent.use_memory    && <span className="cap-badge">🧠 Mémoire</span>}
          {agent.use_ipcra     && <span className="cap-badge">🎯 IPCRA</span>}
          <span className="cap-badge forge">⚡ Forge</span>
          {voiceEnabled && <span className="cap-badge voice">🔊 Voix</span>}
          {alwaysListening && <span className="cap-badge wake">👂 Écoute</span>}
        </div>

        {/* Messages */}
        <div className="agent-chat-messages">
          {messages.map((msg, i) => (
            <div key={i} className={`chat-msg ${msg.role}`}>
              {msg.role === 'agent' && (
                <span className="msg-avatar">{agent.avatar_emoji}</span>
              )}
              <div
                className="msg-bubble"
                dangerouslySetInnerHTML={{ __html: renderContent(msg.content) }}
              />
              {msg.role === 'user' && (
                <span className="msg-avatar user">{moi?.avatar_emoji || '🧑'}</span>
              )}
            </div>
          ))}
          {loading && (
            <div className="chat-msg agent">
              <span className="msg-avatar">{agent.avatar_emoji}</span>
              <div className="msg-bubble typing">
                <span/><span/><span/>
              </div>
            </div>
          )}
          <div ref={bottomRef}/>
        </div>

        {/* Input */}
        <form className="agent-chat-input" onSubmit={sendMessage}>
          {hasSpeechRecognition && (
            <button
              type="button"
              className={`mic-btn ${isListening ? 'listening' : ''}`}
              onMouseDown={startListening}
              onMouseUp={stopListening}
              onTouchStart={startListening}
              onTouchEnd={stopListening}
              title="Maintenir pour parler"
              disabled={loading}
            >
              {isListening ? '🔴' : '🎤'}
            </button>
          )}
          <input
            type="text"
            value={input}
            onChange={e => setInput(e.target.value)}
            placeholder={alwaysListening ? `En écoute… ou écris un message` : `Message ${agent.nom}…`}
            disabled={loading}
            autoFocus
          />
          <button type="submit" disabled={loading || !input.trim()}>
            {loading ? '⏳' : '↑'}
          </button>
        </form>
      </div>
    </div>
  )
}

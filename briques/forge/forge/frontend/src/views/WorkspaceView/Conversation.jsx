import { useState, useEffect, useRef, useCallback } from 'react'
import InputBar from './InputBar'
import AgentCallTree from '../../components/AgentCallTree'
import { useWebSocket } from '../../hooks/useWebSocket'
import { token, api, activeOrg } from '../../services/api'
import styles from './Conversation.module.css'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8600'  // S136 : core strangler

function speak(text, lang = 'fr-FR') {
  if (!window.speechSynthesis) return
  window.speechSynthesis.cancel()
  const chunks = text.match(/.{1,200}(?:\s|$)/g) || [text]
  chunks.forEach(chunk => {
    const utt = new SpeechSynthesisUtterance(chunk.trim())
    utt.lang = lang
    utt.rate = 1.05
    const voices = window.speechSynthesis.getVoices()
    const preferred = voices.find(v => v.lang.startsWith('fr'))
    if (preferred) utt.voice = preferred
    window.speechSynthesis.speak(utt)
  })
}

async function synthesize(text) {
  try {
    const voiceSettings = JSON.parse(localStorage.getItem('forge_voice_settings') || '{}')
    const provider = voiceSettings.ttsProvider || 'openai'
    const voice    = voiceSettings.ttsVoice    || 'nova'
    const res = await fetch(`${API}/api/voice/synthesize`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token.get()}` },
      body: JSON.stringify({ text: text.slice(0, 2000), provider, voice }),
    })
    if (!res.ok) throw new Error()
    const blob = await res.blob()
    const url  = URL.createObjectURL(blob)
    const audio = new Audio(url)
    audio.onended = () => URL.revokeObjectURL(url)
    audio.play()
  } catch {
    speak(text)
  }
}

export default function Conversation({ session, onArtifact, onNew }) {
  const [messages, setMessages]       = useState([])
  const [isStreaming, setIsStreaming]  = useState(false)
  const [voiceMode, setVoiceMode]     = useState(false)
  const [v2vMode, setV2vMode]         = useState(false)
  const [reactSteps, setReactSteps]   = useState([])
  const [pendingHitl, setPendingHitl] = useState([])
  const bottomRef        = useRef(null)
  const assistantIdRef   = useRef(null)
  const lastAssistantRef = useRef('')

  // Poll HITL pending requests
  useEffect(() => {
    if (!session) return
    const poll = async () => {
      try {
        const rows = await api.get('/api/hitl/pending')
        setPendingHitl(rows)
      } catch {}
    }
    poll()
    const iv = setInterval(poll, 10000)
    return () => clearInterval(iv)
  }, [session])

  const handleChunk = useCallback((chunk) => {
    lastAssistantRef.current += chunk
    setMessages(prev => prev.map(m =>
      m.id === assistantIdRef.current ? { ...m, content: m.content + chunk } : m
    ))
  }, [])

  const handleDone = useCallback((content, steps) => {
    setIsStreaming(false)
    setReactSteps([])
    if (voiceMode && lastAssistantRef.current) {
      synthesize(lastAssistantRef.current)
    }
    lastAssistantRef.current = ''
    assistantIdRef.current = null
  }, [voiceMode])

  const handleReactStep = useCallback((step) => {
    setReactSteps(prev => [...prev, step])
    if (step.type === 'answer') {
      setMessages(prev => prev.map(m =>
        m.id === assistantIdRef.current ? { ...m, content: step.content } : m
      ))
      lastAssistantRef.current = step.content
    }
  }, [])

  const handleThinking = useCallback(() => {}, [])
  const handleWsError  = useCallback(() => setIsStreaming(false), [])

  const handleActualModel = useCallback((actualModel, actualProvider) => {
    setMessages(prev => prev.map(m =>
      m.id === assistantIdRef.current ? { ...m, actualModel, actualProvider } : m
    ))
  }, [])

  const { send: wsSend } = useWebSocket(session?.id ?? null, {
    onChunk:        handleChunk,
    onDone:         handleDone,
    onThinking:     handleThinking,
    onError:        handleWsError,
    onReactStep:    handleReactStep,
    onActualModel:  handleActualModel,
  })

  useEffect(() => {
    if (!session) { setMessages([]); return }
    fetch(`${API}/api/sessions/${session.id}/messages`, {
      headers: {
        Authorization: `Bearer ${token.get()}`,
        ...(activeOrg.get() ? { 'X-Org-ID': activeOrg.get() } : {}),
      },
    })
      .then(r => r.json())
      .then(data => setMessages(Array.isArray(data) ? data : []))
      .catch(() => setMessages([]))
  }, [session?.id])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, reactSteps])

  function stopSpeech() { window.speechSynthesis?.cancel() }

  async function sendMessage(content, provider, model, reactMode = false) {
    if (!session) return
    stopSpeech()
    setReactSteps([])

    const userMsg = { id: `u-${Date.now()}`, role: 'user', content }
    const aId     = `a-${Date.now()}`
    assistantIdRef.current  = aId
    lastAssistantRef.current = ''

    setMessages(prev => [...prev, userMsg, { id: aId, role: 'assistant', content: '', reactMode }])
    setIsStreaming(true)

    const sent = wsSend(content, provider, model, reactMode)
    if (sent) return

    // SSE fallback (non-ReAct)
    try {
      const res = await fetch(`${API}/api/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token.get()}` },
        body: JSON.stringify({ sessionId: session.id, content, provider, model }),
      })
      const reader  = res.body.getReader()
      const decoder = new TextDecoder()
      let fullText = '', artifactDone = false
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        for (const line of decoder.decode(value).split('\n')) {
          if (line.startsWith('0:')) {
            try {
              const text = JSON.parse(line.slice(2))
              fullText += text
              setMessages(prev => prev.map(m => m.id === aId ? { ...m, content: fullText } : m))
            } catch {}
          }
        }
        if (!artifactDone && fullText.includes('```')) {
          const match = fullText.match(/```(\w+)?\n([\s\S]+?)```/)
          if (match) {
            artifactDone = true
            onArtifact({ id: Date.now(), type: 'code', language: match[1] || 'text', content: match[2], status: 'pending' })
          }
        }
      }
      if (voiceMode && fullText) synthesize(fullText)
    } catch {
      setMessages(prev => prev.map(m => m.id === aId ? { ...m, content: 'Erreur de connexion.' } : m))
    } finally {
      setIsStreaming(false)
      assistantIdRef.current = null
      lastAssistantRef.current = ''
    }
  }

  async function decideHitl(id, decision) {
    try {
      await api.post(`/api/hitl/requests/${id}/decide`, { decision })
      setPendingHitl(prev => prev.filter(r => r.id !== id))
    } catch {}
  }

  if (!session) {
    return (
      <div className={styles.empty}>
        <div className={styles.emptyInner}>
          <div className={styles.emptyIcon}>⚡</div>
          <h2>Forge</h2>
          <p>Démarrez une conversation avec votre IA.</p>
          <button className={styles.emptyBtn} onClick={onNew}>+ Nouvelle conversation</button>
        </div>
      </div>
    )
  }

  return (
    <div className={styles.container}>
      <header className={styles.header}>
        <span className={styles.sessionName}>{session.name}</span>
        {session.scope === 'pole' && session.poleName && (
          <span className={styles.pole} title="Pôle">
            {session.poleEmoji ?? '🌍'} {session.poleName}
          </span>
        )}
        {session.scope === 'venture' && session.ventureName && (
          <span className={styles.pole} title="Venture">
            {session.ventureEmoji ?? '🚀'} {session.ventureName}
          </span>
        )}
        <span className={`${styles.status} ${isStreaming ? styles.streaming : ''}`}>
          {isStreaming ? 'thinking...' : '● ready'}
        </span>
        {voiceMode && (
          <button className={styles.stopSpeechBtn} onClick={stopSpeech} title="Couper la voix">
            🔇
          </button>
        )}
        {pendingHitl.length > 0 && (
          <span className={styles.hitlBadge} title="Approbations en attente">
            🟡 {pendingHitl.length}
          </span>
        )}
      </header>

      {/* HITL Panel */}
      {pendingHitl.length > 0 && (
        <div className={styles.hitlPanel}>
          <div className={styles.hitlTitle}>Approbations requises</div>
          {pendingHitl.map(req => (
            <div key={req.id} className={styles.hitlItem}>
              <div className={styles.hitlNiveau}>
                Niveau {req.niveau} — {['', 'Information', 'Confirmation', 'Approbation', 'Validation', 'Autorisation', 'Critique'][req.niveau]}
              </div>
              <div className={styles.hitlAction}>{req.action}</div>
              <div className={styles.hitlActions}>
                <button className={styles.hitlApprove} onClick={() => decideHitl(req.id, 'approved')}>
                  Approuver
                </button>
                <button className={styles.hitlReject} onClick={() => decideHitl(req.id, 'rejected')}>
                  Rejeter
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      <div className={styles.messages}>
        {messages.map(msg => (
          <Message key={msg.id} message={msg} voiceMode={voiceMode} />
        ))}

        {/* Agent call chain breadcrumb */}
        {isStreaming && reactSteps.length > 0 && (
          <AgentCallTree steps={reactSteps} />
        )}

        {/* ReAct steps */}
        {isStreaming && reactSteps.length > 0 && (
          <div className={styles.reactSteps}>
            {reactSteps.map((step, i) => (
              <ReactStepItem key={i} step={step} />
            ))}
          </div>
        )}

        {isStreaming && messages.at(-1)?.content === '' && reactSteps.length === 0 && (
          <div className={styles.thinking}><span /><span /><span /></div>
        )}
        <div ref={bottomRef} />
      </div>

      <InputBar
        onSend={sendMessage}
        disabled={isStreaming}
        voiceMode={voiceMode}
        onToggleVoiceMode={() => {
          if (voiceMode) stopSpeech()
          setVoiceMode(v => !v)
        }}
        v2vMode={v2vMode}
        onToggleV2V={() => setV2vMode(v => {
          const next = !v
          if (next && !voiceMode) setVoiceMode(true)
          return next
        })}
      />
    </div>
  )
}

function ReactStepItem({ step }) {
  const [open, setOpen] = useState(step.type === 'answer')
  const icons = { thought: '💭', tool_call: '🔧', tool_result: '📋', answer: '✅' }
  const labels = { thought: 'Réflexion', tool_call: `Outil: ${step.toolName}`, tool_result: `Résultat: ${step.toolName}`, answer: 'Réponse' }

  return (
    <div className={`${styles.reactStep} ${styles[`reactStep_${step.type}`]}`}>
      <button className={styles.reactStepHeader} onClick={() => setOpen(v => !v)}>
        <span>{icons[step.type]}</span>
        <span>{labels[step.type]}</span>
        <span>{open ? '▾' : '▸'}</span>
      </button>
      {open && <pre className={styles.reactStepContent}>{step.content}</pre>}
    </div>
  )
}

function Message({ message, voiceMode }) {
  const isUser = message.role === 'user'
  const parts  = parseContent(message.content)

  return (
    <div className={`${styles.message} ${isUser ? styles.user : styles.assistant}`}>
      <div className={styles.role}>
        {isUser ? 'Vous' : 'Forge'}
        {!isUser && message.content && (
          <button
            className={styles.speakBtn}
            onClick={() => synthesize(message.content)}
            title="Lire à voix haute"
          >
            🔊
          </button>
        )}
      </div>
      <div className={styles.content}>
        {parts.map((part, i) =>
          part.type === 'code' ? (
            <pre key={i} className={styles.code}>
              {part.lang && <span className={styles.codeLang}>{part.lang}</span>}
              <code>{part.content}</code>
            </pre>
          ) : (
            <p key={i}>{part.content}</p>
          )
        )}
        {!isUser && message.actualModel && (
          <div style={{ fontSize: '10px', color: 'var(--text-muted, #888)', marginTop: '4px', fontStyle: 'italic' }}>
            ⓘ modèle utilisé : {message.actualProvider}/{message.actualModel}
          </div>
        )}
      </div>
    </div>
  )
}

function parseContent(text) {
  const parts = []
  const regex = /```(\w+)?\n?([\s\S]*?)```/g
  let last = 0, match

  while ((match = regex.exec(text)) !== null) {
    if (match.index > last)
      parts.push({ type: 'text', content: text.slice(last, match.index).trim() })
    parts.push({ type: 'code', lang: match[1] || '', content: match[2] })
    last = match.index + match[0].length
  }
  if (last < text.length)
    parts.push({ type: 'text', content: text.slice(last).trim() })

  return parts.filter(p => p.content)
}


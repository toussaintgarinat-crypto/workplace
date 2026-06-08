import { useState, useRef, useEffect } from 'react'
import { token, activeOrg } from '../../services/api'
import styles from './InputBar.module.css'

const PROVIDERS = [
  { id: 'ollama',      label: 'Ollama' },
  { id: 'lmstudio',   label: 'LM Studio' },
  { id: 'anthropic',  label: 'Anthropic' },
  { id: 'openai',     label: 'OpenAI' },
  { id: 'openrouter', label: 'OpenRouter' },
  { id: 'groq',       label: 'Groq' },
  { id: 'gemini',     label: 'Gemini' },
  { id: 'mistral',    label: 'Mistral' },
  { id: 'deepseek',   label: 'DeepSeek' },
]

const API = import.meta.env.VITE_API_URL || 'http://localhost:8600'  // S136 : core strangler

export default function InputBar({ onSend, disabled, voiceMode, onToggleVoiceMode, v2vMode, onToggleV2V }) {
  const [value, setValue]             = useState('')
  const [provider, setProvider]       = useState('ollama')
  const [reactMode, setReactMode]     = useState(false)
  const [isRecording, setIsRecording] = useState(false)
  const [isTranscribing, setIsTranscribing] = useState(false)
  const textareaRef = useRef(null)
  const mediaRecRef = useRef(null)
  const chunksRef   = useRef([])

  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 160) + 'px'
  }, [value])

  function submit() {
    const text = value.trim()
    if (!text || disabled) return
    onSend(text, provider, undefined, reactMode)
    setValue('')
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
  }

  function handleKey(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  async function startRecording() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      chunksRef.current = []

      const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : MediaRecorder.isTypeSupported('audio/ogg;codecs=opus')
          ? 'audio/ogg;codecs=opus'
          : 'audio/mp4'

      const rec = new MediaRecorder(stream, { mimeType })
      rec.ondataavailable = e => { if (e.data.size > 0) chunksRef.current.push(e.data) }
      rec.onstop = () => {
        stream.getTracks().forEach(t => t.stop())
        transcribeAudio(chunksRef.current, mimeType)
      }
      rec.start()
      mediaRecRef.current = rec
      setIsRecording(true)
    } catch {
      alert('Microphone inaccessible — autorise l\'accès dans les paramètres du navigateur.')
    }
  }

  function stopRecording() {
    mediaRecRef.current?.stop()
    mediaRecRef.current = null
    setIsRecording(false)
  }

  async function transcribeAudio(chunks, mimeType) {
    if (!chunks.length) return
    setIsTranscribing(true)
    try {
      const blob = new Blob(chunks, { type: mimeType })
      const ext  = mimeType.includes('ogg') ? 'ogg' : mimeType.includes('mp4') ? 'mp4' : 'webm'
      const fd   = new FormData()
      fd.append('audio', blob, `recording.${ext}`)
      const voiceSettings = JSON.parse(localStorage.getItem('forge_voice_settings') || '{}')
      if (voiceSettings.sttProvider) fd.append('provider', voiceSettings.sttProvider)
      const orgId = activeOrg.get()
      const res = await fetch(`${API}/api/voice/transcribe`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token.get()}`,
          ...(orgId ? { 'X-Org-ID': orgId } : {}),
        },
        body: fd,
      })
      if (!res.ok) throw new Error()
      const { text } = await res.json()
      if (text?.trim()) {
        if (v2vMode) {
          onSend(text.trim(), provider, undefined, reactMode)
        } else {
          setValue(prev => prev + (prev ? ' ' : '') + text.trim())
        }
      }
    } catch {
      // garde ce qui était déjà saisi
    } finally {
      setIsTranscribing(false)
    }
  }

  function toggleRecording() {
    if (isRecording) stopRecording()
    else startRecording()
  }

  const micLabel = isTranscribing ? '⏳' : isRecording ? '⏹' : '🎤'
  const micTitle = isTranscribing ? 'Transcription…' : isRecording ? 'Arrêter' : 'Enregistrement vocal'

  return (
    <div className={styles.wrapper}>
      <div className={`${styles.bar} ${isRecording ? styles.recording : ''}`}>
        {isRecording && (
          <div className={styles.waveform}>
            {Array.from({ length: 5 }).map((_, i) => (
              <span key={i} style={{ animationDelay: `${i * 0.1}s` }} />
            ))}
          </div>
        )}

        <textarea
          ref={textareaRef}
          className={styles.input}
          placeholder={
            isRecording    ? 'Parle… clique sur ⏹ pour terminer' :
            isTranscribing ? 'Transcription en cours…' :
            'Message Forge… (Entrée pour envoyer)'
          }
          value={value}
          onChange={e => setValue(e.target.value)}
          onKeyDown={handleKey}
          disabled={disabled || isRecording || isTranscribing}
          rows={1}
        />

        <div className={styles.actions}>
          <button
            className={`${styles.btn} ${styles.reactBtn} ${reactMode ? styles.active : ''}`}
            onClick={() => setReactMode(v => !v)}
            title={reactMode ? 'Mode ReAct activé (raisonnement + outils)' : 'Activer le mode ReAct'}
          >
            ⚛
          </button>

          <select
            className={styles.providerSelect}
            value={provider}
            onChange={e => setProvider(e.target.value)}
          >
            {PROVIDERS.map(p => (
              <option key={p.id} value={p.id}>{p.label}</option>
            ))}
          </select>

          {onToggleVoiceMode && (
            <button
              className={`${styles.btn} ${styles.ttsBtn} ${voiceMode ? styles.active : ''}`}
              onClick={onToggleVoiceMode}
              title={voiceMode ? 'Désactiver lecture vocale' : 'Activer lecture vocale'}
            >
              🔊
            </button>
          )}

          {onToggleV2V && (
            <button
              className={`${styles.btn} ${styles.ttsBtn} ${v2vMode ? styles.active : ''}`}
              onClick={onToggleV2V}
              title={v2vMode ? 'Désactiver mode Voice-to-Voice' : 'Activer mode Voice-to-Voice (STT→LLM→TTS auto)'}
              style={{ fontSize: '0.8rem' }}
            >
              V2V
            </button>
          )}

          <button
            className={`${styles.btn} ${styles.voiceBtn} ${isRecording ? styles.active : ''}`}
            onClick={toggleRecording}
            disabled={isTranscribing}
            title={micTitle}
          >
            {micLabel}
          </button>

          <button
            className={`${styles.btn} ${styles.sendBtn}`}
            onClick={submit}
            disabled={!value.trim() || disabled}
          >
            ▶
          </button>
        </div>
      </div>

      {reactMode && (
        <div className={styles.reactBadge}>
          ⚛ Mode ReAct — l'agent peut utiliser des outils (RAG, Web, Calcul)
        </div>
      )}
    </div>
  )
}

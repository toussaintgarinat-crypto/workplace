import { useState, useRef, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { api, authHeaders } from '../services/api.js'
import { formatBytes } from '@workspace/shared-ui/utils'

const BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'
const VOICE_LOCALE = { fr: 'fr-FR', en: 'en-US', es: 'es-ES' }

export default function JardinPanel({ moi }) {
  const { t, i18n } = useTranslation()
  const [agent, setAgent]           = useState(null)
  const [messages, setMessages]     = useState([])
  const [input, setInput]           = useState('')
  const [loading, setLoading]       = useState(false)
  const [files, setFiles]           = useState([])
  const [uploading, setUploading]   = useState(false)
  const [showConfig, setShowConfig] = useState(false)
  const [activeTab, setActiveTab]   = useState('chat') // 'chat' | 'docs' | 'search'
  const [searchQ, setSearchQ]       = useState('')
  const [searchResults, setSearchResults] = useState(null)
  const [isListening, setIsListening] = useState(false)
  const [selectedFile, setSelectedFile] = useState(null) // doc sélectionné pour aperçu

  const bottomRef      = useRef(null)
  const fileInputRef   = useRef(null)
  const recognitionRef = useRef(null)
  const lastUserMsg    = useRef('')

  useEffect(() => { loadAgent(); loadFiles() }, [])
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])

  async function loadAgent() {
    const data = await api.get('/jardin/agent').catch(() => null)
    if (data?.id) {
      setAgent(data)
      setMessages([{
        role: 'assistant',
        content: t('jardin.greeting', { nom: moi?.nom || '' }),
        ts: new Date().toISOString(),
      }])
    }
  }

  async function loadFiles() {
    const data = await api.get('/jardin/files').catch(() => [])
    setFiles(Array.isArray(data) ? data : [])
  }

  // ── Envoi message ──────────────────────────────────────────────

  async function sendMessage(text) {
    const msg = (text || input).trim()
    if (!msg || loading) return
    setInput('')
    lastUserMsg.current = msg

    setMessages(prev => [...prev, { role: 'user', content: msg, ts: new Date().toISOString() }])
    setLoading(true)

    let answer = ''
    const assistantId = Date.now()
    setMessages(prev => [...prev, { role: 'assistant', content: '', ts: new Date().toISOString(), id: assistantId }])

    try {
      const res = await fetch(`${BASE}/api/jardin/chat`, {
        method: 'POST',
        headers: authHeaders({ 'Content-Type': 'application/json' }),
        credentials: 'include',
        body: JSON.stringify({ message: msg, save_to_memory: true }),
      })

      const reader = res.body.getReader()
      const decoder = new TextDecoder()

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        const text = decoder.decode(value)
        const lines = text.split('\n').filter(l => l.startsWith('data: '))
        for (const line of lines) {
          try {
            const data = JSON.parse(line.slice(6))
            if (data.type === 'answer' && data.content) {
              answer += data.content
              setMessages(prev => prev.map(m =>
                m.id === assistantId ? { ...m, content: answer } : m
              ))
            }
          } catch {}
        }
      }

      // Sauvegarde de la réponse complète en mémoire
      if (answer) {
        api.post('/jardin/memory', {
          user_message: msg,
          assistant_response: answer,
        }).catch(() => {})
      }
    } catch (e) {
      setMessages(prev => prev.map(m =>
        m.id === assistantId ? { ...m, content: t('jardin.connError') } : m
      ))
    } finally {
      setLoading(false)
    }
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage() }
  }

  // ── Upload ─────────────────────────────────────────────────────

  async function handleUpload(file) {
    if (!file) return
    setUploading(true)
    const form = new FormData()
    form.append('file', file)
    try {
      const res = await fetch(`${BASE}/api/jardin/upload`, {
        method: 'POST', credentials: 'include', headers: authHeaders(), body: form,
      })
      if (res.ok) {
        const doc = await res.json()
        setFiles(prev => [{ id: doc.id, nom: doc.nom, type_mime: doc.type_mime, taille: doc.taille, has_md: !!doc.content_md, created_at: doc.created_at }, ...prev])
        setMessages(prev => [...prev, {
          role: 'assistant',
          content: t('jardin.received', { nom: doc.nom }) + (doc.content_md ? '\n\n' + t('jardin.extractedLabel') + '\n\n' + doc.content_md : ''),
          ts: new Date().toISOString(),
        }])
      }
    } catch {}
    setUploading(false)
  }

  function onDrop(e) {
    e.preventDefault()
    const file = e.dataTransfer.files[0]
    if (file) handleUpload(file)
  }

  function onDragOver(e) { e.preventDefault() }

  async function deleteFile(id) {
    await api.delete(`/jardin/files/${id}`).catch(() => {})
    setFiles(prev => prev.filter(f => f.id !== id))
    if (selectedFile?.id === id) setSelectedFile(null)
  }

  async function viewMarkdown(file) {
    const data = await api.get(`/jardin/files/${file.id}/markdown`).catch(() => null)
    if (data) setSelectedFile({ ...file, content_md: data.content_md })
    setActiveTab('docs')
  }

  // ── Recherche ──────────────────────────────────────────────────

  async function doSearch() {
    if (!searchQ.trim()) return
    const data = await api.get(`/jardin/search?q=${encodeURIComponent(searchQ)}&n=8`).catch(() => null)
    setSearchResults(data?.results || [])
  }

  // ── STT ────────────────────────────────────────────────────────

  function toggleListening() {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!SR) return
    if (isListening) {
      recognitionRef.current?.stop()
      setIsListening(false)
      return
    }
    const rec = new SR()
    rec.lang = VOICE_LOCALE[i18n.language] || 'fr-FR'
    rec.interimResults = false
    rec.onresult = e => setInput(prev => prev ? prev + ' ' + e.results[0][0].transcript : e.results[0][0].transcript)
    rec.onend = () => setIsListening(false)
    recognitionRef.current = rec
    rec.start()
    setIsListening(true)
  }

  // ── Rendu ──────────────────────────────────────────────────────

  if (!agent) return (
    <div className="jardin-panel">
      <div className="jardin-loading">{t('jardin.loading')}</div>
    </div>
  )

  return (
    <div className="jardin-panel" onDrop={onDrop} onDragOver={onDragOver}>

      {/* Header */}
      <div className="jardin-header">
        <span className="jardin-header-icon">🌿</span>
        <div className="jardin-header-info">
          <span className="jardin-header-title">{t('jardin.title')}</span>
          <span className="jardin-header-sub">{agent.nom} · {agent.forge_provider} / {agent.forge_model || '…'}</span>
        </div>
        <div className="jardin-header-tabs">
          <button className={`jardin-tab ${activeTab === 'chat' ? 'active' : ''}`} onClick={() => setActiveTab('chat')}>{t('jardin.chat')}</button>
          <button className={`jardin-tab ${activeTab === 'docs' ? 'active' : ''}`} onClick={() => setActiveTab('docs')}>{t('jardin.documents')} {files.length > 0 && <span className="jardin-badge">{files.length}</span>}</button>
          <button className={`jardin-tab ${activeTab === 'search' ? 'active' : ''}`} onClick={() => setActiveTab('search')}>{t('jardin.memory')}</button>
        </div>
        <button className="jardin-config-btn" onClick={() => setShowConfig(true)} title={t('jardin.configTooltip')}>⚙</button>
      </div>

      {/* Corps */}
      <div className="jardin-body">

        {/* ── Chat ── */}
        {activeTab === 'chat' && (
          <div className="jardin-chat">
            <div className="jardin-messages">
              {messages.map((m, i) => (
                <div key={i} className={`jardin-msg ${m.role}`}>
                  <span className="jardin-msg-avatar">{m.role === 'user' ? (moi?.avatar_emoji || '👤') : agent.avatar_emoji}</span>
                  <div className="jardin-msg-bubble">
                    <span className="jardin-msg-name">{m.role === 'user' ? moi?.nom : agent.nom}</span>
                    <div className="jardin-msg-text" style={{ whiteSpace: 'pre-wrap' }}>{m.content || (loading && m.id ? <span className="jardin-typing">…</span> : '')}</div>
                  </div>
                </div>
              ))}
              <div ref={bottomRef} />
            </div>

            <div className="jardin-input-row">
              <button
                className="jardin-upload-btn"
                onClick={() => fileInputRef.current?.click()}
                title={t('jardin.attachFile')}
                disabled={uploading}
              >
                {uploading ? '⏳' : '📎'}
              </button>
              <input
                ref={fileInputRef}
                type="file"
                style={{ display: 'none' }}
                onChange={e => { if (e.target.files[0]) handleUpload(e.target.files[0]) }}
              />
              <textarea
                className="jardin-input"
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={t('jardin.inputPlaceholder')}
                rows={1}
                disabled={loading}
              />
              <button
                className={`jardin-mic-btn ${isListening ? 'listening' : ''}`}
                onClick={toggleListening}
                title={t('jardin.micTitle')}
              >🎤</button>
              <button
                className="jardin-send-btn"
                onClick={() => sendMessage()}
                disabled={loading || !input.trim()}
              >
                {loading ? '…' : '↑'}
              </button>
            </div>
          </div>
        )}

        {/* ── Documents ── */}
        {activeTab === 'docs' && (
          <div className="jardin-docs">
            <div className="jardin-docs-sidebar">
              <button
                className="jardin-upload-big"
                onClick={() => fileInputRef.current?.click()}
                disabled={uploading}
              >
                <input
                  ref={fileInputRef}
                  type="file"
                  style={{ display: 'none' }}
                  onChange={e => { if (e.target.files[0]) handleUpload(e.target.files[0]) }}
                />
                <span>{uploading ? '⏳' : '+'}</span>
                <span>{uploading ? t('jardin.processing') : t('jardin.addFile')}</span>
              </button>

              <div className="jardin-drop-hint">{t('jardin.dropHint')}</div>

              {files.length === 0 ? (
                <div className="jardin-docs-empty">{t('jardin.noDocs')}</div>
              ) : (
                <ul className="jardin-docs-list">
                  {files.map(f => (
                    <li
                      key={f.id}
                      className={`jardin-doc-item ${selectedFile?.id === f.id ? 'selected' : ''}`}
                      onClick={() => viewMarkdown(f)}
                    >
                      <span className="jardin-doc-icon">{docIcon(f.type_mime)}</span>
                      <div className="jardin-doc-info">
                        <span className="jardin-doc-nom">{f.nom}</span>
                        <span className="jardin-doc-meta">{formatSize(f.taille)} · {formatDate(f.created_at, i18n.language)}</span>
                      </div>
                      <a
                        href={`${BASE}${f.url}`}
                        target="_blank"
                        rel="noreferrer"
                        className="jardin-doc-open"
                        onClick={e => e.stopPropagation()}
                        title={t('jardin.openOriginal')}
                      >↗</a>
                      <button
                        className="jardin-doc-del"
                        onClick={e => { e.stopPropagation(); deleteFile(f.id) }}
                        title={t('common.delete')}
                      >✕</button>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div className="jardin-docs-main">
              {selectedFile ? (
                <>
                  <div className="jardin-docs-main-header">
                    <span>{docIcon(selectedFile.type_mime)} {selectedFile.nom}</span>
                    <button className="jardin-doc-close" onClick={() => setSelectedFile(null)}>✕</button>
                  </div>
                  <pre className="jardin-md-preview">{selectedFile.content_md || t('jardin.noContent')}</pre>
                </>
              ) : (
                <div className="jardin-docs-placeholder">
                  <span>📄</span>
                  <p>{t('jardin.docsPlaceholder')}</p>
                </div>
              )}
            </div>
          </div>
        )}

        {/* ── Recherche mémoire ── */}
        {activeTab === 'search' && (
          <div className="jardin-search">
            <div className="jardin-search-bar">
              <input
                className="jardin-search-input"
                value={searchQ}
                onChange={e => setSearchQ(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && doSearch()}
                placeholder={t('jardin.searchPlaceholder')}
              />
              <button className="jardin-search-btn" onClick={doSearch}>{t('jardin.searchBtn')}</button>
            </div>
            {searchResults === null && (
              <div className="jardin-search-hint">
                <span>🧠</span>
                <p>{t('jardin.searchHint')}</p>
              </div>
            )}
            {searchResults !== null && searchResults.length === 0 && (
              <div className="jardin-search-empty">{t('jardin.searchEmpty')}</div>
            )}
            {searchResults?.length > 0 && (
              <ul className="jardin-search-results">
                {searchResults.map((r, i) => (
                  <li key={i} className="jardin-search-result">
                    <div className="jardin-result-meta">
                      <span className="jardin-result-wing">{r.wing}/{r.room}</span>
                      <span className="jardin-result-sim">{Math.round(r.similarity * 100)}%</span>
                    </div>
                    <p className="jardin-result-text">{r.text}</p>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>

      {/* Modal config agent */}
      {showConfig && (
        <AgentConfigModal
          agent={agent}
          onSave={async (updates) => {
            const updated = await api.patch('/jardin/agent', updates).catch(() => null)
            if (updated) setAgent(updated)
            setShowConfig(false)
          }}
          onClose={() => setShowConfig(false)}
        />
      )}
    </div>
  )
}


// ── Modal de configuration ─────────────────────────────────────────────────

function AgentConfigModal({ agent, onSave, onClose }) {
  const { t } = useTranslation()
  const [form, setForm] = useState({
    nom:           agent.nom,
    avatar_emoji:  agent.avatar_emoji,
    system_prompt: agent.system_prompt,
    forge_url:     agent.forge_url,
    forge_provider: agent.forge_provider,
    forge_model:   agent.forge_model,
    wake_word:     agent.wake_word,
  })

  const PROVIDERS = ['openrouter', 'ollama', 'anthropic', 'openai', 'groq', 'mistral', 'gemini', 'deepseek', 'lmstudio']

  function set(k, v) { setForm(f => ({ ...f, [k]: v })) }

  return (
    <div className="jardin-modal-overlay" onClick={onClose}>
      <div className="jardin-modal" onClick={e => e.stopPropagation()}>
        <div className="jardin-modal-header">
          <span>{t('jardin.configHeader')}</span>
          <button onClick={onClose}>✕</button>
        </div>

        <div className="jardin-modal-body">
          <div className="jardin-form-row">
            <label>{t('jardin.name')}</label>
            <input value={form.nom} onChange={e => set('nom', e.target.value)} />
          </div>
          <div className="jardin-form-row">
            <label>{t('jardin.emoji')}</label>
            <input value={form.avatar_emoji} onChange={e => set('avatar_emoji', e.target.value)} style={{ width: 64 }} />
          </div>
          <div className="jardin-form-row">
            <label>{t('jardin.provider')}</label>
            <select value={form.forge_provider} onChange={e => set('forge_provider', e.target.value)}>
              {PROVIDERS.map(p => <option key={p} value={p}>{p}</option>)}
            </select>
          </div>
          <div className="jardin-form-row">
            <label>{t('jardin.model')}</label>
            <input value={form.forge_model} onChange={e => set('forge_model', e.target.value)} placeholder={t('jardin.modelPlaceholder')} />
          </div>
          <div className="jardin-form-row">
            <label>{t('jardin.forgeUrl')}</label>
            <input value={form.forge_url} onChange={e => set('forge_url', e.target.value)} placeholder="http://localhost:3001" />
          </div>
          <div className="jardin-form-row">
            <label>{t('jardin.wakeWord')}</label>
            <input value={form.wake_word} onChange={e => set('wake_word', e.target.value)} placeholder={t('jardin.wakeWordPlaceholder')} />
          </div>
          <div className="jardin-form-row col">
            <label>{t('jardin.systemPrompt')}</label>
            <textarea value={form.system_prompt} onChange={e => set('system_prompt', e.target.value)} rows={5} />
          </div>
        </div>

        <div className="jardin-modal-footer">
          <button className="jardin-btn-secondary" onClick={onClose}>{t('common.cancel')}</button>
          <button className="jardin-btn-primary" onClick={() => onSave(form)}>{t('common.save')}</button>
        </div>
      </div>
    </div>
  )
}


// ── Utilitaires ────────────────────────────────────────────────────────────

function docIcon(mime = '') {
  if (mime.startsWith('image/')) return '🖼'
  if (mime.includes('pdf')) return '📄'
  if (mime.startsWith('audio/')) return '🎵'
  if (mime.startsWith('video/')) return '🎬'
  if (mime.includes('word') || mime.includes('document')) return '📝'
  if (mime.includes('sheet') || mime.includes('excel')) return '📊'
  if (mime.includes('presentation')) return '📽'
  return '📎'
}

// formatSize remplacé par formatBytes (@workspace/shared-ui/utils) — sprint S98
const formatSize = (b) => formatBytes(b)

function formatDate(iso, locale = 'fr') {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString(locale, { day: 'numeric', month: 'short' })
}

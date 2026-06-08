import { useState, useRef, useEffect, useCallback } from 'react'
import { api, authHeaders } from '../services/api.js'
import { formatBytes } from '@workspace/shared-ui/utils'

const BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'

export default function JardinPanel({ moi }) {
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
        content: `Bonjour ${moi?.nom || ''} ! Je suis ton assistant personnel. Tu peux me parler, m'envoyer des documents ou faire des recherches dans ta mémoire.`,
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
        m.id === assistantId ? { ...m, content: '[Erreur de connexion à Forge]' } : m
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
          content: `J'ai reçu et mémorisé **${doc.nom}**.\n\n${doc.content_md ? 'Contenu extrait :\n\n' + doc.content_md : ''}`,
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
    rec.lang = 'fr-FR'
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
      <div className="jardin-loading">Chargement du Jardin Secret…</div>
    </div>
  )

  return (
    <div className="jardin-panel" onDrop={onDrop} onDragOver={onDragOver}>

      {/* Header */}
      <div className="jardin-header">
        <span className="jardin-header-icon">🌿</span>
        <div className="jardin-header-info">
          <span className="jardin-header-title">Mon Jardin Secret</span>
          <span className="jardin-header-sub">{agent.nom} · {agent.forge_provider} / {agent.forge_model || '…'}</span>
        </div>
        <div className="jardin-header-tabs">
          <button className={`jardin-tab ${activeTab === 'chat' ? 'active' : ''}`} onClick={() => setActiveTab('chat')}>💬 Chat</button>
          <button className={`jardin-tab ${activeTab === 'docs' ? 'active' : ''}`} onClick={() => setActiveTab('docs')}>📁 Documents {files.length > 0 && <span className="jardin-badge">{files.length}</span>}</button>
          <button className={`jardin-tab ${activeTab === 'search' ? 'active' : ''}`} onClick={() => setActiveTab('search')}>🔍 Mémoire</button>
        </div>
        <button className="jardin-config-btn" onClick={() => setShowConfig(true)} title="Configurer l'assistant">⚙</button>
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
                title="Joindre un fichier"
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
                placeholder="Écris quelque chose… (Entrée pour envoyer)"
                rows={1}
                disabled={loading}
              />
              <button
                className={`jardin-mic-btn ${isListening ? 'listening' : ''}`}
                onClick={toggleListening}
                title="Microphone"
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
                <span>{uploading ? 'Traitement…' : 'Ajouter un fichier'}</span>
              </button>

              <div className="jardin-drop-hint">ou glisse-dépose ici</div>

              {files.length === 0 ? (
                <div className="jardin-docs-empty">Aucun document — envoie des PDF, images, audio…</div>
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
                        <span className="jardin-doc-meta">{formatSize(f.taille)} · {formatDate(f.created_at)}</span>
                      </div>
                      <a
                        href={`${BASE}${f.url}`}
                        target="_blank"
                        rel="noreferrer"
                        className="jardin-doc-open"
                        onClick={e => e.stopPropagation()}
                        title="Ouvrir l'original"
                      >↗</a>
                      <button
                        className="jardin-doc-del"
                        onClick={e => { e.stopPropagation(); deleteFile(f.id) }}
                        title="Supprimer"
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
                  <pre className="jardin-md-preview">{selectedFile.content_md || '(pas de contenu extrait)'}</pre>
                </>
              ) : (
                <div className="jardin-docs-placeholder">
                  <span>📄</span>
                  <p>Clique sur un document pour voir son contenu extrait (Markdown)</p>
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
                placeholder="Cherche dans ta mémoire…"
              />
              <button className="jardin-search-btn" onClick={doSearch}>Chercher</button>
            </div>
            {searchResults === null && (
              <div className="jardin-search-hint">
                <span>🧠</span>
                <p>Recherche sémantique dans toute ta mémoire : conversations, documents, sessions IPCRA.</p>
              </div>
            )}
            {searchResults !== null && searchResults.length === 0 && (
              <div className="jardin-search-empty">Aucun souvenir trouvé pour cette requête.</div>
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
          <span>⚙ Configurer l'assistant</span>
          <button onClick={onClose}>✕</button>
        </div>

        <div className="jardin-modal-body">
          <div className="jardin-form-row">
            <label>Nom</label>
            <input value={form.nom} onChange={e => set('nom', e.target.value)} />
          </div>
          <div className="jardin-form-row">
            <label>Emoji</label>
            <input value={form.avatar_emoji} onChange={e => set('avatar_emoji', e.target.value)} style={{ width: 64 }} />
          </div>
          <div className="jardin-form-row">
            <label>Provider</label>
            <select value={form.forge_provider} onChange={e => set('forge_provider', e.target.value)}>
              {PROVIDERS.map(p => <option key={p} value={p}>{p}</option>)}
            </select>
          </div>
          <div className="jardin-form-row">
            <label>Modèle</label>
            <input value={form.forge_model} onChange={e => set('forge_model', e.target.value)} placeholder="ex: llama3.2, anthropic/claude-sonnet-4-6" />
          </div>
          <div className="jardin-form-row">
            <label>URL Forge</label>
            <input value={form.forge_url} onChange={e => set('forge_url', e.target.value)} placeholder="http://localhost:3001" />
          </div>
          <div className="jardin-form-row">
            <label>Mot d'activation</label>
            <input value={form.wake_word} onChange={e => set('wake_word', e.target.value)} placeholder="ex: jarvis, aria…" />
          </div>
          <div className="jardin-form-row col">
            <label>Prompt système</label>
            <textarea value={form.system_prompt} onChange={e => set('system_prompt', e.target.value)} rows={5} />
          </div>
        </div>

        <div className="jardin-modal-footer">
          <button className="jardin-btn-secondary" onClick={onClose}>Annuler</button>
          <button className="jardin-btn-primary" onClick={() => onSave(form)}>Sauvegarder</button>
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

function formatDate(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' })
}

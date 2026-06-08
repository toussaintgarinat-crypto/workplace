import { useState, useEffect } from 'react'
import { api } from '../../services/api'

export default function MCPView() {
  const [servers, setServers]   = useState([])
  const [form, setForm]         = useState({ nom: '', url: '', authType: 'none', authToken: '' })
  const [tools, setTools]       = useState({})
  const [loading, setLoading]   = useState(false)
  const [error, setError]       = useState('')

  useEffect(() => {
    api.get('/api/mcp/servers').then(setServers).catch(() => {})
  }, [])

  async function addServer(e) {
    e.preventDefault()
    setError('')
    try {
      const server = await api.post('/api/mcp/servers', form)
      setServers(prev => [...prev, server])
      setForm({ nom: '', url: '', authType: 'none', authToken: '' })
    } catch (err) {
      setError(err.data?.error || 'Erreur création')
    }
  }

  async function deleteServer(id) {
    await api.delete(`/api/mcp/servers/${id}`)
    setServers(prev => prev.filter(s => s.id !== id))
    setTools(prev => { const n = { ...prev }; delete n[id]; return n })
  }

  async function toggleServer(id, actif) {
    const updated = await api.patch(`/api/mcp/servers/${id}`, { actif })
    setServers(prev => prev.map(s => s.id === id ? updated : s))
  }

  async function listTools(id) {
    setLoading(true)
    try {
      const list = await api.get(`/api/mcp/servers/${id}/tools`)
      setTools(prev => ({ ...prev, [id]: list }))
    } catch (err) {
      setError('Impossible de contacter ce serveur MCP')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ padding: '2rem', maxWidth: 800, margin: '0 auto' }}>
      <h1 style={{ color: '#e2e8f0', marginBottom: '1.5rem' }}>
        🔌 Serveurs MCP
      </h1>
      <p style={{ color: '#94a3b8', marginBottom: '2rem' }}>
        Model Context Protocol — connectez des outils externes à Forge.
        Les outils découverts sont automatiquement disponibles en mode ReAct.
      </p>

      {/* Form */}
      <form onSubmit={addServer} style={{ background: '#1e1e2e', borderRadius: 12, padding: '1.5rem', marginBottom: '2rem', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
        <h3 style={{ color: '#c4b5fd', margin: 0 }}>Ajouter un serveur</h3>
        {error && <div style={{ color: '#f87171', fontSize: '0.875rem' }}>{error}</div>}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: '0.75rem' }}>
          <input
            placeholder="Nom"
            value={form.nom}
            onChange={e => setForm(f => ({ ...f, nom: e.target.value }))}
            required
            style={inputStyle}
          />
          <input
            placeholder="URL (ex: http://localhost:5000)"
            value={form.url}
            onChange={e => setForm(f => ({ ...f, url: e.target.value }))}
            required
            style={inputStyle}
          />
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: '0.75rem' }}>
          <select
            value={form.authType}
            onChange={e => setForm(f => ({ ...f, authType: e.target.value }))}
            style={inputStyle}
          >
            <option value="none">Pas d'auth</option>
            <option value="bearer">Bearer Token</option>
            <option value="basic">Basic Auth</option>
          </select>
          {form.authType !== 'none' && (
            <input
              placeholder="Token / credentials"
              value={form.authToken}
              onChange={e => setForm(f => ({ ...f, authToken: e.target.value }))}
              type="password"
              style={inputStyle}
            />
          )}
        </div>
        <button type="submit" style={btnStyle('#6366f1')}>
          + Ajouter
        </button>
      </form>

      {/* Server list */}
      {servers.length === 0 ? (
        <div style={{ color: '#64748b', textAlign: 'center', padding: '3rem' }}>
          Aucun serveur MCP configuré.
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          {servers.map(server => (
            <div key={server.id} style={{ background: '#1e1e2e', borderRadius: 12, padding: '1.25rem', border: `1px solid ${server.actif ? '#6366f1' : '#2d2d44'}` }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.5rem' }}>
                <span style={{ fontSize: '1.25rem' }}>{server.actif ? '🟢' : '⚫'}</span>
                <span style={{ color: '#e2e8f0', fontWeight: 600 }}>{server.nom}</span>
                <span style={{ color: '#64748b', fontSize: '0.8rem', fontFamily: 'monospace' }}>{server.url}</span>
                <div style={{ marginLeft: 'auto', display: 'flex', gap: '0.5rem' }}>
                  <button onClick={() => listTools(server.id)} style={btnStyle('#0ea5e9', true)} disabled={loading}>
                    {loading ? '⏳' : '🔍 Outils'}
                  </button>
                  <button onClick={() => toggleServer(server.id, !server.actif)} style={btnStyle('#64748b', true)}>
                    {server.actif ? 'Désactiver' : 'Activer'}
                  </button>
                  <button onClick={() => deleteServer(server.id)} style={btnStyle('#ef4444', true)}>
                    🗑
                  </button>
                </div>
              </div>

              {tools[server.id] && (
                <div style={{ marginTop: '0.75rem', padding: '0.75rem', background: '#0f0f1a', borderRadius: 8 }}>
                  <div style={{ color: '#94a3b8', fontSize: '0.75rem', marginBottom: '0.5rem' }}>
                    {tools[server.id].length} outil(s) disponible(s)
                  </div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
                    {tools[server.id].map(t => (
                      <span key={t.name} style={{ background: '#1e1e2e', color: '#c4b5fd', padding: '0.25rem 0.75rem', borderRadius: 999, fontSize: '0.8rem', border: '1px solid #6366f1' }}>
                        🔧 {t.name}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

const inputStyle = {
  background: '#0f0f1a', border: '1px solid #2d2d44', borderRadius: 8,
  padding: '0.6rem 0.875rem', color: '#e2e8f0', fontSize: '0.9rem', outline: 'none', width: '100%',
}

function btnStyle(color, small = false) {
  return {
    background: color, color: '#fff', border: 'none', borderRadius: 8,
    padding: small ? '0.4rem 0.75rem' : '0.6rem 1.5rem',
    cursor: 'pointer', fontSize: small ? '0.8rem' : '0.9rem', fontWeight: 600,
  }
}

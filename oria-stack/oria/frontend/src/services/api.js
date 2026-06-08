import keycloak from '../keycloak'

const BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'

function notifyError(message) {
  window.dispatchEvent(new CustomEvent('oria:error', { detail: message }))
}

function _authHeaders(extra = {}) {
  return {
    'Content-Type': 'application/json',
    ...(keycloak.token ? { Authorization: `Bearer ${keycloak.token}` } : {}),
    ...extra,
  }
}

async function _refreshToken() {
  if (!keycloak.authenticated) return
  try { await keycloak.updateToken(30) } catch { keycloak.logout?.() }
}

// S99 — Versioning API. On prefixe /v1/api/* (canonique). Si on retire /v1/,
// l'alias legacy renvoie des headers Deprecation/Sunset (date sunset 2026-11-23).
async function request(path, options = {}) {
  await _refreshToken()
  try {
    const r = await fetch(`${BASE}/v1/api${path}`, {
      credentials: 'include',
      ...options,
      headers: _authHeaders(options.headers),
    })
    if (!r.ok) {
      let detail = `Erreur ${r.status}`
      try { const body = await r.json(); detail = body.detail || detail } catch {}
      notifyError(detail)
      return null
    }
    if (r.status === 204) return null
    return await r.json()
  } catch (e) {
    if (e.name === 'TypeError') {
      notifyError('Serveur inaccessible — vérifie ta connexion')
    } else {
      notifyError(e.message || 'Erreur inattendue')
    }
    return null
  }
}

export const api = {
  get:   (path)        => request(path),
  post:  (path, body)  => request(path, { method: 'POST',  body: JSON.stringify(body) }),
  patch: (path, body)  => request(path, { method: 'PATCH', body: JSON.stringify(body) }),
  del:   (path)        => request(path, { method: 'DELETE' }),
  upload: async (path, formData) => {
    await _refreshToken()
    const headers = keycloak.token ? { Authorization: `Bearer ${keycloak.token}` } : {}
    return fetch(`${BASE}/v1/api${path}`, {
      method: 'POST',
      credentials: 'include',
      headers,
      body: formData,
    })
      .then(async r => {
        if (!r.ok) { const b = await r.json().catch(() => ({})); notifyError(b.detail || `Erreur ${r.status}`); return null }
        return r.json()
      })
      .catch(() => { notifyError('Erreur upload'); return null })
  },
}

// Helper pour les fetch directs dans les composants (streaming, uploads custom)
export function authHeaders(extra = {}) {
  return {
    ...(keycloak.token ? { Authorization: `Bearer ${keycloak.token}` } : {}),
    ...extra,
  }
}

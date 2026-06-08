import keycloak from '../keycloak'

const BASE = import.meta.env.VITE_API_URL || ''

// Org active stockée en localStorage
export const activeOrg = {
  get:   ()    => localStorage.getItem('forge_org_id'),
  set:   (id)  => localStorage.setItem('forge_org_id', id),
  clear: ()    => localStorage.removeItem('forge_org_id'),
}

// Shim de compatibilité — les vues qui importent { token } continuent de fonctionner.
// Le token est maintenant géré par keycloak-js (plus de localStorage).
export const token = {
  get:   () => keycloak.token || null,
  set:   () => {},   // no-op — keycloak-js gère les tokens
  clear: () => {},   // no-op — utiliser keycloak.logout()
}

// S99 — API versioning. Tous les endpoints sont disponibles sous /v1/api/* ;
// le legacy /api/* fonctionne encore mais renvoie Deprecation/Sunset. On
// reecrit ici les paths /api/* → /v1/api/* pour profiter du canonique sans
// devoir toucher les ~150 endpoints definis plus bas.
function _versionPath(path) {
  if (path.startsWith('/api/')) return `/v1${path}`
  return path
}

async function request(path, options = {}) {
  // Rafraîchit le token si expiré dans moins de 30s
  await keycloak.updateToken(30).catch(() => {})

  const t = keycloak.token
  if (!t) throw new Error('Not authenticated')
  const orgId = activeOrg.get()
  const res = await fetch(`${BASE}${_versionPath(path)}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(t     ? { Authorization: `Bearer ${t}` } : {}),
      ...(orgId ? { 'X-Org-ID': orgId }           : {}),
      ...options.headers,
    },
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: res.statusText }))
    throw Object.assign(new Error(err.error || err.message || 'Request failed'), { status: res.status, data: err })
  }
  return res.json()
}

// ── API générique (utilisé par les nouvelles vues) ───────────
export const api = {
  get:    (path)        => request(path),
  post:   (path, data)  => request(path, { method: 'POST',   body: JSON.stringify(data) }),
  put:    (path, data)  => request(path, { method: 'PUT',    body: JSON.stringify(data) }),
  patch:  (path, data)  => request(path, { method: 'PATCH',  body: JSON.stringify(data) }),
  delete: (path)        => request(path, { method: 'DELETE' }),
}

// ── Auth ─────────────────────────────────────────────────────
export const auth = {
  updateProfile: (data) => request('/api/auth/me',         { method: 'PATCH',  body: JSON.stringify(data) }),
  export:        ()     => request('/api/auth/me/export'),
  delete:        ()     => request('/api/auth/me',         { method: 'DELETE' }),
}

// ── Sessions ─────────────────────────────────────────────────
export const sessions = {
  list:          (params = {}) => {
    const qs = new URLSearchParams(params).toString()
    return request(`/api/sessions${qs ? `?${qs}` : ''}`)
  },
  listByPole:    (poleId)    => request(`/api/sessions?poleId=${poleId}`),
  listByVenture: (ventureId) => request(`/api/sessions?ventureId=${ventureId}`),
  create:  (data)  => request('/api/sessions',       { method: 'POST',   body: JSON.stringify(data) }),
  rename:  (id, n) => request(`/api/sessions/${id}`, { method: 'PATCH',  body: JSON.stringify({ name: n }) }),
  delete:  (id)    => request(`/api/sessions/${id}`, { method: 'DELETE' }),
}

// ── Poles ─────────────────────────────────────────────────────
export const polesApi = {
  list:   ()      => request('/api/poles'),
  get:    (id)    => request(`/api/poles/${id}`),
  create: (data)  => request('/api/poles',       { method: 'POST',   body: JSON.stringify(data) }),
  update: (id, d) => request(`/api/poles/${id}`, { method: 'PATCH',  body: JSON.stringify(d) }),
  delete: (id)    => request(`/api/poles/${id}`, { method: 'DELETE' }),
}

// ── Command Bridge ───────────────────────────────────────────
export const commandBridge = {
  overview:    ()     => request('/api/command-bridge/overview'),
  decisions:   (s)    => request(`/api/command-bridge/decisions${s ? `?statut=${s}` : ''}`),
  create:      (data) => request('/api/command-bridge/decisions', { method: 'POST', body: JSON.stringify(data) }),
  approve:     (id)   => request(`/api/command-bridge/decisions/${id}/approuver`, { method: 'POST' }),
  reject:      (id)   => request(`/api/command-bridge/decisions/${id}/rejeter`,   { method: 'POST' }),
  togglePause: (id)   => request(`/api/command-bridge/poles/${id}/toggle-pause`,  { method: 'POST' }),
  blackboard:  (n)    => request(`/api/command-bridge/blackboard${n ? `?niveau=${n}` : ''}`),
}

// ── Ventures ─────────────────────────────────────────────────
export const venturesApi = {
  list:          ()         => request('/api/ventures'),
  get:           (id)       => request(`/api/ventures/${id}`),
  create:        (data)     => request('/api/ventures',                       { method: 'POST',   body: JSON.stringify(data) }),
  update:        (id, d)    => request(`/api/ventures/${id}`,                 { method: 'PATCH',  body: JSON.stringify(d) }),
  deleteRequest: (id)       => request(`/api/ventures/${id}/delete-request`,  { method: 'POST' }),
  delete:        (id, code) => request(`/api/ventures/${id}`,                 { method: 'DELETE', body: JSON.stringify({ code }) }),
  poles:         (id)       => request(`/api/ventures/${id}/poles`),
  createPole:    (id, data) => request(`/api/ventures/${id}/poles`,           { method: 'POST',   body: JSON.stringify(data) }),
}

// ── Organisations ────────────────────────────────────────────
export const orgsApi = {
  list:          ()             => request('/api/orgs'),
  create:        (d)            => request('/api/orgs', { method: 'POST', body: JSON.stringify(d) }),
  get:           (id)           => request(`/api/orgs/${id}`),
  update:        (id, d)        => request(`/api/orgs/${id}`, { method: 'PATCH', body: JSON.stringify(d) }),
  delete:        (id)           => request(`/api/orgs/${id}`, { method: 'DELETE' }),
  invite:        (id, d)        => request(`/api/orgs/${id}/members`, { method: 'POST', body: JSON.stringify(d) }),
  removeMember:  (id, userId)   => request(`/api/orgs/${id}/members/${userId}`, { method: 'DELETE' }),
}

// ── API Keys ─────────────────────────────────────────────────
export const apiKeysApi = {
  list:   ()             => request('/api/settings/api-keys'),
  set:    (provider, key) => request(`/api/settings/api-keys/${provider}`, { method: 'PUT', body: JSON.stringify({ key }) }),
  remove: (provider)     => request(`/api/settings/api-keys/${provider}`, { method: 'DELETE' }),
}

// ── Provider Models (dynamic) ────────────────────────────────
export const providerModelsApi = {
  list: (provider) => request(`/api/llm-config/${provider}/models`),
}

// ── Ollama Models ─────────────────────────────────────────────
export const ollamaModelsApi = {
  list: () => request('/api/llm-config/ollama/models'),
  remove: (name) => request(`/api/llm-config/ollama/models?name=${encodeURIComponent(name)}`, { method: 'DELETE' }),
  async pull(name, onProgress) {
    await keycloak.updateToken(30).catch(() => {})
    const t = keycloak.token
    const orgId = activeOrg.get()
    const res = await fetch(`${BASE}/v1/api/llm-config/ollama/pull`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(t     ? { Authorization: `Bearer ${t}` } : {}),
        ...(orgId ? { 'X-Org-ID': orgId }           : {}),
      },
      body: JSON.stringify({ name }),
    })
    if (!res.ok) throw new Error('Pull failed')
    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop()
      for (const line of lines) {
        if (!line.trim()) continue
        try { onProgress(JSON.parse(line)) } catch {}
      }
    }
    if (buffer.trim()) {
      try { onProgress(JSON.parse(buffer)) } catch {}
    }
  },
}

// ── LLM Config ───────────────────────────────────────────────
export const llmConfigApi = {
  providers:       ()              => request('/api/llm-config/providers'),
  get:             (id)            => request(`/api/llm-config/${id}`),
  save:            (id, d)         => request(`/api/llm-config/${id}`, { method: 'PUT', body: JSON.stringify(d) }),
  getPreset:       (scopeType, scopeId) => request(`/api/llm-config/preset?scopeType=${scopeType}&scopeId=${scopeId}`),
  upsertPreset:    (d)             => request('/api/llm-config/preset', { method: 'PUT', body: JSON.stringify(d) }),
  deletePreset:    (scopeType, scopeId) => request(`/api/llm-config/preset?scopeType=${scopeType}&scopeId=${scopeId}`, { method: 'DELETE' }),
  venturePresets:  (ventureId)     => request(`/api/llm-config/venture/${ventureId}`),
  resolve:         (ctx)           => request(`/api/llm-config/resolve?${new URLSearchParams(ctx)}`),
  getGlobal:       ()              => request('/api/llm-config/global'),
  setGlobal:       (body)          => request('/api/llm-config/global', { method: 'PUT', body: JSON.stringify(body) }),
}

// ── MemPalace ────────────────────────────────────────────────
const mpBase = () => localStorage.getItem('mp_url') || 'http://localhost:8100'

async function mpRequest(path, options = {}) {
  const t = localStorage.getItem('mp_token')
  const res = await fetch(`${mpBase()}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(t ? { Authorization: `Bearer ${t}` } : {}),
      ...options.headers,
    },
  })
  if (!res.ok) return null
  return res.json()
}

export const mempalaceApi = {
  login: (username, password) =>
    fetch(`${mpBase()}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ username, password }),
    }).then(r => r.json()).catch(() => null),
  status:      ()                    => mpRequest('/api/status'),
  taxonomy:    ()                    => mpRequest('/api/taxonomy'),
  drawers:     (wing, limit = 50)    => mpRequest(`/api/wings/${encodeURIComponent(wing)}/drawers?limit=${limit}`),
  search:      (q, wing, n = 10)     => mpRequest('/api/search', { method: 'POST', body: JSON.stringify({ query: q, wing, n_results: n }) }),
  addDrawer:   (content, wing, room = 'general', metadata = {}) =>
    mpRequest('/api/drawers', { method: 'POST', body: JSON.stringify({ content, wing, room, metadata }) }),
  deleteDrawer: id => mpRequest(`/api/drawers/${id}`, { method: 'DELETE' }),
}

// ── NetBird ──────────────────────────────────────────────────
export const netbird = {
  createSetupKey: (groups = []) => request('/api/netbird/setup-keys', { method: 'POST', body: JSON.stringify({ groups }) }),
  setupKeys:  ()      => request('/api/netbird/setup-keys'),
  peers:    ()      => request('/api/netbird/peers'),
  groups:   ()      => request('/api/netbird/groups'),
  policies: ()      => request('/api/netbird/policies'),
  routes:   ()      => request('/api/netbird/routes'),
  dns:      ()      => request('/api/netbird/dns'),
  updateGroup:  (id, d) => request(`/api/netbird/groups/${id}`,   { method: 'PUT',    body: JSON.stringify(d) }),
  createGroup:  (d)     => request('/api/netbird/groups',          { method: 'POST',   body: JSON.stringify(d) }),
  deleteGroup:  (id)    => request(`/api/netbird/groups/${id}`,   { method: 'DELETE' }),
  updatePolicy: (id, d) => request(`/api/netbird/policies/${id}`, { method: 'PUT',    body: JSON.stringify(d) }),
  createPolicy: (d)     => request('/api/netbird/policies',        { method: 'POST',   body: JSON.stringify(d) }),
  deletePolicy: (id)    => request(`/api/netbird/policies/${id}`, { method: 'DELETE' }),
}

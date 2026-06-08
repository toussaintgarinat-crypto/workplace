import type {
  NodeResponse,
  NodeCreate,
  NodeUpdate,
  SearchResult,
  PalaceTree,
  GardienConfig,
  GardienSuggestion,
  GardienLogEntry,
  GraphNode,
  GraphResponse,
  Space,
  Template,
  Collection,
} from '../types/api'
import { useAppStore } from '../stores/appStore'

const BASE = '/api/v1'

let authToken: string | null = null

export function setToken(token: string | null) {
  authToken = token
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  }
  if (authToken) {
    headers['Authorization'] = `Bearer ${authToken}`
  }
  const res = await fetch(`${BASE}${path}`, { ...options, headers })
  if (!res.ok) {
    const body = await res.text()
    throw new Error(`API ${res.status}: ${body}`)
  }
  return res.json()
}

export function getSpaceId(): string {
  return useAppStore.getState().activeSpaceId || localStorage.getItem('active_space_id') || ''
}

// Auth
export async function register(email: string, password: string, displayName?: string) {
  const res = await fetch(`${BASE}/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password, display_name: displayName || '' }),
  })
  if (!res.ok) {
    const body = await res.text()
    throw new Error(body)
  }
  return res.json()
}

export async function login(email: string, password: string) {
  const res = await fetch(`${BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
  if (!res.ok) throw new Error('Login failed')
  const data = await res.json()
  setToken(data.access_token)
  localStorage.setItem('auth_token', data.access_token)
  return data
}

export function loadToken() {
  const t = localStorage.getItem('auth_token')
  if (t) setToken(t)
}

export async function getProfile(): Promise<{ id: string; email: string; display_name: string | null; created_at: string }> {
  return request('/auth/me')
}

export async function updateProfile(data: { display_name?: string; email?: string }): Promise<{ id: string; email: string; display_name: string | null; created_at: string }> {
  return request('/auth/me', { method: 'PUT', body: JSON.stringify(data) })
}

export async function changePassword(currentPassword: string, newPassword: string): Promise<{ detail: string }> {
  return request('/auth/me/password', {
    method: 'PUT',
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  })
}

export async function deleteAccount(): Promise<{ detail: string }> {
  const res = await fetch(`${BASE}/auth/me`, {
    method: 'DELETE',
    headers: authToken ? { 'Authorization': `Bearer ${authToken}` } : {},
  })
  if (!res.ok) throw new Error('Failed to delete account')
  localStorage.removeItem('auth_token')
  setToken(null)
  return res.json()
}

export async function getSpace(spaceId: string): Promise<Space & { role: string }> {
  return request(`/spaces/${spaceId}`)
}

export async function updateSpace(spaceId: string, data: { name: string; description?: string }): Promise<Space> {
  return request(`/spaces/${spaceId}`, { method: 'PUT', body: JSON.stringify(data) })
}

export async function deleteSpace(spaceId: string): Promise<{ detail: string }> {
  return request(`/spaces/${spaceId}`, { method: 'DELETE' })
}

export async function getMembers(spaceId: string): Promise<{ id: string; email: string; display_name: string | null; role: string }[]> {
  return request(`/spaces/${spaceId}/members`)
}

// Spaces
export async function getSpaces(): Promise<Space[]> {
  return request('/spaces')
}

export async function createSpace(name: string, description?: string): Promise<Space> {
  return request('/spaces', { method: 'POST', body: JSON.stringify({ name, description }) })
}

// Nodes
export async function getNodes(params?: {
  type?: string
  stage?: string
  tier?: string
  limit?: number
  offset?: number
}): Promise<NodeResponse[]> {
  const q = new URLSearchParams()
  if (params?.type) q.set('type', params.type)
  if (params?.stage) q.set('stage', params.stage)
  if (params?.tier) q.set('tier', params.tier)
  if (params?.limit) q.set('limit', String(params.limit))
  if (params?.offset) q.set('offset', String(params.offset))
  const sid = getSpaceId()
  return request(`/spaces/${sid}/nodes?${q}`)
}

export async function getNode(id: string): Promise<NodeResponse> {
  const sid = getSpaceId()
  return request(`/spaces/${sid}/nodes/${id}`)
}

export async function createNode(data: NodeCreate): Promise<NodeResponse> {
  const sid = getSpaceId()
  return request(`/spaces/${sid}/nodes`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
}

export async function updateNode(id: string, data: NodeUpdate): Promise<NodeResponse> {
  const sid = getSpaceId()
  return request(`/spaces/${sid}/nodes/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
}

export async function deleteNode(id: string): Promise<void> {
  const sid = getSpaceId()
  await request(`/spaces/${sid}/nodes/${id}`, { method: 'DELETE' })
}

export async function touchNode(id: string): Promise<NodeResponse> {
  const sid = getSpaceId()
  return request(`/spaces/${sid}/nodes/${id}/touch`, { method: 'POST' })
}

export async function updateNodeStage(id: string, stage: string, reason?: string): Promise<NodeResponse> {
  const sid = getSpaceId()
  return request(`/spaces/${sid}/nodes/${id}/stage`, {
    method: 'PATCH',
    body: JSON.stringify({ stage, reason }),
  })
}

// Search
export async function search(query: string, filters?: {
  type?: string
  stage?: string
  limit?: number
}): Promise<SearchResult[]> {
  const q = new URLSearchParams({ q: query })
  if (filters?.type) q.set('type', filters.type)
  if (filters?.stage) q.set('stage', filters.stage)
  if (filters?.limit) q.set('limit', String(filters.limit))
  const sid = getSpaceId()
  return request(`/spaces/${sid}/search?${q}`)
}

// Palace
export async function getPalace(): Promise<PalaceTree> {
  const sid = getSpaceId()
  return request(`/spaces/${sid}/palace`)
}

export async function createWing(name: string) {
  const sid = getSpaceId()
  return request(`/spaces/${sid}/palace/wing`, {
    method: 'POST',
    body: JSON.stringify({ name }),
  })
}

export async function createRoom(wing: string, name: string) {
  const sid = getSpaceId()
  return request(`/spaces/${sid}/palace/room`, {
    method: 'POST',
    body: JSON.stringify({ wing, name }),
  })
}

export async function createDrawer(wing: string, room: string, name: string) {
  const sid = getSpaceId()
  return request(`/spaces/${sid}/palace/drawer`, {
    method: 'POST',
    body: JSON.stringify({ wing, room, name }),
  })
}

export async function moveNode(id: string, wing: string, room: string, drawer?: string) {
  const sid = getSpaceId()
  return request(`/spaces/${sid}/nodes/${id}/location`, {
    method: 'PUT',
    body: JSON.stringify({ wing, room, drawer }),
  })
}

// Gardien
export async function getGardienConfig(): Promise<GardienConfig> {
  const sid = getSpaceId()
  return request(`/spaces/${sid}/gardien/config`)
}

export async function updateGardienConfig(config: GardienConfig): Promise<GardienConfig> {
  const sid = getSpaceId()
  return request(`/spaces/${sid}/gardien/config`, {
    method: 'PUT',
    body: JSON.stringify(config),
  })
}

export async function runGardien(): Promise<void> {
  const sid = getSpaceId()
  await request(`/spaces/${sid}/gardien/run`, { method: 'POST' })
}

export async function getGardienSuggestions(): Promise<GardienSuggestion[]> {
  const sid = getSpaceId()
  return request(`/spaces/${sid}/gardien/suggestions`)
}

export async function acceptSuggestion(id: string): Promise<void> {
  const sid = getSpaceId()
  await request(`/spaces/${sid}/gardien/suggestions/${id}/accept`, { method: 'POST' })
}

export async function rejectSuggestion(id: string): Promise<void> {
  const sid = getSpaceId()
  await request(`/spaces/${sid}/gardien/suggestions/${id}/reject`, { method: 'POST' })
}

export async function getGardienLog(): Promise<GardienLogEntry[]> {
  const sid = getSpaceId()
  return request(`/spaces/${sid}/gardien/log`)
}

// Graph
export async function getGraph(rootId?: string, depth = 2): Promise<GraphResponse> {
  const sid = getSpaceId()
  const q = new URLSearchParams()
  if (rootId) q.set('root', rootId)
  q.set('depth', String(depth))
  return request(`/spaces/${sid}/graph?${q}`)
}

export async function createEdge(sourceId: string, targetId: string, type = 'related') {
  const sid = getSpaceId()
  return request(`/spaces/${sid}/graph/edges`, {
    method: 'POST',
    body: JSON.stringify({ source_id: sourceId, target_id: targetId, type }),
  })
}

export async function deleteEdge(edgeId: string) {
  const sid = getSpaceId()
  await request(`/spaces/${sid}/graph/edges/${edgeId}`, { method: 'DELETE' })
}

export async function findPath(sourceId: string, targetId: string): Promise<GraphNode[]> {
  const sid = getSpaceId()
  return request(`/spaces/${sid}/graph/path?source=${sourceId}&target=${targetId}`)
}

export async function getAgingNodes(): Promise<{ id: string; title: string; storage_tier: string; last_accessed: string | null }[]> {
  const sid = getSpaceId()
  return request(`/spaces/${sid}/nodes/aging`)
}

export async function runTierDemotion(): Promise<{ detail: string }> {
  const sid = getSpaceId()
  return request(`/spaces/${sid}/maintenance/tiers`, { method: 'POST' })
}

// Collections (RAG contexts)
export async function getCollections(): Promise<Collection[]> {
  const sid = getSpaceId()
  return request(`/spaces/${sid}/collections`)
}

export async function createCollection(data: { name: string; description?: string; filter_criteria?: Record<string, string> | null; is_dynamic?: boolean }): Promise<Collection> {
  const sid = getSpaceId()
  return request(`/spaces/${sid}/collections`, { method: 'POST', body: JSON.stringify(data) })
}

export async function deleteCollection(id: string): Promise<void> {
  const sid = getSpaceId()
  await request(`/spaces/${sid}/collections/${id}`, { method: 'DELETE' })
}

export async function addNodeToCollection(collectionId: string, nodeId: string): Promise<void> {
  const sid = getSpaceId()
  await request(`/spaces/${sid}/collections/${collectionId}/nodes/${nodeId}`, { method: 'POST' })
}

export async function removeNodeFromCollection(collectionId: string, nodeId: string): Promise<void> {
  const sid = getSpaceId()
  await request(`/spaces/${sid}/collections/${collectionId}/nodes/${nodeId}`, { method: 'DELETE' })
}

export async function getCollectionNodes(collectionId: string): Promise<{ id: string; title: string; type: string }[]> {
  const sid = getSpaceId()
  return request(`/spaces/${sid}/collections/${collectionId}/nodes`)
}

export async function searchCollection(collectionId: string, query: string, limit?: number): Promise<SearchResult[]> {
  const sid = getSpaceId()
  const q = new URLSearchParams({ q: query })
  if (limit) q.set('limit', String(limit))
  return request(`/spaces/${sid}/collections/${collectionId}/search?${q}`)
}

// Templates
export async function getTemplates(nodeType?: string): Promise<Template[]> {
  const sid = getSpaceId()
  const q = nodeType ? `?node_type=${nodeType}` : ''
  return request(`/spaces/${sid}/templates${q}`)
}

export async function updateNodeTier(id: string, tier: string): Promise<{ id: string; storage_tier: string }> {
  const sid = getSpaceId()
  return request(`/spaces/${sid}/nodes/${id}/tier`, {
    method: 'PATCH',
    body: JSON.stringify({ tier }),
  })
}

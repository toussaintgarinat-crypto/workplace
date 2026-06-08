import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Layers, Plus, Trash2, Search, BrainCircuit } from 'lucide-react'
import * as api from '../services/api'
import type { Collection } from '../types/api'

export default function CollectionsPage() {
  const [collections, setCollections] = useState<Collection[]>([])
  const [loading, setLoading] = useState(true)
  const [showNewForm, setShowNewForm] = useState(false)
  const [newName, setNewName] = useState('')
  const [newDesc, setNewDesc] = useState('')
  const [newFilterType, setNewFilterType] = useState('')
  const [selectedCol, setSelectedCol] = useState<Collection | null>(null)
  const [colNodes, setColNodes] = useState<{ id: string; title: string; type: string }[]>([])
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<{ id: string; title: string; score: number }[]>([])

  useEffect(() => {
    loadCollections()
  }, [])

  async function loadCollections() {
    try {
      const cols = await api.getCollections()
      setCollections(cols)
    } catch {
      setCollections([])
    } finally {
      setLoading(false)
    }
  }

  async function handleCreate() {
    if (!newName.trim()) return
    const criteria = newFilterType ? { type: newFilterType } : null
    await api.createCollection({ name: newName.trim(), description: newDesc.trim(), filter_criteria: criteria, is_dynamic: !!criteria })
    setNewName('')
    setNewDesc('')
    setNewFilterType('')
    setShowNewForm(false)
    await loadCollections()
  }

  async function handleDelete(id: string) {
    if (!confirm('Delete this collection?')) return
    await api.deleteCollection(id)
    if (selectedCol?.id === id) setSelectedCol(null)
    await loadCollections()
  }

  async function selectCollection(col: Collection) {
    setSelectedCol(col)
    setSearchResults([])
    setSearchQuery('')
    try {
      const nodes = await api.getCollectionNodes(col.id)
      setColNodes(nodes)
    } catch {
      setColNodes([])
    }
  }

  async function handleSearch() {
    if (!selectedCol || !searchQuery.trim()) return
    const results = await api.searchCollection(selectedCol.id, searchQuery)
    setSearchResults(results.map((r) => ({ id: r.id, title: r.title, score: r.score })))
  }

  const nodeTypeLabels: Record<string, string> = {
    input: 'Input', projet: 'Project', casquette: 'Role', ressource: 'Resource', archive: 'Archive',
  }

  const dynamicLabel = (c: Collection) => {
    if (!c.filter_criteria) return null
    const t = c.filter_criteria.type
    return t ? nodeTypeLabels[t] || t : null
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-semibold text-text-heading">Collections</h2>
          <p className="text-sm text-text mt-1">Isolated RAG contexts — one vector search scope per project, role, or resource type</p>
        </div>
        <button
          onClick={() => setShowNewForm(true)}
          className="flex items-center gap-2 px-3 py-1.5 bg-memory-600 hover:bg-memory-700 text-white text-sm rounded-lg transition-colors"
        >
          <Plus size={16} /> Collection
        </button>
      </div>

      {showNewForm && (
        <div className="bg-surface-2 border border-border rounded-xl p-4 space-y-3">
          <input
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="Collection name (e.g. Projet Voice Search)"
            className="w-full px-3 py-2 bg-surface border border-border rounded-lg text-sm text-text-heading focus:outline-none focus:border-memory-500 placeholder:text-text/40"
            autoFocus
          />
          <input
            value={newDesc}
            onChange={(e) => setNewDesc(e.target.value)}
            placeholder="Description (optional)"
            className="w-full px-3 py-2 bg-surface border border-border rounded-lg text-sm text-text-heading focus:outline-none focus:border-memory-500 placeholder:text-text/40"
          />
          <div className="flex items-center gap-2">
            <span className="text-xs text-text">Auto-filter by type:</span>
            <select
              value={newFilterType}
              onChange={(e) => setNewFilterType(e.target.value)}
              className="flex-1 px-2 py-1 bg-surface border border-border rounded text-sm text-text-heading focus:outline-none focus:border-memory-500"
            >
              <option value="">Manual (add nodes manually)</option>
              {Object.entries(nodeTypeLabels).map(([k, v]) => (
                <option key={k} value={k}>{v} (auto)</option>
              ))}
            </select>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={handleCreate} className="px-4 py-1.5 bg-memory-600 hover:bg-memory-700 text-white text-sm rounded-lg transition-colors">
              Create
            </button>
            <button onClick={() => setShowNewForm(false)} className="px-3 py-1.5 text-xs text-text hover:text-text-heading transition-colors">
              Cancel
            </button>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-1 space-y-2">
          {loading ? (
            <div className="text-text text-sm">Loading...</div>
          ) : collections.length === 0 ? (
            <div className="bg-surface-2 border border-border rounded-xl p-6 text-center">
              <Layers size={28} className="mx-auto text-text mb-2" />
              <p className="text-text-heading font-medium text-sm">No collections</p>
              <p className="text-xs text-text mt-1">Create a collection to isolate RAG contexts</p>
            </div>
          ) : (
            collections.map((c) => (
              <button
                key={c.id}
                onClick={() => selectCollection(c)}
                className={`w-full text-left bg-surface-2 border rounded-xl p-3 transition-colors hover:border-memory-500/30 ${
                  selectedCol?.id === c.id ? 'border-memory-500/50' : 'border-border'
                }`}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 min-w-0">
                    <BrainCircuit size={16} className="text-memory-400 shrink-0" />
                    <span className="text-sm text-text-heading font-medium truncate">{c.name}</span>
                  </div>
                  <button onClick={(e) => { e.stopPropagation(); handleDelete(c.id) }} className="p-1 text-text hover:text-red-400 transition-colors shrink-0">
                    <Trash2 size={12} />
                  </button>
                </div>
                <div className="flex items-center gap-2 mt-1.5">
                  <span className="text-xs text-text/50">{c.node_count} nodes</span>
                  {dynamicLabel(c) && (
                    <span className="text-xs px-1.5 py-0.5 rounded bg-memory-500/10 text-memory-400">{dynamicLabel(c)}</span>
                  )}
                  {c.is_dynamic && <span className="text-xs text-text/40">auto</span>}
                </div>
              </button>
            ))
          )}
        </div>

        <div className="lg:col-span-2 space-y-4">
          {!selectedCol ? (
            <div className="bg-surface-2 border border-border rounded-xl p-8 text-center">
              <Layers size={32} className="mx-auto text-text mb-3" />
              <p className="text-text-heading font-medium">Select a collection</p>
              <p className="text-sm text-text mt-1">Choose a collection on the left to browse its nodes and search within its RAG context</p>
            </div>
          ) : (
            <>
              <div className="bg-surface-2 border border-border rounded-xl p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="font-medium text-text-heading">{selectedCol.name}</h3>
                    {selectedCol.description && <p className="text-xs text-text mt-0.5">{selectedCol.description}</p>}
                  </div>
                  {dynamicLabel(selectedCol) && (
                    <span className="text-xs px-2 py-1 rounded bg-memory-500/10 text-memory-400">{dynamicLabel(selectedCol)} (auto)</span>
                  )}
                </div>

                <div className="flex items-center gap-2">
                  <input
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                    placeholder={`Search within "${selectedCol.name}"...`}
                    className="flex-1 px-3 py-2 bg-surface border border-border rounded-lg text-sm text-text-heading focus:outline-none focus:border-memory-500 placeholder:text-text/40"
                  />
                  <button onClick={handleSearch} className="p-2 bg-memory-600 hover:bg-memory-700 text-white rounded-lg transition-colors">
                    <Search size={16} />
                  </button>
                </div>
              </div>

              {searchResults.length > 0 ? (
                <div className="space-y-1.5">
                  <p className="text-xs text-text">RAG results in "{selectedCol.name}"</p>
                  {searchResults.map((r) => (
                    <Link
                      key={r.id}
                      to={`/memory/note/${r.id}`}
                      className="flex items-center justify-between bg-surface-2 border border-border rounded-lg px-4 py-2 hover:border-memory-500/30 transition-colors"
                    >
                      <span className="text-sm text-text-heading truncate">{r.title}</span>
                      <span className="text-xs text-memory-400 shrink-0 ml-2">{(r.score * 100).toFixed(0)}%</span>
                    </Link>
                  ))}
                </div>
              ) : (
                <div className="space-y-1.5">
                  <p className="text-xs text-text">{colNodes.length} nodes in collection</p>
                  {colNodes.map((n) => (
                    <div key={n.id} className="flex items-center justify-between bg-surface-2 border border-border rounded-lg px-4 py-2 group">
                      <Link to={`/memory/note/${n.id}`} className="text-sm text-text-heading truncate hover:text-memory-400 transition-colors">
                        {n.title}
                      </Link>
                      <span className="text-xs text-text/50 capitalize">{n.type}</span>
                    </div>
                  ))}
                  {colNodes.length === 0 && (
                    <div className="text-xs text-text/50 text-center py-4">No nodes yet. Add nodes from their edit page.</div>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
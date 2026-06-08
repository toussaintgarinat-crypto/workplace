import { useEffect, useState, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { TreePine, Plus, FolderOpen, ChevronRight, ChevronDown, GripVertical } from 'lucide-react'
import * as api from '../services/api'
import type { PalaceRoom, NodeResponse } from '../types/api'

export default function PalacePage() {
  const [tree, setTree] = useState<PalaceRoom[]>([])
  const [nodes, setNodes] = useState<NodeResponse[]>([])
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [showNewForm, setShowNewForm] = useState<'wing' | 'room' | null>(null)
  const [newName, setNewName] = useState('')
  const [selectedWing, setSelectedWing] = useState('')
  const [dragNodeId, setDragNodeId] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([loadPalace(), loadNodes()])
  }, [])

  async function loadPalace() {
    try {
      const p = await api.getPalace()
      setTree(p.wings)
    } catch {
      setTree([])
    } finally {
      setLoading(false)
    }
  }

  async function loadNodes() {
    try {
      const n = await api.getNodes({ limit: 50 })
      setNodes(n.filter((node) => !node.location))
    } catch {
      setNodes([])
    }
  }

  function toggleExpand(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  async function handleCreate() {
    if (!newName.trim()) return
    try {
      if (showNewForm === 'wing') {
        await api.createWing(newName.trim())
      } else if (showNewForm === 'room') {
        await api.createRoom(selectedWing, newName.trim())
      }
      setNewName('')
      setShowNewForm(null)
      await loadPalace()
    } catch {
      // ignore
    }
  }

  const handleDrop = useCallback(async (wing: string, room: string, drawer?: string) => {
    if (!dragNodeId) return
    try {
      await api.moveNode(dragNodeId, wing, room, drawer)
      setDragNodeId(null)
      await loadNodes()
    } catch {
      // ignore
    }
  }, [dragNodeId])

  function renderWing(wing: PalaceRoom) {
    const isOpen = expanded.has(wing.id)
    return (
      <div key={wing.id}>
        <button
          onClick={() => toggleExpand(wing.id)}
          className="flex items-center gap-2 w-full px-3 py-2 rounded-lg hover:bg-surface-3 transition-colors text-left"
        >
          {isOpen ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
          <FolderOpen size={18} className="text-memory-400" />
          <span className="font-medium text-text-heading text-sm">{wing.wing}</span>
          <span className="text-xs text-text ml-auto">{wing.children.length} rooms</span>
        </button>
        {isOpen && (
          <div className="ml-6 space-y-1 mt-1">
            {wing.children.map((room) => (
              <div key={room.id}>
                <div
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={() => handleDrop(wing.wing, room.room)}
                  className={`rounded-lg transition-colors ${dragNodeId ? 'bg-memory-500/5 border border-dashed border-memory-500/30' : ''}`}
                >
                  <button
                    onClick={() => toggleExpand(room.id)}
                    className="flex items-center gap-2 w-full px-3 py-1.5 rounded-lg hover:bg-surface-3 transition-colors text-left"
                  >
                    {room.children.length > 0 ? (
                      expanded.has(room.id) ? <ChevronDown size={14} /> : <ChevronRight size={14} />
                    ) : (
                      <span className="w-3.5" />
                    )}
                    <span className="text-sm text-text">{room.room}</span>
                    {dragNodeId && <span className="text-xs text-memory-400 ml-auto">drop here</span>}
                  </button>
                </div>
                {expanded.has(room.id) && room.children.length > 0 && (
                  <div className="ml-6 space-y-1 mt-1">
                    {room.children.map((drawer) => (
                      <div
                        key={drawer.id}
                        onDragOver={(e) => e.preventDefault()}
                        onDrop={() => handleDrop(wing.wing, room.room, drawer.drawer || drawer.room)}
                        className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm text-text/70 transition-colors ${
                          dragNodeId ? 'hover:bg-memory-500/10 cursor-pointer border border-dashed border-transparent hover:border-memory-500/30' : ''
                        }`}
                      >
                        <span className="w-2 h-2 rounded-full bg-surface-3" />
                        {drawer.drawer || drawer.room}
                        {dragNodeId && <span className="text-xs text-memory-400 ml-auto">drop</span>}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
            <button
              onClick={() => { setShowNewForm('room'); setSelectedWing(wing.wing); setNewName('') }}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-text hover:text-memory-400 transition-colors"
            >
              <Plus size={14} /> Add room
            </button>
          </div>
        )}
      </div>
    )
  }

  if (loading) {
    return <div className="text-text text-sm">Loading palace...</div>
  }

  return (
    <div className="max-w-4xl space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-semibold text-text-heading">Memory Palace</h2>
          <p className="text-sm text-text mt-1">Navigate your spatial organization</p>
        </div>
        <button
          onClick={() => { setShowNewForm('wing'); setNewName('') }}
          className="flex items-center gap-2 px-3 py-1.5 bg-memory-600 hover:bg-memory-700 text-white text-sm rounded-lg transition-colors"
        >
          <Plus size={16} /> Wing
        </button>
      </div>

      {(showNewForm === 'wing' || showNewForm === 'room') && (
        <div className="flex items-center gap-2 bg-surface-2 border border-border rounded-lg p-3">
          {showNewForm === 'room' && (
            <span className="text-xs text-text whitespace-nowrap">in {selectedWing}:</span>
          )}
          <input
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder={showNewForm === 'wing' ? 'Wing name...' : 'Room name...'}
            onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
            className="flex-1 px-2 py-1 bg-surface border border-border rounded text-sm text-text-heading focus:outline-none focus:border-memory-500 placeholder:text-text/40"
            autoFocus
          />
          <button onClick={handleCreate} className="px-3 py-1 bg-memory-600 text-white text-xs rounded-md hover:bg-memory-700 transition-colors">
            Create
          </button>
          <button onClick={() => setShowNewForm(null)} className="px-2 py-1 text-xs text-text hover:text-text-heading transition-colors">
            Cancel
          </button>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2">
          {tree.length === 0 ? (
            <div className="bg-surface-2 border border-border rounded-xl p-8 text-center">
              <TreePine size={32} className="mx-auto text-text mb-3" />
              <p className="text-text-heading font-medium">Empty palace</p>
              <p className="text-sm text-text mt-1">Create your first wing to organize memories</p>
            </div>
          ) : (
            <div className="bg-surface-2 border border-border rounded-xl p-4 space-y-1">
              {tree.map(renderWing)}
            </div>
          )}
        </div>

        <div>
          <div className="bg-surface-2 border border-border rounded-xl p-4">
            <h3 className="text-xs font-medium text-text uppercase tracking-wider mb-3">Unplaced Memories</h3>
            {nodes.length === 0 ? (
              <p className="text-xs text-text/50">All memories are placed</p>
            ) : (
              <div className="space-y-1 max-h-[500px] overflow-y-auto">
                {nodes.map((n) => (
                  <div
                    key={n.id}
                    draggable
                    onDragStart={() => setDragNodeId(n.id)}
                    onDragEnd={() => setDragNodeId(null)}
                    className="flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-surface-3 cursor-grab active:cursor-grabbing transition-colors group"
                  >
                    <GripVertical size={12} className="text-text/30 group-hover:text-text/60 shrink-0" />
                    <Link
                      to={`/memory/note/${n.id}`}
                      className="text-xs text-text truncate hover:text-memory-400 transition-colors"
                      onClick={(e) => e.stopPropagation()}
                    >
                      {n.title}
                    </Link>
                    <span className="text-[10px] px-1 py-0.5 rounded bg-surface-3 text-text capitalize ml-auto">{n.type}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

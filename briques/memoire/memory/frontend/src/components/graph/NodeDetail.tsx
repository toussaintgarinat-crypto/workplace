import { X, ExternalLink } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { GraphNode } from '../../types/api'

interface NodeDetailProps {
  node: GraphNode
  edges: { source: string; target: string; type: string }[]
  onClose: () => void
}

const typeLabels: Record<string, string> = {
  input: 'Input',
  projet: 'Project',
  casquette: 'Role',
  ressource: 'Resource',
  archive: 'Archive',
}

export default function NodeDetail({ node, edges, onClose }: NodeDetailProps) {
  const connectedEdges = edges.filter((e) => e.source === node.id || e.target === node.id)
  const connectionCount = connectedEdges.length

  return (
    <div className="w-72 border-l border-border bg-surface-2 p-4 overflow-y-auto shrink-0">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-text-heading">Node Details</h3>
        <button
          onClick={onClose}
          className="p-1 rounded hover:bg-surface-3 text-text transition-colors"
        >
          <X size={16} />
        </button>
      </div>

      <div className="space-y-4">
        <div>
          <p className="text-xs text-text mb-1">Title</p>
          <p className="text-sm text-text-heading font-medium">{node.title}</p>
        </div>

        <div>
          <p className="text-xs text-text mb-1">Type</p>
          <span className="text-xs px-2 py-0.5 rounded-full bg-surface-3 text-text capitalize">
            {typeLabels[node.type] || node.type}
          </span>
        </div>

        <div>
          <p className="text-xs text-text mb-1">Connections</p>
          <p className="text-sm text-text-heading">{connectionCount}</p>
        </div>

        {connectionCount > 0 && (
          <div>
            <p className="text-xs text-text mb-1">Connected to</p>
            <div className="space-y-1 max-h-32 overflow-y-auto">
              {connectedEdges.slice(0, 10).map((e, i) => {
                const otherId = e.source === node.id ? e.target : e.source
                return (
                  <div key={i} className="text-xs text-text truncate">
                    <span className="text-memory-400">{otherId.slice(0, 8)}</span>
                    <span className="text-text/50 mx-1">—</span>
                    <span className="italic">{e.type}</span>
                  </div>
                )
              })}
            </div>
          </div>
        )}

        <Link
          to={`/memory/note/${node.id}`}
          className="flex items-center gap-2 text-xs text-memory-400 hover:text-memory-300 transition-colors"
        >
          <ExternalLink size={14} />
          Open in editor
        </Link>
      </div>
    </div>
  )
}

import { useEffect, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { Share2 } from 'lucide-react'
import * as api from '../services/api'
import type { GraphNode, GraphEdge } from '../types/api'
import GraphCanvas from '../components/graph/GraphCanvas'
import NodeDetail from '../components/graph/NodeDetail'
import Legend from '../components/graph/Legend'

interface DetailData {
  node: GraphNode
  edges: GraphEdge[]
}

export default function GraphPage() {
  const [nodes, setNodes] = useState<GraphNode[]>([])
  const [edges, setEdges] = useState<GraphEdge[]>([])
  const [detail, setDetail] = useState<DetailData | null>(null)
  const [showLegend, setShowLegend] = useState(false)
  const [loading, setLoading] = useState(true)
  const navigate = useNavigate()

  useEffect(() => {
    loadGraph()
  }, [])

  async function loadGraph() {
    setLoading(true)
    try {
      const data = await api.getGraph('', 2)
      setNodes(data.nodes)
      setEdges(data.edges)
    } catch {
      // API not available
    } finally {
      setLoading(false)
    }
  }

  const handleNodeClick = useCallback(
    (nodeId: string) => {
      const node = nodes.find((n) => n.id === nodeId)
      if (!node) return
      setDetail({ node, edges })
    },
    [nodes, edges],
  )

  const handleNodeDoubleClick = useCallback(
    (nodeId: string) => {
      navigate(`/memory/note/${nodeId}`)
    },
    [navigate],
  )

  const handleEdgeCreate = useCallback(
    async (source: string, target: string) => {
      try {
        await api.createEdge(source, target)
        await loadGraph()
      } catch {
        // ignore
      }
    },
    [],
  )

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-2xl font-semibold text-text-heading">Graph View</h2>
          <p className="text-sm text-text mt-1">Explore connections between your memories</p>
        </div>
        <button
          onClick={() => setShowLegend((v) => !v)}
          className="flex items-center gap-2 px-3 py-1.5 text-sm text-text hover:text-text-heading bg-surface-2 border border-border rounded-lg transition-colors"
        >
          <Share2 size={16} />
          Legend
        </button>
      </div>

      <div className="flex gap-2 flex-1 min-h-0">
        <div className="flex-1 bg-surface-2 border border-border rounded-xl overflow-hidden">
          {loading ? (
            <div className="flex items-center justify-center h-full text-text text-sm">
              Loading...
            </div>
          ) : (
            <GraphCanvas
              nodes={nodes}
              edges={edges}
              onNodeClick={handleNodeClick}
              onNodeDoubleClick={handleNodeDoubleClick}
              onEdgeCreate={handleEdgeCreate}
            />
          )}
        </div>

        {showLegend && (
          <div className="hidden lg:block">
            <Legend />
          </div>
        )}

        {detail && (
          <NodeDetail
            node={detail.node}
            edges={detail.edges}
            onClose={() => setDetail(null)}
          />
        )}
      </div>

      <div className="mt-2 text-xs text-text/50 text-center">
        Click a node to see details &middot; Double-click to edit &middot; Drag between nodes to create edges
      </div>
    </div>
  )
}

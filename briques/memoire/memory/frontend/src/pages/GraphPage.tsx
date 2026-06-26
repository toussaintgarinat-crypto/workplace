import { useEffect, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { Share2 } from 'lucide-react'
import * as api from '../services/api'
import type { GraphNode, GraphEdge, TimelineEntry } from '../types/api'
import GraphCanvas from '../components/graph/GraphCanvas'
import NodeDetail from '../components/graph/NodeDetail'
import Legend from '../components/graph/Legend'
import TimeTravelBar from '../components/graph/TimeTravelBar'

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
  // Machine à remonter le temps (S113) : null = présent / live, sinon ISO de l'instant lu.
  const [asOf, setAsOf] = useState<string | null>(null)
  const [trackHistory, setTrackHistory] = useState(false)
  const [timeline, setTimeline] = useState<TimelineEntry[]>([])
  const [activating, setActivating] = useState(false)
  const navigate = useNavigate()

  useEffect(() => {
    loadGraph()
    loadSpaceHistory()
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

  // Charge l'état du journal temporel de l'espace + les crans du curseur (S113).
  async function loadSpaceHistory() {
    try {
      const space = await api.getSpace(api.getSpaceId())
      setTrackHistory(!!space.track_history)
      if (space.track_history) {
        setTimeline(await api.getGraphTimeline())
      }
    } catch {
      // ignore : l'espace n'expose peut-être pas encore le flag
    }
  }

  // Glissement du curseur : remonter à un instant (asOf) ou revenir au présent (null).
  const handleSeek = useCallback(async (iso: string | null) => {
    setAsOf(iso)
    setDetail(null)
    if (iso === null) {
      await loadGraph()
      return
    }
    setLoading(true)
    try {
      const data = await api.getGraphAt(iso, 2)
      setNodes(data.nodes)
      setEdges(data.edges)
    } catch {
      // ignore
    } finally {
      setLoading(false)
    }
  }, [])

  const handleActivate = useCallback(async () => {
    setActivating(true)
    try {
      await api.updateSpace(api.getSpaceId(), { track_history: true })
      setTrackHistory(true)
      setTimeline(await api.getGraphTimeline())
    } catch {
      // ignore
    } finally {
      setActivating(false)
    }
  }, [])

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
        // Un lien créé est un nouvel instant saillant : rafraîchir les crans.
        if (trackHistory) setTimeline(await api.getGraphTimeline())
      } catch {
        // ignore
      }
    },
    [trackHistory],
  )

  const handleNodePositionChange = useCallback(
    async (nodeId: string, x: number, y: number) => {
      // Persistance silencieuse : on ne recharge pas le graphe (garderait la position
      // déjà affichée par React Flow) ; on met juste à jour notre état local.
      setNodes((prev) =>
        prev.map((n) => (n.id === nodeId ? { ...n, pos: { x, y } } : n)),
      )
      try {
        await api.saveNodePosition(nodeId, x, y)
      } catch {
        // ignore : la position reste visible le temps de la session
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

      <div className="mb-3">
        <TimeTravelBar
          trackHistory={trackHistory}
          timeline={timeline}
          asOf={asOf}
          activating={activating}
          onActivate={handleActivate}
          onSeek={handleSeek}
        />
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
              onNodePositionChange={handleNodePositionChange}
              readOnly={asOf !== null}
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
        Click a node to see details &middot; Double-click to edit &middot; Drag a node to move it (saved) &middot; Drag between nodes to create edges
      </div>
    </div>
  )
}

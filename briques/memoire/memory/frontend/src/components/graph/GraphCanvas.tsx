import { useCallback, useMemo, useState } from 'react'
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  MarkerType,
  Handle,
  Position,
} from '@xyflow/react'
import type { Node, Edge, Connection, NodeProps } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import type { GraphNode, GraphEdge } from '../../types/api'

interface GraphCanvasProps {
  nodes: GraphNode[]
  edges: GraphEdge[]
  onNodeClick: (nodeId: string) => void
  onNodeDoubleClick: (nodeId: string) => void
  onEdgeCreate?: (source: string, target: string) => void
}

const typeColors: Record<string, string> = {
  input: '#f59e0b',
  projet: '#3b82f6',
  casquette: '#8b5cf6',
  ressource: '#10b981',
  archive: '#64748b',
}

const edgeTypeColors: Record<string, string> = {
  related: '#64748b',
  cause: '#ef4444',
  depends: '#f59e0b',
  references: '#3b82f6',
  part_of: '#10b981',
}

function CustomNode({ data, selected }: NodeProps) {
  const color = typeColors[data.type as string] || '#64748b'
  return (
    <div
      className={`px-3 py-2 rounded-lg border-2 text-sm cursor-pointer transition-shadow ${
        selected ? 'shadow-lg shadow-memory-500/20' : ''
      }`}
      style={{
        backgroundColor: `${color}15`,
        borderColor: selected ? color : `${color}40`,
        minWidth: 120,
      }}
    >
      <Handle type="target" position={Position.Left} className="!bg-surface-3 !border-border" />
      <div className="flex items-center gap-2">
        <span
          className="w-2 h-2 rounded-full shrink-0"
          style={{ backgroundColor: color }}
        />
        <span className="text-text-heading text-xs font-medium truncate">{data.label as string}</span>
      </div>
      <Handle type="source" position={Position.Right} className="!bg-surface-3 !border-border" />
    </div>
  )
}

const nodeTypes = { custom: CustomNode }

export default function GraphCanvas({
  nodes: graphNodes,
  edges: graphEdges,
  onNodeClick,
  onNodeDoubleClick,
  onEdgeCreate,
}: GraphCanvasProps) {
  const initialNodes: Node[] = useMemo(
    () =>
      graphNodes.map((n, i) => ({
        id: n.id,
        type: 'custom',
        position: {
          x: 150 + (i % 6) * 180,
          y: 80 + Math.floor(i / 6) * 120,
        },
        data: { label: n.title, type: n.type },
      })),
    [graphNodes],
  )

  const initialEdges: Edge[] = useMemo(
    () =>
      graphEdges.map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        type: 'smoothstep',
        animated: true,
        markerEnd: { type: MarkerType.ArrowClosed, color: edgeTypeColors[e.type] || '#64748b' },
        style: { stroke: edgeTypeColors[e.type] || '#64748b', strokeWidth: 1.5 },
        label: e.type,
      })),
    [graphEdges],
  )

  const [nodesState, , onNodesChange] = useNodesState(initialNodes)
  const [edgesState, , onEdgesChange] = useEdgesState(initialEdges)
  const [, setSelected] = useState<string | null>(null)

  const onConnect = useCallback(
    (conn: Connection) => {
      if (conn.source && conn.target && onEdgeCreate) {
        onEdgeCreate(conn.source, conn.target)
      }
    },
    [onEdgeCreate],
  )

  const onNodeClickHandler = useCallback(
    (_: React.MouseEvent, node: Node) => {
      setSelected(node.id)
      onNodeClick(node.id)
    },
    [onNodeClick],
  )

  const onNodeDoubleClickHandler = useCallback(
    (_: React.MouseEvent, node: Node) => {
      onNodeDoubleClick(node.id)
    },
    [onNodeDoubleClick],
  )

  const defaultEdgeOptions = useMemo(
    () => ({
      type: 'smoothstep',
      animated: true,
      markerEnd: { type: MarkerType.ArrowClosed, color: '#64748b' },
      style: { stroke: '#64748b', strokeWidth: 1.5 },
    }),
    [],
  )

  if (graphNodes.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-text">
        <p className="text-sm">No nodes to display. Create some memories first.</p>
      </div>
    )
  }

  return (
    <div className="w-full h-full min-h-[500px]">
      <ReactFlow
        nodes={nodesState}
        edges={edgesState}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onNodeClick={onNodeClickHandler}
        onNodeDoubleClick={onNodeDoubleClickHandler}
        nodeTypes={nodeTypes}
        defaultEdgeOptions={defaultEdgeOptions}
        fitView
        minZoom={0.3}
        maxZoom={2}
      >
        <Background color="#334155" gap={20} />
        <Controls className="!bg-surface-2 !border-border !text-text" />
        <MiniMap
          nodeColor={(n) => typeColors[(n.data as Record<string, unknown>)?.type as string] || '#64748b'}
          maskColor="rgba(15, 23, 42, 0.8)"
          className="!bg-surface-2 !border-border"
        />
      </ReactFlow>
    </div>
  )
}

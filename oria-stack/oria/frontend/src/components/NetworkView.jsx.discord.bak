import { useState, useEffect, useCallback, useRef } from 'react'
import ForceGraph2D from 'react-force-graph-2d'
import { api } from '../services/api.js'
import CreateLinkModal from './CreateLinkModal.jsx'

const TYPE_COLORS = {
  filiale:     '#5865F2',
  partenaire:  '#57F287',
  client:      '#FEE75C',
  fournisseur: '#EB459E',
  association: '#ED4245',
}

const TYPE_LABELS = {
  filiale:     'Commune membre',
  partenaire:  'Partenaire',
  client:      'Contractant',
  fournisseur: 'Prestataire',
  association: 'EPCI / Groupement',
}

export default function NetworkView({ moi, onOuvrirWorld }) {
  const [graphData, setGraphData]     = useState({ nodes: [], links: [] })
  const [vue, setVue]                 = useState('graph') // 'graph' | 'liste'
  const [showCreate, setShowCreate]   = useState(false)
  const [mondes, setMondes]           = useState([])
  const [selectedNode, setSelectedNode] = useState(null)
  const graphRef = useRef()

  useEffect(() => {
    chargerNetwork()
    chargerMondes()
  }, [])

  // Configurer les forces D3 dès que le graphe est monté
  useEffect(() => {
    const fg = graphRef.current
    if (!fg) return
    fg.d3Force('charge')?.strength(-500)
    fg.d3Force('link')?.distance(160).strength(0.4)
    fg.d3Force('center')?.strength(0.05)
  }, [graphRef.current])

  async function chargerNetwork() {
    const data = await api.get('/network/global/moi')
    if (data?.noeuds) {
      setGraphData({
        nodes: data.noeuds.map(n => ({
          id: n.id,
          nom: n.nom,
          emoji: n.emoji,
          couleur: n.couleur || '#5865F2',
          accessible: n.accessible,
        })),
        links: data.aretes.map(a => ({
          id: a.id,
          source: a.from_world_id,
          target: a.to_world_id,
          type: a.type,
          pourcentage: a.pourcentage,
          color: TYPE_COLORS[a.type] || '#99aab5',
        })),
      })
    }
  }

  async function chargerMondes() {
    const data = await api.get('/worlds/')
    if (Array.isArray(data)) setMondes(data)
  }

  async function supprimerLien(id) {
    await api.del(`/network/${id}`)
    chargerNetwork()
  }

  const nodeCanvasObject = useCallback((node, ctx, globalScale) => {
    const size = 22
    ctx.beginPath()
    ctx.arc(node.x, node.y, size / 2, 0, 2 * Math.PI)
    ctx.fillStyle = node.accessible ? (node.couleur || '#5865F2') : '#4f545c'
    ctx.fill()
    ctx.strokeStyle = selectedNode?.id === node.id ? '#fff' : 'rgba(255,255,255,0.15)'
    ctx.lineWidth = selectedNode?.id === node.id ? 2.5 : 1
    ctx.stroke()

    const fontSize = Math.max(10, 14 / globalScale)
    ctx.font = `${fontSize}px sans-serif`
    ctx.fillStyle = '#fff'
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillText(node.emoji || '🌐', node.x, node.y)

    if (globalScale >= 0.8) {
      ctx.font = `${Math.max(8, 11 / globalScale)}px sans-serif`
      ctx.fillStyle = 'rgba(255,255,255,0.85)'
      ctx.fillText(node.nom, node.x, node.y + size / 2 + 8 / globalScale)
    }
  }, [selectedNode])

  const linkCanvasObject = useCallback((link, ctx) => {
    const start = link.source
    const end   = link.target
    if (!start.x || !end.x) return

    ctx.beginPath()
    ctx.moveTo(start.x, start.y)
    ctx.lineTo(end.x, end.y)
    ctx.strokeStyle = link.color || '#99aab5'
    ctx.lineWidth   = 1.5
    ctx.setLineDash([4, 3])
    ctx.stroke()
    ctx.setLineDash([])

    // Flèche
    const angle = Math.atan2(end.y - start.y, end.x - start.x)
    const arrowSize = 8
    const tx = end.x - Math.cos(angle) * 14
    const ty = end.y - Math.sin(angle) * 14
    ctx.beginPath()
    ctx.moveTo(tx, ty)
    ctx.lineTo(tx - arrowSize * Math.cos(angle - Math.PI / 6), ty - arrowSize * Math.sin(angle - Math.PI / 6))
    ctx.lineTo(tx - arrowSize * Math.cos(angle + Math.PI / 6), ty - arrowSize * Math.sin(angle + Math.PI / 6))
    ctx.closePath()
    ctx.fillStyle = link.color || '#99aab5'
    ctx.fill()

    // Label pourcentage
    if (link.pourcentage) {
      const mx = (start.x + end.x) / 2
      const my = (start.y + end.y) / 2
      ctx.font = '10px sans-serif'
      ctx.fillStyle = link.color || '#99aab5'
      ctx.textAlign = 'center'
      ctx.fillText(`${link.pourcentage}%`, mx, my - 6)
    }
  }, [])

  return (
    <div className="network-view">
      <div className="network-header">
        <span className="network-titre">🕸 Intercommunalité</span>
        <div className="network-actions">
          <button className={`btn-vue ${vue === 'graph' ? 'actif' : ''}`} onClick={() => setVue('graph')}>Graphe</button>
          <button className={`btn-vue ${vue === 'liste' ? 'actif' : ''}`} onClick={() => setVue('liste')}>Liste</button>
          {vue === 'graph' && (
            <button className="btn-vue" onClick={() => {
              // Libérer tous les nœuds fixés et recentrer
              graphData.nodes.forEach(n => { n.fx = undefined; n.fy = undefined })
              graphRef.current?.d3ReheatSimulation()
              setTimeout(() => graphRef.current?.zoomToFit(500, 100), 1200)
            }} title="Réinitialiser les positions">↺</button>
          )}
          <button className="btn-creer-lien" onClick={() => setShowCreate(true)}>+ Lien</button>
        </div>
      </div>

      {vue === 'graph' && (
        <div className="network-graph-wrap">
          <ForceGraph2D
            ref={graphRef}
            graphData={graphData}
            nodeCanvasObject={nodeCanvasObject}
            nodeCanvasObjectMode={() => 'replace'}
            linkCanvasObject={linkCanvasObject}
            linkCanvasObjectMode={() => 'replace'}
            onNodeClick={(node) => {
              setSelectedNode(node)
              if (node.accessible) onOuvrirWorld?.({ id: node.id, nom: node.nom, emoji: node.emoji, couleur: node.couleur })
            }}
            onNodeDragEnd={(node) => {
              // Fixer le nœud après drag : il ne bouge plus
              node.fx = node.x
              node.fy = node.y
            }}
            backgroundColor="#1e2124"
            nodeRelSize={11}
            linkDirectionalArrowLength={0}
            cooldownTicks={300}
            d3AlphaDecay={0.008}
            d3VelocityDecay={0.4}
            onEngineStop={() => graphRef.current?.zoomToFit(500, 100)}
          />
          {selectedNode && (
            <div className="network-node-tooltip">
              <span>{selectedNode.emoji} {selectedNode.nom}</span>
              {!selectedNode.accessible && <span className="badge-prive">Privé</span>}
            </div>
          )}
          <div className="network-legende">
            {Object.entries(TYPE_LABELS).map(([k, v]) => (
              <span key={k} className="legende-item">
                <span className="legende-dot" style={{ background: TYPE_COLORS[k] }} />
                {v}
              </span>
            ))}
          </div>
        </div>
      )}

      {vue === 'liste' && (
        <div className="network-liste">
          {graphData.links.length === 0 && (
            <div className="network-vide">Aucun lien. Reliez des communes avec "+ Lien".</div>
          )}
          {graphData.links.map(lien => {
            const from = graphData.nodes.find(n => n.id === (lien.source?.id ?? lien.source))
            const to   = graphData.nodes.find(n => n.id === (lien.target?.id ?? lien.target))
            return (
              <div key={lien.id} className="network-lien-row">
                <span className="lien-dot" style={{ background: lien.color }} />
                <span className="lien-from">{from?.emoji} {from?.nom}</span>
                <span className="lien-arrow">→</span>
                <span className="lien-to">{to?.emoji} {to?.nom}</span>
                <span className="lien-type" style={{ color: lien.color }}>{TYPE_LABELS[lien.type]}</span>
                {lien.pourcentage && <span className="lien-pct">{lien.pourcentage}%</span>}
                <button className="btn-suppr-lien" onClick={() => supprimerLien(lien.id)}>✕</button>
              </div>
            )
          })}
        </div>
      )}

      {showCreate && (
        <CreateLinkModal
          mondes={mondes}
          onSave={() => { setShowCreate(false); chargerNetwork() }}
          onFermer={() => setShowCreate(false)}
        />
      )}
    </div>
  )
}

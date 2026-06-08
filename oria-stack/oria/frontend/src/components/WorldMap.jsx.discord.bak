import { useEffect, useRef, useState, useCallback } from 'react'
import AgentChatPanel from './AgentChatPanel.jsx'

const TILE  = 48    // px par tile
const COLS  = 24
const ROWS  = 18
const PROXIMITY = 2.5  // distance en tiles pour déclencher le chat

// Palettes terrain
const TERRAIN_COLORS = {
  0: '#2d5a1b',  // herbe
  1: '#8b7355',  // chemin
  2: '#1a3a5c',  // eau
  3: '#4a4a4a',  // sol intérieur
  4: '#6b8c4e',  // herbe claire
}

const TERRAIN_EMOJI = {
  0: null, 1: null, 2: '💧', 3: null, 4: null,
}

function defaultMap(buildings, agents) {
  // Génère une carte par défaut avec sentiers et positions de buildings
  const grid = Array.from({ length: ROWS }, (_, y) =>
    Array.from({ length: COLS }, (_, x) => {
      if (x === 0 || x === COLS-1 || y === 0 || y === ROWS-1) return 3
      if (x % 6 === 0 || y % 6 === 0) return 1  // sentiers
      return 0  // herbe
    })
  )
  // Positions par défaut des buildings (grille régulière)
  const bPositions = buildings.map((b, i) => ({
    id: b.id,
    x: 2 + (i % 4) * 5,
    y: 2 + Math.floor(i / 4) * 5,
    w: 3, h: 2,
    nom: b.nom, emoji: b.emoji || '🏠', couleur: b.couleur || '#5865F2',
  }))
  const aPositions = agents.map((a, i) => ({
    id: a.id,
    x: 3 + (i % 5) * 4,
    y: 3 + Math.floor(i / 5) * 4,
    nom: a.nom, emoji: a.avatar_emoji || '🤖',
  }))
  return { grid, buildings: bPositions, agents: aPositions, spawn: { x: 1, y: 1 } }
}

function dist(ax, ay, bx, by) {
  return Math.sqrt((ax - bx) ** 2 + (ay - by) ** 2)
}

export default function WorldMap({ world, moi, buildings = [], agents = [], onEntrerBuilding }) {
  const canvasRef  = useRef(null)
  const stateRef   = useRef({
    player: { x: 1.5, y: 1.5 },
    keys: {},
    map: null,
    anim: 0,
  })
  const [nearAgent, setNearAgent]   = useState(null)
  const [chatAgent, setChatAgent]   = useState(null)
  const [mapData, setMapData]       = useState(null)
  const [draggingId, setDraggingId] = useState(null)
  const [editMode, setEditMode]     = useState(false)
  const animRef = useRef(null)

  // ── Init map data ───────────────────────────────────────────
  useEffect(() => {
    let parsed = null
    if (world?.map_data) {
      try { parsed = JSON.parse(world.map_data) } catch {}
    }
    if (!parsed) {
      parsed = defaultMap(buildings, agents)
    } else {
      // Sync building/agent lists into map
      parsed.buildings = buildings.map((b, i) => {
        const existing = parsed.buildings?.find(pb => pb.id === b.id)
        return existing || {
          id: b.id, x: 2 + (i % 4) * 5, y: 2 + Math.floor(i / 4) * 5,
          w: 3, h: 2, nom: b.nom, emoji: b.emoji || '🏠', couleur: b.couleur || '#5865F2',
        }
      })
      parsed.agents = agents.map((a, i) => {
        const existing = parsed.agents?.find(pa => pa.id === a.id)
        return existing || {
          id: a.id, x: 3 + (i % 5) * 4, y: 3 + Math.floor(i / 5) * 4,
          nom: a.nom, emoji: a.avatar_emoji || '🤖',
        }
      })
    }
    stateRef.current.player = {
      x: (parsed.spawn?.x ?? 1) + 0.5,
      y: (parsed.spawn?.y ?? 1) + 0.5,
    }
    stateRef.current.map = parsed
    setMapData(parsed)
  }, [world?.map_data, buildings, agents])

  // ── Keyboard ────────────────────────────────────────────────
  useEffect(() => {
    const onDown = e => {
      if (['ArrowUp','ArrowDown','ArrowLeft','ArrowRight','w','a','s','d'].includes(e.key)) {
        e.preventDefault()
        stateRef.current.keys[e.key] = true
      }
      if (e.key === 'Escape') setChatAgent(null)
    }
    const onUp = e => { stateRef.current.keys[e.key] = false }
    window.addEventListener('keydown', onDown)
    window.addEventListener('keyup',   onUp)
    return () => {
      window.removeEventListener('keydown', onDown)
      window.removeEventListener('keyup',   onUp)
    }
  }, [])

  // ── Canvas render loop ──────────────────────────────────────
  useEffect(() => {
    if (!mapData) return
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    canvas.width  = COLS * TILE
    canvas.height = ROWS * TILE

    const SPEED = 0.08

    function canMove(nx, ny, map) {
      if (nx < 0.5 || nx > COLS - 0.5 || ny < 0.5 || ny > ROWS - 0.5) return false
      for (const b of (map.buildings || [])) {
        if (nx > b.x - 0.4 && nx < b.x + b.w + 0.4 &&
            ny > b.y - 0.4 && ny < b.y + b.h + 0.4) return false
      }
      return true
    }

    function update() {
      const s  = stateRef.current
      const k  = s.keys
      const map = s.map
      if (!map) return

      let { x, y } = s.player
      const up    = k['ArrowUp']    || k['w']
      const down  = k['ArrowDown']  || k['s']
      const left  = k['ArrowLeft']  || k['a']
      const right = k['ArrowRight'] || k['d']

      let nx = x + (right ? SPEED : 0) - (left ? SPEED : 0)
      let ny = y + (down  ? SPEED : 0) - (up   ? SPEED : 0)
      if (canMove(nx, y, map))  x = nx
      if (canMove(x, ny, map))  y = ny
      s.player = { x, y }
      s.anim   = (s.anim + 1) % 60

      // Détection proximité agents
      let closest = null
      let closestDist = Infinity
      for (const a of (map.agents || [])) {
        const d = dist(x, y, a.x + 0.5, a.y + 0.5)
        if (d < PROXIMITY && d < closestDist) {
          closestDist = d
          closest = a
        }
      }
      setNearAgent(prev => {
        if (!prev && !closest) return prev
        if (closest?.id !== prev?.id) return closest || null
        return prev
      })
    }

    function drawTile(ctx, tileType, px, py) {
      ctx.fillStyle = TERRAIN_COLORS[tileType] ?? '#2d5a1b'
      ctx.fillRect(px, py, TILE, TILE)
      // Grille subtile
      ctx.strokeStyle = 'rgba(0,0,0,0.08)'
      ctx.lineWidth = 0.5
      ctx.strokeRect(px, py, TILE, TILE)
    }

    function drawBuilding(ctx, b, anim) {
      const px = b.x * TILE, py = b.y * TILE
      const bw = b.w * TILE, bh = b.h * TILE
      // Ombre
      ctx.fillStyle = 'rgba(0,0,0,0.3)'
      ctx.fillRect(px + 4, py + 4, bw, bh)
      // Corps
      ctx.fillStyle = b.couleur || '#5865F2'
      ctx.fillRect(px, py, bw, bh)
      // Bordure
      ctx.strokeStyle = 'rgba(255,255,255,0.3)'
      ctx.lineWidth = 2
      ctx.strokeRect(px, py, bw, bh)
      // Emoji + nom
      ctx.font = `${Math.min(bw, bh) * 0.45}px sans-serif`
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      ctx.fillText(b.emoji, px + bw / 2, py + bh / 2 - 8)
      ctx.font = `bold 11px sans-serif`
      ctx.fillStyle = '#fff'
      ctx.shadowColor = '#000'
      ctx.shadowBlur = 4
      ctx.fillText(b.nom.slice(0, 14), px + bw / 2, py + bh - 10)
      ctx.shadowBlur = 0
    }

    function drawAgent(ctx, a, anim, isNear) {
      const px = a.x * TILE + TILE / 2
      const py = a.y * TILE + TILE / 2
      const r  = isNear ? 22 + Math.sin(anim * 0.2) * 3 : 20
      // Halo si proche
      if (isNear) {
        ctx.beginPath()
        ctx.arc(px, py, r + 8, 0, Math.PI * 2)
        ctx.fillStyle = `rgba(100, 200, 255, ${0.2 + Math.sin(anim * 0.15) * 0.1})`
        ctx.fill()
      }
      // Cercle agent
      ctx.beginPath()
      ctx.arc(px, py, r, 0, Math.PI * 2)
      ctx.fillStyle = isNear ? '#4fc3f7' : '#1a237e'
      ctx.fill()
      ctx.strokeStyle = isNear ? '#fff' : '#7986cb'
      ctx.lineWidth = 2
      ctx.stroke()
      // Emoji
      ctx.font = '20px sans-serif'
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      ctx.fillText(a.emoji, px, py - 2)
      // Nom
      ctx.font = 'bold 10px sans-serif'
      ctx.fillStyle = '#fff'
      ctx.shadowColor = '#000'
      ctx.shadowBlur = 4
      ctx.fillText(a.nom.slice(0, 12), px, py + r + 12)
      ctx.shadowBlur = 0
      // Bulle "Parler" si proche
      if (isNear) {
        ctx.font = '11px sans-serif'
        ctx.fillStyle = '#e3f2fd'
        ctx.fillText('Appuie sur E', px, py + r + 25)
      }
    }

    function drawPlayer(ctx, px, py, anim) {
      const cx = px * TILE + TILE / 2
      const cy = py * TILE + TILE / 2
      // Ombre au sol
      ctx.beginPath()
      ctx.ellipse(cx, cy + 16, 14, 6, 0, 0, Math.PI * 2)
      ctx.fillStyle = 'rgba(0,0,0,0.25)'
      ctx.fill()
      // Corps
      ctx.beginPath()
      ctx.arc(cx, cy - 4 + Math.sin(anim * 0.3) * 2, 18, 0, Math.PI * 2)
      ctx.fillStyle = '#7c4dff'
      ctx.fill()
      ctx.strokeStyle = '#ede7f6'
      ctx.lineWidth = 2
      ctx.stroke()
      // Emoji utilisateur
      ctx.font = '18px sans-serif'
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      ctx.fillText('🧑', cx, cy - 4 + Math.sin(anim * 0.3) * 2)
    }

    function render() {
      const s   = stateRef.current
      const map = s.map
      if (!map) return

      ctx.clearRect(0, 0, canvas.width, canvas.height)

      // Terrain
      for (let row = 0; row < ROWS; row++) {
        for (let col = 0; col < COLS; col++) {
          const tile = map.grid?.[row]?.[col] ?? 0
          drawTile(ctx, tile, col * TILE, row * TILE)
        }
      }

      // Buildings
      for (const b of (map.buildings || [])) drawBuilding(ctx, b, s.anim)

      // Agents
      const near = stateRef.current.player
      for (const a of (map.agents || [])) {
        const isNear = dist(near.x, near.y, a.x + 0.5, a.y + 0.5) < PROXIMITY
        drawAgent(ctx, a, s.anim, isNear)
      }

      // Joueur
      drawPlayer(ctx, s.player.x, s.player.y, s.anim)
    }

    function loop() {
      update()
      render()
      animRef.current = requestAnimationFrame(loop)
    }
    animRef.current = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(animRef.current)
  }, [mapData])

  // ── Touche E pour ouvrir le chat ────────────────────────────
  useEffect(() => {
    const onKey = e => {
      if (e.key === 'e' || e.key === 'E') {
        const s = stateRef.current
        if (!s.map) return
        for (const a of (s.map.agents || [])) {
          if (dist(s.player.x, s.player.y, a.x + 0.5, a.y + 0.5) < PROXIMITY) {
            const fullAgent = agents.find(ag => ag.id === a.id)
            if (fullAgent) setChatAgent(fullAgent)
            break
          }
        }
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [agents])

  // ── Clic sur building ───────────────────────────────────────
  const handleCanvasClick = useCallback(e => {
    if (!mapData || editMode) return
    const rect = canvasRef.current.getBoundingClientRect()
    const cx = (e.clientX - rect.left) / (rect.width  / (COLS * TILE))
    const cy = (e.clientY - rect.top)  / (rect.height / (ROWS * TILE))
    const tx = cx / TILE, ty = cy / TILE

    for (const b of (mapData.buildings || [])) {
      if (tx >= b.x && tx <= b.x + b.w && ty >= b.y && ty <= b.y + b.h) {
        const fullBuilding = buildings.find(bl => bl.id === b.id)
        if (fullBuilding) onEntrerBuilding?.(fullBuilding)
        return
      }
    }
    for (const a of (mapData.agents || [])) {
      if (dist(tx, ty, a.x + 0.5, a.y + 0.5) < 1) {
        const fullAgent = agents.find(ag => ag.id === a.id)
        if (fullAgent) setChatAgent(fullAgent)
        return
      }
    }
  }, [mapData, editMode, buildings, agents, onEntrerBuilding])

  return (
    <div className="worldmap-container">
      {/* Toolbar */}
      <div className="worldmap-toolbar">
        <span className="worldmap-title">{world?.emoji} {world?.nom}</span>
        <span className="worldmap-hint">
          {nearAgent
            ? `💬 ${nearAgent.nom} est proche — appuie sur E`
            : '↑↓←→ ou WASD pour te déplacer'}
        </span>
        {world?.owner_id === moi?.id && (
          <button
            className={`btn-map-edit ${editMode ? 'active' : ''}`}
            onClick={() => setEditMode(v => !v)}
          >
            {editMode ? '✅ Terminé' : '✏️ Éditer carte'}
          </button>
        )}
      </div>

      {/* Canvas */}
      <div className="worldmap-canvas-wrapper">
        <canvas
          ref={canvasRef}
          className="worldmap-canvas"
          onClick={handleCanvasClick}
          tabIndex={0}
          style={{ cursor: editMode ? 'crosshair' : 'default' }}
        />

        {/* Légende */}
        <div className="worldmap-legend">
          <div className="legend-item"><span style={{background:'#7c4dff'}} className="legend-dot"/>Toi</div>
          <div className="legend-item"><span style={{background:'#1a237e'}} className="legend-dot"/>Agent IA</div>
          <div className="legend-item"><span style={{background:'#5865F2'}} className="legend-dot"/>Espace</div>
        </div>
      </div>

      {/* Panel chat agent */}
      {chatAgent && (
        <AgentChatPanel
          agent={chatAgent}
          moi={moi}
          onClose={() => setChatAgent(null)}
        />
      )}
    </div>
  )
}

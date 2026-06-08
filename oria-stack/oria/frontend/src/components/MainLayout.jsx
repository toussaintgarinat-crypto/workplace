import { useState, useEffect, useRef, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import WorldSidebar from './WorldSidebar.jsx'
import LanguagePicker from './LanguagePicker.jsx'
import ChannelPanel from './ChannelPanel.jsx'
import RoomView from './RoomView.jsx'
import MembersPanel from './MembersPanel.jsx'
import DMPanel from './DMPanel.jsx'
import NetworkView from './NetworkView.jsx'
import CreateWorldModal from './CreateWorldModal.jsx'
import { api } from '../services/api.js'
import Toast from './Toast.jsx'
import SyncStatus from './SyncStatus.jsx'
import SettingsModal from './SettingsModal.jsx'
import DocumentsPanel from './DocumentsPanel.jsx'
import VotePanel from './VotePanel.jsx'
import SearchPanel from './SearchPanel.jsx'
import CalendarPanel from './CalendarPanel.jsx'
import ReseauDocumentsPanel from './ReseauDocumentsPanel.jsx'
import SharedZonesPanel from './SharedZonesPanel.jsx'
import LLMConfigPanel from './LLMConfigPanel.jsx'
import { useUnreadCounts } from '../hooks/useUnreadCounts.js'
import { useUnreadDMCounts } from '../hooks/useUnreadDMCounts.js'
// Nouvelles vues
import WorldMap from './WorldMap.jsx'
import DiscoveryPage from './DiscoveryPage.jsx'
import DocumentsManager from './DocumentsManager.jsx'
import AgentManager from './AgentManager.jsx'
import IPCRAPanel from './IPCRAPanel.jsx'
import ActivityFeed from './ActivityFeed.jsx'
import JardinPanel from './JardinPanel.jsx'
import ConductorView from './ConductorView.jsx'
import ProjectsPanel from './ProjectsPanel.jsx'

export default function MainLayout({ moi, onMoiUpdate, onDeconnexion }) {
  const { t } = useTranslation()
  const [worlds, setWorlds]                 = useState([])
  const [worldActif, setWorldActif]         = useState(null)
  const [roomsOuvertes, setRoomsOuvertes]   = useState([])   // [{ room, building }]
  const [largeurs, setLargeurs]             = useState([])   // flex values
  const [creerWorld, setCreerWorld]         = useState(false)
  const [showMembers, setShowMembers]       = useState(false)
  const [dmDestinataire, setDmDestinataire] = useState(null)
  const [showNetwork, setShowNetwork]       = useState(false)
  const [showSettings, setShowSettings]     = useState(false)
  const [docsScope, setDocsScope]           = useState(null) // { type, id, nom }
  const [outilActif, setOutilActif]         = useState(null)
  const [voteConseil, setVoteConseil]       = useState(null) // { conseil, world }
  // Nouvelles vues
  const [showMap, setShowMap]               = useState(false)
  const [showDiscovery, setShowDiscovery]   = useState(false)
  const [showMyDocs, setShowMyDocs]         = useState(false)
  const [showAgents, setShowAgents]         = useState(false)
  const [showIPCRA, setShowIPCRA]           = useState(false)
  const [showFeed, setShowFeed]             = useState(false)
  const [showJardin, setShowJardin]         = useState(false)
  const [showConductor, setShowConductor]   = useState(false)
  const [worldAgents, setWorldAgents]       = useState([])

  const resizeRef = useRef(null) // { index, startX, startWidths, containerWidth }

  useEffect(() => { chargerWorlds(); gererInvitation() }, [])

  useEffect(() => {
    if (worldActif?.id) {
      api.get(`/agents/world/${worldActif.id}`).then(data => {
        setWorldAgents(Array.isArray(data) ? data : [])
      })
    }
  }, [worldActif?.id])

  async function gererInvitation() {
    const params = new URLSearchParams(window.location.search)
    const token = params.get('invite')
    if (!token) return
    await api.post(`/invitations/${token}/rejoindre`, { user_id: moi.id })
    window.history.replaceState({}, '', '/')
    chargerWorlds()
  }

  async function chargerWorlds() {
    const data = await api.get('/worlds')
    if (Array.isArray(data)) {
      setWorlds(data)
      if (data.length > 0 && !worldActif) chargerWorldComplet(data[0].id)
    }
  }

  async function chargerWorldComplet(id) {
    const data = await api.get(`/worlds/${id}`)
    setWorldActif(data)
    // On ne ferme PAS les panneaux ouverts d'autres mondes
    setShowMembers(false)
    setDmDestinataire(null)
    setShowNetwork(false)
  }

  function clearAllViews() {
    setShowMembers(false); setDmDestinataire(null); setDocsScope(null)
    setOutilActif(null); setVoteConseil(null)
    setShowMap(false); setShowDiscovery(false); setShowMyDocs(false)
    setShowAgents(false); setShowIPCRA(false); setShowNetwork(false); setShowFeed(false); setShowJardin(false)
    setShowConductor(false)
  }

  function entrerRoom(room, building) {
    setShowMembers(false)
    setDmDestinataire(null)
    setDocsScope(null)
    setOutilActif(null)
    markAsRead(room.matrix_room_id)
    setRoomsOuvertes(prev => {
      if (prev.find(r => r.room.id === room.id)) return prev
      const next = [...prev, { room, building, world: worldActif }]
      setLargeurs(next.map(() => 1))
      return next
    })
  }

  function quitterRoom(roomId) {
    setRoomsOuvertes(prev => {
      const next = prev.filter(r => r.room.id !== roomId)
      setLargeurs(next.map(() => 1))
      return next
    })
  }

  function ouvrirMembers() {
    setShowMembers(true)
    setDmDestinataire(null)
  }

  function ouvrirOutil(outil) {
    setOutilActif(outil)
    setShowMembers(false)
    setDmDestinataire(null)
    setDocsScope(null)
    setVoteConseil(null)
  }

  function ouvrirVotes(conseil) {
    setVoteConseil(conseil)
    setShowMembers(false)
    setDmDestinataire(null)
    setDocsScope(null)
    setOutilActif(null)
  }

  function ouvrirDM(membre) {
    setDmDestinataire(membre)
    setShowMembers(false)
    markDMAsRead(membre.matrix_user_id)
  }

  function basculerNetwork() {
    setShowNetwork(v => !v)
    if (!showNetwork) {
      setShowMembers(false)
      setDmDestinataire(null)
    }
  }

  async function onWorldCree(world) {
    await chargerWorlds()
    chargerWorldComplet(world.id)
    setCreerWorld(false)
  }

  // ── Redimensionnement ──────────────────────────────────────────
  const startResize = useCallback((index, e) => {
    e.preventDefault()
    const container = e.currentTarget.parentElement
    resizeRef.current = {
      index,
      startX: e.clientX,
      startLargeurs: [...largeurs],
      containerW: container.getBoundingClientRect().width,
    }

    function onMove(e) {
      const { index, startX, startLargeurs, containerW } = resizeRef.current
      const delta = e.clientX - startX
      // Convertir delta en unités flex
      const totalFlex = startLargeurs.reduce((a, b) => a + b, 0)
      const flexPerPx = totalFlex / containerW
      const deltaFlex = delta * flexPerPx

      const next = [...startLargeurs]
      next[index]     = Math.max(0.15, startLargeurs[index] + deltaFlex)
      next[index + 1] = Math.max(0.15, startLargeurs[index + 1] - deltaFlex)
      setLargeurs(next)
    }

    function onUp() {
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
      resizeRef.current = null
    }

    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  }, [largeurs])

  // ── Messages non lus ───────────────────────────────────────────
  const activeMatrixRoomIds = new Set(
    roomsOuvertes.map(r => r.room.matrix_room_id).filter(Boolean)
  )
  const { counts: unreadCounts, markAsRead } = useUnreadCounts(activeMatrixRoomIds)
  const { total: dmUnreadTotal, byMxid: dmUnreadByMxid, markDMAsRead } = useUnreadDMCounts(
    dmDestinataire?.matrix_user_id || null
  )

  // ── Zone principale ────────────────────────────────────────────
  const roomIds = new Set(roomsOuvertes.map(r => r.room.id))

  let contenuPrincipal
  if (showConductor) {
    contenuPrincipal = <ConductorView moi={moi} />
  } else if (showJardin) {
    contenuPrincipal = <JardinPanel moi={moi} />
  } else if (showFeed) {
    contenuPrincipal = (
      <ActivityFeed
        moi={moi}
        onOuvrirWorld={async (worldId) => {
          clearAllViews()
          await chargerWorldComplet(worldId)
        }}
      />
    )
  } else if (showDiscovery) {
    contenuPrincipal = (
      <DiscoveryPage
        moi={moi}
        onJoinWorld={() => { chargerWorlds(); setShowDiscovery(false) }}
      />
    )
  } else if (showMyDocs) {
    contenuPrincipal = (
      <DocumentsManager moi={moi} worldId={worldActif?.id} />
    )
  } else if (showAgents) {
    contenuPrincipal = worldActif
      ? <AgentManager world={worldActif} moi={moi} onAgentsChange={() => {
          api.get(`/agents/world/${worldActif.id}`).then(d => setWorldAgents(Array.isArray(d) ? d : []))
        }} />
      : <div className="need-world-msg"><span>🤖</span><p>{t('main.needWorld')}</p></div>
  } else if (showIPCRA) {
    contenuPrincipal = (
      <IPCRAPanel worldId={worldActif?.id} agents={worldAgents} />
    )
  } else if (showMap) {
    if (!worldActif) {
      contenuPrincipal = <div className="need-world-msg"><span>🗺</span><p>{t('main.needWorldMap')}</p></div>
    } else {
      contenuPrincipal = (
        <WorldMap
          world={worldActif}
          moi={moi}
          buildings={worldActif.buildings || []}
          agents={worldAgents}
          onEntrerBuilding={b => {
            setShowMap(false)
            const room = b.rooms?.[0]
            if (room) entrerRoom(room, b)
          }}
        />
      )
    }
  } else if (showNetwork) {
    contenuPrincipal = (
      <NetworkView moi={moi} onOuvrirWorld={w => { setShowNetwork(false); chargerWorldComplet(w.id) }} />
    )
  } else if (docsScope) {
    contenuPrincipal = (
      <DocumentsPanel
        scope={docsScope.type}
        scopeId={docsScope.id}
        scopeNom={docsScope.nom}
        moi={moi}
        onFermer={() => setDocsScope(null)}
      />
    )
  } else if (outilActif === 'search') {
    contenuPrincipal = <SearchPanel world={worldActif} moi={moi} onFermer={() => setOutilActif(null)} onNavigate={() => {}} />
  } else if (outilActif === 'calendar') {
    contenuPrincipal = <CalendarPanel world={worldActif} moi={moi} onFermer={() => setOutilActif(null)} />
  } else if (outilActif === 'reseau-docs') {
    contenuPrincipal = <ReseauDocumentsPanel world={worldActif} moi={moi} onFermer={() => setOutilActif(null)} />
  } else if (outilActif === 'shared-zones') {
    contenuPrincipal = <SharedZonesPanel onFermer={() => setOutilActif(null)} />
  } else if (outilActif === 'llm-config') {
    contenuPrincipal = <LLMConfigPanel world={worldActif} moi={moi} onFermer={() => setOutilActif(null)} />
  } else if (outilActif === 'projects') {
    contenuPrincipal = (
      <ProjectsPanel
        world={worldActif}
        moi={moi}
        onWorldMisAJour={() => chargerWorldComplet(worldActif?.id)}
      />
    )
  } else if (voteConseil) {
    contenuPrincipal = <VotePanel conseil={voteConseil} world={worldActif} moi={moi} onFermer={() => setVoteConseil(null)} />
  } else if (dmDestinataire) {
    contenuPrincipal = (
      <DMPanel world={worldActif} moi={moi} destinataire={dmDestinataire} onFermer={() => setDmDestinataire(null)} />
    )
  } else if (showMembers) {
    contenuPrincipal = (
      <MembersPanel world={worldActif} moi={moi} onFermer={() => setShowMembers(false)} onOuvrirDM={ouvrirDM} dmUnreadByMxid={dmUnreadByMxid} />
    )
  } else if (roomsOuvertes.length > 0) {
    contenuPrincipal = (
      <div className="multiview">
        {roomsOuvertes.map((ra, i) => (
          <div key={ra.room.id} className="multiview-wrapper" style={{ flex: largeurs[i] ?? 1 }}>
            <RoomView
              room={ra.room}
              building={ra.building}
              world={ra.world}
              moi={moi}
              onQuitter={() => quitterRoom(ra.room.id)}
            />
            {i < roomsOuvertes.length - 1 && (
              <div
                className="resize-handle"
                onMouseDown={e => startResize(i, e)}
                title={t('main.resizeHandle')}
              />
            )}
          </div>
        ))}
      </div>
    )
  } else {
    contenuPrincipal = (
      <div className="main-welcome">
        {worldActif ? (
          <>
            <span className="main-welcome-emoji">{worldActif.emoji}</span>
            <h2>{worldActif.nom}</h2>
            <p>{t('main.selectRoom')}</p>
          </>
        ) : (
          <>
            <span className="main-welcome-emoji">🌍</span>
            <p>{t('main.createOrJoin')}</p>
          </>
        )}
      </div>
    )
  }

  return (
    <div className="layout">
      <WorldSidebar
        worlds={worlds}
        worldActifId={worldActif?.id}
        moi={moi}
        onSelectWorld={id => {
          const w = worlds.find(w => w.id === id)
          if (w?.is_garden) { clearAllViews(); setShowJardin(true) }
          else { clearAllViews(); chargerWorldComplet(id) }
        }}
        onCreerWorld={() => setCreerWorld(true)}
        onDeconnexion={onDeconnexion}
        onNetwork={() => { clearAllViews(); setShowNetwork(true) }}
        showNetwork={showNetwork}
        onSettings={() => setShowSettings(true)}
        onDiscovery={() => { clearAllViews(); setShowDiscovery(true) }}
        showDiscovery={showDiscovery}
        onMap={() => { clearAllViews(); setShowMap(true) }}
        showMap={showMap}
        onAgents={() => { clearAllViews(); setShowAgents(true) }}
        showAgents={showAgents}
        onMyDocs={() => { clearAllViews(); setShowMyDocs(true) }}
        showMyDocs={showMyDocs}
        onIPCRA={() => { clearAllViews(); setShowIPCRA(true) }}
        showIPCRA={showIPCRA}
        onFeed={() => { clearAllViews(); setShowFeed(true) }}
        showFeed={showFeed}
        showJardin={showJardin}
        onConductor={() => { clearAllViews(); setShowConductor(true) }}
        showConductor={showConductor}
      />

      {!showNetwork && (
        <ChannelPanel
          world={worldActif}
          moi={moi}
          roomActiveIds={roomIds}
          unreadCounts={unreadCounts}
          dmUnreadTotal={dmUnreadTotal}
          onEntrerRoom={entrerRoom}
          onWorldMisAJour={() => chargerWorldComplet(worldActif?.id)}
          onOuvrirMembers={ouvrirMembers}
          onOuvrirDM={ouvrirDM}
          onOuvrirDocs={(type, id, nom) => {
            setDocsScope({ type, id, nom })
            setShowMembers(false)
            setDmDestinataire(null)
          }}
          onOuvrirOutil={ouvrirOutil}
          onOuvrirVotes={ouvrirVotes}
        />
      )}

      <div className="main-content">
        {contenuPrincipal}
      </div>

      {creerWorld && (
        <CreateWorldModal onCree={onWorldCree} onFermer={() => setCreerWorld(false)} />
      )}

      {showSettings && (
        <SettingsModal
          moi={moi}
          onSauvegarde={user => { onMoiUpdate(user); setShowSettings(false) }}
          onDeconnexion={onDeconnexion}
          onFermer={() => setShowSettings(false)}
        />
      )}

      <Toast />
      <SyncStatus />
      <LanguagePicker style={{ position: 'fixed', bottom: 12, left: 68, zIndex: 100 }} />
    </div>
  )
}

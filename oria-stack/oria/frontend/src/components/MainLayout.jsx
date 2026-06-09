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
import { applyWorldAmbiance, clearWorldAmbiance } from '../theme/theme.js'
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
import { useUrlSync, parseHash } from '../hooks/useUrlSync.js'
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
  const [showSettings, setShowSettings]     = useState(false)
  const [worldAgents, setWorldAgents]       = useState([])

  // ── Vue centrale : un seul état d'overlay exclusif (S26) ──────────
  // `roomsOuvertes` est la couche de base ; `vue` est l'overlay actif
  // par-dessus (ou null = on retombe sur les rooms / l'écran d'accueil).
  //   null
  //   { kind: 'map' | 'agents' | 'ipcra' | 'feed' | 'discovery'
  //          | 'mydocs' | 'conductor' | 'jardin' | 'network' | 'members' }
  //   { kind: 'dm',    membre }
  //   { kind: 'docs',  scope, scopeId, scopeNom }
  //   { kind: 'votes', conseil }
  //   { kind: 'outil', outil }   // search|calendar|reseau-docs|shared-zones|llm-config|projects
  const [vue, setVue] = useState(null)

  // Repère de première visite, déposé par l'onboarding (consommé une seule fois) :
  // déclenche un accueil guidé dans la zone principale.
  const [premiereVisite] = useState(() => {
    if (sessionStorage.getItem('oria_onboarding') === '1') {
      sessionStorage.removeItem('oria_onboarding')
      return true
    }
    return false
  })

  const resizeRef = useRef(null) // { index, startX, startWidths, containerWidth }

  useEffect(() => { chargerWorlds(parseHash()); gererInvitation() }, [])

  useEffect(() => {
    if (worldActif?.id) {
      api.get(`/agents/world/${worldActif.id}`).then(data => {
        setWorldAgents(Array.isArray(data) ? data : [])
      })
    }
  }, [worldActif?.id])

  // S25 — ambiance par monde : l'accent suit `World.couleur` tant qu'on est dans
  // le monde, puis revient au thème perso à la sortie.
  useEffect(() => {
    if (worldActif?.couleur) applyWorldAmbiance(worldActif.couleur)
    else clearWorldAmbiance()
    return clearWorldAmbiance
  }, [worldActif?.id, worldActif?.couleur])

  async function gererInvitation() {
    const params = new URLSearchParams(window.location.search)
    const token = params.get('invite')
    if (!token) return
    await api.post(`/invitations/${token}/rejoindre`, { user_id: moi.id })
    window.history.replaceState({}, '', '/')
    chargerWorlds()
  }

  async function chargerWorlds(cibleInitiale) {
    const data = await api.get('/worlds')
    if (Array.isArray(data)) {
      setWorlds(data)
      // Au montage : on applique la cible présente dans l'URL (deep-link / refresh) ;
      // sinon on ouvre le premier monde par défaut.
      if (cibleInitiale && cibleInitiale.kind) {
        appliquerCible(cibleInitiale)
      } else if (data.length > 0 && !worldActif) {
        chargerWorldComplet(data[0].id)
      }
    }
  }

  // Applique une cible de navigation parsée depuis l'URL (montage ou popstate).
  const appliquerCible = useCallback(async (cible) => {
    if (!cible || !cible.kind) return
    // Vues globales (indépendantes d'un monde).
    if (['feed', 'discovery', 'network', 'conductor', 'jardin', 'mydocs'].includes(cible.kind)) {
      setVue({ kind: cible.kind })
      return
    }
    if (!cible.worldId) return
    const w = await chargerWorldComplet(cible.worldId)
    if (cible.kind === 'rooms') {
      const aOuvrir = []
      for (const b of (w?.buildings || [])) {
        for (const r of (b.rooms || [])) {
          if (cible.roomIds.includes(r.id)) aOuvrir.push({ room: r, building: b, world: w })
        }
      }
      setVue(null)
      setRoomsOuvertes(aOuvrir)
      setLargeurs(aOuvrir.map(() => 1))
      aOuvrir.forEach(ra => markAsRead(ra.room.matrix_room_id))
    } else if (cible.kind === 'outil') {
      setVue({ kind: 'outil', outil: cible.outil })
    } else if (cible.kind === 'world') {
      setVue(null)
    } else {
      setVue({ kind: cible.kind }) // map | agents | ipcra | members
    }
  }, [])

  async function chargerWorldComplet(id) {
    const data = await api.get(`/worlds/${id}`)
    setWorldActif(data)
    // On ne ferme PAS les panneaux ouverts d'autres mondes (docs, outils, votes…) ;
    // seuls les overlays liés à l'ancien contexte (membres/DM/réseau) se referment.
    setVue(v => (v && ['members', 'dm', 'network'].includes(v.kind) ? null : v))
    return data
  }

  function entrerRoom(room, building) {
    setVue(null)
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
    setVue({ kind: 'members' })
  }

  function ouvrirOutil(outil) {
    setVue({ kind: 'outil', outil })
  }

  function ouvrirVotes(conseil) {
    setVue({ kind: 'votes', conseil })
  }

  function ouvrirDM(membre) {
    setVue({ kind: 'dm', membre })
    markDMAsRead(membre.matrix_user_id)
  }

  function basculerNetwork() {
    setVue(v => (v?.kind === 'network' ? null : { kind: 'network' }))
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
    (vue?.kind === 'dm' ? vue.membre?.matrix_user_id : null) || null
  )

  // S26 — l'URL suit la vue (refresh, deep-link, précédent/suivant).
  useUrlSync({ worldActif, vue, roomsOuvertes }, appliquerCible)

  // ── Zone principale ────────────────────────────────────────────
  const roomIds = new Set(roomsOuvertes.map(r => r.room.id))

  // Première pièce ouvrable du monde actif (pour le fil guidé d'accueil).
  const premiereRoomDispo = (() => {
    for (const b of (worldActif?.buildings || [])) {
      const r = (b.rooms || [])[0]
      if (r) return { room: r, building: b }
    }
    return null
  })()

  // Outil (panneau) éventuellement actif, dérivé de la vue.
  const outilActif = vue?.kind === 'outil' ? vue.outil : null
  const fermerVue = () => setVue(null)

  let contenuPrincipal
  if (vue?.kind === 'conductor') {
    contenuPrincipal = <ConductorView moi={moi} />
  } else if (vue?.kind === 'jardin') {
    contenuPrincipal = <JardinPanel moi={moi} />
  } else if (vue?.kind === 'feed') {
    contenuPrincipal = (
      <ActivityFeed
        moi={moi}
        onOuvrirWorld={async (worldId) => {
          await chargerWorldComplet(worldId)
          setVue(null)
        }}
      />
    )
  } else if (vue?.kind === 'discovery') {
    contenuPrincipal = (
      <DiscoveryPage
        moi={moi}
        onJoinWorld={() => { chargerWorlds(); setVue(null) }}
      />
    )
  } else if (vue?.kind === 'mydocs') {
    contenuPrincipal = (
      <DocumentsManager moi={moi} worldId={worldActif?.id} />
    )
  } else if (vue?.kind === 'agents') {
    contenuPrincipal = worldActif
      ? <AgentManager world={worldActif} moi={moi} onAgentsChange={() => {
          api.get(`/agents/world/${worldActif.id}`).then(d => setWorldAgents(Array.isArray(d) ? d : []))
        }} />
      : <div className="need-world-msg"><span>🤖</span><p>{t('main.needWorld')}</p></div>
  } else if (vue?.kind === 'ipcra') {
    contenuPrincipal = (
      <IPCRAPanel worldId={worldActif?.id} agents={worldAgents} />
    )
  } else if (vue?.kind === 'map') {
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
            const room = b.rooms?.[0]
            if (room) entrerRoom(room, b)
            else setVue(null)
          }}
        />
      )
    }
  } else if (vue?.kind === 'network') {
    contenuPrincipal = (
      <NetworkView moi={moi} onOuvrirWorld={w => { chargerWorldComplet(w.id) }} />
    )
  } else if (vue?.kind === 'docs') {
    contenuPrincipal = (
      <DocumentsPanel
        scope={vue.scope}
        scopeId={vue.scopeId}
        scopeNom={vue.scopeNom}
        moi={moi}
        onFermer={fermerVue}
      />
    )
  } else if (outilActif === 'search') {
    contenuPrincipal = <SearchPanel world={worldActif} moi={moi} onFermer={fermerVue} onNavigate={() => {}} />
  } else if (outilActif === 'calendar') {
    contenuPrincipal = <CalendarPanel world={worldActif} moi={moi} onFermer={fermerVue} />
  } else if (outilActif === 'reseau-docs') {
    contenuPrincipal = <ReseauDocumentsPanel world={worldActif} moi={moi} onFermer={fermerVue} />
  } else if (outilActif === 'shared-zones') {
    contenuPrincipal = <SharedZonesPanel onFermer={fermerVue} />
  } else if (outilActif === 'llm-config') {
    contenuPrincipal = <LLMConfigPanel world={worldActif} moi={moi} onFermer={fermerVue} />
  } else if (outilActif === 'projects') {
    contenuPrincipal = (
      <ProjectsPanel
        world={worldActif}
        moi={moi}
        onWorldMisAJour={() => chargerWorldComplet(worldActif?.id)}
      />
    )
  } else if (vue?.kind === 'votes') {
    contenuPrincipal = <VotePanel conseil={vue.conseil} world={worldActif} moi={moi} onFermer={fermerVue} />
  } else if (vue?.kind === 'dm') {
    contenuPrincipal = (
      <DMPanel world={worldActif} moi={moi} destinataire={vue.membre} onFermer={fermerVue} />
    )
  } else if (vue?.kind === 'members') {
    contenuPrincipal = (
      <MembersPanel world={worldActif} moi={moi} onFermer={fermerVue} onOuvrirDM={ouvrirDM} dmUnreadByMxid={dmUnreadByMxid} />
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
            <h2>{premiereVisite ? `Bienvenue dans ${worldActif.nom} ! 🎉` : worldActif.nom}</h2>
            {premiereRoomDispo ? (
              <>
                <p>{premiereVisite ? 'Ouvre ta première pièce pour commencer.' : t('main.selectRoom')}</p>
                <button
                  className="btn-primary"
                  style={{ marginTop: 16 }}
                  onClick={() => entrerRoom(premiereRoomDispo.room, premiereRoomDispo.building)}
                >
                  ▶ Ouvrir « {premiereRoomDispo.room.nom} »
                </button>
              </>
            ) : premiereVisite ? (
              <p>Ton monde est prêt ! Crée ton premier espace puis une pièce
                 depuis le panneau de gauche&nbsp;←</p>
            ) : (
              <p>{t('main.selectRoom')}</p>
            )}
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
          if (w?.is_garden) { setVue({ kind: 'jardin' }) }
          else { setVue(null); chargerWorldComplet(id) }
        }}
        onCreerWorld={() => setCreerWorld(true)}
        onDeconnexion={onDeconnexion}
        onNetwork={() => setVue({ kind: 'network' })}
        onSettings={() => setShowSettings(true)}
        onDiscovery={() => setVue({ kind: 'discovery' })}
        onMap={() => setVue({ kind: 'map' })}
        onAgents={() => setVue({ kind: 'agents' })}
        onMyDocs={() => setVue({ kind: 'mydocs' })}
        onIPCRA={() => setVue({ kind: 'ipcra' })}
        onFeed={() => setVue({ kind: 'feed' })}
        onConductor={() => setVue({ kind: 'conductor' })}
        vueActive={vue?.kind}
      />

      {vue?.kind !== 'network' && (
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
          onOuvrirDocs={(type, id, nom) => setVue({ kind: 'docs', scope: type, scopeId: id, scopeNom: nom })}
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

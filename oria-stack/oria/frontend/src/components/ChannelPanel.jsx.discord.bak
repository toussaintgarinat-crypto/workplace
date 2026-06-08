import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../services/api.js'
import CreateBuildingModal from './CreateBuildingModal.jsx'
import CreateQuartierModal from './CreateQuartierModal.jsx'
import AddRoomModal from './AddRoomModal.jsx'
import EditBuildingModal from './EditBuildingModal.jsx'
import EditRoomModal from './EditRoomModal.jsx'
import EditQuartierModal from './EditQuartierModal.jsx'
import InviteModal from './InviteModal.jsx'
import AbonnementsModal from './AbonnementsModal.jsx'

export default function ChannelPanel({
  world, moi, roomActiveIds, unreadCounts, dmUnreadTotal,
  onEntrerRoom, onWorldMisAJour,
  onOuvrirMembers, onOuvrirDM, onOuvrirDocs, onOuvrirOutil,
}) {
  const { t } = useTranslation()
  const [collapsed, setCollapsed]         = useState({})
  const [creerBuilding, setCreerBuilding] = useState(false)
  const [creerQuartier, setCreerQuartier] = useState(false)
  const [quartierCible, setQuartierCible] = useState(null)
  const [addRoomBuilding, setAddRoomBuilding] = useState(null)
  const [editBuilding, setEditBuilding]   = useState(null)
  const [editRoom, setEditRoom]           = useState(null)
  const [editQuartier, setEditQuartier]   = useState(null)
  const [showInvite, setShowInvite]           = useState(false)
  const [showAbonnements, setShowAbonnements] = useState(false)

  const estProprietaire = world?.owner_id === moi?.id

  function toggleCollapse(id) {
    setCollapsed(p => ({ ...p, [id]: !p[id] }))
  }

  async function supprimerBuilding(building) {
    if (!confirm(t('channel.deleteBuilding', { name: building.nom }))) return
    await api.del(`/buildings/${building.id}`)
    onWorldMisAJour()
  }

  async function supprimerRoom(room) {
    if (!confirm(t('channel.deleteRoom', { name: room.nom }))) return
    await api.del(`/buildings/rooms/${room.id}`)
    onWorldMisAJour()
  }

  async function supprimerQuartier(q) {
    if (!confirm(t('channel.deleteDistrict', { name: q.nom }))) return
    await api.del(`/quartiers/${q.id}`)
    onWorldMisAJour()
  }

  if (!world) return (
    <div className="channel-panel vide">
      <div className="channel-panel-empty">
        <span>🌍</span>
        <p>{t('channel.selectWorld')}</p>
      </div>
    </div>
  )

  const buildingsLibres = world.buildings_libres || world.buildings || []
  const quartiers       = world.quartiers || []

  return (
    <div className="channel-panel">
      {/* Header monde */}
      <div className="channel-panel-header" style={{ borderBottom: `2px solid ${world.couleur || '#5865F2'}` }}>
        <div className="channel-panel-world">
          <span className="channel-panel-emoji">{world.emoji}</span>
          <span className="channel-panel-nom">{world.nom}</span>
        </div>
        <div className="channel-panel-header-actions">
          {estProprietaire && (
            <button className="channel-panel-icon-btn" onClick={() => setShowInvite(true)} title={t('channel.inviteTitle')}>✉</button>
          )}
          {estProprietaire && (
            <button className="channel-panel-icon-btn" onClick={() => setShowAbonnements(true)} title={t('channel.manageSubscriptions')}>💳</button>
          )}
          <button
            className="channel-panel-icon-btn"
            onClick={() => onOuvrirDocs?.('world', world.id, world.nom)}
            title={t('channel.worldDocs')}
          >📁</button>
          <button className="channel-panel-icon-btn" onClick={onOuvrirMembers} title={t('channel.membersAgents')} style={{ position: 'relative' }}>
            👥 <span>{world.membres?.length || 0}</span>
            {dmUnreadTotal > 0 && (
              <span className="unread-badge" style={{ position: 'absolute', top: -4, right: -4 }}>
                {dmUnreadTotal > 99 ? '99+' : dmUnreadTotal}
              </span>
            )}
          </button>
        </div>
      </div>

      {/* Liste des canaux */}
      <div className="channel-panel-body">

        {/* Bâtiments sans quartier */}
        {buildingsLibres.length > 0 && (
          <BuildingSection
            building={null}
            rooms={buildingsLibres.flatMap(b =>
              (b.rooms || []).map(r => ({ ...r, _building: b }))
            )}
            buildings={buildingsLibres}
            roomActiveIds={roomActiveIds}
            unreadCounts={unreadCounts}
            onEntrerRoom={onEntrerRoom}
            onOuvrirDocs={onOuvrirDocs}
            estProprietaire={estProprietaire}
            onEditerBuilding={b => setEditBuilding(b)}
            onSupprimerBuilding={supprimerBuilding}
            onAjouterRoom={b => setAddRoomBuilding(b)}
            onEditerRoom={r => setEditRoom(r)}
            onSupprimerRoom={supprimerRoom}
            collapsed={collapsed}
            toggleCollapse={toggleCollapse}
          />
        )}

        {/* Quartiers */}
        {quartiers.map(q => (
          <div key={q.id} className="channel-quartier">
            <div className="channel-category-header" onClick={() => toggleCollapse(q.id)}>
              <span className="channel-category-arrow">{collapsed[q.id] ? '▶' : '▼'}</span>
              <span className="channel-category-emoji">{q.emoji}</span>
              <span className="channel-category-nom">{q.nom}</span>
              {estProprietaire && (
                <div className="channel-category-actions" onClick={e => e.stopPropagation()}>
                  <button onClick={() => { setQuartierCible(q.id); setCreerBuilding(true) }} title={t('channel.addService')}>＋</button>
                  <button onClick={() => setEditQuartier(q)} title={t('common.edit')}>✎</button>
                  <button onClick={() => supprimerQuartier(q)} title={t('common.delete')}>✕</button>
                </div>
              )}
            </div>
            {!collapsed[q.id] && q.buildings.map(b => (
              <BuildingSection
                key={b.id}
                building={b}
                rooms={b.rooms || []}
                buildings={null}
                roomActiveIds={roomActiveIds}
                unreadCounts={unreadCounts}
                onEntrerRoom={r => onEntrerRoom(r, b)}
                onOuvrirDocs={onOuvrirDocs}
                estProprietaire={estProprietaire}
                onEditerBuilding={() => setEditBuilding(b)}
                onSupprimerBuilding={() => supprimerBuilding(b)}
                onAjouterRoom={() => setAddRoomBuilding(b)}
                onEditerRoom={r => setEditRoom(r)}
                onSupprimerRoom={supprimerRoom}
                collapsed={collapsed}
                toggleCollapse={toggleCollapse}
              />
            ))}
          </div>
        ))}

        {/* Outils */}
        <div className="channel-section-title">{t('channel.tools')}</div>
        <div className="channel-outils">
          <button className="channel-outil-btn" onClick={() => onOuvrirOutil?.('search')}>
            <span>🔍</span> {t('channel.search')}
          </button>
          <button className="channel-outil-btn" onClick={() => onOuvrirOutil?.('calendar')}>
            <span>📅</span> {t('channel.calendar')}
          </button>
          <button className="channel-outil-btn" onClick={() => onOuvrirOutil?.('projects')}>
            <span>📁</span> Projets
          </button>
          <button className="channel-outil-btn" onClick={() => onOuvrirOutil?.('reseau-docs')}>
            <span>🏘</span> {t('channel.network')}
          </button>
          <button className="channel-outil-btn" onClick={() => onOuvrirOutil?.('shared-zones')}>
            <span>🔗</span> {t('channel.zones')}
          </button>
          {estProprietaire && (
            <button className="channel-outil-btn" onClick={() => onOuvrirOutil?.('llm-config')}>
              <span>🤖</span> {t('channel.aiConfig')}
            </button>
          )}
        </div>

        {/* Boutons admin */}
        {estProprietaire && (
          <div className="channel-panel-admin">
            <button onClick={() => { setQuartierCible(null); setCreerBuilding(true) }}>
              <span>＋</span> {t('channel.addService')}
            </button>
            <button onClick={() => setCreerQuartier(true)}>
              <span>🏘</span> {t('channel.addDistrict')}
            </button>
          </div>
        )}
      </div>

      {/* Modals */}
      {creerBuilding && (
        <CreateBuildingModal worldId={world.id} quartierId={quartierCible}
          onCree={() => { setCreerBuilding(false); setQuartierCible(null); onWorldMisAJour() }}
          onFermer={() => setCreerBuilding(false)} />
      )}
      {creerQuartier && (
        <CreateQuartierModal worldId={world.id}
          onCree={() => { setCreerQuartier(false); onWorldMisAJour() }}
          onFermer={() => setCreerQuartier(false)} />
      )}
      {addRoomBuilding && (
        <AddRoomModal building={addRoomBuilding} worldId={world.id}
          onCree={() => { setAddRoomBuilding(null); onWorldMisAJour() }}
          onFermer={() => setAddRoomBuilding(null)} />
      )}
      {editBuilding && (
        <EditBuildingModal building={editBuilding}
          onSave={() => { setEditBuilding(null); onWorldMisAJour() }}
          onFermer={() => setEditBuilding(null)} />
      )}
      {editRoom && (
        <EditRoomModal room={editRoom} worldId={world.id}
          onSave={() => { setEditRoom(null); onWorldMisAJour() }}
          onFermer={() => setEditRoom(null)} />
      )}
      {showAbonnements && (
        <AbonnementsModal world={world} onFermer={() => setShowAbonnements(false)} />
      )}
      {editQuartier && (
        <EditQuartierModal quartier={editQuartier}
          onSave={() => { setEditQuartier(null); onWorldMisAJour() }}
          onFermer={() => setEditQuartier(null)} />
      )}
      {showInvite && (
        <InviteModal world={world} onFermer={() => setShowInvite(false)} />
      )}
    </div>
  )
}

/* ── Section bâtiment ── */
function BuildingSection({
  building, rooms, buildings,
  roomActiveIds, unreadCounts, onEntrerRoom, estProprietaire,
  onEditerBuilding, onSupprimerBuilding, onAjouterRoom,
  onEditerRoom, onSupprimerRoom,
  onOuvrirDocs,
  collapsed, toggleCollapse,
}) {
  const { t } = useTranslation()
  // Si buildings est fourni, on affiche plusieurs bâtiments sans header de quartier
  if (buildings) {
    return buildings.map(b => (
      <BuildingSection
        key={b.id}
        building={b}
        rooms={b.rooms || []}
        buildings={null}
        roomActiveIds={roomActiveIds}
        unreadCounts={unreadCounts}
        onEntrerRoom={r => onEntrerRoom(r, b)}
        estProprietaire={estProprietaire}
        onEditerBuilding={() => onEditerBuilding(b)}
        onSupprimerBuilding={() => onSupprimerBuilding(b)}
        onAjouterRoom={() => onAjouterRoom(b)}
        onEditerRoom={onEditerRoom}
        onSupprimerRoom={onSupprimerRoom}
        onOuvrirDocs={onOuvrirDocs}
        collapsed={collapsed}
        toggleCollapse={toggleCollapse}
      />
    ))
  }

  const id = building?.id
  const isCollapsed = id ? collapsed[id] : false

  return (
    <div className="channel-building-section">
      {building && (
        <div className="channel-category-header" onClick={() => toggleCollapse(id)}>
          <span className="channel-category-arrow">{isCollapsed ? '▶' : '▼'}</span>
          <span className="channel-category-emoji">{building.emoji}</span>
          <span className="channel-category-nom">{building.nom}</span>
          <div className="channel-category-actions" onClick={e => e.stopPropagation()}>
            <button
              onClick={() => onOuvrirDocs?.('building', building.id, building.nom)}
              title={t('channel.buildingDocs')}
            >📁</button>
            {estProprietaire && (<>
              <button onClick={onAjouterRoom} title={t('channel.addRoom')}>＋</button>
              <button onClick={onEditerBuilding} title={t('common.edit')}>✎</button>
              <button onClick={onSupprimerBuilding} title={t('common.delete')}>✕</button>
            </>)}
          </div>
        </div>
      )}

      {!isCollapsed && (
        <div className="channel-rooms">
          {rooms.map(room => {
            const icone   = room.type === 'vocal' ? '🔊' : room.type === 'texte' ? '💬' : room.type === 'broadcast' ? '📢' : '⚡'
            const actif   = roomActiveIds?.has(room.id)
            const unread  = room.matrix_room_id ? (unreadCounts?.[room.matrix_room_id] || 0) : 0
            const bloque  = room.acces_restreint === 'cadenas' && room.a_acces === false
            return (
              <div key={room.id} className={`channel-room-item ${actif ? 'actif' : ''} ${unread > 0 ? 'has-unread' : ''} ${bloque ? 'bloque' : ''}`}>
                <button
                  className="channel-room-btn"
                  onClick={() => bloque ? null : onEntrerRoom(room)}
                  style={bloque ? { opacity: 0.5, cursor: 'not-allowed' } : {}}
                  title={bloque ? t('channel.subscribe', { plans: (room.abonnements_requis || []).map(a => a.nom).join(' ou ') }) : room.nom}
                >
                  <span className="channel-room-icone">{icone}</span>
                  <span className="channel-room-nom">{room.nom}</span>
                  {room.acces_restreint && room.acces_restreint !== 'libre' && (
                    <span style={{ marginLeft: 4, fontSize: 12 }}>{bloque ? '🔒' : '🔓'}</span>
                  )}
                  {actif && <span className="channel-room-open-dot" />}
                  {unread > 0 && !actif && <span className="unread-badge">{unread > 99 ? '99+' : unread}</span>}
                </button>
                {estProprietaire && (
                  <div className="channel-room-actions">
                    <button onClick={() => onEditerRoom(room)} title={t('common.edit')}>✎</button>
                    <button onClick={() => onSupprimerRoom(room)} title={t('common.delete')}>✕</button>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

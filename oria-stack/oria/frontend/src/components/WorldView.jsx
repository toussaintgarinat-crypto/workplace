import { useState } from 'react'
import { api } from '../services/api.js'
import BuildingCard from './BuildingCard.jsx'
import CreateBuildingModal from './CreateBuildingModal.jsx'
import CreateQuartierModal from './CreateQuartierModal.jsx'
import AddRoomModal from './AddRoomModal.jsx'
import EditBuildingModal from './EditBuildingModal.jsx'
import EditRoomModal from './EditRoomModal.jsx'
import EditQuartierModal from './EditQuartierModal.jsx'
import InviteModal from './InviteModal.jsx'

export default function WorldView({ world, moi, roomActive, onEntrerRoom, onWorldMisAJour, onOuvrirMembers }) {
  const [creerBuilding, setCreerBuilding]     = useState(false)
  const [creerQuartier, setCreerQuartier]     = useState(false)
  const [quartierCible, setQuartierCible]     = useState(null)
  const [addRoomBuilding, setAddRoomBuilding] = useState(null)
  const [editBuilding, setEditBuilding]       = useState(null)
  const [editRoom, setEditRoom]               = useState(null)
  const [editQuartier, setEditQuartier]       = useState(null)
  const [showInvite, setShowInvite]           = useState(false)

  const estProprietaire = world?.owner_id === moi?.id

  function ouvrirModalBuilding(quartierId = null) {
    setQuartierCible(quartierId)
    setCreerBuilding(true)
  }

  function apresCreationBuilding() {
    setCreerBuilding(false)
    setQuartierCible(null)
    onWorldMisAJour()
  }

  async function supprimerBuilding(building) {
    if (!confirm(`Supprimer l'espace « ${building.nom} » ?`)) return
    await api.del(`/buildings/${building.id}`)
    onWorldMisAJour()
  }

  async function supprimerRoom(room) {
    if (!confirm(`Supprimer la pièce « ${room.nom} » ?`)) return
    await api.del(`/buildings/rooms/${room.id}`)
    onWorldMisAJour()
  }

  async function supprimerQuartier(quartier) {
    if (!confirm(`Supprimer le quartier « ${quartier.nom} » et tous ses espaces ?`)) return
    await api.del(`/quartiers/${quartier.id}`)
    onWorldMisAJour()
  }

  if (!world) return (
    <div className="world-view vide">
      <div className="world-vide-msg">
        <span>🌍</span>
        <p>Crée ton premier monde avec le <strong>＋</strong> à gauche</p>
      </div>
    </div>
  )

  const buildingsLibres = world.buildings_libres || world.buildings || []
  const quartiers       = world.quartiers  || []

  return (
    <div className="world-view">
      {/* Header du monde */}
      <div className="world-header">
        <div className="world-header-info">
          <span className="world-header-emoji">{world.emoji}</span>
          <div>
            <h2 className="world-header-nom">{world.nom}</h2>
            {world.description && <p className="world-header-desc">{world.description}</p>}
          </div>
        </div>
        <div className="world-header-actions">
          <button className="btn-membres" onClick={onOuvrirMembers}>
            👥 {world.membres?.length || 0}
          </button>
          {estProprietaire && (
            <>
              <button className="btn-inviter" onClick={() => setShowInvite(true)}>
                ✉ Inviter
              </button>
              <button className="btn-ajouter btn-secondary" onClick={() => setCreerQuartier(true)}>
                🏘 Quartier
              </button>
              <button className="btn-ajouter" onClick={() => ouvrirModalBuilding(null)}>
                ＋ Espace
              </button>
            </>
          )}
        </div>
      </div>

      <div className="world-content">
        {/* Bâtiments libres (sans quartier) */}
        {buildingsLibres.length > 0 && (
          <section className="section-libre">
            <div className="buildings-grid">
              {buildingsLibres.map(b => (
                <BuildingCard
                  key={b.id}
                  building={b}
                  roomActiveId={roomActive?.room?.id}
                  onEntrerRoom={(room) => onEntrerRoom(room, b)}
                  onAjouterRoom={estProprietaire ? setAddRoomBuilding : null}
                  onEditer={estProprietaire ? () => setEditBuilding(b) : null}
                  onSupprimer={estProprietaire ? () => supprimerBuilding(b) : null}
                  onEditerRoom={estProprietaire ? (room) => setEditRoom(room) : null}
                  onSupprimerRoom={estProprietaire ? (room) => supprimerRoom(room) : null}
                />
              ))}
              {estProprietaire && (
                <button className="btn-add-building-inline" onClick={() => ouvrirModalBuilding(null)}>
                  <span>＋</span>
                  <span>Ajouter un espace</span>
                </button>
              )}
            </div>
          </section>
        )}

        {buildingsLibres.length === 0 && quartiers.length === 0 && (
          <div className="buildings-vide">
            <p>Aucun espace pour l'instant.</p>
            {estProprietaire && (
              <div style={{ display: 'flex', gap: 12, justifyContent: 'center', flexWrap: 'wrap' }}>
                <button className="btn-ajouter" onClick={() => ouvrirModalBuilding(null)}>＋ Créer un espace</button>
                <button className="btn-ajouter btn-secondary" onClick={() => setCreerQuartier(true)}>🏘 Créer un quartier</button>
              </div>
            )}
          </div>
        )}

        {/* Quartiers */}
        {quartiers.map(q => (
          <section key={q.id} className="quartier-section" style={{ '--qcouleur': q.couleur }}>
            <div className="quartier-header">
              <div className="quartier-header-left">
                <span className="quartier-emoji">{q.emoji}</span>
                <div>
                  <span className="quartier-nom">{q.nom}</span>
                  {q.description && <span className="quartier-desc">{q.description}</span>}
                </div>
              </div>
              {estProprietaire && (
                <div className="quartier-actions">
                  <button className="btn-edit-quartier" onClick={() => setEditQuartier(q)} title="Modifier">✎</button>
                  <button className="btn-del-quartier" onClick={() => supprimerQuartier(q)} title="Supprimer">✕</button>
                  <button className="btn-ajouter btn-sm" onClick={() => ouvrirModalBuilding(q.id)}>＋ Espace</button>
                </div>
              )}
            </div>

            <div className="buildings-grid">
              {q.buildings.map(b => (
                <BuildingCard
                  key={b.id}
                  building={b}
                  roomActiveId={roomActive?.room?.id}
                  onEntrerRoom={(room) => onEntrerRoom(room, b)}
                  onAjouterRoom={estProprietaire ? setAddRoomBuilding : null}
                  onEditer={estProprietaire ? () => setEditBuilding(b) : null}
                  onSupprimer={estProprietaire ? () => supprimerBuilding(b) : null}
                  onEditerRoom={estProprietaire ? (room) => setEditRoom(room) : null}
                  onSupprimerRoom={estProprietaire ? (room) => supprimerRoom(room) : null}
                />
              ))}
              {q.buildings.length === 0 && (
                <p className="quartier-vide">Aucun espace dans ce quartier.</p>
              )}
            </div>
          </section>
        ))}
      </div>

      {/* Modals */}
      {creerBuilding && (
        <CreateBuildingModal
          worldId={world.id}
          quartierId={quartierCible}
          onCree={apresCreationBuilding}
          onFermer={() => setCreerBuilding(false)}
        />
      )}
      {creerQuartier && (
        <CreateQuartierModal
          worldId={world.id}
          onCree={() => { setCreerQuartier(false); onWorldMisAJour() }}
          onFermer={() => setCreerQuartier(false)}
        />
      )}
      {addRoomBuilding && (
        <AddRoomModal
          building={addRoomBuilding}
          onCree={() => { setAddRoomBuilding(null); onWorldMisAJour() }}
          onFermer={() => setAddRoomBuilding(null)}
        />
      )}
      {editBuilding && (
        <EditBuildingModal
          building={editBuilding}
          onSave={() => { setEditBuilding(null); onWorldMisAJour() }}
          onFermer={() => setEditBuilding(null)}
        />
      )}
      {editRoom && (
        <EditRoomModal
          room={editRoom}
          onSave={() => { setEditRoom(null); onWorldMisAJour() }}
          onFermer={() => setEditRoom(null)}
        />
      )}
      {editQuartier && (
        <EditQuartierModal
          quartier={editQuartier}
          onSave={() => { setEditQuartier(null); onWorldMisAJour() }}
          onFermer={() => setEditQuartier(null)}
        />
      )}
      {showInvite && (
        <InviteModal
          world={world}
          onFermer={() => setShowInvite(false)}
        />
      )}
    </div>
  )
}

import { useState } from 'react'
import { useTranslation } from 'react-i18next'

export default function BuildingCard({
  building, roomActiveId, onEntrerRoom, onAjouterRoom,
  onEditer, onSupprimer, onEditerRoom, onSupprimerRoom,
}) {
  const { t } = useTranslation()
  const { type, nom, emoji, couleur, rooms = [], description } = building
  const [menuOpen, setMenuOpen] = useState(false)

  const etages = type === 'immeuble'
    ? [...new Set(rooms.map(r => r.etage))].sort((a, b) => b - a)
    : null

  return (
    <div className={`building-card type-${type}`} style={{ '--couleur': couleur }}>
      <div className="building-header">
        <div className="building-icon">{emoji}</div>
        <div className="building-info">
          <span className="building-nom">{nom}</span>
          <span className="building-type-badge">{t(`building.${type}`)}</span>
        </div>
        {(onEditer || onSupprimer) && (
          <div className="building-menu-wrap">
            <button className="btn-building-menu" onClick={() => setMenuOpen(v => !v)}>⚙</button>
            {menuOpen && (
              <div className="building-menu" onClick={() => setMenuOpen(false)}>
                {onEditer && <button onClick={onEditer}>✎ {t('common.edit')}</button>}
                {onSupprimer && <button className="danger" onClick={onSupprimer}>🗑 {t('common.delete')}</button>}
              </div>
            )}
          </div>
        )}
      </div>

      {description && <p className="building-desc">{description}</p>}

      {type === 'immeuble' ? (
        <div className="immeuble-etages">
          {etages.map(etage => (
            <div key={etage} className="immeuble-etage">
              <span className="etage-label">{etage === 0 ? t('building.floorGround') : t('building.floorN', { n: etage })}</span>
              <div className="etage-rooms">
                {rooms.filter(r => r.etage === etage).map(room => (
                  <RoomChip key={room.id} room={room} actif={roomActiveId === room.id}
                    onClick={() => onEntrerRoom(room)}
                    onEditer={onEditerRoom ? () => onEditerRoom(room) : null}
                    onSupprimer={onSupprimerRoom ? () => onSupprimerRoom(room) : null}
                  />
                ))}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="building-rooms">
          {rooms.map(room => (
            <RoomChip key={room.id} room={room} actif={roomActiveId === room.id}
              onClick={() => onEntrerRoom(room)}
              onEditer={onEditerRoom ? () => onEditerRoom(room) : null}
              onSupprimer={onSupprimerRoom ? () => onSupprimerRoom(room) : null}
            />
          ))}
        </div>
      )}

      {onAjouterRoom && (
        <div className="building-footer">
          <button className="btn-add-room" onClick={() => onAjouterRoom(building)}>
            ＋ {t('building.addRoom')}
          </button>
        </div>
      )}
    </div>
  )
}

function RoomChip({ room, actif, onClick, onEditer, onSupprimer }) {
  const { t } = useTranslation()
  const icone = room.type === 'vocal' ? '🔊' : room.type === 'texte' ? '💬' : '⚡'
  return (
    <div className="room-chip-wrap">
      <button className={`room-chip ${actif ? 'actif' : ''}`} onClick={onClick} title={room.nom}>
        <span className="room-chip-icone">{icone}</span>
        <span className="room-chip-nom">{room.nom}</span>
        {actif && <span className="room-chip-dot" />}
      </button>
      {(onEditer || onSupprimer) && (
        <div className="room-chip-actions">
          {onEditer && <button className="btn-room-edit" onClick={e => { e.stopPropagation(); onEditer() }} title={t('common.edit')}>✎</button>}
          {onSupprimer && <button className="btn-room-del" onClick={e => { e.stopPropagation(); onSupprimer() }} title={t('common.delete')}>✕</button>}
        </div>
      )}
    </div>
  )
}

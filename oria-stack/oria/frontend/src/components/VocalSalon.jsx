import { useParticipants, useLocalParticipant, useTrackToggle, RoomAudioRenderer, ParticipantTile } from '@livekit/components-react'
import { Track } from 'livekit-client'
import { useTranslation } from 'react-i18next'

export default function VocalSalon({ room, moi, onQuitter }) {
  const { t } = useTranslation()
  const remoteParticipants = useParticipants()
  const { localParticipant } = useLocalParticipant()

  const { toggle: toggleMic, enabled: micOn } = useTrackToggle({ source: Track.Source.Microphone })
  const { toggle: toggleCam, enabled: camOn } = useTrackToggle({ source: Track.Source.Camera })

  const tousLesParticipants = localParticipant
    ? [localParticipant, ...remoteParticipants]
    : remoteParticipants

  const avecCamera = tousLesParticipants.filter(p => p?.isCameraEnabled)
  const sansCamera = tousLesParticipants.filter(p => !p?.isCameraEnabled)

  return (
    <div className="vocal-salon">
      <RoomAudioRenderer />

      {/* Zone vidéo — visible seulement si quelqu'un active sa caméra */}
      {avecCamera.length > 0 && (
        <div className={`vocal-videos vocal-videos-${Math.min(avecCamera.length, 4)}`}>
          {avecCamera.map(p => (
            <div key={p.sid} className="vocal-video-tile">
              <ParticipantTile participant={p} />
            </div>
          ))}
        </div>
      )}

      {/* Liste des membres dans le salon (style Discord) */}
      <div className="vocal-membres-zone">
        <div className="vocal-membres-titre">
          <span className="vocal-icon">🔊</span>
          <span>{room.nom}</span>
          <span className="vocal-count">{tousLesParticipants.length}</span>
        </div>
        <div className="vocal-membres-liste">
          {tousLesParticipants.map(p => {
            if (!p) return null
            const isLocal = p.sid === localParticipant?.sid
            const nom = p.name || p.identity || t('vocal.unknown')
            const initiale = nom.charAt(0).toUpperCase()
            return (
              <div key={p.sid} className={`vocal-membre ${p.isSpeaking ? 'parle' : ''}`}>
                <div className={`vocal-membre-avatar ${p.isSpeaking ? 'parle' : ''}`}>
                  {isLocal ? (moi.avatar_emoji || initiale) : initiale}
                  {!p.isMicrophoneEnabled && (
                    <span className="vocal-membre-mute-badge">🔇</span>
                  )}
                </div>
                <span className="vocal-membre-nom">
                  {nom} {isLocal && <span className="vocal-vous">{t('vocal.you')}</span>}
                </span>
                <div className="vocal-membre-icones">
                  {p.isCameraEnabled && <span title={t('vocal.camActive')}>📹</span>}
                  {!p.isMicrophoneEnabled && <span title={t('vocal.micOff')}>🔇</span>}
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {/* Barre de contrôle */}
      <div className="vocal-controls">
        <div className="vocal-controls-info">
          <span className="vocal-controls-room">{room.emoji} {room.nom}</span>
          <span className="vocal-controls-status">{t('vocal.connected')}</span>
        </div>
        <div className="vocal-controls-btns">
          <button
            className={`vocal-btn ${micOn ? 'actif' : 'inactif'}`}
            onClick={toggleMic}
            title={micOn ? t('vocal.muteMic') : t('vocal.unmuteMic')}
          >
            {micOn ? '🎤' : '🔇'}
            <span>{micOn ? t('vocal.micLabel') : t('vocal.muteLabel')}</span>
          </button>

          <button
            className={`vocal-btn ${camOn ? 'actif' : 'inactif'}`}
            onClick={toggleCam}
            title={camOn ? t('vocal.camOff') : t('vocal.camOn')}
          >
            {camOn ? '📹' : '📷'}
            <span>{t('vocal.camLabel')}</span>
          </button>

          <button
            className="vocal-btn vocal-btn-quitter"
            onClick={onQuitter}
            title={t('vocal.quitSalon')}
          >
            📵
            <span>{t('vocal.quitLabel')}</span>
          </button>
        </div>
      </div>
    </div>
  )
}

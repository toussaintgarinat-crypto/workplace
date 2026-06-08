import { useState, useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { LiveKitRoom } from '@livekit/components-react'
import { api, authHeaders } from '../services/api.js'
import { useMatrixRoom } from '../hooks/useMatrixRoom.js'
import { getMatrixClient } from '../services/matrixClient.js'
import VocalSalon from './VocalSalon.jsx'
import CoinPanel from './CoinPanel.jsx'

const LIVEKIT_URL = import.meta.env.VITE_LIVEKIT_URL || 'ws://localhost:7880'
const API_URL     = import.meta.env.VITE_API_URL      || 'http://localhost:8000'

const EMOJIS_REACTION = ['👍','❤️','😂','😮','😢','🔥','🎉','👏']

export default function RoomView({ room, building, world, moi, onQuitter }) {
  const { t } = useTranslation()
  const [token, setToken]         = useState(null)
  const [onglet, setOnglet]       = useState(room.type === 'texte' ? 'chat' : 'vocal')
  const [fichiers, setFichiers]   = useState([])
  const [emojiPickerId, setEmojiPickerId] = useState(null)
  const [texte, setTexte]         = useState('')
  const [accesPaye, setAccesPaye] = useState(null) // null=loading, true=ok, false=paywall
  const [infoAcces, setInfoAcces] = useState(null)
  const basRef = useRef(null)
  const fileRef = useRef(null)

  const matrix   = useMatrixRoom(room.matrix_room_id)
  const messages = matrix.messages

  useEffect(() => {
    verifierAcces()
  }, [room.id])

  useEffect(() => {
    if (accesPaye) {
      chargerFichiers()
      if (room.type !== 'texte') obtenirToken()
    }
  }, [room.id, accesPaye])

  async function verifierAcces() {
    if (!room.est_payante) { setAccesPaye(true); return }
    const data = await api.get(`/rooms/${room.id}/acces-paye`)
    if (data) {
      setAccesPaye(data.acces)
      setInfoAcces(data)
    } else {
      setAccesPaye(false)
    }
  }

  async function demanderCheckout() {
    const data = await api.post(`/rooms/${room.id}/checkout-acces`, {})
    if (data?.checkout_url) window.open(data.checkout_url, '_blank')
    else if (data?.acces) setAccesPaye(true)
  }

  async function chargerFichiers() {
    const data = await api.get(`/files/room/${room.id}`)
    if (Array.isArray(data)) setFichiers(data)
  }

  async function obtenirToken() {
    const data = await api.post('/tokens/', { room_id: room.id, user_id: moi.id, user_nom: moi.nom })
    setToken(data.token)
  }

  async function envoyer(e) {
    e.preventDefault()
    if (!texte.trim() || !matrix.disponible) return

    const client = getMatrixClient()
    await client.sendEvent(room.matrix_room_id, 'm.room.message', {
      msgtype: 'm.text',
      body: texte.trim(),
      'io.oria.nom':   moi.nom,
      'io.oria.emoji': moi.avatar_emoji,
    })
    setTexte('')
  }

  async function supprimerMessage(id) {
    await matrix.supprimer(id)
  }

  async function reagir(messageId, emoji) {
    setEmojiPickerId(null)
    await matrix.reagir(messageId, emoji)
  }

  async function uploaderFichier(e) {
    const file = e.target.files[0]
    if (!file) return
    const form = new FormData()
    form.append('file', file)
    form.append('uploaded_by', moi.id)
    form.append('uploader_nom', moi.nom)
    const res = await fetch(`${API_URL}/api/files/upload/${room.id}`, {
      method: 'POST',
      credentials: 'include',
      headers: authHeaders(),
      body: form,
    })
    if (res.ok) chargerFichiers()
    e.target.value = ''
  }

  async function supprimerFichier(id) {
    await api.del(`/files/${id}`)
    chargerFichiers()
  }

  useEffect(() => { basRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])

  // Écran chargement accès
  if (accesPaye === null) {
    return (
      <div className="room-view" style={{ display: 'flex', alignItems: 'center',
                                          justifyContent: 'center', color: '#72767d' }}>
        {t('room.checkingAccess')}
      </div>
    )
  }

  // Paywall
  if (accesPaye === false) {
    const prix = infoAcces?.prix_acces
    const devise = infoAcces?.devise_acces || 'EUR'
    const type = infoAcces?.type_paiement
    return (
      <div className="room-view" style={{ display: 'flex', alignItems: 'center',
                                          justifyContent: 'center' }}>
        <div style={{
          background: '#2b2d31', borderRadius: 16, padding: '40px 48px',
          textAlign: 'center', maxWidth: 400, boxShadow: '0 8px 32px rgba(0,0,0,.4)',
        }}>
          <div style={{ fontSize: 48, marginBottom: 12 }}>🔒</div>
          <h2 style={{ color: '#fff', marginBottom: 8 }}>{room.emoji} {room.nom}</h2>
          <p style={{ color: '#b5bac1', fontSize: 14, marginBottom: 20 }}>
            {t('room.paidRoom')}
            {prix ? ` ${t('room.paidFrom', { price: prix, currency: devise })}${type === 'abonnement' ? t('room.paidMonthly') : ''}.` : ''}
          </p>
          <button
            onClick={demanderCheckout}
            style={{
              padding: '12px 32px', borderRadius: 10, border: 'none',
              background: '#5865f2', color: 'white', fontSize: 15,
              fontWeight: 700, cursor: 'pointer',
            }}
          >
            {t('room.payAccess')}
          </button>
          <div style={{ marginTop: 16 }}>
            <button onClick={onQuitter}
              style={{ background: 'none', border: 'none', color: '#72767d',
                       cursor: 'pointer', fontSize: 13 }}>
              {t('common.back')}
            </button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="room-view" onClick={() => setEmojiPickerId(null)}>
      <div className="room-header">
        <div className="room-header-info">
          <span>{room.emoji}</span>
          <span className="room-header-nom">{room.nom}</span>
          {room.status === 'closed' && (
            <span style={{
              fontSize: 11, padding: '2px 8px', borderRadius: 10,
              background: '#3a3a3a', color: '#aaa', fontWeight: 600,
            }}>🔒 Terminé</span>
          )}
          {matrix.disponible && room.status !== 'closed' && (
            <span title={t('room.encryptedE2EE')} style={{ fontSize: 11, color: '#57F287' }}>🔒</span>
          )}
          <span className="room-header-building" style={{ color: building.couleur }}>
            {building.emoji} {building.nom}
          </span>
          {world && (
            <span className="room-header-world" style={{ color: world.couleur }}>
              {world.emoji} {world.nom}
            </span>
          )}
        </div>
        <div className="room-header-actions">
          {room.type === 'mixte' && (
            <div className="room-onglets">
              <button className={onglet === 'chat' ? 'actif' : ''} onClick={() => setOnglet('chat')}>💬</button>
              <button className={onglet === 'vocal' ? 'actif' : ''} onClick={() => setOnglet('vocal')}>🔊</button>
            </div>
          )}
          {room.est_payante && (
            <div className="room-onglets">
              <button className={onglet === 'coins' ? 'actif' : ''} onClick={() => setOnglet('coins')}
                title={t('room.coinsTitle')}>🏠</button>
            </div>
          )}
          <button className="btn-quitter-room" onClick={onQuitter}>✕</button>
        </div>
      </div>

      {onglet === 'coins' && (
        <div style={{ flex: 1, overflow: 'hidden' }}>
          <CoinPanel room={room} moi={moi} />
        </div>
      )}

      {onglet !== 'coins' && onglet === 'vocal' && token && (
        <div className="room-vocal">
          <LiveKitRoom
            serverUrl={LIVEKIT_URL}
            token={token}
            connect
            audio={true}
            video={false}
            style={{ flex: 1, display: 'flex', flexDirection: 'column' }}
          >
            <VocalSalon room={room} moi={moi} onQuitter={onQuitter} />
          </LiveKitRoom>
        </div>
      )}
      {onglet !== 'coins' && onglet === 'vocal' && !token && (
        <div className="vocal-connecting">{t('room.connectingVoice')}</div>
      )}

      {onglet !== 'coins' && onglet !== 'vocal' && (
        <>
          <div className="room-messages">
            {messages.length === 0 && fichiers.length === 0 && (
              <div className="messages-vide">
                <span>{room.emoji}</span>
                <p>{t('room.startOf')} <strong>{room.nom}</strong></p>
              </div>
            )}

            {fichiers.length > 0 && (
              <div className="fichiers-liste">
                {fichiers.map(f => (
                  <div key={f.id} className="fichier-item">
                    <a href={`${API_URL}/api/files/download/${f.id}`} target="_blank" rel="noreferrer" className="fichier-lien">
                      📎 {f.nom}
                      <span className="fichier-taille">({Math.round(f.taille / 1024)} Ko)</span>
                    </a>
                    <span className="fichier-auteur">{f.uploader_nom}</span>
                    {f.uploaded_by === moi.id && (
                      <button className="btn-suppr-fichier" onClick={() => supprimerFichier(f.id)}>✕</button>
                    )}
                  </div>
                ))}
              </div>
            )}

            {messages.map((m, i) => {
              const precedent  = messages[i - 1]
              const memeAuteur = precedent?.author_nom === m.author_nom
              const isMoi      = m.author_id === getMatrixClient()?.getUserId()
              return (
                <div key={m.id} className={`message ${memeAuteur ? 'groupe' : ''}`}>
                  {!memeAuteur && (
                    <div className="message-header">
                      <span className="message-avatar">{m.author_emoji}</span>
                      <span className="message-auteur">{m.author_nom}</span>
                      <span className="message-time">{m.created_at?.slice(11, 16)}</span>
                    </div>
                  )}
                  <div className="message-row">
                    <div className="message-contenu">{m.contenu}</div>
                    <div className="message-actions" onClick={e => e.stopPropagation()}>
                      <button
                        className="btn-react"
                        onClick={() => setEmojiPickerId(emojiPickerId === m.id ? null : m.id)}
                        title={t('room.react')}
                      >😊</button>
                      {isMoi && (
                        <button className="btn-suppr-msg" onClick={() => supprimerMessage(m.id)} title={t('room.deleteMessage')}>🗑</button>
                      )}
                    </div>
                  </div>
                  {emojiPickerId === m.id && (
                    <div className="emoji-reaction-picker" onClick={e => e.stopPropagation()}>
                      {EMOJIS_REACTION.map(e => (
                        <button key={e} onClick={() => reagir(m.id, e)}>{e}</button>
                      ))}
                    </div>
                  )}
                  {m.reactions && Object.keys(m.reactions).length > 0 && (
                    <div className="reactions">
                      {Object.entries(m.reactions).map(([emoji, data]) => (
                        <button
                          key={emoji}
                          className={`reaction-btn ${data.users?.includes(moi.id) ? 'moi' : ''}`}
                          onClick={() => reagir(m.id, emoji)}
                          title={data.users?.join(', ')}
                        >
                          {emoji} {data.count}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )
            })}
            <div ref={basRef} />
          </div>

          {room.status === 'closed' ? (
            <div className="broadcast-locked">
              <span>🔒</span> Projet terminé — cette room est en lecture seule
            </div>
          ) : room.type === 'broadcast' && world?.owner_id !== moi?.id ? (
            <div className="broadcast-locked">
              <span>📢</span> {t('room.broadcastLocked')}
            </div>
          ) : (
            <form className="room-input" onSubmit={envoyer}>
              <button type="button" className="btn-upload" onClick={() => fileRef.current?.click()} title={t('room.uploadFile')}>📎</button>
              <input ref={fileRef} type="file" style={{ display: 'none' }} onChange={uploaderFichier} />
              <input
                value={texte}
                onChange={e => setTexte(e.target.value)}
                placeholder={t('room.messagePlaceholder', { roomName: room.nom })}
                autoFocus
              />
              <button type="submit">↑</button>
            </form>
          )}
        </>
      )}
    </div>
  )
}

import { useState, useEffect, useRef } from 'react'
import { useMatrixDM } from '../hooks/useMatrixDM.js'

export default function DMPanel({ world, moi, destinataire, onFermer }) {
  const [texte, setTexte] = useState('')
  const bottomRef         = useRef(null)

  const matrix   = useMatrixDM(destinataire.matrix_user_id || null)
  const messages = matrix.messages

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  async function envoyer(e) {
    e.preventDefault()
    if (!texte.trim() || !matrix.disponible) return
    await matrix.envoyer(texte, moi)
    setTexte('')
  }

  return (
    <div className="dm-panel">
      <div className="dm-panel-header">
        <span>
          {destinataire.avatar_emoji} {destinataire.nom}
          {matrix.disponible && <span title="Chiffré Matrix" style={{ fontSize: 11, color: '#57F287', marginLeft: 6 }}>🔒</span>}
        </span>
        <button className="btn-quitter-room" onClick={onFermer}>✕</button>
      </div>

      {matrix.chargement && (
        <div style={{ padding: 16, color: '#72767d', fontSize: 13 }}>Connexion au canal sécurisé…</div>
      )}

      <div className="dm-messages">
        {messages.map((m, i) => {
          const isMe = m.from_user_id === localStorage.getItem('matrix_user_id')
          return (
            <div key={m.id ?? i} className={`dm-message ${isMe ? 'moi' : ''}`}>
              {!isMe && <span className="dm-avatar">{m.from_emoji}</span>}
              <div className="dm-bubble">
                {!isMe && <span className="dm-nom">{m.from_nom}</span>}
                <p>{m.contenu}</p>
              </div>
            </div>
          )
        })}
        <div ref={bottomRef} />
      </div>

      <form className="dm-form" onSubmit={envoyer}>
        <input
          value={texte}
          onChange={e => setTexte(e.target.value)}
          placeholder={`Message à ${destinataire.nom}…`}
          autoFocus
          disabled={matrix.chargement}
        />
        <button type="submit" disabled={!texte.trim()}>➤</button>
      </form>
    </div>
  )
}

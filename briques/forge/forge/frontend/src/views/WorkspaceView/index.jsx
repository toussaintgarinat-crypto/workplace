import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import Conversation from './Conversation'
import ArtifactsPanel from './ArtifactsPanel'
import { sessions as sessionsApi } from '../../services/api'
import styles from './WorkspaceView.module.css'

export default function WorkspaceView() {
  const { sessionId } = useParams()
  const navigate = useNavigate()
  const [activeSession, setActiveSession] = useState(null)
  const [artifacts, setArtifacts] = useState([])

  useEffect(() => {
    if (!sessionId) { setActiveSession(null); return }
    sessionsApi.list()
      .then(list => setActiveSession(list.find(s => s.id === sessionId) ?? null))
      .catch(() => {})
  }, [sessionId])

  async function createSession() {
    const s = await sessionsApi.create({ scope: 'user' })
    navigate(`/workspace/${s.id}`)
  }

  return (
    <div className={`${styles.layout} ${artifacts.length > 0 ? styles.withArtifacts : ''}`}>
      <Conversation
        session={activeSession}
        onArtifact={artifact => setArtifacts(prev => [artifact, ...prev])}
        onNew={createSession}
      />

      {artifacts.length > 0 && (
        <ArtifactsPanel
          artifacts={artifacts}
          onApprove={id => setArtifacts(prev => prev.map(a => a.id === id ? { ...a, status: 'approved' } : a))}
          onReject={id => setArtifacts(prev => prev.filter(a => a.id !== id))}
          onClose={() => setArtifacts([])}
        />
      )}
    </div>
  )
}

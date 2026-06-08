import { useState, useEffect } from 'react'

export default function Toast() {
  const [toasts, setToasts] = useState([]) // [{ id, message }]

  useEffect(() => {
    function onError(e) {
      const id = Date.now() + Math.random()
      setToasts(prev => [...prev, { id, message: e.detail }])
      setTimeout(() => {
        setToasts(prev => prev.filter(t => t.id !== id))
      }, 4000)
    }
    window.addEventListener('oria:error', onError)
    return () => window.removeEventListener('oria:error', onError)
  }, [])

  if (toasts.length === 0) return null

  return (
    <div className="toast-container">
      {toasts.map(t => (
        <div key={t.id} className="toast">
          <span>⚠️ {t.message}</span>
          <button onClick={() => setToasts(prev => prev.filter(x => x.id !== t.id))}>✕</button>
        </div>
      ))}
    </div>
  )
}

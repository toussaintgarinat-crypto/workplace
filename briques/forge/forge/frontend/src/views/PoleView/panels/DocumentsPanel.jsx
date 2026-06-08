import { useState, useEffect, useRef } from 'react'
import { token } from '../../../services/api'
import styles from './Panel.module.css'

const BASE = ''
async function req(path, opts = {}) {
  const t = token.get()
  const res = await fetch(`${BASE}${path}`, {
    ...opts,
    headers: { 'Content-Type': 'application/json', ...(t ? { Authorization: `Bearer ${t}` } : {}), ...opts.headers }
  })
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || 'Erreur')
  return res.json()
}

export default function DocumentsPanel({ poleId }) {
  const [docs, setDocs]         = useState([])
  const [selected, setSelected] = useState(null)
  const [uploading, setUploading] = useState(false)
  const fileRef = useRef()

  useEffect(() => {
    req('/api/documents').then(setDocs).catch(() => {})
  }, [poleId])

  async function handleFile(e) {
    const file = e.target.files[0]
    if (!file) return
    setUploading(true)
    try {
      const text = await file.text()
      const doc = await req('/api/documents/upload', {
        method: 'POST',
        body: JSON.stringify({ nom: file.name, contenu: text, type: file.type, poleId })
      })
      setDocs(prev => [doc, ...prev])
      setSelected(doc)
    } catch (err) {
      alert(err.message)
    } finally {
      setUploading(false)
      e.target.value = ''
    }
  }

  async function remove(id) {
    await req(`/api/documents/${id}`, { method: 'DELETE' })
    setDocs(prev => prev.filter(d => d.id !== id))
    if (selected?.id === id) setSelected(null)
  }

  async function openDoc(doc) {
    if (doc.analyse) { setSelected(doc); return }
    const full = await req(`/api/documents/${doc.id}`)
    setSelected(full)
  }

  return (
    <div className={styles.panel}>
      <div className={styles.toolbar}>
        <button className={styles.btnPrimary} onClick={() => fileRef.current?.click()} disabled={uploading}>
          {uploading ? 'Analyse en cours…' : '+ Uploader un document'}
        </button>
        <input ref={fileRef} type="file" accept=".txt,.md,.pdf,.csv,.json" style={{ display: 'none' }} onChange={handleFile} />
      </div>

      <div className={styles.docLayout}>
        <div className={styles.docList}>
          {docs.length === 0 && <p className={styles.empty}>Aucun document.</p>}
          {docs.map(doc => (
            <div key={doc.id}
              className={`${styles.docItem} ${selected?.id === doc.id ? styles.activeDoc : ''}`}
              onClick={() => openDoc(doc)}>
              <span>📄</span>
              <div className={styles.docMeta}>
                <div className={styles.rowTitle}>{doc.nom}</div>
                <div className={styles.rowSub}>{doc.type} · {((doc.taille || 0) / 1024).toFixed(1)} KB</div>
              </div>
              <button className={styles.micro} style={{ color: '#ef4444', flexShrink: 0 }}
                onClick={e => { e.stopPropagation(); remove(doc.id) }}>✕</button>
            </div>
          ))}
        </div>

        {selected && (
          <div className={styles.docPreview}>
            <h3 className={styles.docTitle}>{selected.nom}</h3>
            {selected.analyse ? (
              <div className={styles.analyse}>{selected.analyse}</div>
            ) : (
              <p className={styles.empty}>Analyse non disponible.</p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

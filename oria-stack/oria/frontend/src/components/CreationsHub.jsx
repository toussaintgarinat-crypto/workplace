import { useEffect, useState } from 'react'
import { api } from '../services/api.js'

// Hub « Créations » — regroupe les outils créatifs de Workplace.
// Deux familles de tuiles :
//   • internes  → vue Oria existante (ex. Studio = AtelierPanel), ouverte via callback parent.
//   • externes  → brique autonome (ex. personnages, port 5900) affichée en iframe DANS Oria.
// Ajouter une brique créative = ajouter une tuile dans TUILES (extensible par design).

// URL des briques externes : surchargée par env (déploiement), sinon localhost (usage perso).
const URL_PERSONNAGES =
  import.meta.env.VITE_PERSONNAGES_URL || 'http://localhost:5900/atelier'
// S53 : le Studio est désormais une BRIQUE autonome (port 6060), embarquée en iframe
// comme Personnages/Images (l'ancienne vue interne AtelierPanel est décommissionnée en S54).
// Port 6060 et pas 6000 : 6000 = X11, sur la liste des ports interdits de Chrome → l'iframe
// échouerait en ERR_UNSAFE_PORT.
const URL_STUDIO =
  import.meta.env.VITE_STUDIO_URL || 'http://localhost:6060/atelier'

const TUILES = [
  {
    id: 'studio',
    emoji: '🎬',
    titre: 'Studio audio-séries',
    desc: 'Écrire des séries, distribuer des voix, produire des épisodes audio.',
    type: 'externe',        // brique studio (6060) en iframe
    url: URL_STUDIO,
    accent: '#C9A227',
  },
  {
    id: 'personnages',
    emoji: '🎭',
    titre: 'Atelier de personnages',
    desc: 'Générer un personnage holistique (numérologie, astro, traditions) ou retrouver les signes d’un caractère.',
    type: 'externe',
    url: URL_PERSONNAGES,
    accent: '#B5835A',
  },
  {
    id: 'images-video',
    emoji: '🖼️',
    titre: 'Images & Vidéo',
    desc: 'Génération d’images et de vidéo — brique à venir.',
    type: 'bientot',
    accent: '#6b6f76',
  },
]

export default function CreationsHub({ world, onOpenStudio }) {
  // Quand on ouvre une brique externe, on l'affiche en plein cadre (iframe) avec un retour.
  const [externe, setExterne] = useState(null) // { titre, url } | null
  // Synergie : un personnage poussé par l'iframe Personnages, en attente d'import dans une série.
  const [recu, setRecu] = useState(null)        // { nom, archetype, empreinte, … } | null
  const [series, setSeries] = useState([])      // séries du monde (cibles d'import)
  const [importVers, setImportVers] = useState('')
  const [importEtat, setImportEtat] = useState('') // '' | 'en_cours' | 'ok' | 'erreur'

  // Pont postMessage : l'atelier Personnages (iframe) envoie un personnage → on propose
  // de l'importer comme rôle d'une série du Studio. On ne réagit qu'à NOTRE type de message.
  useEffect(() => {
    function onMessage(e) {
      const d = e.data
      if (!d || d.type !== 'personnage:export' || !d.perso) return
      setRecu(d.perso); setImportEtat(''); setImportVers('')
    }
    window.addEventListener('message', onMessage)
    return () => window.removeEventListener('message', onMessage)
  }, [])

  // Charge les séries du monde quand un personnage arrive (pour choisir la cible).
  useEffect(() => {
    if (!recu || !world?.id) return
    api.get(`/atelier/series?world_id=${world.id}`).then(r => {
      const liste = Array.isArray(r) ? r : []
      setSeries(liste)
      setImportVers(liste[0]?.id || '')
    })
  }, [recu, world?.id])

  async function importer() {
    if (!importVers || !recu) return
    setImportEtat('en_cours')
    const r = await api.post(`/atelier/series/${importVers}/personnages/importer`, {
      nom: recu.nom, role: recu.role || null, description: recu.description || null,
      archetype: recu.archetype || null, empreinte: recu.empreinte || [],
      source: recu.source || 'personnages',
    })
    setImportEtat(r ? 'ok' : 'erreur')
    if (r) setTimeout(() => setRecu(null), 1400)
  }

  function ouvrir(tuile) {
    if (tuile.type === 'bientot') return
    if (tuile.type === 'interne') { onOpenStudio?.(); return }
    setExterne({ titre: tuile.titre, url: tuile.url })
  }

  // Modale d'import (synergie Personnages → Studio), partagée par les deux vues.
  const modalImport = recu && (
    <div style={S.overlay} onClick={() => importEtat !== 'en_cours' && setRecu(null)}>
      <div style={S.modal} onClick={e => e.stopPropagation()}>
        <h3 style={S.modalTitre}>📤 Importer « {recu.nom} » au Studio</h3>
        {recu.archetype && <p style={S.modalSous}>Archétype : {recu.archetype}</p>}
        {!world?.id ? (
          <p style={S.modalSous}>Ouvre d'abord un monde pour choisir une série.</p>
        ) : series.length === 0 ? (
          <p style={S.modalSous}>Aucune série dans ce monde — crée-en une dans le Studio d'abord.</p>
        ) : (
          <>
            <label style={S.modalSous}>Série cible :</label>
            <select style={S.select} value={importVers} onChange={e => setImportVers(e.target.value)}>
              {series.map(s => <option key={s.id} value={s.id}>{s.titre}</option>)}
            </select>
          </>
        )}
        {importEtat === 'ok' && <p style={{ ...S.modalSous, color: '#7bdc9a' }}>✅ Importé dans la distribution.</p>}
        {importEtat === 'erreur' && <p style={{ ...S.modalSous, color: '#e0667a' }}>⚠ Échec de l'import — réessaie.</p>}
        <div style={S.modalActions}>
          <button style={S.btnGhost} disabled={importEtat === 'en_cours'} onClick={() => setRecu(null)}>Annuler</button>
          <button style={S.btnPrim} disabled={!importVers || importEtat === 'en_cours' || importEtat === 'ok'}
            onClick={importer}>{importEtat === 'en_cours' ? 'Import…' : 'Importer'}</button>
        </div>
      </div>
    </div>
  )

  if (externe) {
    return (
      <div style={S.frameWrap}>
        <div style={S.frameBar}>
          <button style={S.retour} onClick={() => setExterne(null)}>← Créations</button>
          <span style={S.frameTitre}>{externe.titre}</span>
          <a style={S.lienExterne} href={externe.url} target="_blank" rel="noreferrer">Ouvrir dans un onglet ↗</a>
        </div>
        <iframe
          title={externe.titre}
          src={externe.url}
          style={S.iframe}
        />
        {modalImport}
      </div>
    )
  }

  return (
    <div style={S.page}>
      {modalImport}
      <div style={S.entete}>
        <h1 style={S.h1}>🎨 Créations</h1>
        <p style={S.sous}>Les outils créatifs de Workplace, réunis ici.</p>
      </div>

      <div style={S.grille}>
        {TUILES.map(tuile => (
          <button
            key={tuile.id}
            style={{
              ...S.tuile,
              borderColor: tuile.accent + '55',
              opacity: tuile.type === 'bientot' ? 0.55 : 1,
              cursor: tuile.type === 'bientot' ? 'default' : 'pointer',
            }}
            onClick={() => ouvrir(tuile)}
            disabled={tuile.type === 'bientot'}
          >
            <span style={{ ...S.tuileEmoji, background: tuile.accent + '22' }}>{tuile.emoji}</span>
            <span style={S.tuileTitre}>{tuile.titre}</span>
            <span style={S.tuileDesc}>{tuile.desc}</span>
            {tuile.type === 'bientot'
              ? <span style={S.badgeBientot}>Bientôt</span>
              : tuile.type === 'externe'
                ? <span style={S.badgeBrique}>Brique · port {new URL(tuile.url).port || '—'}</span>
                : <span style={S.badgeInterne}>Intégré à Oria</span>}
          </button>
        ))}
      </div>
    </div>
  )
}

const S = {
  page: { padding: '32px 40px', height: '100%', overflowY: 'auto' },
  entete: { marginBottom: 28 },
  h1: { fontFamily: 'Fraunces, serif', fontSize: 30, margin: 0, color: 'var(--texte, #f3e9d2)' },
  sous: { margin: '6px 0 0', color: 'var(--texte-doux, #b9b09a)', fontSize: 15 },
  grille: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))',
    gap: 18,
  },
  tuile: {
    display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 10,
    textAlign: 'left', padding: 22,
    background: 'var(--fond-2, #1d1a17)',
    border: '1px solid',
    borderRadius: 16,
    color: 'var(--texte, #f3e9d2)',
    transition: 'transform .12s ease, border-color .12s ease',
  },
  tuileEmoji: {
    fontSize: 28, width: 52, height: 52, borderRadius: 12,
    display: 'flex', alignItems: 'center', justifyContent: 'center',
  },
  tuileTitre: { fontSize: 18, fontWeight: 600, fontFamily: 'Fraunces, serif' },
  tuileDesc: { fontSize: 13.5, lineHeight: 1.5, color: 'var(--texte-doux, #b9b09a)' },
  badgeBrique: { fontSize: 11, color: '#B5835A', border: '1px solid #B5835A55', borderRadius: 999, padding: '2px 10px' },
  badgeInterne: { fontSize: 11, color: '#C9A227', border: '1px solid #C9A22755', borderRadius: 999, padding: '2px 10px' },
  badgeBientot: { fontSize: 11, color: '#9aa0a6', border: '1px solid #9aa0a655', borderRadius: 999, padding: '2px 10px' },

  frameWrap: { display: 'flex', flexDirection: 'column', height: '100%' },
  frameBar: {
    display: 'flex', alignItems: 'center', gap: 16,
    padding: '10px 16px', borderBottom: '1px solid var(--bordure, #2a2620)',
    background: 'var(--fond-2, #1d1a17)',
  },
  retour: {
    background: 'transparent', border: '1px solid var(--bordure, #3a342b)',
    color: 'var(--texte, #f3e9d2)', borderRadius: 8, padding: '6px 12px', cursor: 'pointer',
  },
  frameTitre: { fontFamily: 'Fraunces, serif', fontSize: 16, color: 'var(--texte, #f3e9d2)' },
  lienExterne: { marginLeft: 'auto', fontSize: 13, color: 'var(--accent, #C9A227)', textDecoration: 'none' },
  iframe: { flex: 1, width: '100%', border: 'none', background: '#fff' },

  overlay: {
    position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 1000,
    display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20,
  },
  modal: {
    background: 'var(--fond-2, #1d1a17)', border: '1px solid var(--bordure, #3a342b)',
    borderRadius: 14, padding: 22, maxWidth: 440, width: '100%',
    color: 'var(--texte, #f3e9d2)',
  },
  modalTitre: { margin: '0 0 6px', fontFamily: 'Fraunces, serif', fontSize: 19 },
  modalSous: { margin: '8px 0 4px', fontSize: 13.5, color: 'var(--texte-doux, #b9b09a)' },
  select: {
    width: '100%', marginTop: 6, padding: '9px 10px', borderRadius: 8,
    background: 'var(--fond, #15120f)', color: 'var(--texte, #f3e9d2)',
    border: '1px solid var(--bordure, #3a342b)',
  },
  modalActions: { display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 18 },
  btnGhost: {
    background: 'transparent', border: '1px solid var(--bordure, #3a342b)',
    color: 'var(--texte, #f3e9d2)', borderRadius: 8, padding: '8px 14px', cursor: 'pointer',
  },
  btnPrim: {
    background: 'var(--accent, #C9A227)', border: 'none', color: '#1a1510',
    borderRadius: 8, padding: '8px 16px', cursor: 'pointer', fontWeight: 600,
  },
}

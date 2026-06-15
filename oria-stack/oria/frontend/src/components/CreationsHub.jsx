import { useState } from 'react'

// Hub « Créations » d'Oria — outils créatifs (briques autonomes) affichés en iframe.
// Le Studio audio-séries a MIGRÉ d'Oria vers le dashboard du Cœur (onglet « Créations ») :
// il n'apparaît donc plus ici. Ajouter une brique créative = ajouter une tuile dans TUILES.

// URL des briques externes : surchargée par env (déploiement), sinon localhost (usage perso).
const URL_PERSONNAGES =
  import.meta.env.VITE_PERSONNAGES_URL || 'http://localhost:5900/atelier'

const TUILES = [
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

export default function CreationsHub() {
  // Quand on ouvre une brique externe, on l'affiche en plein cadre (iframe) avec un retour.
  const [externe, setExterne] = useState(null) // { titre, url } | null

  function ouvrir(tuile) {
    if (tuile.type === 'bientot') return
    setExterne({ titre: tuile.titre, url: tuile.url })
  }

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
      </div>
    )
  }

  return (
    <div style={S.page}>
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
              : <span style={S.badgeBrique}>Brique · port {new URL(tuile.url).port || '—'}</span>}
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
}

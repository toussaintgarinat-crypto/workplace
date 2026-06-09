import { useEffect, useRef } from 'react'

// S26 — Synchronisation de la navigation avec l'URL (hash), sans dépendance.
//
// On sérialise l'état navigable de MainLayout dans le hash pour que :
//   - un refresh (F5) conserve la vue,
//   - un lien soit partageable (monde / room / vue globale),
//   - les boutons précédent / suivant du navigateur fonctionnent.
//
// Grammaire du hash :
//   #/                         accueil (aucun monde)
//   #/feed | #/discovery | #/network | #/conductor | #/jardin | #/mydocs
//                              vues globales (indépendantes d'un monde)
//   #/w/<worldId>              monde ouvert, aucun overlay
//   #/w/<worldId>/<kind>       overlay lié au monde : map | agents | ipcra | members
//   #/w/<worldId>/outil/<nom>  panneau outil (search|calendar|reseau-docs|…)
//   #/w/<worldId>/r/<id>,<id>  une ou plusieurs rooms ouvertes
//
// Les vues à charge utile runtime (dm, docs, votes — qui portent un objet
// membre/conseil/scope non sérialisable) ne sont volontairement pas deep-linkées :
// on retombe alors sur `#/w/<worldId>` (le monde reste partageable).

const VUES_GLOBALES = ['feed', 'discovery', 'network', 'conductor', 'jardin', 'mydocs']
const VUES_MONDE    = ['map', 'agents', 'ipcra', 'members'] // overlays sérialisables liés au monde

export function serializeNav({ worldActif, vue, roomsOuvertes }) {
  if (vue && VUES_GLOBALES.includes(vue.kind)) return `#/${vue.kind}`

  const worldId = worldActif?.id
  if (!worldId) return '#/'

  const base = `#/w/${worldId}`
  if (vue && VUES_MONDE.includes(vue.kind)) return `${base}/${vue.kind}`
  if (vue?.kind === 'outil' && vue.outil)   return `${base}/outil/${vue.outil}`
  // dm / docs / votes : pas de payload sérialisable → on garde juste le monde.
  if (vue) return base

  if (roomsOuvertes.length > 0) {
    const ids = roomsOuvertes.map(r => r.room.id).join(',')
    return `${base}/r/${ids}`
  }
  return base
}

export function parseHash(hash = window.location.hash) {
  const raw = (hash || '').replace(/^#\/?/, '')
  if (!raw) return { kind: null }
  const seg = raw.split('/')

  if (VUES_GLOBALES.includes(seg[0])) return { kind: seg[0] }

  if (seg[0] === 'w' && seg[1]) {
    const worldId = decodeURIComponent(seg[1]) // UUID (string)
    if (!seg[2]) return { kind: 'world', worldId }
    if (seg[2] === 'r' && seg[3]) {
      const roomIds = seg[3].split(',').map(decodeURIComponent).filter(Boolean)
      return { kind: 'rooms', worldId, roomIds }
    }
    if (seg[2] === 'outil' && seg[3]) return { kind: 'outil', worldId, outil: seg[3] }
    if (VUES_MONDE.includes(seg[2]))  return { kind: seg[2], worldId }
    return { kind: 'world', worldId }
  }
  return { kind: null }
}

// Synchronise l'URL avec l'état et réagit aux navigations du navigateur.
//  - `state`       : { worldActif, vue, roomsOuvertes }
//  - `applyTarget` : (cible parsée) => void, appelé sur popstate (précédent/suivant).
export function useUrlSync(state, applyTarget) {
  const dernierHash = useRef(null)

  // État → URL (pushState quand la vue change réellement).
  useEffect(() => {
    const hash = serializeNav(state)
    const actuel = window.location.hash || '#/'
    if (hash !== actuel && hash !== dernierHash.current) {
      dernierHash.current = hash
      window.history.pushState(null, '', hash)
    }
  }, [state.worldActif?.id, JSON.stringify(state.vue), state.roomsOuvertes.map(r => r.room.id).join(',')])

  // URL (boutons précédent/suivant) → état.
  useEffect(() => {
    function onPop() {
      dernierHash.current = window.location.hash || '#/'
      applyTarget(parseHash())
    }
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [applyTarget])
}

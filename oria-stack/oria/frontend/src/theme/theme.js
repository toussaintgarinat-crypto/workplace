/* ============================================================
   ORIA — moteur de thème
   Pilote les 4 variables réglables (--accent, --surface, --text-base, --tint)
   sur :root, persiste le thème actif et gère des profils nommés
   (sauvegarde / export / import). Tout le reste du design system
   (src/styles/tokens.css) en dérive automatiquement via color-mix.
   ============================================================ */

const VARS = {
  accent:  '--accent',
  surface: '--surface',
  text:    '--text-base',
}

export const DEFAULT_THEME = {
  accent:  '#d49a36',
  surface: '#d49a36',
  text:    '#f1ece3',
  tint:    16,
}

const ACTIVE_KEY   = 'oria-theme'
const PROFILES_KEY = 'oria-theme-profiles'

/* ── Application ─────────────────────────────────────────────── */
export function applyTheme(theme = {}) {
  const t = { ...DEFAULT_THEME, ...theme }
  const root = document.documentElement
  root.style.setProperty(VARS.accent,  t.accent)
  root.style.setProperty(VARS.surface, t.surface)
  root.style.setProperty(VARS.text,    t.text)
  root.style.setProperty('--tint', (parseInt(t.tint) || 0) + '%')
  return t
}

export function setVar(which, hex) {
  if (VARS[which]) document.documentElement.style.setProperty(VARS[which], hex)
}

export function setTint(pct) {
  document.documentElement.style.setProperty('--tint', (parseInt(pct) || 0) + '%')
}

/* ── Thème actif (persisté) ──────────────────────────────────── */
export function getActiveTheme() {
  try { return { ...DEFAULT_THEME, ...JSON.parse(localStorage.getItem(ACTIVE_KEY) || '{}') } }
  catch { return { ...DEFAULT_THEME } }
}

export function saveActiveTheme(theme) {
  localStorage.setItem(ACTIVE_KEY, JSON.stringify(theme))
}

/** À appeler au démarrage de l'app. */
export function initTheme() {
  return applyTheme(getActiveTheme())
}

/* ── Persistance backend (S25) ───────────────────────────────────
   Le thème vit côté serveur (modèle User, route /auth/me) en plus du
   localStorage. Source de vérité au login = backend ; le localStorage
   sert de cache hors-ligne et de repli avant la résolution de /me. */
import { api } from '../services/api.js'

/** Hydrate le thème depuis le backend (objet renvoyé par GET /auth/me).
 *  Applique + met à jour le cache localStorage. No-op si rien de serveur. */
export function hydrateRemoteTheme(remote) {
  if (!remote || typeof remote !== 'object') return getActiveTheme()
  const t = { ...DEFAULT_THEME, ...remote }
  applyTheme(t)
  saveActiveTheme(t)
  return t
}

/** Ambiance par monde (S25) : un monde porte sa couleur (`World.couleur`) comme
 *  accent pour tous ses membres, le temps qu'on y est. Override ÉPHÉMÈRE — on ne
 *  touche ni au localStorage ni au backend, c'est le thème perso de l'utilisateur
 *  qui reste la base.
 *
 *  L'ambiance ne s'applique QU'aux mondes dont la couleur a été choisie
 *  délibérément. Les couleurs par défaut HÉRITÉES (le blurple Discord `#5865F2` du
 *  modèle, le vert `#2D5A27` posé par l'onboarding avant la refonte « dark chaud &
 *  or ») sont ignorées : sinon elles masqueraient le thème perso de l'utilisateur
 *  et on aurait l'impression que changer son accent ne fait rien. */
const _LEGACY_DEFAULTS = new Set(['#5865f2', '#2d5a27'])
export function applyWorldAmbiance(couleur) {
  const c = (couleur || '').trim().toLowerCase()
  if (!c || !/^#[0-9a-f]{3,8}$/.test(c) || _LEGACY_DEFAULTS.has(c)) {
    clearWorldAmbiance()
    return
  }
  setVar('accent', c)
}

/** Restaure l'accent du thème perso (sortie de monde / monde sans couleur). */
export function clearWorldAmbiance() {
  setVar('accent', getActiveTheme().accent)
}

let _pushTimer = null
/** Pousse le thème vers le backend (PATCH /auth/me), débouncé pour ne pas
 *  spammer pendant le drag d'un curseur ou le balayage d'un nuancier. */
export function pushRemoteTheme(theme, delay = 600) {
  clearTimeout(_pushTimer)
  _pushTimer = setTimeout(() => {
    api.patch('/auth/me', { theme: {
      accent:  theme.accent,
      surface: theme.surface,
      text:    theme.text,
      tint:    parseInt(theme.tint) || 0,
    } })
  }, delay)
}

/* ── Profils nommés ──────────────────────────────────────────── */
export function getProfiles() {
  try { return JSON.parse(localStorage.getItem(PROFILES_KEY) || '{}') }
  catch { return {} }
}

export function saveProfile(name, theme) {
  const all = getProfiles()
  all[name] = { ...theme }
  localStorage.setItem(PROFILES_KEY, JSON.stringify(all))
  return all
}

export function deleteProfile(name) {
  const all = getProfiles()
  delete all[name]
  localStorage.setItem(PROFILES_KEY, JSON.stringify(all))
  return all
}

/* ── Export / Import ─────────────────────────────────────────── */
export function exportTheme(theme) {
  const data = JSON.stringify({ oriaTheme: 1, ...theme }, null, 2)
  const blob = new Blob([data], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'oria-theme.json'
  a.click()
  URL.revokeObjectURL(url)
}

export function importThemeFromFile(file) {
  return new Promise((resolve, reject) => {
    const r = new FileReader()
    r.onload = () => {
      try {
        const obj = JSON.parse(r.result)
        resolve({
          accent:  obj.accent  ?? DEFAULT_THEME.accent,
          surface: obj.surface ?? DEFAULT_THEME.surface,
          text:    obj.text    ?? DEFAULT_THEME.text,
          tint:    obj.tint    ?? DEFAULT_THEME.tint,
        })
      } catch (e) { reject(e) }
    }
    r.onerror = reject
    r.readAsText(file)
  })
}

/* ── Génération des nuanciers ────────────────────────────────── */
export function hslHex(h, s, l) {
  s /= 100; l /= 100
  const k = n => (n + h / 30) % 12
  const a = s * Math.min(l, 1 - l)
  const f = n => l - a * Math.max(-1, Math.min(k(n) - 3, 9 - k(n), 1))
  const v = n => Math.round(255 * f(n)).toString(16).padStart(2, '0')
  return '#' + v(0) + v(8) + v(4)
}

/** Nuancier standard (accent / ambiance) : 12 teintes × 4 intensités. */
export function paletteStandard() {
  const HUES = [35, 18, 2, 330, 300, 270, 235, 205, 170, 135, 95, 60]
  const SHADES = [{ s: 68, l: 64 }, { s: 62, l: 54 }, { s: 58, l: 45 }, { s: 52, l: 37 }]
  const out = []
  SHADES.forEach(sh => HUES.forEach(h => out.push(hslHex(h, sh.s, sh.l))))
  return out
}

/** Nuancier texte, plus fin : 5 familles × 12 niveaux de clarté. */
export function paletteTexte() {
  const FAM = [{ h: 40, s: 16 }, { h: 0, s: 0 }, { h: 210, s: 15 }, { h: 140, s: 13 }, { h: 285, s: 13 }]
  const LS = [95, 91, 87, 83, 79, 75, 71, 67, 63, 59, 55, 51]
  const out = []
  FAM.forEach(f => LS.forEach(l => out.push(hslHex(f.h, f.s, l))))
  return out
}

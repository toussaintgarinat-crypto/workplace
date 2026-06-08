export const DEFAULTS = {
  '--bg':         '#0a0a0f',
  '--bg-panel':   '#111118',
  '--bg-hover':   '#1a1a24',
  '--border':     '#2a2a38',
  '--text':       '#e8e8f0',
  '--text-muted': '#6b6b80',
  '--accent':     '#6366f1',
  '--accent-dim': '#6366f130',
}

export const PRESETS = [
  { name: 'Indigo',  accent: '#6366f1', bg: '#0a0a0f', bgPanel: '#111118', bgHover: '#1a1a24', border: '#2a2a38', text: '#e8e8f0', muted: '#6b6b80' },
  { name: 'Purple',  accent: '#a855f7', bg: '#0a0a0f', bgPanel: '#111118', bgHover: '#1c1a24', border: '#2e2a3a', text: '#e8e8f0', muted: '#6b6b80' },
  { name: 'Cyan',    accent: '#06b6d4', bg: '#050f14', bgPanel: '#091519', bgHover: '#0d1e24', border: '#1a3040', text: '#e0f0f5', muted: '#5a8090' },
  { name: 'Emerald', accent: '#10b981', bg: '#050f0a', bgPanel: '#091410', bgHover: '#0d1e16', border: '#1a3025', text: '#e0f5ec', muted: '#4a7860' },
  { name: 'Rose',    accent: '#f43f5e', bg: '#0f050a', bgPanel: '#180911', bgHover: '#200d18', border: '#3a1525', text: '#f5e0e8', muted: '#906070' },
  { name: 'Amber',   accent: '#f59e0b', bg: '#0f0d05', bgPanel: '#181509', bgHover: '#22200d', border: '#3a3015', text: '#f5f0e0', muted: '#908060' },
  { name: 'Slate',   accent: '#94a3b8', bg: '#080c10', bgPanel: '#0f1318', bgHover: '#161b22', border: '#252d38', text: '#dde4ed', muted: '#607080' },
]

function presetToVars(p) {
  return {
    '--bg':         p.bg,
    '--bg-panel':   p.bgPanel,
    '--bg-hover':   p.bgHover,
    '--border':     p.border,
    '--text':       p.text,
    '--text-muted': p.muted,
    '--accent':     p.accent,
    '--accent-dim': p.accent + '30',
  }
}

export function applyVars(vars) {
  const root = document.documentElement
  for (const [k, v] of Object.entries(vars)) {
    root.style.setProperty(k, v)
  }
}

export function applyPreset(preset) {
  const vars = presetToVars(preset)
  applyVars(vars)
  localStorage.setItem('forge_theme', JSON.stringify(vars))
}

export function applyAccent(hex) {
  const vars = { '--accent': hex, '--accent-dim': hex + '30' }
  applyVars(vars)
  const saved = getSaved()
  localStorage.setItem('forge_theme', JSON.stringify({ ...saved, ...vars }))
}

export function getSaved() {
  try { return JSON.parse(localStorage.getItem('forge_theme') || '{}') } catch { return {} }
}

export function loadTheme() {
  const saved = getSaved()
  if (Object.keys(saved).length) applyVars(saved)
}

export function resetTheme() {
  localStorage.removeItem('forge_theme')
  const root = document.documentElement
  for (const k of Object.keys(DEFAULTS)) root.style.removeProperty(k)
}

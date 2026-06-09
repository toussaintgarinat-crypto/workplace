import { useState, useMemo, useRef } from 'react'
import {
  getActiveTheme, saveActiveTheme, setVar, setTint,
  getProfiles, saveProfile, deleteProfile,
  exportTheme, importThemeFromFile,
  paletteStandard, paletteTexte, pushRemoteTheme,
} from '../theme/theme.js'

const STANDARD = paletteStandard()
const TEXTE = paletteTexte()

function Nuancier({ colors, value, onPick, cols = 12 }) {
  return (
    <div className="nuancier" style={{ gridTemplateColumns: `repeat(${cols},1fr)` }}>
      {colors.map(hex => (
        <span
          key={hex}
          className={`nu ${value.toLowerCase() === hex.toLowerCase() ? 'on' : ''}`}
          style={{ background: hex }}
          title={hex}
          onClick={() => onPick(hex)}
        />
      ))}
    </div>
  )
}

export default function AppearanceSettings() {
  const initial = useMemo(getActiveTheme, [])
  const [accent, setAccent]   = useState(initial.accent)
  const [surface, setSurface] = useState(initial.surface)
  const [text, setText]       = useState(initial.text)
  const [tint, setTintState]  = useState(initial.tint)
  const [profiles, setProfiles] = useState(getProfiles)
  const [name, setName]       = useState('')
  const fileRef = useRef(null)

  const theme = { accent, surface, text, tint }

  function persist(next) {
    const t = { accent, surface, text, tint, ...next }
    saveActiveTheme(t)        // cache local immédiat
    pushRemoteTheme(t)        // persistance backend (débouncée), cf. S25
  }

  function pickAccent(hex)  { setAccent(hex);  setVar('accent', hex);  persist({ accent: hex }) }
  function pickSurface(hex) { setSurface(hex); setVar('surface', hex); persist({ surface: hex }) }
  function pickText(hex)    { setText(hex);    setVar('text', hex);    persist({ text: hex }) }
  function pickTint(v)      { const n = parseInt(v); setTintState(n); setTint(n); persist({ tint: n }) }

  function applyProfile(t) {
    setAccent(t.accent); setSurface(t.surface); setText(t.text); setTintState(t.tint)
    setVar('accent', t.accent); setVar('surface', t.surface); setVar('text', t.text); setTint(t.tint)
    saveActiveTheme(t)
    pushRemoteTheme(t)
  }

  function onSave() {
    const n = name.trim()
    if (!n) return
    setProfiles(saveProfile(n, theme))
    setName('')
  }
  function onDelete(n) { setProfiles(deleteProfile(n)) }

  async function onImport(e) {
    const f = e.target.files?.[0]
    if (!f) return
    try { applyProfile(await importThemeFromFile(f)) }
    catch { alert('Fichier de thème invalide') }
    e.target.value = ''
  }

  const names = Object.keys(profiles)

  return (
    <div className="appearance">
      {/* ACCENT */}
      <div className="ap-block">
        <div className="ap-label">
          <span className="ap-cur"><i style={{ background: accent }} />{accent.toUpperCase()}</span>
          <b>Accent</b>
          <span>Boutons, liserés, badges, liens.</span>
        </div>
        <Nuancier colors={STANDARD} value={accent} onPick={pickAccent} />
        <label className="ap-free">
          <span className="ring" />
          <input type="color" value={accent} onChange={e => pickAccent(e.target.value)} />
          <em>Couleur sur-mesure</em>
        </label>
      </div>

      {/* AMBIANCE */}
      <div className="ap-block">
        <div className="ap-label">
          <span className="ap-cur"><i style={{ background: surface }} />{surface.toUpperCase()}</span>
          <b>Ambiance (fonds)</b>
          <span>Teinte du rail, des colonnes, des cartes.</span>
        </div>
        <Nuancier colors={STANDARD} value={surface} onPick={pickSurface} />
        <label className="ap-free">
          <span className="ring" />
          <input type="color" value={surface} onChange={e => pickSurface(e.target.value)} />
          <em>Couleur sur-mesure</em>
        </label>
        <div className="ap-tint">
          <span>Intensité</span>
          <input type="range" min="0" max="34" value={tint} onChange={e => pickTint(e.target.value)} />
          <span className="ap-tintval">{tint}%</span>
        </div>
      </div>

      {/* TEXTE */}
      <div className="ap-block">
        <div className="ap-label">
          <span className="ap-cur"><i style={{ background: text }} />{text.toUpperCase()}</span>
          <b>Texte</b>
          <span>Nuancier fin — la hiérarchie reste lisible automatiquement.</span>
        </div>
        <Nuancier colors={TEXTE} value={text} onPick={pickText} />
        <label className="ap-free">
          <span className="ring" />
          <input type="color" value={text} onChange={e => pickText(e.target.value)} />
          <em>Couleur sur-mesure</em>
        </label>
      </div>

      {/* PROFILS */}
      <div className="ap-block ap-profiles">
        <div className="ap-label">
          <b>Profil de réglages</b>
          <span>Sauvegarde, exporte ou importe une combinaison complète.</span>
        </div>
        <div className="ap-save">
          <input
            className="ap-pname"
            placeholder="Nom du profil (ex. Atelier — chaleur)"
            value={name}
            onChange={e => setName(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); onSave() } }}
          />
          <button type="button" className="ap-btn accent" onClick={onSave}>💾 Sauvegarder</button>
        </div>
        <div className="ap-list">
          {names.length === 0 && <div className="ap-empty">Aucun profil sauvegardé.</div>}
          {names.map(n => (
            <div key={n} className="ap-item">
              <span className="ap-mini">
                <i style={{ background: profiles[n].accent }} />
                <i style={{ background: profiles[n].surface }} />
                <i style={{ background: profiles[n].text }} />
              </span>
              <span className="ap-pn">{n}</span>
              <span className="ap-acts">
                <button type="button" className="apply" onClick={() => applyProfile(profiles[n])}>Appliquer</button>
                <button type="button" onClick={() => onDelete(n)}>Supprimer</button>
              </span>
            </div>
          ))}
        </div>
        <div className="ap-io">
          <button type="button" className="ap-btn" onClick={() => exportTheme(theme)}>⤓ Exporter (.json)</button>
          <button type="button" className="ap-btn" onClick={() => fileRef.current?.click()}>⤒ Importer</button>
          <input ref={fileRef} type="file" accept="application/json" hidden onChange={onImport} />
        </div>
      </div>
    </div>
  )
}

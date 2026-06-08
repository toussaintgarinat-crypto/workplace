import { useState, useEffect } from 'react'
import { PRESETS, applyPreset, applyVars, getSaved, resetTheme } from '../../theme'
import { llmConfigApi, providerModelsApi } from '../../services/api'
import styles from './SettingsPanel.module.css'

export default function SettingsPanel({ onClose }) {
  const [tab, setTab] = useState('theme')
  return (
    <div className={styles.overlay} onClick={onClose}>
      <div className={styles.panel} onClick={e => e.stopPropagation()}>
        <div className={styles.header}>
          <h2>Paramètres</h2>
          <button className={styles.close} onClick={onClose}>✕</button>
        </div>
        <div style={{ display: 'flex', gap: 4, padding: '0 20px 4px', borderBottom: '1px solid var(--border)' }}>
          <button className={`${styles.navBtn} ${tab === 'theme' ? styles.active : ''}`} onClick={() => setTab('theme')}>🎨 Apparence</button>
          <button className={`${styles.navBtn} ${tab === 'llm'   ? styles.active : ''}`} onClick={() => setTab('llm')}>🤖 LLM par défaut</button>
        </div>
        <div className={styles.content}>
          {tab === 'theme' && <ThemeTab />}
          {tab === 'llm'   && <DefaultLlmTab />}
        </div>
      </div>
    </div>
  )
}

function ThemeTab() {
  const saved = getSaved()
  const [accent, setAccent] = useState(saved['--accent'] || '#6366f1')
  const [bg, setBg]         = useState(saved['--bg']     || '#0a0a0f')
  const [active, setActive] = useState(null)

  function pickPreset(preset) {
    applyPreset(preset)
    setAccent(preset.accent)
    setBg(preset.bg)
    setActive(preset.name)
  }

  function changeColor(key, hex) {
    const updates = { [key]: hex }
    if (key === '--accent') {
      updates['--accent-dim'] = hex + '30'
      setAccent(hex)
    }
    if (key === '--bg') {
      setBg(hex)
      updates['--bg-panel'] = lighten(hex, 7)
      updates['--bg-hover'] = lighten(hex, 14)
      updates['--border']   = lighten(hex, 22)
    }
    setActive(null)
    const next = { ...getSaved(), ...updates }
    applyVars(next)
    localStorage.setItem('forge_theme', JSON.stringify(next))
  }

  function reset() {
    resetTheme()
    setAccent('#6366f1')
    setBg('#0a0a0f')
    setActive(null)
  }

  return (
    <div className={styles.tabContent}>
      <div className={styles.field}>
        <label>Thèmes prédéfinis</label>
        <div className={styles.themeGrid}>
          {PRESETS.map(p => (
            <button
              key={p.name}
              className={`${styles.themePreset} ${active === p.name ? styles.themePresetActive : ''}`}
              onClick={() => pickPreset(p)}
            >
              <span className={styles.themePresetDot} style={{ background: p.accent }} />
              <span className={styles.themePresetBg}  style={{ background: p.bg }} />
              <span className={styles.themePresetName}>{p.name}</span>
            </button>
          ))}
        </div>
      </div>

      <div className={styles.field} style={{ borderTop: '1px solid var(--border)', paddingTop: 14 }}>
        <label>Personnalisation</label>
        <div className={styles.themeCustomRow}>
          <div className={styles.themeCustomItem}>
            <span className={styles.themeCustomLabel}>Accent</span>
            <input type="color" value={accent}
              onChange={e => changeColor('--accent', e.target.value)}
              className={styles.themeColorPicker}
            />
            <span className={styles.themeColorHex}>{accent}</span>
          </div>
          <div className={styles.themeCustomItem}>
            <span className={styles.themeCustomLabel}>Fond</span>
            <input type="color" value={bg}
              onChange={e => changeColor('--bg', e.target.value)}
              className={styles.themeColorPicker}
            />
            <span className={styles.themeColorHex}>{bg}</span>
          </div>
        </div>
      </div>

      <button className={styles.btnSmGhost} onClick={reset}>
        Réinitialiser
      </button>
    </div>
  )
}

function DefaultLlmTab() {
  const [providers, setProviders]       = useState([])
  const [modelOptions, setModelOptions] = useState([])
  const [provider, setProvider]         = useState('')
  const [model, setModel]               = useState('')
  const [saving, setSaving]             = useState(false)
  const [saved, setSavedFlag]           = useState(false)
  const [error, setError]               = useState(null)

  // Load providers and current global preset on mount
  useEffect(() => {
    llmConfigApi.providers()
      .then(all => setProviders(all.filter(p => p.id === 'ollama' || p.id === 'openrouter')))
      .catch(() => {})
    llmConfigApi.getGlobal()
      .then(data => {
        if (data?.provider) setProvider(data.provider)
        if (data?.model)    setModel(data.model)
      })
      .catch(() => {})
  }, [])

  // Reload model list when provider changes — poll Ollama every 5s to detect new models
  useEffect(() => {
    if (!provider) return
    const load = () => {
      providerModelsApi.list(provider)
        .then(data => setModelOptions(data.models ?? []))
        .catch(() => {
          const fallback = providers.find(p => p.id === provider)?.models ?? []
          setModelOptions(fallback)
        })
    }
    load()
    if (provider === 'ollama') {
      const id = setInterval(load, 5000)
      return () => clearInterval(id)
    }
  }, [provider, providers])

  async function handleSave(e) {
    e.preventDefault()
    setSaving(true)
    setError(null)
    setSavedFlag(false)
    try {
      await llmConfigApi.setGlobal({ provider, model })
      setSavedFlag(true)
      setTimeout(() => setSavedFlag(false), 2000)
    } catch (err) {
      setError(err.message || 'Erreur lors de la sauvegarde')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className={styles.tabContent} style={{ borderTop: '1px solid var(--border)' }}>
      <div className={styles.field}>
        <label>LLM par défaut</label>
        <p style={{ fontSize: 12, color: 'var(--text-muted)', margin: 0 }}>
          Utilisé par défaut pour tous les briefs et agents sans config spécifique
        </p>
      </div>

      <form onSubmit={handleSave} style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <div className={styles.row}>
          <select
            className={styles.select}
            value={provider}
            onChange={e => { setProvider(e.target.value); setModel('') }}
            style={{ flex: 1 }}
          >
            <option value="">— fournisseur —</option>
            {providers.map(p => (
              <option key={p.id} value={p.id}>{p.label}</option>
            ))}
          </select>

          {modelOptions.length > 12 ? (
            <>
              <input
                className={styles.input}
                placeholder="Rechercher un modèle…"
                list="global-model-list"
                value={model}
                onChange={e => setModel(e.target.value)}
                style={{ flex: 1 }}
              />
              <datalist id="global-model-list">
                {modelOptions.map(m => <option key={m} value={m} />)}
              </datalist>
            </>
          ) : (
            <select
              className={styles.select}
              value={model}
              onChange={e => setModel(e.target.value)}
              style={{ flex: 1 }}
            >
              <option value="">— modèle —</option>
              {modelOptions.map(m => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
          )}
        </div>

        {error && <span className={styles.themeError}>{error}</span>}

        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <button
            type="submit"
            className={styles.btnPrimary}
            disabled={saving || !provider}
          >
            {saving ? 'Enregistrement…' : 'Enregistrer'}
          </button>
          {saved && (
            <span style={{ fontSize: 12, color: '#4ade80' }}>Sauvegardé ✓</span>
          )}
        </div>
      </form>
    </div>
  )
}

function lighten(hex, amount) {
  const n = parseInt(hex.slice(1), 16)
  const r = Math.min(255, (n >> 16) + amount)
  const g = Math.min(255, ((n >> 8) & 0xff) + amount)
  const b = Math.min(255, (n & 0xff) + amount)
  return '#' + [r, g, b].map(x => x.toString(16).padStart(2, '0')).join('')
}

import { useState } from 'react'
import { useTranslation } from 'react-i18next'

const LANGUAGES = [
  { code: 'fr', label: 'Français', flag: '🇫🇷' },
  { code: 'en', label: 'English',  flag: '🇬🇧' },
  { code: 'zh', label: '中文',     flag: '🇨🇳' },
  { code: 'es', label: 'Español',  flag: '🇪🇸' },
  { code: 'ar', label: 'العربية',  flag: '🇸🇦' },
  { code: 'pt', label: 'Português',flag: '🇧🇷' },
  { code: 'ja', label: '日本語',   flag: '🇯🇵' },
]

export default function LanguagePicker({ style }) {
  const { i18n } = useTranslation()
  const [open, setOpen] = useState(false)

  const current = LANGUAGES.find(l => l.code === i18n.language) || LANGUAGES[0]

  function select(code) {
    i18n.changeLanguage(code)
    setOpen(false)
  }

  return (
    <div style={{ position: 'relative', display: 'inline-block', ...style }}>
      <button
        onClick={() => setOpen(v => !v)}
        title={current.label}
        style={{
          background: 'none',
          border: '1px solid #3a3a4a',
          borderRadius: 8,
          padding: '4px 10px',
          cursor: 'pointer',
          color: '#b9bbbe',
          fontSize: 13,
          display: 'flex',
          alignItems: 'center',
          gap: 6,
        }}
      >
        <span>{current.flag}</span>
        <span>{current.label}</span>
        <span style={{ fontSize: 10, opacity: 0.6 }}>▾</span>
      </button>

      {open && (
        <div style={{
          position: 'absolute',
          bottom: '110%',
          left: 0,
          background: '#1e2030',
          border: '1px solid #3a3a4a',
          borderRadius: 10,
          overflow: 'hidden',
          zIndex: 9999,
          minWidth: 140,
          boxShadow: '0 4px 20px rgba(0,0,0,.5)',
        }}>
          {LANGUAGES.map(l => (
            <button
              key={l.code}
              onClick={() => select(l.code)}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                width: '100%',
                padding: '8px 14px',
                background: l.code === i18n.language ? '#2a2d3e' : 'none',
                border: 'none',
                color: l.code === i18n.language ? '#a78bfa' : '#b9bbbe',
                cursor: 'pointer',
                fontSize: 13,
                textAlign: 'left',
              }}
            >
              <span>{l.flag}</span>
              <span>{l.label}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

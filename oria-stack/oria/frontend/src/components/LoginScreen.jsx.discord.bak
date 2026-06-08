import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../services/api.js'
import LanguagePicker from './LanguagePicker.jsx'

const AVATARS = ['👤','🧑','👩','🧔','👨‍💻','👩‍💻','🧑‍🎨','👩‍🎤','🧑‍🚀','🦊','🐺','🐸']

export default function LoginScreen({ onConnexion }) {
  const { t } = useTranslation()
  const [onglet, setOnglet]     = useState('connexion') // 'connexion' | 'inscription' | '2fa'
  const [email, setEmail]       = useState('')
  const [password, setPassword] = useState('')
  const [nom, setNom]           = useState('')
  const [avatar, setAvatar]     = useState('👤')
  const [erreur, setErreur]     = useState('')
  const [chargement, setChargement] = useState(false)
  const [totpCode, setTotpCode] = useState('')

  function changerOnglet(o) {
    setOnglet(o)
    setErreur('')
  }

  async function connexion(e) {
    e.preventDefault()
    setErreur('')
    setChargement(true)
    const data = await api.post('/auth/login', { email, password })
    setChargement(false)
    if (!data) return setErreur(t('login.connectionError'))
    if (data.detail) return setErreur(data.detail)
    if (data.requires_2fa) {
      setOnglet('2fa')
      return
    }
    onConnexion(data)
  }

  async function verifier2fa(e) {
    e.preventDefault()
    setErreur('')
    setChargement(true)
    const data = await api.post('/auth/login', { email, password, totp_code: totpCode })
    setChargement(false)
    if (!data) return setErreur(t('login.connectionError'))
    if (data.detail) return setErreur(data.detail)
    if (data.requires_2fa) return setErreur(t('login.wrongCode'))
    onConnexion(data)
  }

  async function inscription(e) {
    e.preventDefault()
    setErreur('')
    setChargement(true)
    const data = await api.post('/auth/register', { email, nom, avatar_emoji: avatar, password })
    setChargement(false)
    if (data.detail) return setErreur(data.detail)
    onConnexion(data)
  }

  return (
    <div className="login-screen">
      <LanguagePicker style={{ position: 'fixed', top: 16, right: 16, zIndex: 100 }} />
      <div className="login-card">
        <div className="login-logo">🌍</div>
        <h1 className="login-titre">Oria</h1>
        <p className="login-sub">{t('login.tagline')}</p>

        {onglet !== '2fa' && (
          <div className="login-onglets">
            <button
              className={`onglet-btn ${onglet === 'connexion' ? 'actif' : ''}`}
              onClick={() => changerOnglet('connexion')}
            >
              {t('login.login')}
            </button>
            <button
              className={`onglet-btn ${onglet === 'inscription' ? 'actif' : ''}`}
              onClick={() => changerOnglet('inscription')}
            >
              {t('login.register')}
            </button>
          </div>
        )}

        {onglet === '2fa' ? (
          <form onSubmit={verifier2fa}>
            <p style={{ fontSize: 13, color: '#b9bbbe', marginBottom: 12, textAlign: 'center' }}>
              {t('login.twoFaTitle')}
            </p>
            <input
              className="input-nom"
              type="text"
              placeholder={t('login.sixDigitCode')}
              value={totpCode}
              onChange={e => setTotpCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
              autoFocus
              required
              maxLength={6}
              style={{ letterSpacing: 8, textAlign: 'center', fontSize: 22 }}
            />
            {erreur && <p className="login-erreur">{erreur}</p>}
            <button className="btn-entrer" type="submit" disabled={chargement || totpCode.length < 6}>
              {chargement ? '...' : t('login.verify')}
            </button>
            <button type="button" style={{ background: 'none', border: 'none', color: '#72767d', fontSize: 12, cursor: 'pointer', marginTop: 8, width: '100%' }}
              onClick={() => { setOnglet('connexion'); setTotpCode(''); setErreur('') }}>
              {t('common.back')}
            </button>
          </form>
        ) : onglet === 'connexion' ? (
          <form onSubmit={connexion}>
            <input
              className="input-nom"
              type="email"
              placeholder={t('login.email')}
              value={email}
              onChange={e => setEmail(e.target.value)}
              autoFocus
              required
            />
            <input
              className="input-nom"
              type="password"
              placeholder={t('login.password')}
              value={password}
              onChange={e => setPassword(e.target.value)}
              required
            />
            {erreur && <p className="login-erreur">{erreur}</p>}
            <button className="btn-entrer" type="submit" disabled={chargement}>
              {chargement ? '...' : t('login.connect')}
            </button>
          </form>
        ) : (
          <form onSubmit={inscription}>
            <div className="avatar-picker">
              {AVATARS.map(a => (
                <button key={a} type="button"
                  className={`avatar-btn ${avatar === a ? 'actif' : ''}`}
                  onClick={() => setAvatar(a)}>{a}
                </button>
              ))}
            </div>
            <input
              className="input-nom"
              type="text"
              placeholder={t('login.name')}
              value={nom}
              onChange={e => setNom(e.target.value)}
              autoFocus
              required
            />
            <input
              className="input-nom"
              type="email"
              placeholder={t('login.email')}
              value={email}
              onChange={e => setEmail(e.target.value)}
              required
            />
            <input
              className="input-nom"
              type="password"
              placeholder={t('login.password')}
              value={password}
              onChange={e => setPassword(e.target.value)}
              required
            />
            {erreur && <p className="login-erreur">{erreur}</p>}
            <button className="btn-entrer" type="submit" disabled={chargement}>
              {chargement ? '...' : t('login.createAccount')}
            </button>
          </form>
        )}
      </div>
    </div>
  )
}

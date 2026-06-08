import { useState } from 'react'
import { useAuth } from '../../hooks/useAuth'
import styles from './AuthView.module.css'

export default function AuthView() {
  const { login, register } = useAuth()
  const [mode, setMode]     = useState('login')  // login | register
  const [error, setError]   = useState('')
  const [needs2fa, set2fa]  = useState(false)
  const [form, setForm]     = useState({ email: '', nom: '', password: '', totpCode: '' })
  const [loading, setLoading] = useState(false)

  function update(field, value) {
    setForm(f => ({ ...f, [field]: value }))
    setError('')
  }

  async function submit(e) {
    e.preventDefault()
    setLoading(true)
    setError('')
    try {
      if (mode === 'register') {
        await register(form.email, form.nom, form.password)
      } else {
        const res = await login(form.email, form.password, needs2fa ? form.totpCode : undefined)
        if (res?.requires2fa) { set2fa(true); setLoading(false); return }
      }
    } catch (err) {
      setError(err.message || 'An error occurred')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className={styles.page}>
      <div className={styles.card}>
        <div className={styles.logo}>⚡ Forge</div>
        <p className={styles.tagline}>AI workspace for founders</p>

        <div className={styles.tabs}>
          <button className={mode === 'login'    ? styles.active : ''} onClick={() => { setMode('login');    setError(''); set2fa(false) }}>Sign in</button>
          <button className={mode === 'register' ? styles.active : ''} onClick={() => { setMode('register'); setError(''); set2fa(false) }}>Create account</button>
        </div>

        <form onSubmit={submit} className={styles.form}>
          {mode === 'register' && (
            <div className={styles.field}>
              <label>Name</label>
              <input
                type="text" placeholder="Your name" required
                value={form.nom} onChange={e => update('nom', e.target.value)}
              />
            </div>
          )}

          <div className={styles.field}>
            <label>Email</label>
            <input
              type="email" placeholder="you@example.com" required
              value={form.email} onChange={e => update('email', e.target.value)}
            />
          </div>

          <div className={styles.field}>
            <label>Password</label>
            <input
              type="password" placeholder={mode === 'register' ? 'Min. 8 characters' : 'Your password'} required
              value={form.password} onChange={e => update('password', e.target.value)}
            />
          </div>

          {needs2fa && (
            <div className={styles.field}>
              <label>2FA Code</label>
              <input
                type="text" placeholder="6-digit code" maxLength={6} autoFocus
                value={form.totpCode} onChange={e => update('totpCode', e.target.value)}
              />
            </div>
          )}

          {error && <p className={styles.error}>{error}</p>}

          <button type="submit" className={styles.submit} disabled={loading}>
            {loading ? 'Loading...' : mode === 'login' ? 'Sign in' : 'Create account'}
          </button>
        </form>
      </div>
    </div>
  )
}

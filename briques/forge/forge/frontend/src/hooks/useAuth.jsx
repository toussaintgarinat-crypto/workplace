import { useState, useEffect, createContext, useContext } from 'react'
import keycloak from '../keycloak'

const AuthContext = createContext(null)

// Garde module : keycloak-js ne peut être initialisé qu'une fois (cf. S19).
let initPromise = null

// BroadcastChannel partagé entre l'onglet popup de login et l'iframe Forge.
// Permet à l'onglet popup de notifier l'iframe après authentification (S130).
const authChannel = typeof BroadcastChannel !== 'undefined'
  ? new BroadcastChannel('forge-auth')
  : null

// Détecte si la SPA tourne dans une iframe (ex: dashboard Workplace).
const enIframe = () => { try { return window.self !== window.top } catch { return true } }

export function AuthProvider({ children }) {
  const [user, setUser]           = useState(null)
  const [loading, setLoading]     = useState(true)
  const [nonConnecte, setNonConnecte] = useState(false)

  useEffect(() => {
    // En iframe : écouter le signal d'auth émis par l'onglet popup de login.
    if (enIframe() && authChannel) {
      authChannel.onmessage = (e) => {
        if (e.data === 'authenticated') window.location.reload()
      }
    }

    const appliquerUtilisateur = () => {
      if (keycloak.authenticated) {
        const p = keycloak.tokenParsed
        setUser({
          id:          p.sub,
          nom:         p.nom || p.preferred_username || p.name || 'Utilisateur',
          avatarEmoji: p.avatarEmoji || '👤',
          email:       p.email || '',
        })
        // Onglet popup de login (ouvert par l'iframe via window.open) :
        // notifier l'iframe puis fermer le popup.
        if (window.opener && authChannel) {
          authChannel.postMessage('authenticated')
          window.close()
        }
      } else if (enIframe()) {
        // Dans l'iframe, check-sso a confirmé que l'utilisateur n'est pas connecté.
        setNonConnecte(true)
      }
    }

    if (!initPromise) {
      const dansIframe = enIframe()
      initPromise = keycloak.init({
        // En iframe : check-sso silencieux (pas de redirect visible).
        // Hors iframe : login-required (redirect KC si non connecté).
        onLoad:      dansIframe ? 'check-sso' : 'login-required',
        pkceMethod:  'S256',
        checkLoginIframe: false,
        // Iframe silencieuse (S130) : évite un redirect visible dans l'iframe
        // lors du check-sso. Le fichier est servi statiquement par nginx.
        ...(dansIframe && {
          silentCheckSsoRedirectUri: window.location.origin + '/silent-check-sso.html',
        }),
      })
      keycloak.onTokenExpired = () => {
        keycloak.updateToken(30).catch(() => keycloak.logout())
      }
    }

    initPromise
      .then(appliquerUtilisateur)
      .finally(() => setLoading(false))
  }, [])

  function login() {
    // Ouvre le flow KC dans un nouvel onglet (pas en iframe : KC envoie X-Frame-Options).
    window.open(keycloak.createLoginUrl(), '_blank')
  }

  function logout() {
    keycloak.logout({ redirectUri: window.location.origin })
  }

  // En iframe, non connecté → écran de connexion à la place de l'app.
  if (!loading && nonConnecte) {
    return <EcranConnexion onLogin={login} />
  }

  return (
    <AuthContext.Provider value={{ user, loading, logout, keycloak }}>
      {children}
    </AuthContext.Provider>
  )
}

function EcranConnexion({ onLogin }) {
  const [enAttente, setEnAttente] = useState(false)

  function handleLogin() {
    onLogin()
    setEnAttente(true)
  }

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', alignItems: 'center',
      justifyContent: 'center', height: '100vh', gap: '12px',
      fontFamily: 'system-ui, sans-serif', color: '#6b6b80', background: '#0f0f14',
    }}>
      <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#4f7cf7" strokeWidth="2">
        <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/>
        <path d="M7 11V7a5 5 0 0 1 10 0v4"/>
      </svg>
      <p style={{ margin: 0, fontSize: '14px' }}>
        {enAttente ? 'Connectez-vous dans le nouvel onglet…' : 'Connexion Forge requise'}
      </p>
      {!enAttente && (
        <button
          onClick={handleLogin}
          style={{
            padding: '8px 18px', background: '#4f7cf7', color: '#fff',
            border: 'none', borderRadius: '6px', cursor: 'pointer', fontSize: '13px',
          }}
        >
          Se connecter
        </button>
      )}
      {enAttente && (
        <button
          onClick={() => window.location.reload()}
          style={{
            padding: '6px 14px', background: 'transparent', color: '#6b6b80',
            border: '1px solid #333', borderRadius: '6px', cursor: 'pointer', fontSize: '12px',
          }}
        >
          Actualiser
        </button>
      )}
    </div>
  )
}

export const useAuth = () => useContext(AuthContext)

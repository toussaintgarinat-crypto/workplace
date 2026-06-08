import { useState, useEffect, createContext, useContext } from 'react'
import keycloak from '../keycloak'

const AuthContext = createContext(null)

// Garde au niveau MODULE : keycloak-js ne peut être initialisé qu'une fois, or
// React 18 StrictMode invoque l'effet deux fois. L'ancien garde testait
// `keycloak.authenticated`, mais avec PKCE l'init est ASYNC (digest crypto.subtle)
// → `authenticated` est encore `undefined` au 2ᵉ passage synchrone → un 2ᵉ
// `init()` partait et cassait le 1er (login-required ne redirigeait jamais, l'app
// se rendait NON authentifiée). Un drapeau module garantit un init unique (S19).
let initPromise = null

export function AuthProvider({ children }) {
  const [user, setUser]       = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const appliquerUtilisateur = () => {
      if (keycloak.authenticated) {
        const p = keycloak.tokenParsed
        setUser({
          id:          p.sub,
          nom:         p.nom || p.preferred_username || p.name || 'Utilisateur',
          avatarEmoji: p.avatarEmoji || '👤',
          email:       p.email || '',
        })
      }
    }

    if (!initPromise) {
      initPromise = keycloak.init({
        onLoad:      'login-required',
        pkceMethod:  'S256',
        checkLoginIframe: false,
      })
      // Rafraîchissement automatique du token (posé une seule fois)
      keycloak.onTokenExpired = () => {
        keycloak.updateToken(30).catch(() => keycloak.logout())
      }
    }

    initPromise
      .then(appliquerUtilisateur)
      .finally(() => setLoading(false))
  }, [])

  function logout() {
    keycloak.logout({ redirectUri: window.location.origin })
  }

  return (
    <AuthContext.Provider value={{ user, loading, logout, keycloak }}>
      {children}
    </AuthContext.Provider>
  )
}

export const useAuth = () => useContext(AuthContext)

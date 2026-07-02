import Keycloak from 'keycloak-js'

// S130 : URL dérivée dynamiquement depuis window.location.origin.
// Le nginx de la SPA proxifie /realms/* et /resources/* vers Keycloak,
// rendant KC same-origin quel que soit le host (LAN, mesh, localhost).
// VITE_KEYCLOAK_URL n'est plus utilisé (plus de bake-in).
const keycloak = new Keycloak({
  url:      window.location.origin,
  realm:    import.meta.env.VITE_KEYCLOAK_REALM    || 'oria',
  clientId: import.meta.env.VITE_KEYCLOAK_CLIENT_ID || 'oria-app',
})

export default keycloak

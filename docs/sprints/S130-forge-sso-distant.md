# S130 — Forge SSO distant (accès mesh)

**Objectif** : Forge SSO fonctionne depuis n'importe quel client connecté au mesh NetBird
(`https://100.124.248.226:13000`), sans bake-in de `localhost:8081`.

## Problème

`VITE_KEYCLOAK_URL=http://localhost:8081` était gelé au build. Un navigateur distant
(mesh, iPhone…) résout `localhost` sur **sa propre machine**, pas sur le HP → SSO cassé.

## Solution (A1 + B1 + D)

### A1 — Keycloak same-origin via nginx

Le nginx de la SPA Forge proxifie les chemins Keycloak sous le **même origin** que Forge :

| Chemin externe         | Cible nginx               |
|------------------------|---------------------------|
| `/realms/*`            | `http://host.docker.internal:8081/realms/*` |
| `/resources/*`         | `http://host.docker.internal:8081/resources/*` |

Keycloak est configuré avec `KC_HOSTNAME_STRICT=false` + `KC_PROXY=edge` → il dérive son
`iss` de `X-Forwarded-Host` passé par nginx. Ainsi :

- Accès mesh : `https://100.124.248.226:13000` → `iss = https://100.124.248.226:13000/realms/oria`
- Accès LAN : `http://192.168.1.89:3000` → `iss = http://192.168.1.89:3000/realms/oria`

Le backend Forge Core valide les tokens via JWKS (`http://host.docker.internal:8081`) sans
vérifier l'`iss` (python-jose ne le fait pas par défaut) → aucun changement backend.

`keycloak.js` utilise désormais `window.location.origin` (dynamique) au lieu du bake-in.

### B1 — Login en nouvel onglet (en iframe)

Forge est chargé dans une iframe du dashboard du Cœur. Si l'utilisateur n'est pas connecté :

1. `useAuth` détecte `window.self !== window.top` → `onLoad: 'check-sso'` (silencieux).
2. Non connecté → écran « Se connecter » avec bouton `window.open(loginUrl, '_blank')`.
3. L'onglet popup complète le flow KC → `BroadcastChannel('forge-auth').postMessage('authenticated')` → `window.close()`.
4. L'iframe reçoit le message → `window.location.reload()` → check-sso trouve la session → authentifié.

Fichier `public/silent-check-sso.html` servi statiquement pour le check-sso silencieux (iframe cachée).

### D — redirect URIs Keycloak (étape déploiement)

Ajouter dans le client Keycloak `oria-app` (realm `oria`) :

- **Valid Redirect URIs** : `https://100.124.248.226:13000/*`
- **Web Origins** : `https://100.124.248.226:13000`

#### Script (exécuter sur le HP après démarrage de Keycloak)

```bash
KC_URL=http://localhost:8081
KC_REALM=oria
KC_ADMIN=${KEYCLOAK_ADMIN:-admin}
KC_PASS=${KEYCLOAK_ADMIN_PASSWORD:-admin}
FORGE_URL=https://100.124.248.226:13000

# 1. Obtenir un token admin
TOKEN=$(curl -s -X POST "$KC_URL/realms/master/protocol/openid-connect/token" \
  -d "client_id=admin-cli&grant_type=password&username=$KC_ADMIN&password=$KC_PASS" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# 2. Trouver l'ID du client oria-app
CLIENT_ID=$(curl -s -H "Authorization: Bearer $TOKEN" \
  "$KC_URL/admin/realms/$KC_REALM/clients?clientId=oria-app" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['id'])")

# 3. Lire la config actuelle
CLIENT_JSON=$(curl -s -H "Authorization: Bearer $TOKEN" \
  "$KC_URL/admin/realms/$KC_REALM/clients/$CLIENT_ID")

# 4. Ajouter l'URL mesh dans redirectUris et webOrigins
UPDATED=$(echo "$CLIENT_JSON" | python3 -c "
import sys,json
c = json.load(sys.stdin)
url = '$FORGE_URL'
redirect = url + '/*'
if redirect not in c.get('redirectUris',[]):
    c.setdefault('redirectUris',[]).append(redirect)
if url not in c.get('webOrigins',[]):
    c.setdefault('webOrigins',[]).append(url)
print(json.dumps(c))
")

# 5. Mettre à jour le client
curl -s -X PUT "$KC_URL/admin/realms/$KC_REALM/clients/$CLIENT_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "$UPDATED" && echo "✓ Client oria-app mis à jour"
```

## Fichiers modifiés

| Fichier | Changement |
|---------|-----------|
| `briques/forge/forge/frontend/src/keycloak.js` | `url = window.location.origin` (plus de VITE_KEYCLOAK_URL) |
| `briques/forge/forge/frontend/src/hooks/useAuth.jsx` | Détection iframe, check-sso, login nouvel onglet, BroadcastChannel |
| `briques/forge/forge/frontend/nginx.conf` | Proxy `/realms/` et `/resources/` → Keycloak |
| `briques/forge/forge/frontend/public/silent-check-sso.html` | Fichier silent check-sso (nouveau) |
| `outils/mesh-https/Caddyfile.briques` | Bloc Forge mesh `13000` |

## Déploiement

```bash
# Sur le HP
cd /home/debian/workplace/briques/forge
docker compose build frontend && docker compose up -d frontend

cd /home/debian/workplace/outils/mesh-https
docker compose up -d --force-recreate

# Mettre à jour les redirect URIs Keycloak (script ci-dessus)
```

## État

CODE-COMPLET — LIVE DIFFÉRÉ (déploiement groupé S129+S130+S131).

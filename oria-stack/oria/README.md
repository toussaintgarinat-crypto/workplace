# Oria — Plateforme collaboration temps réel

Plateforme de collaboration avec agents IA résidents, communication temps réel (Matrix/Synapse), appels vidéo (LiveKit) et intégration Forge. Inclut PostgreSQL, MinIO, Synapse et LiveKit.

- **Frontend** : `http://localhost:3002`
- **Backend API** : `http://localhost:8000`
- **Matrix/Synapse** : `http://localhost:8008`
- **LiveKit** : `ws://localhost:7880`


## Démarrage

Oria nécessite une configuration Synapse avant le premier lancement.

### Premier lancement

```bash
# 1. Générer la configuration Synapse (à faire une seule fois)
docker run -it --rm \
  -v $(pwd)/oria/matrix/synapse_data:/data \
  -e SYNAPSE_SERVER_NAME=oria.local \
  -e SYNAPSE_REPORT_STATS=no \
  matrixdotorg/synapse:latest generate

# 2. Générer les tokens Matrix (copier les valeurs dans .env)
openssl rand -hex 32   # → ORIA_MATRIX_AS_TOKEN
openssl rand -hex 32   # → ORIA_MATRIX_HS_TOKEN

# 3. Démarrer
make start-oria
```


## Variables d'environnement

### Obligatoires — Base de données

| Variable | Description | Comment générer |
|---|---|---|
| `ORIA_POSTGRES_PASSWORD` | Mot de passe PostgreSQL Oria | `openssl rand -base64 16` |
| `ORIA_SYNAPSE_DB_PASSWORD` | Mot de passe PostgreSQL Synapse | `openssl rand -base64 16` |

> Les deux bases PostgreSQL sont séparées (Oria sur port 5433, Synapse interne).


### Obligatoires — LiveKit (appels vidéo)

| Variable | Description | Comment générer |
|---|---|---|
| `ORIA_LIVEKIT_API_SECRET` | Secret HMAC pour signer les tokens LiveKit | `openssl rand -base64 32` (min 32 chars) |

> `LIVEKIT_API_KEY` est fixé à `devkey` dans `livekit/livekit.yaml`. Vous pouvez le changer, mais assurez-vous de le mettre à jour dans le fichier YAML aussi.


### Obligatoires — Matrix/Synapse

Ces tokens permettent au backend Oria de communiquer avec Synapse via l'API Application Service.

| Variable | Description | Comment générer |
|---|---|---|
| `ORIA_MATRIX_AS_TOKEN` | Token Application Service → Synapse | `openssl rand -hex 32` |
| `ORIA_MATRIX_HS_TOKEN` | Token Synapse → Application Service | `openssl rand -hex 32` |

> Ces deux tokens doivent correspondre à ceux dans `oria/matrix/synapse_data/homeserver.yaml` après la génération Synapse.

**Après génération Synapse**, vérifiez que `homeserver.yaml` contient votre `server_name` et ajoutez la section application service si Oria doit écouter les events Matrix :
```yaml
app_service_config_files:
  - /data/oria_appservice.yaml
```


### Optionnelles — MinIO (stockage fichiers)

| Variable | Description | Défaut |
|---|---|---|
| `ORIA_MINIO_USER` | Utilisateur admin MinIO | `oria` |
| `ORIA_MINIO_PASSWORD` | Mot de passe admin MinIO | `oria_secret` — **à changer** |


### Optionnelles — URLs publiques (frontend)

Ces variables sont injectées dans le build du frontend React. **Elles doivent correspondre aux URLs accessibles depuis le navigateur** (pas depuis Docker).

| Variable | Description | Défaut |
|---|---|---|
| `VITE_ORIA_API_URL` | URL de l'API backend Oria | `http://localhost:8000` |
| `VITE_ORIA_KEYCLOAK_URL` | URL Keycloak pour le SSO | `http://localhost:8080` |


### Optionnelles — Forge (agents IA)

Permet aux agents résidents dans Oria d'utiliser Forge comme moteur d'IA.

| Variable | Description | Défaut |
|---|---|---|
| `FORGE_URL` | URL du backend Forge | `http://localhost:3001` |


### Optionnelles — Stripe (facturation)

| Variable | Description | Comment l'obtenir |
|---|---|---|
| `STRIPE_SECRET_KEY` | Clé secrète Stripe | [dashboard.stripe.com](https://dashboard.stripe.com) → Developers → API Keys |
| `STRIPE_WEBHOOK_SECRET` | Secret webhook Stripe | Dashboard Stripe → Webhooks → Ajouter un endpoint |

> En mode test, utilisez les clés préfixées `sk_test_` et `whsec_test_`.


## Configuration Synapse (Matrix)

Synapse est le serveur de messagerie Matrix. **Il ne démarre pas sans `homeserver.yaml`.**

### Génération automatique

```bash
docker run -it --rm \
  -v $(pwd)/oria/matrix/synapse_data:/data \
  -e SYNAPSE_SERVER_NAME=oria.local \
  -e SYNAPSE_REPORT_STATS=no \
  matrixdotorg/synapse:latest generate
```

Cela crée `oria/matrix/synapse_data/homeserver.yaml`. Vérifiez que :
```yaml
server_name: "oria.local"   # votre nom de domaine
# Pour un déploiement derrière un reverse proxy :
# public_baseurl: https://matrix.votredomaine.com
```

### Connexion à la base PostgreSQL

Par défaut, la config générée utilise SQLite. Pour pointer vers PostgreSQL (recommandé en production), modifiez `homeserver.yaml` :
```yaml
database:
  name: psycopg2
  args:
    user: synapse
    password: <ORIA_SYNAPSE_DB_PASSWORD>
    database: synapse
    host: synapse_db
    cp_min: 5
    cp_max: 10
```


## Configuration LiveKit

Le fichier `oria/livekit/livekit.yaml` contient la configuration LiveKit. Par défaut :
```yaml
keys:
  devkey: <ORIA_LIVEKIT_API_SECRET>
```

Pour un déploiement avec TURN (appels derrière NAT/firewall) :
```yaml
turn:
  enabled: true
  domain: turn.votredomaine.com
  tls_port: 5349
  udp_port: 3478
  external_tls: true
```

# Forge — Plateforme agents IA

Plateforme full-stack pour créer et orchestrer des agents IA avec RAG, gestion de projets, authentification SSO et stockage objet. Inclut Keycloak, PostgreSQL, Qdrant et MinIO.

- **Frontend** : `http://localhost:3000`
- **Core API** : `http://localhost:8600`
- **Keycloak** : `http://localhost:8080`


## Démarrage

```bash
# Depuis la racine du workspace
make start-forge

# Premier lancement seulement (configure Keycloak + DB)
cd forge && bash setup.sh
```

> Le premier démarrage prend 2-3 minutes — Keycloak s'initialise et importe le realm.


## Variables d'environnement

### Obligatoires — Sécurité

| Variable | Description | Comment générer |
|---|---|---|
| `ENCRYPTION_KEY` | Clé de chiffrement pour les secrets stockés (tokens OAuth, clés API) | `openssl rand -base64 32` |
| `KEYCLOAK_ADMIN_PASSWORD` | Mot de passe du compte administrateur Keycloak | Choisir un mot de passe fort |

> **Important** : `ENCRYPTION_KEY` doit rester identique entre les redémarrages. Si vous la changez, les secrets chiffrés stockés deviennent illisibles.


### Optionnelles — Fournisseurs LLM

Forge peut utiliser plusieurs providers. Configurez au moins l'un d'entre eux, ou pointez vers le **gateway** (recommandé).

| Variable | Description | Comment l'obtenir |
|---|---|---|
| `ANTHROPIC_API_KEY` | Clé API Anthropic (Claude) | [console.anthropic.com](https://console.anthropic.com) → API Keys |
| `OPENAI_API_KEY` | Clé API OpenAI | [platform.openai.com](https://platform.openai.com/api-keys) |
| `GROQ_API_KEY` | Clé API Groq (inférence rapide) | [console.groq.com](https://console.groq.com) → API Keys |
| `OPENROUTER_API_KEY` | Clé API OpenRouter (+200 modèles) | [openrouter.ai](https://openrouter.ai) → Keys |
| `MISTRAL_API_KEY` | Clé API Mistral | [console.mistral.ai](https://console.mistral.ai) |
| `GEMINI_API_KEY` | Clé API Google Gemini | [aistudio.google.com](https://aistudio.google.com) → Get API Key |
| `OLLAMA_BASE_URL` | URL Ollama local | `http://<IP-machine>:11434/api` — laisser vide si pas d'Ollama |

**Recommandé** : passer par le gateway plutôt que de configurer toutes les clés ici. Dans ce cas :
```bash
GATEWAY_BASE_URL=http://localhost:4000
GATEWAY_API_KEY=sk-forge
DEFAULT_LLM_PROVIDER=openai   # ou anthropic
DEFAULT_LLM_MODEL=openai/gpt-4o
```


### Optionnelles — Modèle par défaut

| Variable | Description | Défaut |
|---|---|---|
| `DEFAULT_LLM_PROVIDER` | Provider par défaut (`ollama`, `anthropic`, `openai`, `groq`) | `ollama` |
| `DEFAULT_LLM_MODEL` | Modèle par défaut | `llama3.2` |


### Optionnelles — Email (SMTP)

Nécessaire pour les notifications et invitations utilisateurs.

| Variable | Description | Exemple |
|---|---|---|
| `SMTP_HOST` | Serveur SMTP | `smtp.gmail.com` |
| `SMTP_PORT` | Port SMTP | `587` |
| `SMTP_USER` | Adresse email | `votre@gmail.com` |
| `SMTP_PASS` | Mot de passe / App Password | Voir ci-dessous |
| `SMTP_FROM` | Expéditeur affiché | `Forge <votre@gmail.com>` |

**Gmail** : utilisez un [App Password](https://myaccount.google.com/apppasswords) (pas votre mot de passe principal) — nécessite la validation en 2 étapes activée.


### Optionnelles — MinIO (stockage fichiers)

Les valeurs par défaut fonctionnent en local. **À changer en production.**

| Variable | Description | Défaut |
|---|---|---|
| `MINIO_ROOT_USER` | Utilisateur admin MinIO | `forge` |
| `MINIO_ROOT_PASSWORD` | Mot de passe admin MinIO | `forge_secret` — **à changer** |


### Optionnelles — MemPalace

Pour enrichir le RAG Forge avec la mémoire MemPalace.

| Variable | Description | Comment l'obtenir |
|---|---|---|
| `MEMPALACE_API_URL` | URL de l'API MemPalace | `http://localhost:8100` |
| `MEMPALACE_API_TOKEN` | Token d'accès MemPalace | `POST /auth/service-token` sur MemPalace après démarrage |


### Optionnelles — Recherche web

| Variable | Description | Comment l'obtenir |
|---|---|---|
| `BRAVE_SEARCH_API_KEY` | Recherche web Brave | [brave.com/search/api](https://brave.com/search/api/) — 2000 req/mois gratuit |


### Optionnelles — Voice

| Variable | Description | Comment l'obtenir |
|---|---|---|
| `DEEPGRAM_API_KEY` | Speech-to-Text | [console.deepgram.com](https://console.deepgram.com) — 200h gratuit |
| `ELEVENLABS_API_KEY` | Text-to-Speech (voix réalistes) | [elevenlabs.io](https://elevenlabs.io) — 10k char/mois gratuit |


## Logs containers (Dozzle)

Dozzle est un visualiseur de logs Docker embarqué, exposé en **LAN-only** par défaut.

- **URL locale** : `http://localhost:9998`
- Accessible depuis les pôles **Dev** : bouton 🪵 dans le header, dans le Kanban Dev et dans les nœuds DAG de type agent.

> **Sécurité** : Dozzle bind sur `127.0.0.1:9998` — jamais exposé sur `0.0.0.0`. En production derrière Traefik, protéger l'accès avec un forward-auth Keycloak avant toute exposition externe. Les boutons Stop/Restart sont désactivés (`DOZZLE_ENABLE_ACTIONS=false`).


## Administration Keycloak

Keycloak gère l'authentification. Interface admin : `http://localhost:8080`

- Login : `admin` / valeur de `KEYCLOAK_ADMIN_PASSWORD`
- Le realm `forge` est importé automatiquement au démarrage
- Les clients `forge-app`, `netbird-client` sont préconfigurés

> Pour réinitialiser Keycloak : `make reset` dans le dossier forge (supprime les volumes).


## Obtenir les clés API

### Anthropic (Claude)
1. Créer un compte sur [console.anthropic.com](https://console.anthropic.com)
2. **API Keys** → **Create Key**
3. Format : `sk-ant-api03-...`

### OpenAI (GPT-4o, etc.)
1. Créer un compte sur [platform.openai.com](https://platform.openai.com)
2. **API Keys** → **Create new secret key**
3. Format : `sk-proj-...`

### Groq (inférence rapide, Llama gratuit)
1. Créer un compte sur [console.groq.com](https://console.groq.com)
2. **API Keys** → **Create API Key**
3. Plan gratuit : 14 400 tokens/minute sur Llama 3.3

### Google Gemini
1. Aller sur [aistudio.google.com](https://aistudio.google.com)
2. **Get API Key** → **Create API key in new project**
3. Quota gratuit : 1M tokens/minute sur Gemini 2.5 Flash

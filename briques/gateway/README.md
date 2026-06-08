# Gateway — Routeur LLM unifié

Basé sur [LiteLLM](https://docs.litellm.ai/), le gateway expose une API OpenAI-compatible sur le port **4000** et route les requêtes vers OpenRouter (cloud) ou Ollama (local).

Tous les autres services (Assistant, Forge, MemPalace) pointent vers le gateway — **vous ne changez les clés API qu'à un seul endroit**.


## Démarrage

```bash
# Depuis la racine du workspace
make start-gateway

# Ou directement
cd gateway
cp ../.env.example ../.env   # si pas encore fait
docker compose up -d

# Vérifier
curl http://localhost:4000/health
```


## Variables d'environnement

### Obligatoires

| Variable | Description | Comment l'obtenir |
|---|---|---|
| `LITELLM_MASTER_KEY` | Clé d'administration LiteLLM. Utilisée pour gérer les clés virtuelles et l'UI. | Générer : `openssl rand -base64 32` — préfixer avec `sk-` |
| `OPENROUTER_API_KEY` | Clé API OpenRouter — donne accès à GPT-4o, Claude, Gemini, etc. | Créer un compte sur [openrouter.ai](https://openrouter.ai) → Keys |

### Optionnelles

| Variable | Description | Comment l'obtenir |
|---|---|---|
| `OLLAMA_URL` | URL du serveur Ollama local. Laisser vide pour désactiver les modèles locaux. | IP de votre machine Ollama — ex: `http://192.168.1.x:11434` ou IP NetBird `http://100.x.x.x:11434` |


## Clés virtuelles (pré-configurées)

Le fichier `litellm_config.yaml` définit des clés virtuelles par service. **Vous n'avez pas besoin de les changer** — elles sont déjà configurées avec des budgets mensuels :

| Clé | Usage | Budget |
|---|---|---|
| `sk-forge` | Forge core API | 10 $/mois |
| `sk-assistant` | Assistant backend | 10 $/mois |
| `sk-mempalace` | MemPalace LLM | 5 $/mois |

Ces clés sont utilisées par les autres services. Elles correspondent aux valeurs `GATEWAY_API_KEY` dans leurs `.env`.


## Modèles disponibles

| Nom du modèle | Provider | Notes |
|---|---|---|
| `openai/gpt-4o` | OpenRouter | Via OPENROUTER_API_KEY |
| `openai/gpt-4o-mini` | OpenRouter | |
| `anthropic/claude-sonnet-4-6` | OpenRouter | |
| `google/gemini-2.5-flash` | OpenRouter | |
| `ollama/llama3.2` | Ollama local | Nécessite `OLLAMA_URL` |
| `ollama/llama3.3` | Ollama local | Nécessite `OLLAMA_URL` |


## Obtenir une clé OpenRouter

1. Créer un compte sur [openrouter.ai](https://openrouter.ai)
2. Aller dans **Keys** → **Create Key**
3. Copier la clé (format `sk-or-v1-...`)
4. La coller dans `.env` : `OPENROUTER_API_KEY=sk-or-v1-...`
5. Créditer votre compte (5 $ suffisent pour commencer)

> OpenRouter agrège +200 modèles. Vous payez à l'usage, pas d'abonnement.


## Configurer Ollama (optionnel)

Ollama doit tourner sur une machine accessible depuis le serveur Docker.

```bash
# Sur la machine Ollama
ollama serve   # démarre sur :11434 par défaut

# Trouver son IP réseau local
ip addr show   # Linux
ipconfig       # Windows
```

Puis dans `.env` :
```bash
OLLAMA_URL=http://192.168.1.100:11434   # IP LAN
# ou via NetBird (VPN mesh)
OLLAMA_URL=http://100.x.x.x:11434
```

> Si Ollama est sur la même machine que Docker sur **Linux**, utilisez l'IP de l'interface réseau (pas `localhost` — `localhost` dans un container désigne le container lui-même).
> Sur **macOS avec Docker Desktop**, `http://host.docker.internal:11434` fonctionne aussi.


## Interface d'administration

LiteLLM expose une UI sur `http://localhost:4000/ui`.

Connexion : avec votre `LITELLM_MASTER_KEY`.

Vous pouvez y voir les logs, les consommations par clé et gérer les modèles.

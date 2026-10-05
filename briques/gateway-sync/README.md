# Brique `gateway-sync` — entretien des modèles gratuits de la Gateway

Aligne les modèles gratuits servis par LiteLLM sur les catalogues du moment : un modèle
gratuit peut passer payant ou disparaître sans préavis, et LiteLLM remonte alors des
`NotFoundError` en boucle sur un slug qui n'existe plus.

Deux **sources** (S239), chacune ne gérant QUE son préfixe :

| Préfixe | Source | Clé |
|---|---|---|
| `free/*` | OpenRouter | `OPENROUTER_API_KEY` requise (sinon source ignorée) |
| `kilo/*` | Kilo Code (`https://api.kilo.ai/api/gateway`) | aucune (`api_key: anonymous`) |

Une source en panne (catalogue injoignable, clé absente, ou catalogue vide / sans aucun
gratuit à outils alors que des modèles de son préfixe sont en place) n'efface rien et
n'empêche pas l'autre de se synchroniser. À l'inverse, une sélection vidée VOLONTAIREMENT
(`KILO_TOP_N=0`, ou `KILO_EXCLURE` qui écarte tout) retire bien les `kilo/*` en place :
c'est le moyen de couper un fournisseur pour raison de confidentialité. Les méta-routeurs (`kilo-auto/free`, `openrouter/free`) sont
écartés : ils choisissent eux-mêmes le modèle, le journal du Cœur ne saurait plus lequel a
répondu. ⚠ Les gratuits Kilo peuvent journaliser les requêtes : ils sont le **filet** de la
cascade du Cœur, jamais sa tête.

## ⚠️ Pas de `docker-compose.yml` ici

Ce service est déclaré dans **`briques/gateway/docker-compose.yml`**, pas dans ce dossier.
Il doit joindre LiteLLM sur le réseau interne du projet gateway (`http://gateway:4000`), ce
qu'un compose séparé n'obtiendrait qu'au prix d'un réseau externe au nom fragile.

```sh
cd ../gateway && docker compose up -d --build   # démarre gateway + gateway-sync
```

Le code et le `manifest.json` vivent bien ici : le registre du Cœur scanne
`briques/*/manifest.json`, indépendamment de l'emplacement du compose.

## Comment le sync est déclenché

1. **Au démarrage** du service — une base LiteLLM neuve n'a aucun modèle gratuit, puisqu'ils
   ne sont plus déclarés dans `litellm_config.yaml`.
2. **Chaque jour**, par l'horloge du Cœur : la tâche `sync-modeles-gratuits` est déclarée
   dans `manifest.json`, et son exécution est journalisée — visible via
   `GET /horloge/taches` sur le Cœur.
3. **À la demande** : `make sync` depuis `briques/gateway`, ou `POST /sync` sur le port 4002.

Le sync est **différentiel et idempotent** : il compare, puis n'applique que l'écart. Il ne
touche jamais un modèle hors de `free/` et `kilo/`, ni un modèle déclaré dans le YAML
(`model_info.db_model` faux) — les payants, `go/*`, locaux et alias (`gratuit/auto`,
`forge/defaut`) restent le repli de toute la cascade. `POST /sync` renvoie l'agrégat
habituel plus le détail par source (`sources.openrouter`, `sources.kilo`) ; il répond 502
seulement si AUCUNE source n'a pu tourner.

## Variables

| Variable | Rôle |
|---|---|
| `LITELLM_URL` | base de LiteLLM (défaut `http://gateway:4000`) |
| `LITELLM_MASTER_KEY` | clé maîtresse LiteLLM — sans elle, no-op |
| `OPENROUTER_API_KEY` | source OpenRouter — sans elle, cette source seule est ignorée |
| `FREE_MODELS_TOP_N` | nombre de `free/*` retenus (défaut 12), triés par contexte |
| `KILO_TOP_N` | nombre de `kilo/*` retenus (défaut 6), triés par contexte |
| `KILO_EXCLURE` | ids Kilo à écarter, séparés par des virgules, comparés par segment sans la variante `:free` (ex. `nvidia` écarte `nvidia/…` mais pas `nvidia-autre/…`) |
| `GATEWAY_SYNC_KEY` | protège `POST /sync` si définie ; sinon ouvert |

## Pourquoi ce service existe

Consigné dans l'ADR
[`docs/decisions/2026-07-27-sync-modeles-gratuits-gateway.md`](../../docs/decisions/2026-07-27-sync-modeles-gratuits-gateway.md),
avec les alternatives écartées. En bref : le YAML est monté en lecture seule, LiteLLM sait
modifier ses modèles à chaud par API (donc sans redémarrage ni accès au socket Docker), et
`core/horloge.py` exige qu'une tâche périodique soit portée par une brique exposant un
endpoint HTTP — ce que l'image officielle LiteLLM ne peut pas faire.

# Brique `gateway-sync` — entretien des modèles gratuits de la Gateway

Aligne les modèles `free/*` servis par LiteLLM sur le catalogue OpenRouter du moment : un
modèle gratuit peut passer payant ou disparaître sans préavis, et LiteLLM remonte alors des
`NotFoundError` en boucle sur un slug qui n'existe plus.

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
touche jamais un modèle qui n'est pas préfixé `free/` — les payants, `go/*` et locaux
viennent du YAML et restent le repli de toute la cascade.

## Variables

| Variable | Rôle |
|---|---|
| `LITELLM_URL` | base de LiteLLM (défaut `http://gateway:4000`) |
| `LITELLM_MASTER_KEY` | clé maîtresse LiteLLM — sans elle, no-op |
| `OPENROUTER_API_KEY` | lecture du catalogue — sans elle, no-op |
| `FREE_MODELS_TOP_N` | nombre de gratuits retenus (défaut 12), triés par contexte |
| `GATEWAY_SYNC_KEY` | protège `POST /sync` si définie ; sinon ouvert |

## Pourquoi ce service existe

Consigné dans l'ADR
[`docs/decisions/2026-07-27-sync-modeles-gratuits-gateway.md`](../../docs/decisions/2026-07-27-sync-modeles-gratuits-gateway.md),
avec les alternatives écartées. En bref : le YAML est monté en lecture seule, LiteLLM sait
modifier ses modèles à chaud par API (donc sans redémarrage ni accès au socket Docker), et
`core/horloge.py` exige qu'une tâche périodique soit portée par une brique exposant un
endpoint HTTP — ce que l'image officielle LiteLLM ne peut pas faire.

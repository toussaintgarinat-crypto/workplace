---
name: review-infra
description: >
  Audit d'infra & code spécifique au projet Workplace (archi noyau + briques) :
  reprend la méthodologie standard review-infra et y ajoute les points propres à
  Workplace (Gateway, briques, secrets connus). Use when user says "review infra",
  "audit infra", "vérifier l'infra", "vérification d'infra", "review-infra".
---

# Révision d'infrastructure — Workplace (addendum sur-mesure)

Ce projet est **Workplace** : un Cœur Python/FastAPI dans `core/`, des briques Docker
indépendantes dans `briques/` (chacune avec son `manifest.json`, `docker-compose.yml`,
`.env.example`), la stack `oria-stack/`, des outils dans `outils/`.

**Applique d'abord les 5 catégories standard** de l'audit review-infra, dans l'ordre,
avec le même format de sortie (tableau de synthèse + `[AUTO-FIXÉ]` / `[SPRINT À PLANIFIER]`
/ `[À VALIDER]` / `[INFO]`) et les mêmes règles de comportement (expliquer simplement,
ne jamais corriger un point de sécurité sans l'expliquer, travailler en parallèle) :

1. **Tags Docker flottants** (`:latest`/tags roulants) — corrige vers la version stable.
2. **Sécurité JWT / Auth / Secrets** — `verify_aud=False`, secrets hardcodés, `DEBUG`/`reload`, CORS `*`.
3. **Cohérence des configs** — env vs `.env.example`, modèles inconnus du registre, ports en double.
4. **Healthchecks** — tout `restart: unless-stopped` doit en avoir un (pas de `bash -c`).
5. **Dépendances non épinglées** — `requirements.txt` (signale, ne corrige pas).

## Spécificités Workplace à intégrer dans ces catégories

- **Registre de modèles = la Gateway** : `briques/gateway/litellm_config.yaml` (clés `model_name`).
  Tout modèle référencé en défaut (`GATEWAY_MODEL`, `FALLBACK_MODELS`, `MODELE_ECONOME`,
  `MODELE_RESUME`, `SHADOW_CANDIDAT`, `LLM_CACHE_EMBEDDING`) mais **absent** de ce fichier
  échouera à l'appel → signale (catégorie 3).
- **Secrets connus à traquer** (catégorie 2) : `GATEWAY_KEY` / valeur `sk-master-change-this`,
  `OPENROUTER_API_KEY`, `MEMOIRE_PASSWORD`, mots de passe Postgres des briques (`memoire`, `donnees`).
- **Ports & manifestes** (catégorie 3) : recoupe le champ `port` de chaque `briques/*/manifest.json`
  avec le port exposé par le `docker-compose.yml` de la même brique ; signale toute divergence
  ou tout port exposé en double entre briques.
- **JWT multi-tenant** (catégorie 2) : la brique `memoire` (backend Memory) et `oria-stack`
  (Keycloak) manipulent des JWT — précise le contexte single/multi-tenant pour chaque `verify_aud=False`.
- **Périmètre** : audite `core/`, `briques/`, `oria-stack/`, `outils/`. **Ignore `apps_exportees/`**
  (livrables clients figés, pas l'infra du projet), `node_modules`, `.git`.

## Sauvegarde des sprints à planifier
Dossier mémoire du projet : `/Users/garinat_t/.claude/projects/-Users-garinat-t-Desktop-Workplace/memory/`
(type `project`, + entrée dans `MEMORY.md`). Lie le sprint à `[[workplace-architecture]]` et,
s'il touche les coûts LLM, à `[[sprint-s138-cout-llm]]`.

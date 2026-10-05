# S238b — Résultats : client OpenAI de la Forge (openai/httpx « proxies »)

Date : 2026-10-05. Branche : `sprint/s238b-forge-openai-httpx`, fusionnée dans `main` (bb2644b).
Plan et diagnostic : [plan](../superpowers/plans/2026-10-05-S238b-forge-openai-httpx.md).

## Diagnostic (avant correction)

- Cassé depuis `9b9b63b` (S205/S206, 2026-07-27, httpx 0.27.0 → 0.28.1 avec openai 1.54.0) ;
  image en prod construite le 2026-08-20. Reproduit dans `forge-forge-1` : `TypeError … 'proxies'`.
- Touchait tout le LLM de la Forge : chat (REST, flux, WebSocket), assistant pipeline, ReAct,
  agents via `generate_text`, embeddings RAG (ingestion + recherche Qdrant).
- Masquage partiel : RAG, conseil, documents, entretiens, brief et audit avalaient l'erreur
  (réponse vide) ; chat, ReAct, SEO, juridique, contenu, prospection, RGPD, gitpack → 500.
- Usage réel faible : 0 message de chat en base, dernière ingestion Qdrant le 2026-06-21.
- Inventaire des conteneurs du HP : seuls Mémoire (1.55.3, corrigée en S238) et Gateway
  (2.33.0) embarquent aussi openai, tous deux sains.

## Livré

- `openai==1.55.3` dans `briques/forge/forge/core/requirements.txt`.
- `briques/forge/forge/core/tests/test_client_openai_s238b.py` (4 tests) : construction avec les
  réglages réels, et `generate_text`, `_embed_local`, `react_executor._client()` pointés sur un
  port fermé doivent lever `APIConnectionError` (pas `TypeError`). ROUGE prouvé sur 1.54.0
  (3 failed, TypeError 'proxies'), VERT sur 1.55.3.
- `tests/test_couple_openai_httpx.py` : filet transverse sur tous les `requirements*.txt` de
  `briques/`, `core/`, `oria-stack/` (`-r` suivis) — rouge si openai < 1.55.3 avec httpx ≥ 0.28.
  Rouge sur l'ancien `main` (forge/core et forge/requirements-dev.txt), vert aujourd'hui.
  Limites écrites dans son en-tête : openai tiré transitivement, plusieurs `-r` enchaînés dans
  un Dockerfile, fichiers `-c`.
- `.dockerignore` racine et forge/core : `.venv*` exclu (un build depuis le poste embarquait le
  venv local `.venv_s227` et son openai 1.54.0).

## Tests

- `scripts/tests_briques.sh forge` : 328 passed, 2 skipped.
- `python3 -m pytest tests/test_couple_openai_httpx.py -o addopts="" -q` : 86 passed.

## Revue

Revue indépendante : 0 Critical ; 1 Important (venv local copié dans l'image par un build depuis
le Mac) et 6 Minor corrigés (commentaires pip à tabulation, continuation sur commentaire,
marqueurs d'environnement, références directes `openai @ URL` refusées, délai du test, passage
par `react_executor._client()`). Restent, assumés : fichiers hors `requirements*.txt` et
installations multi-fichiers des Dockerfile ; bundles déjà exportés dans `apps_exportees/`
(ex. `essai-bundle`) encore en 1.54.0 — à réexporter.

## Preuve LIVE HP (2026-10-05)

Image construite sur le Mac depuis `git archive main`, chargée sur le HP ; sauvegarde
`~/s238b-forge-avant.dump`, ancienne image `workplace-forge-core:avant-s238b`. Fichiers du
sprint copiés dans le dépôt du HP (resté sur 4ce4141, comme S237b/S238).

- Conteneur `healthy`, `forge-forge-migrate-1` sorti en 0, openai 1.55.3 / httpx 0.28.1.
- `memory._embed_local` via la Gateway : vecteur de 384 dimensions.
- `memory._qdrant_search("test")` : 1 739 caractères de contexte (RAG de nouveau fonctionnel).
- `generate_text` : le client se construit et la requête atteint la Gateway — mais **aucun modèle
  de chat ne répond** (voir ci-dessous). Le chemin chat n'a donc pas pu être prouvé jusqu'à une
  réponse de modèle.

## Découverte : génération de texte de la Gateway entièrement en panne

39 modèles de chat testés depuis la Forge, 0 réponse :
- OpenCode Go (`go/*`, dont le défaut de la Forge et la tête de cascade du Cœur) : 400
  « Request is missing x-opencode-session » — changement côté fournisseur.
- OpenRouter (`free/*`, `openai/*`, `anthropic/*`, `deepseek/*`, `google/*`) : 401 « User not found ».
- Anthropic, DeepSeek, Groq, Mistral directs : clé refusée ; OpenAI et Gemini directs : clé absente.
- Ollama : aucun modèle de chat chargé (`llama3.2`, `gemma4:e4b`… not found) ; `local/*` : clé refusée.

Hors périmètre S238b : relève des comptes/clés fournisseurs et de la configuration Gateway.

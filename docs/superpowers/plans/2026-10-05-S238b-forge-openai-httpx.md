# S238b — Client OpenAI de la Forge (openai/httpx « proxies »)

> Sprint court, suite directe de S238. Décision utilisateur 2026-10-05 : sprint séparé.

## Diagnostic (établi avant correction, 2026-10-05)

- `briques/forge/forge/core/requirements.txt` épingle `openai==1.54.0` ; S205/S206
  (`9b9b63b`, 2026-07-27) y a passé `httpx` de 0.27.0 à 0.28.1. httpx 0.28 a retiré
  l'argument `proxies`, qu'openai < 1.55.3 passe encore → **toute construction**
  d'`AsyncOpenAI(...)` lève `TypeError: AsyncClient.__init__() got an unexpected keyword
  argument 'proxies'`. Reproduit dans `forge-forge-1` sur le HP (image du 2026-08-20).
- Le client sert à **tout le LLM de la Forge** (via la Gateway) :
  - chat : `routers/chat.py` (`/chat`, `/chat/stream`), `routers/ws.py` (WebSocket),
    `routers/pipeline_templates.py` (`/pipeline-assistant/chat`), `react_executor.py` ;
  - `llm.generate_text` → agents conseil, SEO, juridique, contenu, prospection, RGPD,
    brief, audit, documents, entretiens, gitpack, pole_dev_bridge ;
  - embeddings RAG : `memory._embed_local` / `_embed_api` (ingestion + recherche Qdrant).
- Masquage : **partiel**. Avalent l'erreur (réponse vide / dégradée, pas de 500) : RAG
  (ingestion et recherche), conseil, documents, entretiens, brief, audit. Échouent en 500 :
  chat (construction hors du `try`), chat/stream, ReAct, SEO, juridique, contenu,
  prospection, RGPD, gitpack.
- Usage réel en prod faible : 0 message de chat en base, dernière ingestion Qdrant le
  2026-06-21 (38 points `forge_local`), 3 exécutions d'agents (juin).
- Autres conteneurs du HP embarquant openai : Mémoire 1.55.3 (corrigée en S238), Gateway
  2.33.0 — sains. La Forge est la seule touchée.

## Tâches

### T1 — Forge : openai 1.55.3 + tests de non-régression
- `briques/forge/forge/core/requirements.txt` : `openai==1.55.3` (aligné sur la Mémoire),
  commentaire expliquant le couple avec httpx 0.28.
- `briques/forge/forge/core/tests/test_client_openai_s238b.py` :
  - construction d'`AsyncOpenAI` avec les réglages réels (`settings.GATEWAY_BASE_URL`,
    `GATEWAY_API_KEY`) → pas d'exception ;
  - chemins réels : `llm.generate_text` et `memory._embed_local` pointés sur un port fermé
    (`http://127.0.0.1:9/v1`) doivent lever `openai.APIConnectionError` — preuve que la
    construction est franchie et la requête partie (un `TypeError` = régression). Garder le
    test rapide (pas 3 tentatives avec back-off).
- Vérifier ROUGE avant (openai 1.54.0) puis VERT après, en conteneur
  (`scripts/tests_briques.sh forge`), et la suite forge complète verte.

### T2 — Filet transverse : couple openai/httpx sur toutes les briques
- `tests/test_couple_openai_httpx.py` (racine, à côté des autres filets) : parcourt les
  `requirements*.txt` de `briques/`, `core/`, `oria-stack/` (hors `node_modules`, `.venv*`,
  `.claude/worktrees`, `apps_exportees`), suit les `-r`, et échoue si une même unité
  d'installation combine `openai` < 1.55.3 avec un `httpx` ≥ 0.28 (épinglé, borné par le
  bas ou non épinglé = résolu à la dernière version). Message d'échec nommant le fichier et
  les versions.
- Un test qui prouve que le filet mord (cas synthétique rouge), et un qui vérifie qu'il a
  bien trouvé des fichiers à inspecter (pas de faux vert sur un parcours vide).
- Limite assumée et écrite : une dépendance qui tirerait openai transitivement n'est pas
  vue statiquement — couverte par l'inventaire des conteneurs du HP (résultats du sprint).

## Déploiement HP (après fusion dans main)
Build sur le Mac (`docker build --platform linux/amd64`, contexte racine), tag
`workplace-forge-core:avant-s238b` sur le HP, dump `forge` avant, `docker save | ssh docker load`,
`docker compose up -d --no-build forge`. Preuve LIVE : construction du client dans le
conteneur, appel réel `generate_text` + embedding via la Gateway, un `/chat` authentifié.

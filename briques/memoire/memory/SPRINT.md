# Memory — Sprints

## Sprint 1 ✓ (Terminé)
**Phase 1 — Fondation Backend + DB**

### Ce qui a été codé
- `docker-compose.yml` — PostgreSQL 16 + pgvector
- `Makefile` — Commandes pratiques
- `backend/app/main.py` — Entrypoint FastAPI
- `backend/app/config.py` — Settings
- `backend/app/database.py` — SQLAlchemy async
- `backend/app/dependencies.py` — JWT auth
- `backend/app/models/` — Node, Edge, PalaceRoom, User/Space/SpaceUser, GardenerLog/ActivityLog
- `backend/app/schemas/` — Node, Search, Graph, Palace, Gardener
- `backend/app/routers/` — auth, spaces, nodes, search, palace, graph, gardener, temporal, export
- `backend/app/services/` — node, search, graph, palace, gardener, decay, embed
- `backend/app/llm/` — client, embedder, suggestor, prompts
- `cli/main.py` — CLI Typer (add, recall, list, stats)
- `scripts/seed.py` — Données de démo
- `.env.example`

### Comment lancer
```bash
make up        # PostgreSQL
make dev       # API sur :8000
make seed      # Données de démo
make cli       # CLI
```

---

## Sprint 2 ✓ (Terminé)
**Phase 2 — Frontend React + Tailwind**

### Ce qui a été codé
- `frontend/` — Projet Vite + React 19 + TypeScript + Tailwind 4
- `frontend/src/components/layout/` — AppLayout, Sidebar, TopBar, BottomNav (responsive)
- `frontend/src/pages/Dashboard.tsx` — Stats + liste des souvenirs récents
- `frontend/src/pages/NotePage.tsx` — Éditeur de note (Markdown + frontmatter)
- `frontend/src/pages/SearchPage.tsx` — Recherche plein texte + vectorielle
- `frontend/src/pages/PalacePage.tsx` — Arbre ailes/pièces/tiroirs
- `frontend/src/pages/GardenerPage.tsx` — Configuration + suggestions
- `frontend/src/pages/SettingsPage.tsx` — Login / Settings
- `frontend/src/components/editor/` — MarkdownEditor, FrontmatterEditor, Markdown (react-markdown renderer)
- `frontend/src/services/api.ts` — Client HTTP vers le backend
- `frontend/src/types/api.ts` — Types TypeScript
- `frontend/src/stores/appStore.ts` — Zustand store

### Comment lancer
```bash
cd frontend
npm run dev    # Dev sur :5173 (proxy /api → :8000)
npm run build  # Build production
```

---

## Sprint 3 ✓ (Terminé)
**Phase 3 — Graphe + Temporalité**

### Ce qui a été codé
- `backend/app/services/graph_service.py` — BFS multi-hop (`depth`), shortest path (BFS réel)
- `backend/app/scheduler.py` — APScheduler intégré (decay quotidien automatique)
- `backend/app/main.py` — Scheduler start/stop dans le lifespan
- `frontend/src/pages/GraphPage.tsx` — Vue graphe interactive (React Flow)
- `frontend/src/components/graph/GraphCanvas.tsx` — Toile graphe avec zoom, pan, mini-map
- `frontend/src/components/graph/NodeDetail.tsx` — Panneau latéral détails nœud
- `frontend/src/components/graph/Legend.tsx` — Légende types nœuds/arêtes
- `frontend/src/pages/Dashboard.tsx` — Notifications decaying items (section dédiée)
- `frontend/src/App.tsx` — Route `/memory/graph` ajoutée
- `frontend/src/components/layout/Sidebar.tsx` — Lien Graph
- `frontend/src/components/layout/BottomNav.tsx` — Lien Graph
- `frontend/src/services/api.ts` — API getGraph sans root, deleteEdge, findPath, getDecayingNodes

### Comment lancer
```bash
make up        # PostgreSQL
make dev       # API sur :8000 (scheduler decay auto)
cd frontend && npm run dev  # Frontend sur :5173
```

### Détails techniques
- **React Flow** (`@xyflow/react`) pour la visualisation interactive
- **APScheduler** (mode asyncio) pour le decay quotidien à minuit
- **BFS expansif** : `depth` paramètre respecté (requêtes N-level)
- **Shortest path** : BFS réel avec parcours en largeur multi-hop
- **Drag & connect** : glisser entre deux nœuds pour créer une arête

---

## Sprint 4 ✓ (Terminé)
**Phase 4 — IPCRa + Jardinier LLM**

### Ce qui a été codé
- `backend/app/models/gardien.py` — `GardienConfigModel` (persistance config en DB)
- `backend/app/llm/suggestor.py` — `suggest_for_node()`, `summarize_cluster()`, `infer_links()`, `archive_decision()`
- `backend/app/services/gardien_service.py` — `run()` LLM-powered, `execute_suggestion()` (change le stage IPCRa réellement), `load_config()`/`save_config()` (DB), `get_logs()`
- `backend/app/routers/gardien.py` — `POST /run` appelle le service, `POST /suggestions/{id}/accept` exécute la transition, config persistée en DB
- `backend/app/scheduler.py` — Job `gardien_auto` toutes les heures (si mode != "off")
- `frontend/src/pages/GardienPage.tsx` — Vue suggestions (texte LLM lisible), sélecteur mode (propose/auto/off), vue historique avec statuts
- `frontend/src/services/api.ts` — `getGardienLog()`
- `frontend/src/types/api.ts` — `GardienLogEntry`

### Détails techniques
- **Suggestor LLM** utilise les 5 prompts (SUMMARIZE_CLUSTER, MERGE_DUPLICATES, SUGGEST_IPCRa, INFERENCE_LINKS, FORGET_DECISION)
- **Workflow IPCRa** : LLM suggère → utilisateur accepte → `NodeService.update_stage()` change réellement le stage
- **Config persistée** en base avec `GardenerConfigModel` (une ligne par espace)
- **Scheduler** : decay quotidien + jardinier toutes les heures
- **Mode Propose** : suggestions en attente ; **Auto** : exécution directe ; **Off** : désactivé

### Comment lancer
```bash
make up        # PostgreSQL
make dev       # API sur :8000 (scheduler decay + gardener auto)
cd frontend && npm run dev  # Frontend sur :5173
```

---

## Sprint 5 ✓ (Terminé)
**Phase 5 — MCP Server + Multi-utilisateur + Export/Import**

### Ce qui a été codé

- **MCP Server Go** (`mcp-server/`) — Proxy maigre vers le backend FastAPI
  - `main.go` — Entrypoint, initialisation des 8 outils MCP
  - `client/backend.go` — Client HTTP vers l'API REST
  - `tools/remember.go` — `memory_remember` : stocker un souvenir
  - `tools/recall.go` — `memory_recall` : recherche sémantique
  - `tools/search.go` — `memory_search` : recherche textuelle + vectorielle
  - `tools/graph_query.go` — `memory_graph_query` : sous-graphe ou chemin
  - `tools/update_stage.go` — `memory_update_stage` : changer stage IPCRa
  - `tools/suggest.go` — `memory_suggest_transitions` : lancer le jardinier
  - `tools/insights.go` — `memory_get_insights` : état global de l'espace
  - `tools/stats.go` — `memory_stats` : statistiques
  - `tools/tools.go` — Helpers partagés

- **Multi-utilisateur & Permissions** (`backend/`)
  - `dependencies.py` — `get_current_user_id`, `get_current_user_db`, `check_space_access`, `require_space_role`
  - `routers/spaces.py` — Auto-attribution du rôle `owner` à la création, filtrage des espaces par utilisateur, endpoints `GET /members`, `POST /invite`, `DELETE /members/{id}`, `PUT /members/{id}/role`
  - Modèle `SpaceUser` déjà existant avec rôles `owner/admin/member/viewer`

- **Export amélioré** (`routers/export.py`)
  - Export complet : nœuds + arêtes + palais + config jardinier
  - Formats JSON et Markdown

- **Import JSON** (`routers/import_router.py`)
  - `POST /api/v1/spaces/{space_id}/import` — Importer des nœuds en JSON

- **Stats endpoint** (`routers/stats.py`)
  - `GET /api/v1/spaces/{space_id}/stats` — Statistiques (total, par type, par stage, poids moyen, decaying)

- **Scripts** (`scripts/setup.sh`) — Script d'installation complet

### Détails techniques
- **MCP Server** : utilise `mark3labs/mcp-go` SDK, communique en stdio, proxy REST vers FastAPI
- **Permissions** : 4 rôles (owner/admin/member/viewer) avec `require_space_role()` en dépendance FastAPI
- **Export complet** : inclut désormais edges, palace rooms et gardener config
- **Import** : accepte un tableau de nœuds au format JSON
- **Configuration MCP** : `MEMORY_BACKEND_URL` (défaut: `http://localhost:8000`), `MEMORY_TOKEN` (requis), `MCP_PORT` (défaut: `8100`)

### Comment lancer
```bash
# Backend
make up        # PostgreSQL
make dev       # API sur :8000

# MCP Server (dans un autre terminal)
export MEMORY_TOKEN="votre-jwt-token"
make mcp       # MCP Server sur stdio

# Frontend
cd frontend && npm run dev  # Frontend sur :5173

# Ou tout d'un coup
bash scripts/setup.sh

---

## Sprint 6 (Terminé)
**Refonte du modèle temporel — Tiers + Timestamps**

### Ce qui a été changé

#### Modèle de données
- Supprimé `Node.weight` (plus de decay/poids artificiel)
- Ajouté `Node.storage_tier` (ENUM: `hot`, `archive`, `cold_archive`)
- Ajouté `Node.happened_at` (date réelle de l'événement)
- Ajouté `Node.stage_changed_at` (date du dernier changement de stage IPCRa)
- `last_accessed` maintenant mis à jour automatiquement à chaque lecture

#### Configuration
- Supprimés : `decay_daily_factor`, `decay_archive_threshold`, `decay_forget_threshold`, `decay_min_weight`, `reinforcement_bump`, `weight_max`
- Ajoutés : `tier_hot_days: 30`, `tier_archive_days: 90`, `tier_cold_archive_days: 365`

#### Nouveaux services
- `backend/app/services/tier_service.py` — déménagement automatique entre tiers basé sur `last_accessed`/`created_at`
- `decay_service.py` supprimé

#### API
- `GET /nodes/aging` — liste les nœuds prêts à changer de tier
- `POST /maintenance/tiers` — déclenche le déménagement automatique
- `PATCH /nodes/{id}/tier` — changer manuellement le tier d'un nœud
- Supprimés : `GET /nodes/decaying`, `POST /maintenance/decay`
- `NodeResponse` inclut `storage_tier`, `happened_at`, `stage_changed_at`
- `NodeCreate` / `NodeUpdate` incluent `happened_at`
- La recherche traverse tous les statuts (active + archived)

#### Jardinier LLM
- `auto_forget` remplacé par `auto_archive`
- `FORGET_DECISION` prompt remplacé par `ARCHIVE_DECISION`
- Le jardinier suggère le passage en cold archive au lieu de "l'oubli"

#### Frontend
- Dashboard : stats par tier, dates affichées, plus de section "Decaying"
- NotePage : timestamps visibles (créé, modifié, accédé, événement), sélecteur de tier
- SearchPage : badge du tier + `happened_at` dans les résultats
- Graph : plus de `weight` sur les nœuds

#### CLI + MCP
- `decaying` → `aging`, `decay` → `demote`
- `auto_forget` → `auto_archive`
- Stats sans weight

### Migration DB nécessaire
```sql
ALTER TABLE nodes DROP COLUMN weight;
ALTER TABLE nodes ADD COLUMN storage_tier VARCHAR DEFAULT 'hot' NOT NULL;
ALTER TABLE nodes ADD COLUMN happened_at TIMESTAMPTZ;
ALTER TABLE nodes ADD COLUMN stage_changed_at TIMESTAMPTZ;
```
```

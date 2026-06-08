# Memory — Plan d'Architecture Complet

> **Système de mémoire personnelle augmentée**
> Fusion : Pensine (Harry Potter) × Palais mental × IPCRa × Anytype × Neurosciences

---

## 1. Vision

Memory est un système de gestion de connaissances personnelles qui combine :

- **Organisation spatiale** (Palais mental : ailes → pièces → tiroirs)
- **Cycle de vie IPCRa** (Input → Projet → Casquette/Ressource → Archive)
- **Graphe associatif** (liens entre souvenirs, navigation libre)
- **Mémoire temporelle** (decay, reinforcement, oubli sélectif)
- **Jardinier LLM** (auto-organisation : résumé, fusion, inférence)
- **Recherche vectorielle** (pgvector, similarité sémantique)
- **Accessible partout** : Web app responsive, CLI, API REST, MCP Server

### Principe fondateur

> Un souvenir n'est pas un fichier. C'est un nœud dans un graphe, rangé dans une pièce d'un palais, qui voyage à travers des étapes de maturation, qui se renforce ou s'estompe avec le temps, et que des agents LLM aident à organiser.

---

## 2. Concepts Fondamentaux

### 2.1 Objet (Node)

Tout est un objet. Un objet = un souvenir.

Chaque objet a :
- Un **Type** (définit sa structure : Input, Projet, etc.)
- Des **Propriétés** (relations propres à son type)
- Un **Corps** en Markdown (`.md` avec frontmatter YAML)
- Un **Emplacement** dans le palais (aile → pièce → tiroir)
- Un **Poids** (force du souvenir, sujet au decay)
- Des **Liens** vers d'autres objets (graphe orienté typé)

### 2.2 Types (inspirés d'Anytype)

Chaque type définit ses propres propriétés.

| Type | Propriétés spécifiques | Cicatrices |
|------|----------------------|------------|
| **Input** | `source_url`, `captured_from` (email/web/voice/note), `priority` | Capture brute |
| **Projet** | `deadline`, `status` (todo/actif/terminé), `priority`, `next_actions[]` | Objectif |
| **Casquette** | `role_name`, `responsabilités[]`, `domaines[]` | Rôle |
| **Ressource** | `resource_type` (article/code/template/outil), `tags[]`, `usage_count` | Savoir |
| **Archive** | `archived_date`, `lessons_learned`, `original_type` | Bilan |

### 2.3 Palais (Palace)

Organisation spatiale :

```
Palais de l'utilisateur
├── Aile "Travail"
│   ├── Pièce "Projets actifs"
│   │   └── Tiroir "Voice Search"
│   ├── Pièce "Veille"
│   └── Pièce "Code"
├── Aile "Savoir"
│   ├── Pièce "Python"
│   └── Pièce "Design"
├── Aile "Vie"
│   ├── Pièce "Santé"
│   └── Pièce "Finances"
└── Aile "Archives"
    └── Pièce "2025"
```

Un objet peut être dans un tiroir (optionnel). Si aucun tiroir, il est dans la pièce.

### 2.4 Cycle IPCRa

```
      ┌──────────────────────────────────────┐
      │                                      │
      ▼                                      │
  ┌──────┐    ┌────────┐    ┌───────────┐    │
  │ Input│───▶│ Projet │───▶│ Archive   │────┘
  └──────┘    └────────┘    └───────────┘
                  │
          ┌───────┴────────┐
          ▼                ▼
     ┌──────────┐   ┌───────────┐
     │Casquette │   │ Ressource │
     └──────────┘   └───────────┘
```

- **Manuel** : l'utilisateur déplace lui-même
- **Automatique** : le LLM propose des transitions (suggestions dans un panneau)
- Passage en Archive = préparation à l'oubli (decay accéléré)

### 2.5 Temporalité (Decay & Reinforcement)

```
Poids
 1.0 │  ● (création)
     │    \
 0.8 │     \  ● (rappel = reinforcement +0.2)
     │      \
 0.6 │       \
     │        \
 0.4 │         ● (seuil d'archivage)
     │          \
 0.2 │           ● (seuil d'oubli → LLM décide)
     │
     └──────────────────────────► Temps
```

- **Decay** : `poids *= 0.95` par jour (paramétrable par type)
- **Reinforcement** : `poids += 0.2` à chaque accès/rappel
- **Archivage** : poids < 0.3 → déplacé dans Archive
- **Oubli** : poids < 0.1 → LLM décide : résumer, fusionner, ou supprimer

### 2.6 Jardinier LLM

Agent d'arrière-plan configurable :

| Action | Déclencheur | Comportement |
|--------|-------------|--------------|
| Résumé | 10+ objets liés | Condense en un objet "concept" de haut niveau |
| Fusion | ≥2 objets similaires (score > 0.9) | Propose fusion avec conservation des métadonnées |
| Inférence | Nouvel objet créé | Détecte les liens possibles avec objets existants |
| Suggestion IPCRa | Input non traité depuis 7j | Propose de déplacer en Projet/Ressource |
| Oubli | Poids < 0.1 | Propose archivage ou suppression |
| Contradiction | 2 objets qui se contredisent | Détecte et crée un objet "note de contradiction" |

**Modes** :
- `auto` : agit sans demander (actions non destructives)
- `propose` : crée une suggestion que l'utilisateur valide (par défaut)
- `off` : désactivé

---

## 3. Architecture Technique

### 3.1 Stack

```
┌───────────────────────────────────────────────────────────┐
│                       Clients                             │
│  ┌──────────┐  ┌─────┐  ┌──────────┐  ┌────────────────┐ │
│  │ Web App  │  │ CLI │  │ API REST │  │ MCP Client     │ │
│  │ (React)  │  │     │  │ (curl)   │  │ (Claude/etc.)  │ │
│  └────┬─────┘  └──┬──┘  └────┬─────┘  └───────┬────────┘ │
└───────┼───────────┼──────────┼──────────────────┼──────────┘
        │           │          │                  │
┌───────▼───────────▼──────────▼──────────────────▼──────────┐
│                    Backend (FastAPI)                       │
│  ┌──────────┐  ┌──────────┐  ┌────────┐  ┌─────────────┐  │
│  │ Routers  │  │ Services │  │ LLM    │  │ Background  │  │
│  │ (REST)   │──│ (CRUD)   │──│ Garden │──│ Scheduler   │  │
│  └──────────┘  └────┬─────┘  └────────┘  │ (decay,     │  │
│                     │                     │  gardener)  │  │
│                     ▼                     └─────────────┘  │
│              ┌──────────────┐                              │
│              │ Embedder     │                              │
│              │ (pgvector)   │                              │
│              └──────┬───────┘                              │
└─────────────────────┼──────────────────────────────────────┘
                      │
┌─────────────────────▼──────────────────────────────────────┐
│           PostgreSQL 16 + pgvector                         │
│  ┌───────┐  ┌───────┐  ┌────────┐  ┌───────┐  ┌────────┐ │
│  │ nodes │  │ edges │  │ palace │  │ users │  │gardener│ │
│  │       │  │       │  │ rooms  │  │spaces │  │ logs   │ │
│  └───────┘  └───────┘  └────────┘  └───────┘  └────────┘ │
└───────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────▼─────────────────────────────┐
│               MCP Server (Go)                              │
│  Tools : remember | recall | search | graph_query          │
│          update_stage | suggest_transition                  │
└───────────────────────────────────────────────────────────┘
```

### 3.2 Composants

| Composant | Technologie | Port par défaut |
|-----------|-------------|-----------------|
| API REST | Python 3.12 + FastAPI + Uvicorn | 8000 |
| Base de données | PostgreSQL 16 + pgvector | 5432 |
| MCP Server | Go + MCP SDK | 8100 |
| Frontend | React 19 + Vite + Tailwind | 5173 |
| CLI | Python Click/Typer | — |
| LLM | OpenRouter / OpenAI / Ollama | — |

---

## 4. Modèle de Données

### 4.1 Diagramme Entité-Relation

```sql
── Espaces (multi-utilisateur)

┌───────────┐     ┌──────────────┐     ┌──────────────┐
│  spaces   │1──N│   space_users │N──1│    users     │
└───────────┘     └──────────────┘     └──────────────┘
      1
      │
      N
┌──────────────────────────────────────────────────────────┐
│                        nodes                              │
│──────────────────────────────────────────────────────────│
│ id              UUID           PK                         │
│ space_id        UUID           FK → spaces                │
│ user_id         UUID           FK → users (owner)         │
│ type            ENUM(input|projet|casquette|ressource|archive)
│ ipcra_stage     ENUM(input|projet|casquette|ressource|archive)
│ status          ENUM(active|archived|pending_removal)     │
│ title           TEXT                                      │
│ content_md      TEXT            (markdown body)           │
│ frontmatter     JSONB           (propriétés typées)       │
│ weight          FLOAT           DEFAULT 1.0               │
│ access_count    INT             DEFAULT 0                 │
│ last_accessed   TIMESTAMPTZ                               │
│ source_url      TEXT            nullable                  │
│ captured_from   TEXT            nullable (email/web/voice) │
│ created_at      TIMESTAMPTZ                               │
│ updated_at      TIMESTAMPTZ                               │
│ embedding       vector(384)     pgvector index             │
└──────────────────────────────────────────────────────────┘
      1              N
      │              │
      │         ┌────┴──────────────┐
      │         │      edges        │
      │         │───────────────────│
      │         │ id       UUID PK  │
      ├─────────│ source FK → nodes │
      └─────────│ target FK → nodes │
                │ type    ENUM      │
                │ weight  FLOAT     │
                │ created_by ENUM   │
                │ (user|llm|auto)   │
                │ created_at        │
                └──────────────────┘

┌───────────────────┐    ┌──────────────────────┐
│   palace_rooms     │    │   gardener_log       │
│───────────────────│    │──────────────────────│
│ id       UUID PK  │    │ id        UUID PK     │
│ space_id FK       │    │ space_id  FK          │
│ wing     TEXT     │    │ action    TEXT         │
│ room     TEXT     │    │ node_id   FK → nodes   │
│ drawer   TEXT     │    │ details   JSONB        │
│ parent   UUID FK  │    │ status    ENUM         │
│ position INT      │    │ (proposed|accepted|    │
│ created_at        │    │  rejected|auto)        │
└───────────────────┘    │ created_at             │
                         └──────────────────────┘

┌───────────────────┐
│ activity_log      │  (break-glass, transitions, etc.)
│──────────────────│
│ id      UUID PK  │
│ space_id FK      │
│ actor_id FK      │→ users
│ target_id FK     │→ users (null if self)
│ node_id FK       │→ nodes (null si global)
│ action  TEXT     │
│ details JSONB    │
│ created_at       │
└──────────────────┘
```

### 4.2 Détail des colonnes `frontmatter` (JSONB) par type

```jsonc
// TYPE = "input"
{
  "priority": "low|medium|high",
  "source_url": "https://...",
  "captured_from": "web|email|voice|note",
  "tags": ["tag1", "tag2"],
  "suggested_stage": null  // rempli par le LLM
}

// TYPE = "projet"
{
  "deadline": "2026-07-15",
  "status": "todo|active|done",
  "priority": "low|medium|high|critical",
  "next_actions": ["Action 1", "Action 2"],
  "tags": ["tag1"],
  "color": "#dc2626"
}

// TYPE = "casquette"
{
  "role_name": "Tech Lead",
  "responsabilites": ["Review code", "Mentoring"],
  "domaines": ["Python", "Architecture"],
  "projets_associes": ["uuid1", "uuid2"],  // FK vers nodes Projet
  "tags": ["role"]
}

// TYPE = "ressource"
{
  "resource_type": "article|code|template|outil|note",
  "tags": ["python", "fastapi"],
  "usage_count": 5,
  "related_resources": ["uuid1"]
}

// TYPE = "archive"
{
  "original_type": "projet",
  "archived_date": "2026-06-01",
  "lessons_learned": "Ne pas oublier de...",
  "related_to": ["uuid1"],
  "tags": []
}
```

### 4.3 Indexation vectorielle

```sql
-- Index pgvector (cosine distance)
CREATE INDEX idx_nodes_embedding ON nodes
  USING ivfflat (embedding vector_cosine_ops)
  WHERE status = 'active';

-- Recherche sémantique
SELECT title, content_md, 1 - (embedding <=> query_embedding) AS score
FROM nodes
WHERE space_id = $1 AND status = 'active'
ORDER BY embedding <=> query_embedding
LIMIT 10;
```

---

## 5. API REST (FastAPI)

### 5.1 Endpoints

#### Nodes (souvenirs)

```
GET    /api/v1/spaces/{space_id}/nodes
       → Liste paginée, filtres (type, stage, status, tags, wing, room)
POST   /api/v1/spaces/{space_id}/nodes
       → Créer un souvenir (avec type et propriétés)
GET    /api/v1/spaces/{space_id}/nodes/{id}
       → Détail d'un souvenir (avec ses edges)
PUT    /api/v1/spaces/{space_id}/nodes/{id}
       → Modifier contenu, propriétés, stage
PATCH  /api/v1/spaces/{space_id}/nodes/{id}/stage
       → Changer d'étape IPCRa
DELETE /api/v1/spaces/{space_id}/nodes/{id}
       → Archiver (soft delete)
```

#### Recherche

```
GET    /api/v1/spaces/{space_id}/search?q=machine+learning&type=ressource
       → Recherche textuelle + vectorielle combinée
POST   /api/v1/spaces/{space_id}/search/semantic
       → Body: {query, limit, stage_filter, type_filter}
       → Résultats vectoriels bruts
```

#### Palais (organisation spatiale)

```
GET    /api/v1/spaces/{space_id}/palace
       → Arbre complet ailes → pièces → tiroirs
POST   /api/v1/spaces/{space_id}/palace/wing
       → Créer une aile
POST   /api/v1/spaces/{space_id}/palace/room
       → Créer une pièce
POST   /api/v1/spaces/{space_id}/palace/drawer
       → Créer un tiroir
PUT    /api/v1/spaces/{space_id}/nodes/{id}/location
       → Déplacer un objet dans une pièce/tiroir
```

#### Graphe

```
GET    /api/v1/spaces/{space_id}/graph?depth=2&root=node_id
       → Sous-graphe autour d'un nœud (pour la vue graphe)
POST   /api/v1/spaces/{space_id}/edges
       → Créer un lien entre deux nœuds
DELETE /api/v1/spaces/{space_id}/edges/{id}
       → Supprimer un lien
GET    /api/v1/spaces/{space_id}/graph/path?from=A&to=B
       → Chemin le plus court entre deux nœuds (BFS graphe)
```

#### Jardinier LLM

```
GET    /api/v1/spaces/{space_id}/gardener/config
       → Voir la configuration (mode, intervalle, actions activées)
PUT    /api/v1/spaces/{space_id}/gardener/config
       → Modifier la configuration
POST   /api/v1/spaces/{space_id}/gardener/run
       → Déclencher une session de jardinage manuellement
GET    /api/v1/spaces/{space_id}/gardener/suggestions
       → Suggestions en attente de validation
POST   /api/v1/spaces/{space_id}/gardener/suggestions/{id}/accept
       → Accepter une suggestion
POST   /api/v1/spaces/{space_id}/gardener/suggestions/{id}/reject
       → Rejeter une suggestion
GET    /api/v1/spaces/{space_id}/gardener/log
       → Historique des actions du jardinier
```

#### Temporalité

```
POST   /api/v1/spaces/{space_id}/nodes/{id}/touch
       → Renforcer un souvenir (accès manuel)
GET    /api/v1/spaces/{space_id}/nodes/decaying
       → Objets proches du seuil d'oubli
POST   /api/v1/spaces/{space_id}/maintenance/decay
       → Déclencher le cycle de decay manuellement
```

#### Espaces & Utilisateurs

```
POST   /api/v1/spaces
       → Créer un espace
GET    /api/v1/spaces
       → Espaces de l'utilisateur courant
POST   /api/v1/spaces/{space_id}/users
       → Inviter un utilisateur
DELETE /api/v1/spaces/{space_id}/users/{user_id}
       → Retirer un utilisateur
```

#### Export / Import

```
GET    /api/v1/spaces/{space_id}/export?format=json|markdown
       → Exporter tout l'espace
POST   /api/v1/spaces/{space_id}/import?format=obsidian|notion|json
       → Importer depuis un autre outil
```

### 5.2 Formats

**Création d'un nœud (exemple Projet)** :

```http
POST /api/v1/spaces/{space_id}/nodes
Content-Type: application/json

{
  "type": "projet",
  "title": "Intégration Whisper API",
  "content_md": "## Objectif\nPermettre la recherche vocale...\n\n## Étapes\n1. ...",
  "frontmatter": {
    "deadline": "2026-07-15",
    "status": "active",
    "priority": "high",
    "next_actions": [
      "Configurer le compte OpenAI",
      "Écrire le prototype"
    ],
    "tags": ["voice", "whisper", "mobile"]
  },
  "location": {
    "wing": "Travail",
    "room": "Projets actifs",
    "drawer": "Voice"
  }
}
```

**Réponse** :

```json
{
  "id": "uuid",
  "type": "projet",
  "ipcra_stage": "projet",
  "title": "Intégration Whisper API",
  "content_md": "...",
  "frontmatter": { "...": "..." },
  "weight": 1.0,
  "access_count": 0,
  "location": { "wing": "Travail", "room": "Projets actifs", "drawer": "Voice" },
  "edges": [],
  "created_at": "2026-06-02T10:00:00Z",
  "updated_at": "2026-06-02T10:00:00Z"
}
```

---

## 6. MCP Server (Go)

### 6.1 Outils exposés

```go
// Chaque outil = une fonction appelable par l'agent
tools := []Tool{
  {
    Name: "memory_remember",
    Description: "Stocke un nouveau souvenir dans Memory",
    Args: schema{type: "object", properties: {
      "space_id":    {type: "string"},
      "title":       {type: "string"},
      "content":     {type: "string"},
      "type":        {type: "string", enum: [...]},
      "properties":  {type: "object"},
      "tags":        {type: "array", items: {type: "string"}},
      "location":    {type: "object"}, // wing, room, drawer
    }},
  },
  {
    Name: "memory_recall",
    Description: "Cherche des souvenirs pertinents par similarité sémantique",
    Args: schema{...}, // query, space_id, limit, stage_filter
  },
  {
    Name: "memory_search",
    Description: "Recherche textuelle + vectorielle combinée",
    Args: schema{...}, // query, space_id, filters
  },
  {
    Name: "memory_graph_query",
    Description: "Explore le graphe autour d'un nœud ou cherche des chemins",
    Args: schema{...}, // node_id, direction, depth, relation_type
  },
  {
    Name: "memory_update_stage",
    Description: "Change l'étape IPCRa d'un souvenir",
    Args: schema{...}, // node_id, new_stage, reason
  },
  {
    Name: "memory_suggest_transitions",
    Description: "Demande au LLM de suggérer les prochaines étapes IPCRa",
    Args: schema{...}, // space_id, node_id (optionnel)
  },
  {
    Name: "memory_get_insights",
    Description: "État global : top souvenirs, decaying, suggestions en attente",
    Args: schema{...}, // space_id
  },
  {
    Name: "memory_stats",
    Description: "Statistiques sur la mémoire (taille, répartition IPCRa, poids moyen)",
    Args: schema{...}, // space_id
  },
}
```

### 6.2 Architecture Go

```
mcp-server/
├── main.go              ← Initialisation, écoute MCP
├── client/
│   └── backend.go       ← Client HTTP vers le backend FastAPI
├── tools/
│   ├── remember.go
│   ├── recall.go
│   ├── search.go
│   ├── graph_query.go
│   ├── update_stage.go
│   ├── suggest.go
│   ├── insights.go
│   └── stats.go
└── go.mod
```

Le MCP Server est un proxy maigre : il valide les entrées, puis appelle l'API REST du backend Python. Pas de logique métier dans Go.

---

## 7. Frontend (React + Tailwind)

### 7.1 Pages / Vues

```
/memory                     → Dashboard (stats, souvenirs récents, decaying items)
/memory/search              → Recherche plein texte + vectorielle
/memory/palace              → Navigation spatiale (arbre ailes/pièces/tiroirs)
/memory/graph               → Vue graphe interactive
/memory/note/{id}           → Édition d'un souvenir (éditeur Markdown + propriétés)
/memory/note/{id}/history   → Timeline du souvenir (transitions, accès)
/memory/gardener            → Configuration + suggestions en attente + historique
/memory/templates           → Gestion des templates Markdown
/memory/settings            → Config espace, LLM, utilisateurs
/memory/admin               → Gestion espace, invitations (multi-user)
```

### 7.2 Responsive

Layout adaptatif :

```
Desktop (>1024px)       Tablet (768-1024px)      Mobile (<768px)
┌─────────┬──────────┐  ┌──────────┬─────────┐   ┌──────────────┐
│ Sidebar │  Content │  │ Sidebar  │ Content │   │   TopBar     │
│ (nav +  │  (main)  │  │ (icons)  │         │   ├──────────────┤
│ palace) │          │  │          │         │   │              │
│         │          │  │          │         │   │   Content    │
│         │          │  │          │         │   │              │
└─────────┴──────────┘  └──────────┴─────────┘   ├──────────────┤
                                                   │  BottomNav   │
                                                   └──────────────┘
```

- Sidebar se rétracte en icônes (tablet) ou en bottom nav (mobile)
- Éditeur Markdown plein écran sur mobile
- Graphe : version simplifiée sur mobile (top 20 nœuds au lieu du graphe complet)

### 7.3 Composants clés

```
src/
├── components/
│   ├── layout/
│   │   ├── Sidebar.tsx           ← Navigation responsive
│   │   ├── TopBar.tsx
│   │   └── BottomNav.tsx         ← Mobile only
│   ├── editor/
│   │   ├── MarkdownEditor.tsx    ← Édition avec preview
│   │   ├── FrontmatterEditor.tsx ← Propriétés typées
│   │   └── StageBadge.tsx        ← Badge IPCRa avec drag
│   ├── graph/
│   │   ├── GraphCanvas.tsx       ← Cytoscape.js
│   │   ├── NodeDetail.tsx        ← Panel latéral au clic
│   │   └── Legend.tsx            ← Légende des types de liens
│   ├── palace/
│   │   ├── PalaceTree.tsx        ← Arbre ailes/pièces/tiroirs
│   │   └── DragNode.tsx          ← Drag & drop vers tiroir
│   ├── gardener/
│   │   ├── SuggestionList.tsx    ← Suggestions en attente
│   │   └── GardenerConfig.tsx    ← Configuration
│   └── search/
│       ├── SearchBar.tsx         ← Barre de recherche unifiée
│       └── SearchResults.tsx     ← Résultats avec scores
├── pages/
│   ├── Dashboard.tsx
│   ├── SearchPage.tsx
│   ├── PalacePage.tsx
│   ├── GraphPage.tsx
│   ├── NotePage.tsx
│   ├── GardenerPage.tsx
│   └── SettingsPage.tsx
├── hooks/
│   ├── useNodes.ts               ← CRUD nodes
│   ├── usePalace.ts              ← Palace tree
│   ├── useGraph.ts               ← Graphe data
│   └── useGardener.ts            ← Jardinier suggestions
├── services/
│   └── api.ts                    ← Client HTTP
├── stores/
│   └── appStore.ts               ← Zustand (espace actif, mode)
└── App.tsx
```

### 7.4 Stack frontend

| Technologie | Usage |
|-------------|-------|
| React 19 | UI |
| Vite | Build / dev |
| Tailwind CSS 4 | Styles responsifs |
| React Router 7 | Navigation |
| Zustand | State management |
| Cytoscape.js | Graphe interactif |
| react-markdown | Rendu Markdown |
| SimpleMDE / CodeMirror | Éditeur Markdown |
| Lucide React | Icônes |

---

## 8. CLI (Python)

```bash
# Commandes principales
memory init                    # Initialiser la config (créer un espace)
memory add "Titre" -t input    # Ajouter un souvenir
memory recall "requête"        # Chercher des souvenirs
memory search "texte" -t projet
memory list --stage input      # Lister par catégorie
memory open <id>               # Ouvrir dans le navigateur
memory edit <id>               # Éditer (ouvre $EDITOR sur le .md)
memory move <id> --to projet   # Changer d'étape IPCRa
memory link <idA> <idB> -t cause  # Lier deux souvenirs
memory graph <id>              # Voir le graphe autour d'un nœud
memory palace                  # Voir l'arbre du palais
memory stats                   # Statistiques
memory gardener run            # Lancer le jardinier
memory gardener suggestions    # Voir les suggestions
memory gardener accept <id>    # Accepter une suggestion
memory export                  # Exporter tout
memory import --from obsidian  # Importer
```

---

## 9. Structure du projet

```
/Users/garinat_t/Desktop/Memory/
│
├── PLAN.md                         ← Ce fichier
├── docker-compose.yml              ← PostgreSQL + services
├── Makefile                        ← Commandes pratiques
│
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                 ← Entrypoint FastAPI
│   │   ├── config.py               ← Settings (pydantic-settings)
│   │   ├── database.py             ← Session SQLAlchemy + pgvector
│   │   ├── dependencies.py         ← Dépendances FastAPI
│   │   │
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   ├── node.py             ← Node ORM + embedding
│   │   │   ├── edge.py             ← Edge ORM
│   │   │   ├── palace.py           ← Palace rooms ORM
│   │   │   ├── user.py             ← Users + spaces
│   │   │   └── gardener.py         ← Gardener log ORM
│   │   │
│   │   ├── routers/
│   │   │   ├── __init__.py
│   │   │   ├── nodes.py            ← CRUD souvenirs
│   │   │   ├── search.py           ← Recherche texte + vecteur
│   │   │   ├── palace.py           ← Organisation spatiale
│   │   │   ├── graph.py            ← Graphe endpoints
│   │   │   ├── gardener.py         ← Jardinier endpoints
│   │   │   ├── temporal.py         ← Decay / reinforcement
│   │   │   ├── spaces.py           ← Espaces multi-user
│   │   │   └── export.py           ← Export / import
│   │   │
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── node_service.py     ← Logique CRUD + validation
│   │   │   ├── search_service.py   ← Recherche hybride
│   │   │   ├── graph_service.py    ← Requêtes graphe (CTE récursif)
│   │   │   ├── palace_service.py   ← Logique palais
│   │   │   ├── gardener_service.py ← Orchestration jardinier
│   │   │   ├── decay_service.py    ← Algorithme de decay
│   │   │   └── embed_service.py    ← Embedding via LLM
│   │   │
│   │   ├── llm/
│   │   │   ├── __init__.py
│   │   │   ├── client.py           ← Client LLM unifié (OpenRouter/Ollama)
│   │   │   ├── gardener_prompts.py ← Prompts pour le jardinier
│   │   │   ├── embedder.py         ← Embedding (texte → vecteur)
│   │   │   └── suggestor.py        ← Suggestions IPCRa
│   │   │
│   │   └── schemas/
│   │       ├── __init__.py
│   │       ├── node.py             ← Pydantic schemas
│   │       ├── search.py
│   │       ├── graph.py
│   │       ├── palace.py
│   │       └── gardener.py
│   │
│   ├── alembic/                    ← Migrations DB
│   ├── requirements.txt
│   └── Dockerfile
│
├── mcp-server/
│   ├── main.go                     ← Entrypoint MCP
│   ├── client/
│   │   └── backend.go              ← HTTP client vers FastAPI
│   ├── tools/
│   │   ├── remember.go
│   │   ├── recall.go
│   │   ├── search.go
│   │   ├── graph_query.go
│   │   ├── update_stage.go
│   │   ├── suggest.go
│   │   ├── insights.go
│   │   └── stats.go
│   ├── go.mod
│   └── Dockerfile
│
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   ├── hooks/
│   │   ├── services/
│   │   ├── stores/
│   │   └── App.tsx
│   ├── index.html
│   ├── package.json
│   ├── tailwind.config.ts
│   └── vite.config.ts
│
├── cli/
│   ├── main.py                     ← Entrypoint CLI (Typer)
│   ├── commands/
│   │   ├── add.py
│   │   ├── recall.py
│   │   ├── search.py
│   │   ├── list.py
│   │   ├── move.py
│   │   ├── link.py
│   │   ├── graph.py
│   │   ├── palace.py
│   │   ├── gardener.py
│   │   └── export.py
│   └── client.py                   ← Client HTTP vers backend
│
└── scripts/
    ├── setup.sh                    ← Script d'installation
    └── seed.py                     ← Données de démo
```

---

## 10. Configuration LLM

### 10.1 Environnement

```bash
# .env
DATABASE_URL=postgresql+asyncpg://memory:memory@localhost:5432/memory

# LLM (au choix)
LLM_PROVIDER=openrouter
LLM_API_KEY=sk-...
LLM_MODEL=anthropic/claude-3.5-sonnet

# OU Ollama (local)
# LLM_PROVIDER=ollama
# LLM_BASE_URL=http://localhost:11434
# LLM_MODEL=llama3

# Embedding
EMBEDDING_MODEL=text-embedding-3-small   # ou "local" avec fastembed

# MCP Server
MCP_SERVER_PORT=8100
```

### 10.2 Prompts Jardinier

**Résumé de cluster** :
```
Tu es le jardinier d'un système de mémoire personnelle.
Analyse ces N souvenirs liés et propose un résumé concis qui les condense.
Format : {title, summary, tags}
```

**Fusion de doublons** :
```
Ces deux souvenirs semblent similaires (score: {score}).
Propose une fusion : titre, contenu combiné, propriétés à garder.
```

**Suggestion IPCRa** :
```
Ce souvenir est en stage "input" depuis {days} jours.
... [contenu du souvenir]
Propose un stage de destination (projet/casquette/ressource/archive)
et justifie en une phrase.
```

---

## 11. Phases d'Implémentation

### Phase 1 — Fondation (Backend + DB)
- [ ] PostgreSQL + pgvector setup (Docker)
- [ ] Modèles SQLAlchemy + Alembic
- [ ] Routers CRUD nodes + palace + edges
- [ ] Embedding + recherche vectorielle
- [ ] Authentification basique (JWT)

### Phase 2 — Frontend de base
- [ ] Layout responsive (sidebar, topbar, bottom nav)
- [ ] Dashboard (stats, récents)
- [ ] Éditeur de note (Markdown + frontmatter)
- [ ] Recherche avec résultats
- [ ] Vue palais (arbre)

### Phase 3 — Graphe + temporalité
- [ ] Vue graphe interactive (Cytoscape)
- [ ] API graphe (chemin, sous-graphe, BFS)
- [ ] Decay scheduler (APScheduler / Celery Beat)
- [ ] Reinforcement (touch endpoint)
- [ ] Notifications pour decaying items

### Phase 4 — IPCRa + jardinier
- [ ] Workflow IPCRa (suggestions LLM)
- [ ] Jardinier LLM (cluster, fusion, inférence)
- [ ] Suggestions avec validation
- [ ] Configurable (mode, intervalle)
- [ ] Historique + logs

### Phase 5 — MCP + CLI + Multi-user
- [ ] MCP Server Go (proxy vers FastAPI)
- [ ] CLI Python (add, recall, search, etc.)
- [ ] Espaces multi-utilisateurs
- [ ] Permissions + invitations
- [ ] Export/Import (Obsidian, JSON)

### Phase 6 — Polish
- [ ] Templates par type IPCRa
- [ ] Drag & drop dans le palais
- [ ] Mode hors-ligne (PWA ?)
- [ ] Tests E2E
- [ ] Documentation utilisateur

---

## 12. Dépendances clés

### Python (backend)
```
fastapi
uvicorn[standard]
sqlalchemy[asyncio]
asyncpg
pgvector
alembic
pydantic-settings
pydantic
httpx
openai                   # LLM client
numpy                    # pour pgvector helper
apscheduler              # tâches planifiées (decay)
typer                     # CLI (optionnel, ou Click)
```

### Go (MCP)
```
github.com/mark3labs/mcp-go       # MCP SDK
github.com/go-resty/resty/v2      # HTTP client
```

### Frontend
```
react, react-dom
react-router-dom
zustand
@xyflow/react                    # Cytoscape-like (React Flow)
react-markdown
tailwindcss
lucide-react
```

---

## 13. Exemples de templates Markdown

### Template Input
```markdown
---
type: input
priority: medium
captured_from: web
tags: []
---

# Titre de la capture

Note brute ici...
```

### Template Projet
```markdown
---
type: projet
status: active
deadline: YYYY-MM-DD
priority: medium
next_actions: []
tags: []
---

# Titre du projet

## Objectif

## Contexte

## Prochaines actions

## Notes
```

### Template Archive
```markdown
---
type: archive
original_type: projet
archived_date: YYYY-MM-DD
lessons_learned: ""
tags: []
---

# Titre (archivé)

## Contexte

## Résultat

## Leçons apprises
```

---

## 14. Règles métier importantes

1. **Un nœud ne peut pas être supprimé** (soft delete → archive → oubli progressif)
2. **Changement de stage IPCRa** : toujours loggé dans `activity_log`
3. **Decay** : ne descend jamais en dessous de 0.05 (trace résiduelle)
4. **Reinforcement** : plafonné à 1.5 (poids max)
5. **Embedding** : regénéré automatiquement à chaque modification du contenu
6. **Palace** : un nœud peut être dans 0 ou 1 tiroir, mais toujours dans une pièce
7. **MCP** : toutes les actions MCP sont loggées dans `activity_log`
8. **Jardinier** : en mode `auto`, jamais d'action destructive sans log

---

> **Prochaine étape :** Implémentation Phase 1 (Backend + DB).
> Tu valides ce plan ? On commence par le docker-compose et les modèles SQL ?

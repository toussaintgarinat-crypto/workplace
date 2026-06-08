# Sprint S16 — Forge, brique de première classe (palier 2 : orchestration sans auth)

> **But du sprint** : faire passer Forge de « core qui répond à `/health` » (S15) à
> **brique pleinement intégrée à l'orchestration Workplace** — démarrée avec la stack,
> visible et actionnable depuis le registre/dashboard, et appelable par l'assistant du
> Cœur sur tout ce qui **ne nécessite pas d'authentification**. On prépare aussi la
> décision d'auth qui débloque le fonctionnel (S17), sans encore l'implémenter.

- **Sprint** : S16
- **Pré-requis** : **S15** (core Forge branché, santé prouvée, branché Gateway+Mémoire)
- **Statut** : **réalisé** (2026-06-06) — 5 chantiers prouvés live (adaptateur 5700, outil
  assistant, dashboard, voie d'auth tranchée). Détail des preuves dans chaque chantier.
- **Périmètre** : tout ce qui se prouve **sans Keycloak ni token**. Le cycle agent/RAG
  fonctionnel est explicitement renvoyé à **S17**.

---

## 0. Contexte — ce qui existe déjà (sortie de S15)

| Élément | État |
|---|---|
| Brique `briques/forge/` (compose Postgres + core, branché Gateway 4001 + Mémoire 5600) | ✅ tourne |
| `GET :8600/api/health` (public, sans DB) / `GET :8600/health` (teste la DB) | ✅ prouvés |
| Sonde live du Cœur `GET /briques/forge/sante` | ✅ `{"statut":"ok","code_http":200}` |
| `briques/forge/manifest.json` (port 8600, depends_on gateway+memoire) | ✅ présent |
| Le core monte ses routes en `/api/*` **et** `/v1/api/*` ; `/api/health` = seule route publique | constat S15 |
| Lanceur `Lancer Workplace.command` (gateway→memoire/etl/donnees→audit→generateur→oria→core) | ⚠️ **ne lance pas Forge** |
| Forge non **copié** dans Workplace (build pointe `../../../workspace/forge`) | ⚠️ dossier pas 100 % autonome |

**Constat clé** : Forge est debout mais **hors du flux de vie** de Workplace (pas dans le
lanceur, adaptateur de contrat absent, l'assistant ne sait pas l'appeler). Ce sprint
referme ce gap pour tout ce qui est faisable sans auth.

---

## Chantier 0 (fondation) — Forge dans le cycle de vie de la stack

Sans ça, Forge dépend d'un `make up` manuel et meurt hors du `Lancer Workplace.command`.

- **Modifier** `Lancer Workplace.command` et `Arrêter Workplace.command` : ajouter `forge`
  dans l'ordre de démarrage **après** `gateway` et `memoire` (ses dépendances), attendre
  `:8600/api/health` avant de continuer.
- **Décision à acter** : **copier** `workspace/forge` dans `briques/forge/forge-src/`
  (comme gateway/oria l'ont été) pour rendre le dossier autonome, **ou** assumer le lien
  vers le `workspace` voisin. Recommandation : copier (cohérent avec « Dossier autonome »),
  en excluant `node_modules`/`dist`/`.git` via `.dockerignore` ; ~331 Mo → vérifier l'impact.

**Critères d'acceptation**
- [x] `Lancer Workplace.command` démarre Forge et attend sa santé (mis à jour : attend
  désormais l'**adaptateur** `:5700/sante`, plus parlant que `:8600/api/health` car il prouve
  core + DB ; cohérent avec memoire).
- [x] `Arrêter Workplace.command` arrête proprement la brique `forge` (déjà présent, vérifié).
- [x] (copie faite) `briques/forge/forge` + `shared/` vendorisés, `.dockerignore` en place,
  build `forge/core/Dockerfile` en contexte `.` → dossier autonome (core healthy live).

---

## Chantier 1 — Registre & dashboard : Forge actionnable

> Aujourd'hui la carte Forge existe mais n'expose qu'un lien santé.

### Conception
- Enrichir `briques/forge/manifest.json` : ajouter `url_ui` (Swagger `:8600/docs`, puisque le
  frontend Forge n'est pas levé dans ce palier) et, si pertinent, `vue_dashboard`.
- Vérifier que le panneau de détail du registre (`core/main.py`, fonction d'ouverture de brique)
  affiche pour `forge` : santé live, dépendances (gateway, memoire), port, et le lien Swagger.
- Corriger le rôle/couche affichés (`role: agents`, `couche: backend`) si besoin.

### Critères d'acceptation
- [x] La carte Forge montre **santé live verte** (● en ligne via `:5700/sante`) ; le panneau de
  détail expose « Ouvrir l'application ↗ » → `http://localhost:8600/docs` (via `url_ui`) et
  « Santé ↗ » → `:5700/sante`.
- [x] Dépendances `gateway`/`memoire` affichées et résolues (rôle « Agents », couche « Backend »).
- [x] Vérifié au navigateur (Playwright) : seule erreur console = `favicon.ico` 404 préexistant
  (aucune erreur JS de la carte).

---

## Chantier 2 — Adaptateur de contrat `briques/forge/main.py` (modèle Neovim)

> Comme `briques/memoire/main.py` : un adaptateur fin qui expose un **contrat Workplace
> en français**, et masque l'API interne de Forge. Périmètre S16 = **non authentifié**.

### Conception
- **Nouveau** : `briques/forge/main.py` (FastAPI), conteneur séparé exposé sur l'hôte
  (port libre, ex. 5700), proxy vers le core `:8600`.
- Contrat minimal **sans auth** :
  - `GET /sante` → agrège `:8600/api/health` + `:8600/health` (DB), renvoie le schéma Workplace.
  - `GET /capacites` → liste statique des familles d'agents/offres exposées par Forge
    (lue depuis le manifest : `agents_ia`, `rag`, `vectorisation`) — pour que l'assistant
    sache *ce que Forge peut faire* avant même de pouvoir l'invoquer (S17).
- Mettre `url_sante` du manifest sur l'adaptateur (cohérent avec memoire/etl/donnees en `/sante`).
- **Ne pas** proxifier ici les routes auth (agents/documents) → c'est S17.

### Critères d'acceptation
- [x] `curl :5700/sante` → `{"statut":"ok","service":"forge","core":{…dependances postgres ok}}`
  (agrège `:8600/api/health` + `:8600/health`).
- [x] `curl :5700/capacites` → 3 familles déclarées (agents_ia, rag, vectorisation), `core_en_ligne:true`.
- [x] Le Cœur sonde l'adaptateur : `GET :5100/briques/forge/sante` → `{"statut":"ok","code_http":200}`
  via le nouveau `url_sante` (`:5700/sante`).

> **Note d'implémentation** : l'adaptateur est un **service distinct** `forge-adapter` du
> compose de la brique (port hôte `5700`, image minimale `briques/forge/Dockerfile` + `main.py`),
> proxy vers le core via le DNS compose `http://forge:8600`. Le `port` du manifest passe à `5700`
> → `_brique_base(forge)` du Cœur cible l'adaptateur (comme memoire). Le core reste exposé en
> `8600` (Swagger via `url_ui`).

---

## Chantier 3 — Outil assistant « état/capacités Forge » (lecture seule)

> Donner à l'assistant du Cœur une première prise sur Forge, sans toucher à l'auth.

### Conception
- **Modifier** `core/outils.py` (+ enregistrement dans la boucle `core/assistant.py`) :
  ajouter un outil `forge_capacites` (lecture) qui appelle l'adaptateur `/capacites` + `/sante`.
- Pas d'action à effet de bord → **pas de confirmation** requise (cohérent avec la convention :
  lecture libre, actions gardées par `confirme=true`).
- Préparer (désactivés/documentés) les *signatures* des futurs outils d'action Forge
  (`forge_lancer_agent`, `forge_rag_ingerer`, `forge_rag_chercher`) pour que S17 n'ait qu'à
  brancher l'implémentation derrière l'auth.

### Critères d'acceptation
- [x] À « que peut faire Forge, et est-ce qu'elle tourne ? », l'assistant appelle `forge_capacites`
  (`en_ligne:true, sante:ok`) et répond juste (3 familles + note « nécessite authentification »).
- [x] Dégradation propre : si l'adaptateur est injoignable/HTTP≥400, l'outil renvoie
  `{en_ligne:false, message:"… injoignable / en erreur"}` — pas de stacktrace.
- [x] Prouvé E2E via `POST :5100/assistant/chat` (événement `outil: forge_capacites` émis).
- [x] Signatures S17 désactivées présentes : `OUTILS_FORGE_S17` (`forge_lancer_agent`,
  `forge_rag_ingerer`, `forge_rag_chercher`) — documentées, non branchées dans `OUTILS`.

---

## Chantier 4 — Décider la stratégie d'auth (spike, pas d'implémentation)

> Tout le fonctionnel de Forge (agents, RAG, CRM…) est derrière `get_current_user`
> (Keycloak, résolution par issuer — cf. S14 côté Oria). Il faut **choisir la voie** avant S17.

### Pistes à instruire (livrable = note de décision dans le doc S17)
1. **Clé de service / API key** : le core a un router `api_keys`. Vérifier s'il permet un
   appel machine-à-machine **sans** flux Keycloak interactif. (Voie la plus simple si elle existe.)
2. **Token de service via Keycloak** : réutiliser le **Keycloak d'Oria** (déjà up, `:8081`) avec
   un realm/clientid de service (ROPC ou client_credentials), à l'image du motif S14
   (`KEYCLOAK_REALMS_AUTORISES`, résolution par issuer). Forge accepte un `KEYCLOAK_URL`.
3. **Mode mono-utilisateur** : un middleware Forge « identité par en-tête » (comme la brique
   `agenda` qui fait `X-User-Id`, auth off) — le plus rapide, mais touche le code Forge.

### Critères d'acceptation
- [x] **Note de décision** écrite en tête de S17 : **voie 2 (token Keycloak de service via Oria)**
  retenue ; voies 1 (api_keys = clés provider, pas du M2M) et 3 (X-User-Id = fork du core) écartées,
  avec le pourquoi.
- [x] Faisabilité prouvée à la main : token `client_credentials` (client `forge-service` du realm
  `oria`) accepté par Forge sur `GET /api/agents` — **sans token → 401**, **token bidon → 401**
  (signature vérifiée), **token valide → 500 `users does not exist`** = auth franchie, seul blocage =
  schéma DB non migré (livrable S17). Forge **remis à l'état « sans auth »** après la preuve.

---

## Séquencement & dépendances

```
Chantier 0 (lanceur/autonomie)  ─ indépendant, ferme le gap « hors flux »
Chantier 1 (registre/dashboard) ─ indépendant
Chantier 2 (adaptateur /sante,/capacites) ──► prérequis du Chantier 3
Chantier 3 (outil lecture assistant)
Chantier 4 (spike auth)         ─ indépendant, débloque S17
```

**Ordre recommandé** : `0 → 2 → 3 → 1 → 4` (rendre Forge vivant et lisible d'abord,
spike auth en parallèle/fin).

---

## Backlog découpé (tickets)

| # | Ticket | Chantier | Estim. |
|---|---|---|---|
| S16-1 | Ajouter Forge au `Lancer/Arrêter Workplace.command` (ordre + attente santé) | 0 | S |
| S16-2 | (Décision) copier `workspace/forge` dans la brique + `.dockerignore` → autonomie | 0 | M |
| S16-3 | Enrichir manifest (`url_ui` Swagger) + panneau registre Forge | 1 | S |
| S16-4 | Adaptateur `briques/forge/main.py` : `/sante` + `/capacites` (sans auth) | 2 | M |
| S16-5 | `url_sante` → adaptateur ; re-sonde Cœur OK | 2 | S |
| S16-6 | Outil `forge_capacites` (lecture) dans `core/outils.py` + assistant | 3 | M |
| S16-7 | Signatures (désactivées) des futurs outils d'action Forge | 3 | S |
| S16-8 | Spike auth : tester api_keys / Keycloak Oria / X-User-Id → note de décision | 4 | M |

Tailles indicatives : S ≈ ½j, M ≈ 1–2j.

---

## Métriques de succès du sprint

- **Intégration** : Forge démarre/arrête **avec** la stack (0 commande manuelle).
- **Lisibilité** : carte Forge verte + Swagger ouvrable depuis le registre.
- **Prise assistant** : l'assistant répond correctement sur l'état/les capacités de Forge.
- **Décision** : voie d'auth tranchée + **1** appel authentifié prouvé à la main.

## Hors-scope (→ S17)

- Tout appel **fonctionnel** authentifié généralisé (agents, RAG, CRM, ventures…).
- Migration du schéma DB de Forge (Alembic) et Qdrant pour le RAG.
- Frontend Forge (port 3000) levé dans la stack.
- E2EE / multi-tenant Forge.

---

## Notes d'honnêteté technique

- Ce sprint **n'apporte pas encore de valeur fonctionnelle** Forge à l'utilisateur final :
  il rend Forge *intégré et lisible*, et **prépare** la valeur (S17). À assumer tel quel —
  c'est la moitié « plomberie » nécessaire pour que S17 soit court et sûr.
- Risque de dispersion : ne pas commencer à brancher des routes auth « tant qu'on y est ».
  Le garde-fou = le périmètre « sans auth » de S16 est une frontière dure.

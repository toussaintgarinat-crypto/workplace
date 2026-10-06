# S241 — Recherche unifiée Forge + Mémoire (hybride, sans nouveau moteur)

Date : 2026-10-06. Statut : conception validée par l'utilisateur.
Source : docs/sprints/S235-S239-infrastructure-supervision-recherche.md (ex-« S239 Meilisearch + Qdrant » ; le numéro S239 a servi à la panne LLM).
Branche : `sprint/s241-recherche-unifiee`.

## État constaté (2026-10-06)

- Corpus « documents » = Forge uniquement : `documents` (téléversés, texte déjà extrait) et `kb_articles`. Découpés en fragments 512/64 et vectorisés dans Qdrant (`briques/forge/forge/core/app/memory.py`) par tâche de fond sans reprise ni signalement d'échec.
- HP, lecture seule : 6 documents, 0 article, 1 utilisateur, 38 points dans `forge_local`.
- **Défaut de sécurité** : `_qdrant_search` (`memory.py:261`) ne filtre que sur `pole_id`, jamais sur `user_id`. `GET /api/rag/search` et `get_context` (chat, ReAct) renvoient donc les passages des documents de tous les utilisateurs. Sans effet aujourd'hui (un seul utilisateur).
- Suppression : `delete_by_source` en tâche de fond, échec silencieux ; aucun contrôle.
- `/api/search` : `LIKE` sensible à la casse, sans tolérance de faute.
- Mémoire : recherche hybride depuis S238 (exacts en tête, plein texte + trigrammes, pgvector, RRF), isolée par personne (S186), exposée par `GET /rappeler` (un espace par appel : `perso`, `solution`, `veille`).
- Identité : le Cœur transmet le JWT de l'utilisateur à l'adaptateur Forge par `X-Forge-User-Token` (`core/contexte_tenant.py`), propagé au core Forge.
- Base Forge : `postgres:16.14` (contrib `unaccent`, `pg_trgm` disponibles).

## Décisions

1. **Corpus** : documents + base de connaissances de la Forge **et** souvenirs de la Mémoire, dans une seule recherche (option B).
2. **Usages** : outil de l'assistant **et** barre de recherche du tableau de bord du Cœur (option B). Les recherches internes de la Forge (`/api/search`) ne sont pas basculées.
3. **Fédération sans nouveau moteur** (approche 1) : chaque brique cherche dans sa propre base, qui fait foi ; le Cœur fusionne. Meilisearch écarté : aucun gain mesurable sur 6 documents, et la synchronisation d'un index tiers est la principale source de fuites et de suppressions non propagées. Réévaluable sans changer le contrat du Cœur.
4. **PostgreSQL fait foi, Qdrant est un index reconstructible.**

## 1. Architecture

```
Tableau de bord (barre)  ─┐
Assistant (chercher_documents) ─┴─► Cœur GET /recherche  (session obligatoire)
                    ┌───────────────┴────────────────┐
                    ▼                                ▼
   Adaptateur Forge GET /documents/chercher   Mémoire GET /rappeler × {perso, solution, veille}
   (X-Forge-User-Token)                       (par personne)
                    ▼
   Forge core GET /api/recherche/hybride
     exacts │ lexical (tsvector + trigrammes) │ vectoriel (Qdrant, filtré user_id)
     → recoupement PostgreSQL → regroupement par document → RRF k=60, exacts en tête
```

### 1.1 Forge core

- `app/recherche_fusion.py` — fonctions pures reprises de S238 (`briques/memoire/memory/backend/app/services/recherche_fusion.py`) : `extraire_references(q)`, `fusion_rrf(classements, k=60)`, `ordonner(exacts, fusion)`. Copie adaptée (les briques ne partagent pas de code).
- `app/recherche_documents.py` — requêtes SQL, **toutes filtrées par `user_id = :moi` dans la requête** :
  - plein texte : colonne générée `recherche_tsv` sur `documents` (`nom` poids A, `nom || contenu` poids B) et sur `kb_articles` (`titre` A, `titre || tags || contenu` B), configurations `simple` et `french`, sans accents (fonction `forge_unaccent` IMMUTABLE), index GIN ; requête en OU sur les termes, `ts_rank_cd` ;
  - repli trigramme si le plein texte ne renvoie rien : `word_similarity(...) >= 0.3`, index GIN `gin_trgm_ops` ;
  - références exactes : expression régulière à limites de mot sur titre et contenu normalisés.
- `memory.py` : `_qdrant_search` et `get_context` reçoivent un `user_id` **obligatoire** ajouté au filtre (`must` user_id, + pole_id si fourni). Corrige `/api/rag/search`, le chat et le ReAct. Nouvelle fonction `chercher_fragments(question, user_id, limite)` qui renvoie des points structurés (`source_id`, `source_type`, `text`, `score`) au lieu d'un texte concaténé ; elle **lève** `RechercheVectorielleIndisponible` si l'embedder ou Qdrant échoue (pas de `""` silencieux pour ce chemin).
- `app/routers/recherche.py` — `GET /api/recherche/hybride?q=&limite=&sources=` (protégé, `get_current_user`). Réponse :
  ```json
  {"mode": "hybride" | "lexical",
   "resultats": [{"id", "source": "document" | "kb", "titre", "extrait", "rang", "exact": bool}]}
  ```
  Le `rang` est la position finale (1 = meilleur). Pas de score brut exposé.
- Migrations de démarrage idempotentes (même motif que S238) : `CREATE EXTENSION IF NOT EXISTS unaccent, pg_trgm`, fonction `forge_unaccent`, colonnes générées, index.

### 1.2 Adaptateur Forge (`briques/forge/main.py`)

- `GET /documents/chercher?q=&limite=` → `GET /api/recherche/hybride` via `_appel_protege` (jeton utilisateur propagé). Capacité `forge_documents_chercher` déclarée au manifeste, lecture seule.

### 1.3 Mémoire

Aucun changement de code.

### 1.4 Cœur

- `core/recherche_unifiee.py` : interroge en parallèle Forge (`/documents/chercher`) et Mémoire (`/rappeler` pour `perso`, `solution`, `veille`) avec les en-têtes d'identité existants (`entetes_forge()`, en-têtes par personne de `memoire`). Délai maximal par source : 8 s. Fusion RRF (k=60) des classements par source ; les résultats `exact` de chaque source passent devant. Réponse :
  ```json
  {"resultats": [{"source": "forge-document" | "forge-kb" | "memoire-perso" | ..., "id", "titre", "extrait", "lien"}],
   "modes": {"forge": "hybride", "memoire-perso": "lexical", ...},
   "sources_indisponibles": ["forge"]}
  ```
- Route `GET /recherche?q=&limite=&sources=` : **session obligatoire** (401 sinon : garde de session API de `core/auth.py`, motif S240 ; pas d'admin requis). `sources` filtre (`forge`, `memoire`).
- Outil assistant `chercher_documents` (manifeste du Cœur, lecture seule) appelant le même service.
- Tableau de bord : barre de recherche, liste de résultats (badge source, titre, extrait), lien vers le document Forge ou le souvenir Mémoire, bandeau si `modes` contient `lexical` ou si `sources_indisponibles` est non vide. Rendu par `textContent` / échappement (filet XSS S240).

## 2. Flux, droits, mode réduit

### 2.1 Recherche Forge

1. Exacts, lexical et vectoriel en parallèle.
2. Les `source_id` renvoyés par Qdrant sont **recoupés** : `SELECT id FROM documents WHERE id = ANY(:ids) AND user_id = :moi` (idem `kb_articles`). Tout point orphelin ou mal attribué est écarté.
3. Regroupement par document : chaque document prend le meilleur rang de ses fragments ; l'extrait est ce fragment (vectoriel) ou un `ts_headline` (lexical), tronqué à 280 caractères.
4. `ordonner` : exacts d'abord, puis RRF.

### 2.2 Suppression et retrait d'accès

- La suppression en base rend le document introuvable **immédiatement** dans les trois branches, même si l'effacement Qdrant échoue (recoupement 2.1-2).
- Accès Forge = propriété (`user_id`). `is_public` n'est pas pris en compte par la recherche. Retrait d'un compte (`delete_by_user`, RGPD) : même mécanisme.
- Mémoire : droits inchangés (S186/S238).

### 2.3 Indexation reprenable

- Tâche planifiée `reconcilier_index` dans la Forge, toutes les 10 min : par lots de 50, compare les `source_id` des tables `documents`/`kb_articles` et ceux de la collection active (`payload.source_id`, `payload.user_id`) ; revectorise les sources sans point ou dont un point porte un autre `user_id` ; supprime les points orphelins ; s'arrête au premier échec de l'embedder (reprise au passage suivant). Journalise un compte rendu.
- Commande d'exploitation `python -m app.recherche_reindexer [--user <id>]` (lancée par `docker exec`, pas de route HTTP : la Forge n'a pas de rôle admin) : vide les points d'un utilisateur ou de tous dans la collection active, puis enchaîne la réconciliation jusqu'au bout.
- Les ingestions de tâche de fond existantes (`documents`, `kb`) sont conservées ; la réconciliation les rattrape.

### 2.4 Mode réduit

| Panne | Effet |
|---|---|
| Embedder ou Qdrant | Forge renvoie exacts + lexical, `mode: "lexical"` |
| Forge injoignable / délai | Cœur renvoie la Mémoire, `sources_indisponibles: ["forge"]` |
| Un espace Mémoire | Idem, espace signalé |
| Toutes les sources | 503 avec message explicite |

Jamais de liste vide présentée comme un succès quand une source a échoué.

## 3. Tests, mesure, déploiement

### 3.1 Tests

- Forge (PostgreSQL réel en conteneur) : fonctions pures ; exact, plein texte, trigramme ; **isolation** deux utilisateurs dans chaque branche, y compris un point Qdrant de A volontairement étiqueté `user_id` B ; document supprimé absent malgré un point Qdrant restant ; mode lexical sur embedder en échec ; `reconcilier_index` (rattrapage, orphelins, arrêt au premier échec) ; régression : `/api/rag/search` et `get_context` ne renvoient plus les passages d'un autre utilisateur.
- Adaptateur : propagation du jeton, forme de la réponse.
- Cœur : fusion multi-sources ; délai et `sources_indisponibles` ; 503 si tout échoue ; 401 sans session ; en-têtes d'identité vers Forge et Mémoire ; contrat manifeste ↔ route (filet S210) ; filet XSS statique S240 sur le rendu.

### 3.2 Mesure

Jeu fixe committé (documents et requêtes) : requêtes exactes, sémantiques (reformulations), avec faute de frappe. Rappel@5 en hybride, embedder coupé, et ancien `LIKE` en référence. Chiffres dans `docs/sprints/S241-recherche-unifiee-resultats.md`.

### 3.3 Déploiement HP

Images construites sur le Mac, `docker save | ssh docker load`. Étiquettes `avant-s241`, sauvegarde `~/s241-avant/` (dump base Forge, instantané Qdrant). Migrations de démarrage idempotentes ; la réconciliation indexe l'existant. Aucun nouveau service : supervision S235, sauvegardes S236, Ansible S237 inchangés, sauf la sonde métier qui interroge `/recherche`.

### 3.4 Preuve LIVE

Faute de frappe qui retrouve un vrai document ; embedder coupé → `lexical` ; Forge arrêtée → résultats Mémoire et Forge signalée ; document supprimé introuvable ; 401 sans session.

## Hors périmètre

Meilisearch (réévaluable si le corpus grossit) ; partage de documents entre utilisateurs ; bascule de `/api/search` de la Forge ; messages, mails, wikis.

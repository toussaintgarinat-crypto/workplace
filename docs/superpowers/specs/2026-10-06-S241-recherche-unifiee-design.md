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
- **Brique `ingestion`** (constat pendant la rédaction du plan) : le vrai stock de documents (25 sur le HP, SQLite `/data/ingestion.db`, texte extrait + classement). Une seule clé de service, **pas d'isolation par personne** : tout utilisateur du Cœur voit déjà ces documents. Le Cœur a déjà un outil câblé `chercher_documents` qui charge 200 documents et cherche une sous-chaîne dans leur JSON.
- **Identité Forge depuis le Cœur** : une session web du Cœur ne porte pas de JWT utilisateur (`lire_contexte_tenant` ne lit le jeton que dans les en-têtes). Depuis le Cœur, l'adaptateur Forge agit donc sous son **identité de service unique** (modèle mono-propriétaire S20), comme tous les outils `forge_*`. Le filtre `user_id` reste indispensable dans la Forge (accès direct au front Forge, chat, ReAct).

## Décisions

1. **Corpus** : documents + base de connaissances de la Forge, souvenirs de la Mémoire **et documents de la brique `ingestion`** (décision du 2026-10-06, option A : source ajoutée telle qu'elle est, partagée et signalée comme telle, sans élargir aucun accès).
2. **Usages** : outil de l'assistant **et** onglet de recherche du tableau de bord du Cœur (option B). L'outil câblé existant `chercher_documents` est réutilisé (pas de second outil) : avec `q`, il passe par la recherche unifiée ; sans `q`, il garde son listage filtré (catégorie, projet, entreprise) dont dépend `projets.py`. Les recherches internes de la Forge (`/api/search`) ne sont pas basculées.
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
                                              Ingestion GET /recherche (partagée, clé de service)
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

- `GET /documents/chercher?q=&limite=&sources=` → `GET /api/recherche/hybride` via `_appel_protege` (jeton utilisateur propagé). Renvoie aussi `identite` (`utilisateur` ou `service`) pour que le Cœur marque les résultats partagés. **Non déclarée au manifeste**, raison nommée : l'assistant a déjà `forge_rag_chercher` (Forge seule) et `chercher_documents` (toutes sources) ; une troisième capacité jumelle brouillerait son choix d'outil.

### 1.3 Mémoire

Aucun changement de code. NB : `ingest` de la Forge retient aussi chaque document comme souvenir « ressource » dans l'espace partagé de la Mémoire ; un même document peut donc sortir deux fois (Forge et Mémoire). Pas de dédoublonnage en S241.

### 1.3 bis Ingestion

- Table FTS5 `documents_recherche(doc_id UNINDEXED, nom, texte)` (tokeniseur `unicode61 remove_diacritics 2`) et table FTS5 `documents_trigrammes(doc_id UNINDEXED, texte)` (tokeniseur `trigram`), alimentées **dans la même transaction** que chaque écriture de `stockage.py` (`sauvegarder`, `importer`, `classer`, `supprimer`). Le texte y est normalisé en Python (minuscules, sans accents, NFKD) ; `nom` + `texte_extrait` + catégorie/tags/projet/résumé du classement ; plafond 200 000 caractères.
- `reconstruire_index()` : vide et reremplit les deux tables depuis `documents`. Appelée par `initialiser()` si le nombre de lignes indexées diffère du nombre de documents (rattrape une base antérieure à S241 ou une écriture hors `stockage.py`).
- `chercher(q, limite)` : références exactes d'abord (fonction SQL `regexp` enregistrée sur la connexion, mêmes règles que S238), puis plein texte (`bm25`), puis, si le plein texte ne trouve rien, trigrammes (OU des trigrammes des mots de la requête, `bm25`) — filet pour les fautes de frappe.
- Route `GET /recherche?q=&limite=` (clé de service, comme les autres routes). Réponse au même format que la Forge, `mode: "lexical"`, `source: "ingestion"`. Capacité non exposée au LLM (le Cœur l'appelle en câblé).

### 1.4 Cœur

- `core/recherche_unifiee.py` : interroge en parallèle Forge (`/documents/chercher`, en-têtes `entetes_forge_sortants()`), Ingestion (`/recherche`, `_entetes_brique("ingestion")`) et Mémoire (`/rappeler` pour `perso`, `solution`, `veille`, `_entetes_brique("memoire")`). Délai maximal par source : 8 s. Fusion RRF (k=60) des classements par source ; les résultats `exact` de chaque source passent devant. Réponse :
  ```json
  {"resultats": [{"source": "forge-document" | "forge-kb" | "ingestion" | "memoire-perso" | ..., "id", "titre", "extrait", "partage": bool}],
   "modes": {"forge": "hybride", "memoire-perso": "lexical", ...},
   "sources_indisponibles": ["forge"]}
  ```
- `partage` vaut vrai pour `ingestion` et pour la Forge appelée sans jeton utilisateur (identité de service) : l'interface l'affiche.
- Route `GET /recherche?q=&limite=&sources=` : **session obligatoire** (401 sinon : garde de session API de `core/auth.py`, motif S240 ; pas d'admin requis). `sources` filtre (`forge`, `ingestion`, `memoire`).
- Outil câblé existant `chercher_documents` (`core/outils.py`, `core/outils_domaines/documents.py`) : avec `q` → même service ; sans `q` → listage d'origine.
- Tableau de bord : onglet « 🔎 Recherche » (champ, liste de résultats : badge source, mention « partagé », titre, extrait), bandeau si `modes` contient `lexical` ou si `sources_indisponibles` est non vide. Rendu par création d'éléments et `textContent` uniquement (filet XSS S240). Pas de lien profond vers les fronts de briques en S241 (aucun ne sait ouvrir un document par identifiant).

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
| Un espace Mémoire, ou Ingestion | Idem, source signalée |
| Toutes les sources | 503 avec message explicite |

Jamais de liste vide présentée comme un succès quand une source a échoué.

## 3. Tests, mesure, déploiement

### 3.1 Tests

- Forge (PostgreSQL réel en conteneur) : fonctions pures ; exact, plein texte, trigramme ; **isolation** deux utilisateurs dans chaque branche, y compris un point Qdrant de A volontairement étiqueté `user_id` B ; document supprimé absent malgré un point Qdrant restant ; mode lexical sur embedder en échec ; `reconcilier_index` (rattrapage, orphelins, arrêt au premier échec) ; régression : `/api/rag/search` et `get_context` ne renvoient plus les passages d'un autre utilisateur.
- Adaptateur : propagation du jeton, forme de la réponse.
- Ingestion : index tenu à jour par chaque écriture (y compris suppression et classement), reconstruction, exact/plein texte/trigramme, accents et casse.
- Cœur : fusion multi-sources ; délai et `sources_indisponibles` ; 503 si tout échoue ; 401 sans session ; en-têtes d'identité vers Forge et Mémoire ; contrat manifeste ↔ route (filet S210) ; filet XSS statique S240 sur le rendu.

### 3.2 Mesure

Jeu fixe committé (documents et requêtes) : requêtes exactes, sémantiques (reformulations), avec faute de frappe. Rappel@5 en hybride, embedder coupé, et ancien `LIKE` en référence. Chiffres dans `docs/sprints/S241-recherche-unifiee-resultats.md`.

### 3.3 Déploiement HP

Images (Cœur, Forge core, adaptateur Forge, ingestion) construites sur le Mac, `docker save | ssh docker load`. Étiquettes `avant-s241`, sauvegarde `~/s241-avant/` (dump base Forge, instantané Qdrant, copie de `ingestion.db`). Migrations de démarrage idempotentes ; la réconciliation indexe l'existant. Aucun nouveau service : supervision S235, sauvegardes S236, Ansible S237 inchangés (le volume `ingestion_data` et la base Forge sont déjà sauvegardés ; l'index FTS5 vit dans `ingestion.db` et se reconstruit seul). Pas de nouvelle sonde métier Ansible en S241 : la preuve LIVE couvre `/recherche`.

### 3.4 Preuve LIVE

Faute de frappe qui retrouve un vrai document ; embedder coupé → `lexical` ; Forge arrêtée → résultats Mémoire et Forge signalée ; document supprimé introuvable ; 401 sans session.

## Hors périmètre

Meilisearch (réévaluable si le corpus grossit) ; partage de documents entre utilisateurs ; bascule de `/api/search` de la Forge ; messages, mails, wikis.

# S238 — Recherche Mémoire avec repli lexical indépendant

Date : 2026-10-05. Statut : conception validée par l'utilisateur.
Source : docs/sprints/S235-S239-infrastructure-supervision-recherche.md.
Branche : `sprint/s238-memoire-repli-lexical`.

## État constaté

Code : `briques/memoire/memory/backend/app/services/search_service.py`.

- La recherche « hybride » est une seule requête vectorielle (`n.embedding IS NOT NULL`) à laquelle s'ajoute `+0.3` si un mot apparaît (`ILIKE`). Les souvenirs sans embedding sont invisibles ; si la requête n'est pas vectorisée, la réponse est `[]`.
- `Embedder.embed_text` ne lève jamais : sur échec du Gateway il renvoie un vecteur pseudo-aléatoire constant (graine 42). En recherche, tous les scores se valent et le résultat est du bruit présenté comme un succès. En écriture, ce faux vecteur est **stocké** comme réel.
- HP, lecture seule le 2026-10-05 : 69 souvenirs, 66 avec embedding, **11 portant exactement le vecteur graine 42**, 3 sans embedding.
- Les droits sont vérifiés en amont (`check_space_access` en dépendance de routeur) ; la recherche filtre par `space_id`.
- Aucun appelant (Forge, Cœur, front) n'applique de seuil sur `score`.
- PostgreSQL 16 + pgvector 0.8.2 ; configurations `french` et `simple` présentes ; `unaccent` et `pg_trgm` absentes mais fournies par contrib.
- `/search/semantic` et `/collections/{id}/search` sont purement vectoriels et subissent le même faux vecteur.

## Décisions

1. **Embedder honnête** : l'échec est signalé, jamais remplacé par un vecteur inventé (option A).
2. **Références exactes en priorité stricte** (option A).
3. **Branche lexicale en PostgreSQL natif** : plein texte + trigrammes (approche 1). Meilisearch reste le périmètre de S239.
4. **Fusion RRF (k=60)** des branches lexicale et vectorielle ; aucune addition de scores de natures différentes.

## 1. Embedder et revectorisation

- `Embedder.embed_text` lève `EmbeddingIndisponible` sur toute erreur du client ; un texte vide (après `strip`) renvoie `None`. `embed_batch` suit le même contrat.
- `EmbedService.embed_node` : sur `EmbeddingIndisponible`, laisse `embedding` à `NULL`, journalise un avertissement et renvoie `None`. La création/modification du souvenir n'échoue pas.
- Nouvelle tâche planifiée `revectoriser_manquants` (APScheduler, toutes les 10 min) : sélectionne au plus 50 souvenirs, tous espaces confondus, avec `embedding IS NULL` et contenu ou titre non vide, les vectorise, commit, et s'arrête au premier `EmbeddingIndisponible`.
- `embed_all_missing` utilise le même contrat (arrêt au premier échec).
- `/search/semantic` et la recherche de collection : sur `EmbeddingIndisponible`, réponse **503** « recherche sémantique indisponible (embedder injoignable) ». Pas de branche lexicale pour eux.

## 2. Schéma — migration de démarrage

Une fonction unique `appliquer_migrations(conn)` (module `app/migrations_demarrage.py`), appelée par `lifespan` et par `tests/conftest.py`. Elle reprend les `ALTER` S109–S112 existants et ajoute, tous idempotents :

- `CREATE EXTENSION IF NOT EXISTS unaccent` et `pg_trgm` (aussi ajoutés à `init-pgvector.sql` pour les installations neuves).
- Fonction `memoire_unaccent(text) RETURNS text IMMUTABLE PARALLEL SAFE` enveloppant `public.unaccent('public.unaccent', $1)`.
- Colonne générée stockée `recherche_tsv tsvector` :
  `setweight(to_tsvector('simple', memoire_unaccent(coalesce(title,''))), 'A') || setweight(to_tsvector('french', memoire_unaccent(coalesce(title,'') || ' ' || coalesce(content_md,''))), 'B')`, avec index GIN.
- Index GIN trigramme sur `memoire_unaccent(lower(coalesce(title,'') || ' ' || coalesce(content_md,'')))`.
- Nettoyage graine 42 : `UPDATE nodes SET embedding = NULL WHERE embedding <=> :graine42 < 1e-6`, le vecteur étant recalculé à l'identique (`numpy.random.default_rng(42).uniform(-0.1, 0.1, 384)`). Idempotent ; la tâche de revectorisation prend le relais.

## 3. Recherche

Modules dans `app/services/` :

- `recherche_fusion.py` — fonctions pures, sans base :
  - `extraire_references(q)` : expressions entre guillemets, et jetons contenant un chiffre ou l'un de `- _ . / @ #` (ponctuation de bord retirée). Normalisation : minuscules, sans accents.
  - `fusion_rrf(classements, k=60)` : `Σ 1/(k + rang)` par identifiant.
  - `ordonner(exacts, fusion)` : les exacts d'abord (toutes références trouvées > une partie ; titre > contenu ; puis rang de fusion), puis le reste par score de fusion décroissant. Score final strictement décroissant (offset pour le palier exact).
- `recherche_conditions.py` — constructeur unique des conditions SQL : `space_id`, `status IN ('active','archived')`, type, étape, tier. Toutes les branches l'utilisent.
- `recherche_lexicale.py` :
  - Plein texte : requête en OU sur les termes (`to_tsquery` construit depuis les termes nettoyés, configurations `simple` et `french`, sans accents), classement `ts_rank_cd(recherche_tsv, requête)`. Couvre tous les souvenirs, avec ou sans embedding.
  - Repli trigramme si le plein texte ne renvoie rien : `word_similarity(memoire_unaccent(lower(q)), texte_normalisé) >= 0.3`, trié par similarité.
  - Références exactes : expression régulière avec limites de mot `(^|[^[:alnum:]])<réf échappée>($|[^[:alnum:]])` sur titre et contenu normalisés ; renvoie, par souvenir, le nombre de références trouvées et si le titre en contient.
- `recherche_vectorielle.py` : la requête pgvector actuelle (distance cosinus, `embedding IS NOT NULL`), sans bonus texte.
- `search_service.py` orchestre :
  1. références exactes (si la requête en contient) ;
  2. branche lexicale ;
  3. vectorisation de la requête ; sur `EmbeddingIndisponible`, mode `lexical`, sinon branche vectorielle et mode `hybride` ;
  4. fusion RRF des branches disponibles, puis `ordonner`.
  Chaque branche récupère `max(limit, 50)` candidats ; le résultat est tronqué à `limit`. Requête vide : `[]` (inchangé).

Contrat (extension compatible) :

- `SearchResult.correspondance` : `exacte | lexicale | vectorielle | les_deux`. `score` = score final de fusion.
- `GET /search` : en-tête `X-Memoire-Mode: hybride | lexical`.
- Adaptateur `/rappeler` : clé `"mode"` ajoutée à la réponse (lue depuis l'en-tête) et `correspondance` par souvenir.
- `/search/semantic` conserve son contrat, plus le 503 décrit ci-dessus.

Erreurs : seule l'indisponibilité de l'embedder dégrade en mode lexical. Une erreur SQL n'est pas masquée.

## 4. Tests

Postgres réel (conftest existant), exécution dans un conteneur Docker neuf :

- références exactes (`S237b`, `INV-2026-042`, adresse e-mail, expression entre guillemets) en tête, titre avant contenu ;
- souvenir sans embedding retrouvé ;
- embedder en panne (client simulé levant) : résultats lexicaux, en-tête `lexical`, aucun vecteur stocké à l'écriture ;
- accents (« reunion » ↔ « réunion »), pluriels (`french`), faute de frappe (trigramme) ;
- **isolation** : même terme dans un autre espace jamais renvoyé, dans chaque mode et pour la branche exacte ;
- filtres type, étape et tier respectés par toutes les branches ;
- migration appliquée deux fois sans erreur ; nettoyage graine 42 ; tâche de revectorisation (succès, arrêt au premier échec) ;
- `/search/semantic` → 503 embedder en panne ;
- fonctions de `recherche_fusion` testées unitairement ;
- adaptateur : `/rappeler` propage `mode` et `correspondance`.

## 5. Mesure avant/après

Script `briques/memoire/memory/backend/scripts/mesure_recherche.py` sur un corpus synthétique committé (~40 souvenirs, ~25 requêtes annotées : références, noms, termes métier, paraphrases, fautes de frappe). Il compare l'ancien algorithme (requête figée dans le script) et le nouveau, embedder actif puis coupé : rappel@5, MRR, latence p50/p95. Rapport committé dans `docs/sprints/S238-memoire-repli-lexical-resultats.md`.

## 6. Preuve LIVE HP

Déploiement de la brique mémoire ; vérification des extensions, de la colonne et des index ; Gateway rendu injoignable pour le backend mémoire seulement → `/rappeler` en mode `lexical` avec résultats ; Gateway rétabli → les 11 vecteurs graine 42 revectorisés (compte vérifié à 0) ; latence mesurée sur les données réelles. Seuls des chiffres agrégés sont consignés, aucun contenu de souvenir.

## Hors périmètre

- `core/assistant.py:216` appelle `/rappeler?q=` (requête vide) et reçoit toujours `[]` : contexte de base mort, signalé mais non corrigé ici.
- Branche lexicale pour les collections et `/semantic`.
- Recherche documentaire (S239).

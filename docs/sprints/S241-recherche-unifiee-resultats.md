# S241 — Recherche unifiée Forge + Ingestion + Mémoire : résultats

Date : 2026-10-06. Statut : codé, revu, déployé et prouvé LIVE sur le HP. Branche
`sprint/s241-recherche-unifiee` (non fusionnée dans `main` à la rédaction).
Conception : [spec](../superpowers/specs/2026-10-06-S241-recherche-unifiee-design.md),
[plan](../superpowers/plans/2026-10-06-S241-recherche-unifiee.md). Remplace l'ex-« S239
Meilisearch + Qdrant » du backlog S235→S239.

## Décisions
- Corpus : Forge (documents + base de connaissances), Ingestion (25 documents, partagés) et
  Mémoire (espaces perso, solution, veille).
- Usages : outil `chercher_documents` de l'assistant (avec `q`) et onglet « 🔎 Recherche » du
  tableau de bord.
- Fédération sans nouveau moteur : chaque brique cherche dans sa base, qui fait foi ; le Cœur
  fusionne par rang (RRF k=60, références exactes devant). Meilisearch écarté.

## Livré
- **Forge** : plein texte PostgreSQL (`simple` pour les titres, `french` pour le corps, mots vides
  écartés), trigrammes pour les fautes (opérateur `<%`, index GIN utilisé), références exactes ;
  Qdrant filtré par utilisateur et recoupé avec PostgreSQL ; mode `lexical` annoncé si l'embedder
  ou Qdrant manque (embedding de la requête borné à 3 s) ; route `GET /api/recherche/hybride`.
- **Réconciliation PostgreSQL → Qdrant** toutes les 10 min (revectorise ce qui manque ou est mal
  attribué, supprime orphelins et fragments périmés, bilan honnête) ; reconstruction :
  `docker exec forge-forge-1 python -m app.recherche_reindexer [--user ID]` (couper la boucle
  avec `FORGE_RECONCILIATION=0` pendant une reconstruction complète si l'on veut éviter des
  doublons transitoires).
- **Adaptateur Forge** : `GET /documents/chercher` (non exposé au LLM, raison dans la spec),
  signale `identite` utilisateur/service.
- **Ingestion** : index SQLite FTS5 (mots + trigrammes) tenu à jour dans la même transaction que
  chaque écriture, reconstruit au démarrage s'il est désynchronisé (document illisible sauté et
  journalisé) ; fautes de frappe comparées mot à mot au vocabulaire du document ; `GET /recherche`.
- **Cœur** : `core/recherche_unifiee.py` (appels parallèles, 8 s par source, sources en panne
  signalées : `forge`, `ingestion`, `memoire` ou `memoire-<espace>`, 503 si toutes tombent),
  `GET /recherche` (session obligatoire, 422 sur source inconnue), champ
  `recherche_par_le_sens_indisponible`, `partage` vrai pour Ingestion, Forge sous identité de
  service et Mémoire `solution` ; outil `chercher_documents` (avec `q` → recherche unifiée, sans
  `q` → listage inchangé) ; onglet « 🔎 Recherche » (rendu `textContent` seul, garde contre les
  réponses périmées, 401/réponse inattendue/validation distingués).

## Faille corrigée
`_qdrant_search` (Forge) ne filtrait que `pole_id`, jamais `user_id` : `/api/rag/search`, le chat,
le chat en flux, le WebSocket et le ReAct renvoyaient les passages des documents de **tous** les
utilisateurs. `get_context` exige désormais l'utilisateur ; tous les appelants le passent.

## Mesure (rappel@5, jeu fixe de 12 documents et 24 requêtes)

| Mode | Exacte | Sens | Faute de frappe |
|---|---|---|---|
| hybride (embedder réel de la Gateway HP) | 1.00 | 0.75 | 1.00 |
| lexical (embedder coupé) | 1.00 | 0.62 | 1.00 |
| ancien LIKE (`/api/search`) | 0.88 | 0.00 | 0.12 |

La mesure a révélé un défaut corrigé pendant le sprint : les mots vides français de la requête
(« le », « de », « des ») faisaient remonter tout document dont le titre en contenait (avant
correction, l'hybride n'apportait rien : 0.62). Limite : l'embedder `all-minilm` est un modèle
anglais, faible en français. Script : `briques/forge/forge/core/scripts/mesure_recherche_s241.py`
(refuse de tourner hors du lanceur de test).

## Tests (relancés par l'agent principal)
Forge core (Postgres 16.14 + Qdrant v1.12.4 réels, `scripts/en_docker.sh`) : 341 passed, 2 skipped.
Filet `scripts/tests_briques.sh` : forge 354 passed, ingestion 75 passed, memoire 62 passed.
Cœur `make test-core` : 982 passed. Smoke `make smoke` : 1765 passed, 104 skipped.

## Revue
Revue par tâche (spec + qualité) pour les 12 tâches ; correctifs après revue sur T2 (guillemets
« “ ” » perdus à la copie), T4 (index trigramme inutilisable, isolation non prouvée), T6 (bilan de
réconciliation, fragments périmés), T9 (vocabulaire des pannes), T11 (réponses périmées, session
expirée), T12 (mots vides, repli trigramme). Revue finale de branche (Opus) : 0 Critical,
3 Important corrigés (fausse panne permanente due au mode d'Ingestion, Mémoire `solution`
présentée comme privée, embedder lent qui faisait perdre toute la Forge) + garde de démarrage
d'Ingestion ; relecture : prêt à déployer.

## Déploiement HP (2026-10-06)
Images construites sur le Mac (`docker save | ssh docker load`) : Forge core, adaptateur Forge,
ingestion, Cœur. Les 42 fichiers du sprint, identiques à `main` sur le HP avant copie, ont été
copiés dans `~/workplace`. Étiquettes `*:avant-s241` ; sauvegardes `~/s241-avant/`
(`forge-db.sql.gz`, `ingestion.db`, `fichiers-avant.tgz`) + instantané Qdrant
`forge_local-118931898374217-2026-10-06-12-18-51.snapshot`. Ordre : forge-migrate (schéma S241) →
Forge → adaptateur → Ingestion (index construit : 25/25/25) → Cœur. Au démarrage, la
réconciliation a revectorisé 1 document dont l'indexation en tâche de fond avait échoué.

## Preuve LIVE
- `GET /recherche` sans session → 401.
- Fautes de frappe sur de vrais documents : « legislaton » → `legislation_en.html` (Ingestion) ;
  « Mollik » → les deux analyses de l'interview Ethan Mollick (Forge) ; « politque conges » →
  `politique-conges.txt` ; « cosmetiqe » → www.febea.fr ; par le sens : « compétences
  invisibles de l'IA » → interview Ethan Mollick. Toutes en 0,3 à 0,5 s, aucune source dégradée.
- Adaptateur Forge arrêté → `sources_indisponibles: ["forge"]` en 0,2 s, Ingestion et Mémoire
  répondent ; adaptateur redémarré, sain.
- Suppression de bout en bout : document Forge créé, trouvé par sa référence exacte via la
  recherche unifiée, supprimé par l'API → introuvable partout, sans action sur Qdrant.
- Non prouvé en LIVE : coupure de l'embedder (couverte par les tests d'intégration, dont un
  embedder qui ne répond pas) ; affichage de l'onglet dans un navigateur (pas de session
  utilisable par l'agent) — à vérifier par l'utilisateur.

## Constats LIVE et décisions utilisateur
1. Les 6 documents de la Forge appartenaient à l'ancien compte de service
   (`service-account-forge-service`) ; depuis juillet le jeton de service correspond à
   l'utilisateur « Workplace ». Ils étaient déjà invisibles par `/api/documents` ; seul le RAG non
   filtré les voyait. **Décision : rattachés à « Workplace »** (UPDATE de 6 lignes) et
   revectorisés (6/6).
2. Chaque document Forge était copié dans l'espace Mémoire commun « solution » et la copie
   survivait à sa suppression (la revue l'avait cru inerte). **Décision : la Forge ne copie plus**
   (`ingest` n'appelle plus `mem_retenir`) ; les copies déjà faites restent dans la Mémoire.
3. Ingestion : les longues pages web passaient le filet des fautes de frappe pour n'importe quel
   mot → comparaison mot à mot au vocabulaire du document.

## Limites connues
- Ingestion n'est pas isolée par personne (une seule clé de service) : ses résultats sont marqués
  « partagé ». Depuis le Cœur, la Forge agit sous son identité de service unique.
- Copies Forge → Mémoire antérieures au sprint toujours présentes (doublons possibles).
- La Mémoire (S238) a probablement le même défaut de mots vides que celui corrigé ici côté Forge.
- Embedder anglais (`all-minilm`) : la recherche par le sens en français reste moyenne.
- Pas de lien profond depuis les résultats vers les fronts de briques.
- Mineurs consignés (non bloquants) : délai global de la recherche Qdrant non borné en dehors de
  l'embedding, réindexation qui perd `pole_id`, doublons possibles si une ingestion et la
  réconciliation indexent la même source en même temps, coût du filet trigramme sur de très
  longs documents.

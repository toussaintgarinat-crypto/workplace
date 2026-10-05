# S238 — Résultats : recherche Mémoire avec repli lexical

Date : 2026-10-05. Branche : `sprint/s238-memoire-repli-lexical`.
Conception : [spec](../superpowers/specs/2026-10-05-S238-memoire-repli-lexical-design.md) ; plan : [plan](../superpowers/plans/2026-10-05-S238-memoire-repli-lexical.md).

## Mesure avant/après (corpus synthétique)

Exécutée sur le HP avec le vrai modèle `embedding/all-minilm` servi par la Gateway (copie du backend dans un dossier jetable, dépôt du HP non modifié).


Corpus : 40 souvenirs, 25 requêtes, 5 répétitions. Modèle : embedding/all-minilm.

| Algorithme | Embedder | Rappel@5 | MRR | p50 (ms) | p95 (ms) | faute | metier | nom | paraphrase | reference |
|---|---|---|---|---|---|---|---|---|---|---|
| ancien | actif | 0.92 | 0.90 | 60.0 | 156.5 | 0.75 / 0.76 | 1.00 / 1.00 | 1.00 / 1.00 | 0.75 / 0.59 | 1.00 / 1.00 |
| nouveau | actif | 0.96 | 0.92 | 61.2 | 163.8 | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 | 0.75 / 0.52 | 1.00 / 1.00 |
| ancien | coupé | 0.72 | 0.63 | 1.2 | 1.5 | 0.25 / 0.25 | 0.67 / 0.47 | 1.00 / 1.00 | 0.75 / 0.46 | 0.83 / 0.83 |
| nouveau | coupé | 0.96 | 0.89 | 2.5 | 4.3 | 1.00 / 1.00 | 1.00 / 0.92 | 1.00 / 1.00 | 0.75 / 0.42 | 1.00 / 1.00 |

Cellules par catégorie : rappel@5 / MRR.

Lecture : avec l'embedder coupé, le nouvel algorithme atteint un rappel@5 de 0,96 (MRR 0,89) contre 0,72 (MRR 0,63) pour l'ancien ; les gains viennent des catégories `faute` (0,25 -> 1,00), `metier` (0,67 -> 1,00) et `reference` (0,83 -> 1,00). Avec l'embedder actif, le nouvel algorithme est meilleur ou égal (rappel@5 0,96 contre 0,92), mais la catégorie `paraphrase` ne progresse pas en rappel (0,75 des deux côtés) et son MRR baisse (0,59 -> 0,52 actif, 0,46 -> 0,42 coupé). La latence reste faible : p50 61 ms vs 60 ms en mode actif (dominée par l'appel d'embedding), 2,5 ms vs 1,2 ms en mode coupé.
Critères d'acceptation : (1) rappel@5 >= 0,7 en mode coupé sur `reference`, `nom`, `metier` : atteint (1,00 partout). (2) ancien en mode coupé avec un MRR proche du hasard : NON atteint, le MRR est de 0,63 ; l'ancien score additionne le cosinus contre un vecteur constant (ordre déterministe, propre à chaque souvenir, pas aléatoire) et le bonus lexical `ILIKE` de 0,3 : ce bonus suffit à remonter les souvenirs contenant les mots de la requête. L'hypothèse « proche du hasard » du plan était fausse. (3) `reference` à MRR 1,00 avec le nouvel algorithme dans les deux modes : atteint. (4) rappel global du nouvel algorithme >= ancien en mode actif : atteint (0,96 >= 0,92). Le corpus n'a pas été retouché.

## Tests

- Backend : 106 passed, via `cd briques/memoire/memory/backend && scripts/en_docker.sh python -m pytest -p no:cacheprovider -q`.
- Adaptateur : 62 passed, via `scripts/tests_briques.sh memoire`.

## Constat : embedder de production cassé depuis le 2026-07-27

- `briques/memoire/memory/backend/requirements.txt` épinglait `openai==1.51.0` avec `httpx==0.28.1` (httpx 0.28.1 posé par le commit 9b9b63b, S205/S206, 2026-07-27).
- httpx 0.28 a supprimé l'argument `proxies` que openai < 1.55.3 transmet : `AsyncOpenAI(...)` lève `TypeError: AsyncClient.__init__() got an unexpected keyword argument 'proxies'`.
- Les embeddings de production échouent donc depuis la reconstruction S205/S206 (commit 9b9b63b). Avant S238, l'embedder masquait l'erreur en renvoyant un vecteur constant (graine 42) : 11 noeuds portent ce vecteur sur le HP, créés entre le 2026-06-05 et le 2026-07-30 (ceux antérieurs au 2026-07-27 relèvent d'une autre cause d'échec, non établie — par exemple une indisponibilité de la Gateway). Depuis S238 il lèverait `EmbeddingIndisponible` en permanence : recherche durablement lexicale, aucun vecteur jamais stocké.
- La mesure ci-dessus a tourné avec httpx 0.27.2 dans une copie jetable, d'où l'absence du symptôme.
- Correctif : `openai==1.55.3` (première version compatible httpx 0.28), httpx 0.28.1 conservé ; test de non-régression `test_client_openai_se_construit`. Commit de ce correctif : "fix(memoire): openai 1.55.3 — embeddings broken by httpx 0.28 since S205".

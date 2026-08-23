# World Engine — Maillage spatial (Sprint B)

**Date** : 2026-08-23
**Statut** : design approuvé, plan d'implémentation à venir

## Contexte

Suite de [world-engine-persistance-lignees-design](2026-08-23-world-engine-persistance-lignees-design.md).
Sprint A a donné à `world-engine` une persistance des enfants générés et un
arbre généalogique (DAG mémoïsé). Ce sprint ajoute la **Brique 2** du rapport
d'architecture initial (« Spatial ») : un maillage de cartes procédurales sur
lesquelles les enfants stockés peuvent naître, et qui peuvent être **forkées**
pour représenter des lignées temporelles divergentes (« même monde, évolution
différente »).

Contrairement au sprint Génome, ce sprint n'a pas de protocole d'évaluation
GO/NO-GO — c'est de l'infrastructure (comme Sprint A), pas un test d'une
hypothèse narrative.

## Décisions de conception (issues du brainstorming)

- **Rattaché au génome dès ce sprint** (pas une brique isolée comme l'était le
  prototype Génome initialement) : les enfants stockés obtiennent une position
  spatiale à la naissance.
- **Vorono‌ï, pas hexagones** : cellules irrégulières à partir de points
  générateurs aléatoires — accepté malgré la complexité géométrique
  supérieure, via `scipy.spatial.Voronoi` (réimplémenter Fortune's algorithm à
  la main serait une source de bugs pour un sprint exploratoire). Rupture
  assumée avec la philosophie « zéro lib lourde » du prototype Génome.
- **Bruit cohérent** (`opensimplex`, pur Python, pas de compilation C) pour
  déterminer altitude/humidité par cellule, plutôt qu'un tirage aléatoire
  indépendant par cellule — biomes voisins spatialement cohérents.
- **Plusieurs mondes, forkables.** Un monde = une carte générée nommée. On
  peut le forker (copie indépendante, même état de départ, y compris les
  enfants qui y sont placés) autant de fois qu'on veut, et créer séparément
  d'autres mondes avec une génération différente. Le fork ne régénère pas
  depuis le seed — il copie les lignes persistées, pour un instantané fidèle
  y compris après des modifications futures (Sprint C) qui diffuseraient du
  seed.
- **Cloisonnement par `cle_api`**, même motif que les enfants : une clé API ne
  voit/ne peut forker que ses propres mondes.
- **Nombre de cellules paramétrable** à la création (pas de valeur fixe).
- **Placement automatique à la naissance**, dans le même appel que
  `POST /genome/croiser` (pas un endpoint séparé) — nouveau param `monde_id`
  optionnel sur cet endpoint déjà stable.
- **Héritage de position par le parent mère.** Ajout d'un champ `sexe`
  optionnel (`"F"`/`"M"`) sur `parent_a`/`parent_b` — absent aujourd'hui de
  l'API. Le parent de référence pour hériter une position est celui marqué
  `"F"` ; à défaut (aucun `"F"`), `parent_a`.
- **Habitations/bâtiments explicitement hors périmètre** — confirmé par
  l'utilisateur en brainstorming, couche future éventuelle, pas ce sprint.
  Idem pour tout rendu visuel : `world-engine` reste une brique backend pure
  (JSON), aucun affichage de carte.

## Modèle de données

Extension de `briques/world-engine/stockage.py` (même base SQLite que les
enfants) :

```sql
CREATE TABLE IF NOT EXISTS mondes (
    id TEXT PRIMARY KEY,             -- uuid4().hex
    cle_api TEXT NOT NULL,
    nb_cellules INTEGER NOT NULL,
    seed INTEGER NOT NULL,
    forked_from_id TEXT,             -- NULL si monde d'origine
    cree_le TEXT
)
CREATE INDEX idx_monde_cle ON mondes(cle_api)

CREATE TABLE IF NOT EXISTS cellules (
    monde_id TEXT NOT NULL,
    cellule_id INTEGER NOT NULL,     -- index 0..nb_cellules-1, scopé au monde
    x REAL NOT NULL, y REAL NOT NULL,
    biome TEXT NOT NULL,
    ressources TEXT NOT NULL,        -- JSON liste
    voisins TEXT NOT NULL,           -- JSON liste de cellule_id
    PRIMARY KEY (monde_id, cellule_id)
)

CREATE TABLE IF NOT EXISTS placements (
    enfant_id TEXT NOT NULL,
    monde_id TEXT NOT NULL,
    cellule_id INTEGER NOT NULL,
    place_le TEXT,
    PRIMARY KEY (enfant_id, monde_id)  -- un enfant, une position par monde
)
CREATE INDEX idx_placement_monde ON placements(monde_id)
```

- Un même `enfant_id` peut avoir des lignes dans plusieurs `placements` (une
  par monde où il a été placé, y compris via un fork) — c'est ce qui porte
  « même personne, timelines divergentes ».
- Suppression d'un monde : **cascade** sur `cellules` et `placements` — pas le
  problème DAG des enfants (une cellule n'appartient qu'à un seul monde, la
  suppression est sûre et sans ambiguïté).
- Volume Docker partagé avec la base `world_engine.db` existante (Sprint A) —
  pas de nouveau volume.

## Génération d'un monde

1. Tirer `nb_cellules` points aléatoires dans l'espace normalisé
   `[0, 1000] × [0, 1000]`, RNG seedé (`seed` fourni ou généré et stocké pour
   traçabilité — même si le fork ne régénère jamais, il copie les données).
2. `scipy.spatial.Voronoi` sur ces points → régions + voisinage, lu depuis
   `ridge_points` (paires d'index de points partageant une arête Voronoï,
   donc directement adjacents). Régions non bornées (sur l'enveloppe convexe)
   clippées à la bounding box `[0, 1000]²`.
3. Deux champs de bruit cohérent seedés (`opensimplex.OpenSimplex`) —
   altitude et humidité — évalués à `(x, y)` de chaque cellule. Combinaison
   des deux axes en un des 8 biomes : océan, plaine, forêt, colline,
   montagne, désert, toundra, marais.
4. Table fixe biome → ressources possibles (ex. forêt : bois, gibier ;
   montagne : minerai, pierre ; océan : poisson). Chaque cellule tire 0-2
   ressources dans la liste de son biome, seedé.

## Contrat API

Nouveau routeur `/spatial` dans `main.py`, même style que `/genome`, tout
cloisonné par `cle_api` (404 sur id absent ou d'une autre clé, jamais 403,
même motif que Sprint A).

### `POST /spatial/mondes`

Params : `nb_cellules` (requis, borné ex. 10-2000), `seed` (optionnel).
Génère et stocke le monde. Réponse : `{id, nb_cellules, seed, cree_le}`.

### `POST /spatial/mondes/{id}/forker`

Duplique toutes les lignes `cellules` du monde source (mêmes `cellule_id`,
biomes, ressources, voisins — pas de régénération) sous un nouveau `id`, et
duplique toutes les lignes `placements` correspondantes. Le monde source
n'est jamais modifié. Réponse : `{id, forked_from_id, ...}`. 404 si le monde
source est absent ou d'une autre `cle_api`.

### `GET /spatial/mondes`

Liste allégée cloisonnée : `[{id, nb_cellules, seed, forked_from_id,
cree_le}]`.

### `GET /spatial/mondes/{id}`

Toutes les cellules du monde, chacune avec ses enfants placés :
`{id, cellules: [{cellule_id, x, y, biome, ressources, voisins, enfants:
[{id, prenoms, nom}]}]}`. 404 si absent/autre clé.

### `GET /spatial/mondes/{id}/cellules/{cid}`

Une cellule seule, même forme qu'un élément de la liste ci-dessus. 404 si le
monde ou la cellule est absent.

### `DELETE /spatial/mondes/{id}`

204 si supprimé (cascade cellules+placements), 404 si absent/autre clé.

### `POST /genome/croiser` (modifié)

Deux nouveaux params, tous deux optionnels :

- `sexe` sur `parent_a`/`parent_b` : `"F"` / `"M"` / absent.
- `monde_id` : id d'un monde existant (de la même `cle_api`) où placer
  l'enfant à sa naissance.

Règle de placement :

- `monde_id` absent → enfant non placé (comportement actuel inchangé, aucune
  ligne `placements` créée).
- `monde_id` présent :
  1. Parent de référence = celui des deux marqué `sexe:"F"` ; à défaut (aucun
     `"F"`, ou les deux marqués `"F"`), `parent_a`.
  2. Si ce parent est une fiche brute (pas `{"id": ...}`) → pas de position
     connue → cellule tirée aléatoirement (bornée à `[0, nb_cellules-1]`) du
     monde ciblé.
  3. Si c'est un enfant stocké : on lit son dernier placement. S'il existe
     **dans ce même** `monde_id` → cellule tirée aléatoirement parmi ses
     `voisins`. Sinon (pas de placement, ou placement dans un autre monde) →
     cellule aléatoire bornée du monde ciblé (même repli que 2).
- `monde_id` fourni mais introuvable/autre `cle_api` → 404 (même motif que
  les ids de parents en Sprint A — ressource absente, pas une erreur de forme
  422).
- Échec d'écriture du placement après un croisement par ailleurs réussi → ne
  fait jamais échouer la requête (même motif que l'échec d'écriture
  `enfant_id` en Sprint A) : réponse enrichie d'un `avertissement`,
  `cellule_id: null`.
- Réponse enrichie de `cellule_id` (id de la cellule où l'enfant a été placé,
  `null` si `monde_id` absent).

## Repli honnête (ajouts à la section existante)

- `monde_id`/`cellule_id` absent ou d'une autre `cle_api` → 404, jamais
  confondu avec un 422 de forme.
- Échec d'écriture du placement après un croisement réussi → jamais un 500 ;
  `cellule_id: null` + `avertissement`.
- Chaque cellule expose uniquement son point générateur `(x, y)` (toujours
  fini, dans `[0, TAILLE_MONDE]²` par construction) — jamais le polygone de
  sa région Voronoï. Une région non bornée (sur l'enveloppe convexe) n'a donc
  jamais de coordonnée infinie à exposer : le risque que cette section visait
  à l'origine (clipper un polygone) ne se pose pas avec ce choix de
  représentation.
  ⚠️ Limitation connue (confirmée avec l'utilisateur en revue finale de
  branche, 2026-08-23) : l'absence de géométrie de région est un choix
  délibéré pour ce sprint backend, mais un futur rendu visuel de la carte
  aura besoin des polygones (pas seulement des points) — dette à reprendre
  dans un sprint ultérieur (probablement lié au Compilateur ou à une brique
  de rendu dédiée), pas dans ce sprint.

## Tests

- `test_stockage_spatial.py` (nouveau) : CRUD SQLite des 3 nouvelles tables
  en isolation.
- `test_spatial.py` (nouveau) :
  - génération : `nb_cellules` cellules produites, toutes dans la bounding
    box, voisinage symétrique (A voisin de B ⟺ B voisin de A), pas de
    cellule orpheline (0 voisin) sauf cas dégénéré à très petit `nb_cellules` ;
  - déterminisme : même `seed` + même `nb_cellules` → mêmes cellules
    (positions, biomes, ressources) ;
  - biomes cohérents avec le bruit (pas de test flou sur le rendu, mais sur
    la fonction de mapping bruit→biome en isolation) ;
  - ressources toujours dans la liste autorisée du biome de leur cellule ;
  - fork : cellules et placements identiques juste après le fork ; modifier
    une cellule du fork (test direct en base) n'affecte pas l'original ;
  - cloisonnement `cle_api` sur les 6 endpoints `/spatial/*` ;
  - cascade de suppression : `DELETE` d'un monde vide ses `cellules` et
    `placements`.
- `test_api.py` (étendu) : les 4 branches de la règle de placement sur
  `POST /genome/croiser` (pas de `monde_id` ; parent brut ; parent stocké
  placé dans le même monde → voisin ; parent stocké non placé/autre monde →
  aléatoire bornée) ; `monde_id` invalide → 404.
- Filet manifeste↔route étendu aux 6 nouvelles capacités spatiales + au
  contrat modifié de `genome_croiser`.
- Pas de preuve Docker manuelle requise pour la géométrie (déterministe,
  testable en isolation) ; le protocole d'intégration existant (appel réel à
  `personnages`) reste suffisant pour la partie qui en dépend déjà.

## Manifest

- 6 nouvelles capacités : `spatial_monde_creer`, `spatial_monde_forker`,
  `spatial_mondes_lister`, `spatial_monde_lire`, `spatial_cellule_lire`,
  `spatial_monde_supprimer` — exposées par défaut à l'assistant, conformément
  à [[feedback-exposer-nouvelles-fonctionnalites-assistant]].
- `genome_croiser` : description mise à jour pour documenter `sexe`,
  `monde_id`, `cellule_id` en réponse.

## Dépendances ajoutées

- `scipy` — géométrie Voronoï (`scipy.spatial.Voronoi`).
- `opensimplex` — bruit cohérent (pur Python, pas de compilation C, plus
  simple à builder en Docker que la lib `noise` à extension C).

## Hors périmètre de ce sprint

- Habitations/bâtiments — couche future éventuelle, confirmée hors sujet en
  brainstorming.
- Rendu visuel/carte graphique — brique backend pure.
- Déplacement d'un enfant déjà placé (changer de cellule après la
  naissance) — seul le placement initial à la naissance est couvert.
- Simulation temporelle qui ferait diverger un monde forké tout seul dans le
  temps — c'est l'objet de Sprint C (Horloge). Ce sprint pose la capacité de
  forker un instantané, pas encore ce qui le ferait évoluer automatiquement.
- Sprint C (horloge de simulation), Sprint D (compilateur de packs) —
  roadmap inchangée, voir
  [[backlog-world-engine-genome-cosmique-phases-suivantes]].

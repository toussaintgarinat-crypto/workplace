# Brique `jeu-factions` — création de personnage + factions/territoire (PvE)

## Contexte

L'atelier holistique de la brique `personnages` (S49) calcule, à partir d'une fiche de
naissance, un faisceau de traditions (numérologie, astro occidentale/chinoise/védique,
égyptien, celte, amérindien, maya) agrégées en 8 stats, un archétype dominant, des
forces/une faiblesse. Le moteur est déjà bidirectionnel : `portrait` (date → traits) et
`recherche_inverse` (description de caractère → date qui matche).

Objectif : construire, au-dessus de ce moteur existant, le premier sous-système d'un jeu
plus large (inspiration Ashes of Creation pour l'esprit « monde vivant », pas pour
l'ambition 3D) — **création de personnage + factions + territoire en PvE**. C'est le
premier sous-projet d'une décomposition en cinq :

1. **Ce spec** — personnages + factions/territoire
2. Moteur de combat temps réel (façon WoW) — spec séparé, plus tard
3. Progression différée/idle — spec séparé, plus tard
4. Infra multi-joueurs publique (vrais comptes, hébergement, sécurité) — spec séparé
5. Système de quêtes/lore complet — spec séparé (ce spec ne pose que la structure minimale)

## Non-objectifs

- **Pas de combat temps réel.** Toute résolution de conflit ici est une comparaison de
  stats automatique à un tick planifié (asyncio), pas un moteur d'action/netcode. Le vrai
  combat (façon WoW : sorts, cooldowns, positionnement) est un spec à part qui remplacera
  ce placeholder plus tard.
- **Pas de PvP.** Ce spec couvre un serveur/mode **100 % PvE**. Un éventuel serveur PvP est
  une variante hors scope (probablement la concrétisation du futur spec combat).
- **Pas de vrais comptes.** Un « joueur » ici est juste `cle_api` + `pseudo`, cloisonné
  comme n'importe quel tenant Workplace — pas d'authentification, de mot de passe, de
  session. Le vrai système de comptes est le spec « infra multi-joueurs publique ».
- **Pas de système de quêtes/lore complet.** Les voies d'archétype (ci-dessous) posent la
  structure minimale (étapes ordonnées + texte de lore fixe), sans dialogue, embranchement,
  ni catalogue de récompenses élaboré.
- **Pas d'effets de compétences.** Les compétences débloquées sont de simples
  enregistrements (nom + texte + condition de déblocage) sans effet de jeu défini — leur
  effet sera conçu avec le futur moteur de combat.
- **Pas de rendu graphique.** Front HTML sans build, même motif que
  `personnages/front_holistique.html` — pas de carte animée, pas de sprites.

## Architecture

Nouvelle brique **`jeu-factions`**, FastAPI + Docker, port **6210** (6200 est déjà pris par
`connecteurs`), au motif exact des
40 autres briques (`manifest.json`, `Dockerfile`, `docker-compose.yml`, `API_KEYS` = tenant,
front HTML sans build, `requirements.txt`, tests pytest).

Règle stricte : `jeu-factions` **ne recalcule jamais** le moteur holistique. Tout calcul de
personnage part en HTTP vers `personnages` (`GATEWAY`-style : `PERSONNAGES_URL`,
`PERSONNAGES_KEY`) :
- `POST {PERSONNAGES_URL}/holistique/recherche-inverse` (chemin description uniquement)
- `POST {PERSONNAGES_URL}/holistique/portrait` (les deux chemins y aboutissent)

`jeu-factions` stocke un **snapshot figé** du résultat (pas de recalcul à la lecture) et
gère tout l'état de jeu autour : personnages, zones, assignations, progression, groupes.

Stockage : SQLite (`JEU_FACTIONS_DB`, défaut `/data/jeu_factions.db`), même pattern que
`personnages/stockage.py`.

Le tick de résolution : boucle asyncio interne (pas de cron système externe), intervalle
réglable via `TICK_INTERVAL_HOURS` (défaut 24). Résout à chaque passage **toutes** les zones
de signe non vaincues et **tous** les groupes actifs (voir Flux ci-dessous).

### Exception au cloisonnement tenant

Le motif Workplace habituel isole strictement par `cle_api` (jamais de vue croisée). Ici,
**les zones et leurs scores sont un monde partagé** : tous les tenants voient les mêmes
12 zones de signe et les mêmes voies d'archétype, contribuent au même score global. Seuls
les **personnages** et les **groupes** restent liés à leur `cle_api` propriétaire (lecture/
écriture réservées au propriétaire). C'est une exception délibérée, à documenter dans le
README de la brique pour ne pas être « corrigée » par erreur plus tard vers un
cloisonnement strict.

## Modèle de données

```sql
CREATE TABLE joueurs (
    cle_api TEXT PRIMARY KEY,
    pseudo TEXT NOT NULL
);

CREATE TABLE personnages_jeu (
    id TEXT PRIMARY KEY,
    cle_api TEXT NOT NULL,
    nom TEXT NOT NULL,
    donnees_naissance TEXT NOT NULL,   -- JSON : {date, heure?, lat?, lon?, utc_offset?} ou {description}
    snapshot_holistique TEXT NOT NULL, -- JSON figé : {element, signe, archetype, stats, forces, faiblesse, recit}
    zone_actuelle TEXT REFERENCES zones(id),
    cree_le TEXT NOT NULL
);

CREATE TABLE zones (
    id TEXT PRIMARY KEY,
    nom TEXT NOT NULL,
    element_natif TEXT NOT NULL,     -- Feu/Terre/Air/Eau
    signe_natif TEXT NOT NULL,       -- un des 12 signes, unique par zone (12 zones fixes)
    difficulte_pve INTEGER NOT NULL,
    etat TEXT NOT NULL DEFAULT 'en_cours'  -- en_cours | vaincue
);

CREATE TABLE scores_zone_guilde (
    zone_id TEXT NOT NULL REFERENCES zones(id),
    guilde TEXT NOT NULL,            -- signe du personnage contributeur
    points_cumules INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (zone_id, guilde)
);

CREATE TABLE resolutions (
    id TEXT PRIMARY KEY,
    zone_id TEXT REFERENCES zones(id),          -- NULL si résolution d'un groupe (cf. zone_archetype_id)
    zone_archetype_id TEXT REFERENCES zones_archetype(id),
    horodatage TEXT NOT NULL,
    contributions TEXT NOT NULL,     -- JSON : {guilde_ou_personnage: points}
    etat_resultant TEXT NOT NULL
);

CREATE TABLE zones_archetype (
    id TEXT PRIMARY KEY,
    archetype TEXT NOT NULL,         -- un des 10 archétypes
    ordre INTEGER NOT NULL,          -- séquence au sein de la voie (1, 2, 3…)
    nom TEXT NOT NULL,
    difficulte_pve INTEGER NOT NULL,
    texte_lore TEXT NOT NULL,
    UNIQUE (archetype, ordre)
);

CREATE TABLE progression_archetype (
    personnage_id TEXT NOT NULL REFERENCES personnages_jeu(id),
    zone_archetype_id TEXT NOT NULL REFERENCES zones_archetype(id),
    etat TEXT NOT NULL DEFAULT 'verrouillee',  -- verrouillee | en_cours | vaincue
    date_completion TEXT,
    PRIMARY KEY (personnage_id, zone_archetype_id)
);

CREATE TABLE groupes (
    id TEXT PRIMARY KEY,
    personnage_cible_id TEXT NOT NULL REFERENCES personnages_jeu(id),
    zone_archetype_id TEXT NOT NULL REFERENCES zones_archetype(id),
    etat TEXT NOT NULL DEFAULT 'actif',   -- actif | dissous
    cree_le TEXT NOT NULL
);

CREATE TABLE membres_groupe (
    groupe_id TEXT NOT NULL REFERENCES groupes(id),
    personnage_id TEXT NOT NULL REFERENCES personnages_jeu(id),
    PRIMARY KEY (groupe_id, personnage_id)
);

CREATE TABLE competences (
    id TEXT PRIMARY KEY,
    nom TEXT NOT NULL,
    texte TEXT NOT NULL,
    archetype TEXT NOT NULL,
    ordre_etape INTEGER NOT NULL     -- quelle étape de la voie la débloque
);

CREATE TABLE competences_debloquees (
    personnage_id TEXT NOT NULL REFERENCES personnages_jeu(id),
    competence_id TEXT NOT NULL REFERENCES competences(id),
    date TEXT NOT NULL,
    PRIMARY KEY (personnage_id, competence_id)
);
```

Les 12 `zones` (une par signe) et les `zones_archetype` (N étapes par archétype) sont des
**données de seed**, créées au démarrage de la brique si la table est vide — pas d'API de
création, elles sont fixes.

## Moteur holistique — mapping des factions

Réutilisation directe des tables déjà existantes dans `traditions.py`/`synthese.py` de
`personnages`, aucune duplication :

- **Nation** = élément du signe solaire (`ELEMENTS_SIGNE`) → 4 nations (Feu/Terre/Air/Eau).
- **Guilde** = signe solaire (`signe_solaire.nom`) → 12 guildes, chacune rattachée à sa nation.
- **Classe** = archétype calculé (`_archetype()` dans `synthese.py`) → 10 classes, axe
  orthogonal à nation/guilde (n'influence pas la politique/territoire).

Pour une voie d'archétype **autre que la sienne**, un personnage peut quand même tenter les
étapes : la comparaison au seuil utilise les stats-signature de **la voie choisie** (la
même table `_ARCHETYPES` : 3 stats par archétype), pas celles de son archétype natal. Un
personnage à contre-emploi a des stats plus basses sur ces axes → seuils plus durs à
atteindre seul, d'où l'intérêt du groupe. Aucun système de bonus séparé : l'avantage/désavantage
est déjà encodé dans les stats calculées à la naissance.

## Flux — création de personnage

1. Le joueur choisit un chemin :
   - **Date** : date de naissance (réelle ou fictive) + heure/coordonnées optionnelles + nom.
   - **Description** : texte de caractère libre.
2. `jeu-factions` appelle `personnages` :
   - Chemin date → `POST /holistique/portrait` directement.
   - Chemin description → `POST /holistique/recherche-inverse` d'abord (récupère
     `exemple_date`), puis `POST /holistique/portrait` avec cette date générée. Les deux
     chemins convergent donc toujours vers un appel `portrait` final.
3. Le résultat (élément, signe, archétype, stats, forces/faiblesse, récit) est figé dans
   `snapshot_holistique`. Aucun recalcul ultérieur : si le moteur `personnages` évolue, les
   personnages déjà créés gardent leur snapshot d'origine (cohérence de la partie en cours).
4. Échec de l'appel HTTP (brique `personnages` indisponible, timeout) → `503`, **aucune ligne
   créée** dans `personnages_jeu` (pas de personnage à moitié formé, sans snapshot).

## Flux — zones de signe (PvE partagé)

1. Le joueur assigne un de ses personnages à une zone de son choix (`PATCH
   /personnages/{id}/zone`) — n'importe laquelle des 12, pas seulement celle de son signe
   natif (un Bélier peut aller aider une zone Poissons).
2. Le personnage reste assigné jusqu'à réassignation manuelle.
3. Assigner un personnage à une **zone déjà vaincue** est accepté mais sans effet réel : le
   tick suivant ne fait plus rien pour cette zone (no-op, pas une erreur).
4. À chaque tick, pour chaque zone `etat = 'en_cours'` : sommer les stats combat-pertinentes
   (Combativité + Énergie, cf. Configuration) de tous les personnages actuellement assignés,
   tous comptes confondus.
   - **Répartir les points de CE tick dans `scores_zone_guilde`, par guilde (signe) des
     personnages présents — à chaque tick, que la zone soit vaincue ou non ce tick-là.**
     Décision assumée (revue finale) : la présence prolongée sur une zone est elle-même une
     forme de contribution valable au classement, pas un exploit à corriger — le score reste
     purement informatif (classement, pas de possession exclusive : cf. Non-objectifs, pas de
     PvP), donc mesurer le temps investi plutôt que le seul instant de la victoire est
     acceptable ici.
   - Si la somme ≥ `difficulte_pve` : `etat` → `vaincue`.
   - Logger dans `resolutions` à chaque tick (pas seulement à la victoire).

## Flux — voies d'archétype + groupes

1. Chaque archétype a une suite d'étapes ordonnées (`zones_archetype`, `ordre` croissant),
   chacune avec son seuil et un texte de lore. Une étape complétée (`vaincue`) ne se rejoue
   jamais — c'est la « quête principale », permanente.
2. Un personnage peut tenter **n'importe quelle voie** (pas seulement son archétype natal),
   mais uniquement dans l'ordre de SA propre séquence sur cette voie (`progression_archetype`
   : impossible de sauter une étape).
3. Un groupe (`groupes`) cible **une étape précise pour un personnage cible**
   (`personnage_cible_id`). **N'importe qui peut rejoindre** (`membres_groupe`), quel que
   soit son propre archétype ou sa progression — y compris pour aider un ami sans faire
   avancer sa propre trame (« carry »).
4. À chaque tick, pour chaque groupe `etat = 'actif'` : sommer les stats-signature de la voie
   ciblée pour **tous** les membres. Si la somme ≥ `difficulte_pve` de l'étape :
   - Pour **chaque membre dont cette étape est exactement sa propre prochaine étape** sur
     cette voie : `progression_archetype` → `vaincue`, étape suivante déverrouillée,
     compétence associée (le cas échéant) ajoutée à `competences_debloquees`.
   - Les membres qui ont déjà complété cette étape, ou qui n'y sont pas encore arrivés dans
     leur propre séquence, contribuent leurs stats mais ne voient **pas** leur progression
     changer (pas de saut, pas de re-completion).
   - **Cas particulier assumé (1ʳᵉ étape d'une voie)** : `progression_archetype` ne distingue
     pas « jamais touché cet archétype » de « vise réellement cette étape » — l'absence de
     ligne vaut « pas encore vaincue » dans les deux cas, donc la 1ʳᵉ étape est TOUJOURS la
     « prochaine étape » de quiconque n'a rien tenté sur cette voie. Rejoindre un groupe sur
     l'étape 1 d'un archétype qu'on n'a jamais entamé fait donc AUSSI avancer sa propre
     progression dessus — ce n'est pas une triche, c'est assumé : aider un ami sur ses
     premiers pas t'y engage aussi. La garantie « l'aide ne progresse pas » ne s'applique
     qu'à partir de la 2ᵉ étape, où un personnage qui n'a pas complété la précédente reste
     bloqué (sa propre prochaine étape diffère alors de celle du groupe).
   - Logger dans `resolutions` (`zone_archetype_id` renseigné, `zone_id` NULL).
5. Rejoindre un groupe ciblant une étape déjà `vaincue` **pour le personnage cible** → `400`,
   rien à faire.
6. Créer un groupe visant une étape qui n'est pas la prochaine du personnage cible → `400`.

## API

Toutes les routes stateful nécessitent `X-API-Key`. Les routes zones/archétypes sont en
lecture globale (pas de cloisonnement, cf. Architecture) ; personnages/groupes sont
cloisonnés par propriétaire.

| Méthode | Route | Rôle |
|---|---|---|
| POST | `/personnages` | créer (chemin date ou description) |
| GET | `/personnages` | lister les personnages du compte |
| GET | `/personnages/{id}` | détail (snapshot, zone, progressions, compétences) |
| PATCH | `/personnages/{id}/zone` | assigner à une zone de signe |
| GET | `/zones` | les 12 zones + état + scores par guilde |
| GET | `/zones/{id}` | détail + historique récent |
| GET | `/archetypes/{archetype}/etapes` | étapes de la voie, avec seuils |
| POST | `/groupes` | créer, cible une étape pour un personnage |
| POST | `/groupes/{id}/rejoindre` | un autre personnage rejoint |
| GET | `/personnages/{id}/competences` | compétences débloquées |

Le tick n'est **pas** une route publique : boucle asyncio interne au process (cf.
Architecture).

## Configuration (env)

| Variable | Défaut | Rôle |
|---|---|---|
| `API_KEYS` | (vide) | clés acceptées ; vide = mode ouvert (dev) |
| `PERSONNAGES_URL` | `http://personnages:5900` | brique `personnages` (moteur holistique) |
| `PERSONNAGES_KEY` | (vide) | clé API vers `personnages`, si celle-ci en exige une |
| `TICK_INTERVAL_HOURS` | `24` | intervalle du tick de résolution |
| `JEU_FACTIONS_DB` | `/data/jeu_factions.db` | stockage SQLite |
| `STATS_ZONE_SIGNE` | `Combativité,Énergie` | stats sommées pour les zones de signe |

## Tests

Même pattern que les autres briques (`pytest`, `conftest.py`, `TestClient`) :

- **Création de personnage** : les deux chemins, appel à `personnages` mocké (pas de réseau
  réel dans les tests) ; échec de l'appel → `503`, aucune ligne créée.
- **Résolution de tick — zones de signe** : fonction pure (stats agrégées vs seuil), testée
  hors API ; zone déjà vaincue → no-op ; répartition correcte des scores par guilde.
- **Résolution de tick — groupes/archétype** : cas nominal (étape suivante validée), saut
  d'étape refusé, étape déjà vaincue refusée, cas « carry » (contribue sans progresser).
- **Isolation** : personnages/groupes restent cloisonnés par `cle_api` ; zones/scores restent
  globaux et visibles de tous — test dédié pour ne pas casser cette exception par erreur
  plus tard (comme le filet d'isolation déjà audité sur 28 briques Workplace).

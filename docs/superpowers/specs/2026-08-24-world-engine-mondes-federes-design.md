# World Engine — Mondes fédérés (Sprint D)

**Date** : 2026-08-24
**Statut** : design approuvé, plan d'implémentation à venir

## Contexte

Suite de [world-engine-horloge-simulation-design](2026-08-23-world-engine-horloge-simulation-design.md).
Sprint C a donné à `world-engine` une simulation temporelle par ticks
(vieillissement/mortalité, reproduction, migration, ressources/technologie)
sur UN monde non fédéré. Ce sprint ajoute la fédération de plusieurs mondes en
« pays », troisième étape de la décomposition actée en brainstorming Sprint C
(C mécanique du tick → **D fédération, ce document** → E mise à l'échelle).

## Décisions de conception (issues du brainstorming)

- **Un pays = un monde existant.** Pas de nouveau maillage spatial : chaque
  monde (Sprint B, avec son propre maillage Voronoï, sa propre horloge Sprint
  C) DEVIENT un pays dès qu'il est rattaché à une fédération. La
  **fédération** est un nouveau type d'entité qui regroupe plusieurs pays.
- **Pays totalement indépendants, aucune synchronisation de tick.** Chaque
  pays garde son horloge autonome (manuelle ou scheduler opt-in, comme
  aujourd'hui). La fédération n'impose jamais qu'un pays attende un autre —
  choix explicite pour rester simple et cohérent avec le fait que rien
  n'oblige aujourd'hui deux mondes à avancer au même rythme.
- **Seule interaction inter-pays ce sprint : la migration transfrontière.**
  Étend la migration poussée par la rareté (Sprint C) au-delà du maillage
  d'un seul pays. Reproduction/couples restent strictement intra-pays — un
  couple ne peut jamais avoir ses deux membres dans des mondes différents,
  aucun changement de modèle de données sur `couples` ce sprint.
- **Adjacence entre pays explicite, pas automatique.** Deux mondes n'ont
  aucune géométrie commune (coordonnées propres, maillages Voronoï séparés
  et non comparables) : il n'existe pas de notion naturelle de « pays
  voisin ». L'adjacence est donc un lien déclaré explicitement au sein d'une
  fédération, pas déduite d'une carte.
- **Fédération multi-`cle_api`, avec un modèle de consentement par acte** :
  - Créer une fédération : n'importe quelle `cle_api` (devient créatrice,
    fédération vide au départ).
  - Rattacher un pays existant : **uniquement le propriétaire de ce pays**
    (sa `cle_api`) — jamais le créateur de la fédération pour le compte d'un
    tiers. C'est l'acte de consentement fort : en rattachant son pays, son
    propriétaire accepte implicitement qu'il puisse devenir adjacent à
    d'autres pays de cette même fédération.
  - Déclarer une adjacence entre deux pays déjà membres : n'importe quel
    membre de la fédération (possède au moins un pays dedans) — pas besoin
    de reconsentement séparé des deux propriétaires précis, le rattachement
    initial couvre déjà ce risque.
  - Détacher son propre pays : son propriétaire, à tout moment, sans passer
    par le créateur.
  - Voir l'état (liste des pays, adjacences, agrégats) : le créateur ET tout
    propriétaire d'au moins un pays membre.
  - Supprimer la fédération : le créateur uniquement. Détache tous les pays
    (et leurs adjacences dans cette fédération) — **ne supprime jamais un
    monde/pays sous-jacent**, qui reste un monde indépendant utilisable hors
    fédération.
- **Nom de pays optionnel, propre à la fédération.** La table `mondes`
  n'a et ne gagne aucun champ « nom » (cohérence avec le style actuel, tout
  identifié par uuid). Un nom d'affichage optionnel peut être donné au
  moment du rattachement, stocké côté fédération — un même monde peut avoir
  des noms différents dans deux fédérations, ou aucun (l'id du monde reste
  l'identifiant de repli).
- **Un pays peut appartenir à plusieurs fédérations simultanément.** Pas de
  restriction à une seule — au moment du tick, les pays adjacents éligibles
  à la migration transfrontière sont l'union des adjacences déclarées dans
  TOUTES les fédérations dont ce pays est membre.
- **Migration transfrontière : probabilité séparée, plus faible, en repli
  vers l'existant.** Pour un habitant tiré dans une cellule saturée
  (mécanique Sprint C inchangée) : un jet à probabilité faible décide
  d'abord s'il franchit une frontière (seulement si le pays a au moins une
  adjacence déclarée) ; en cas d'échec de ce jet, repli sur la migration
  intra-pays existante, exactement inchangée. Jamais les deux le même tick
  pour un même habitant — préserve l'invariant Sprint C « un habitant ne
  migre jamais deux fois dans le même tick ».
- **Destination transfrontière : pays adjacent tiré uniformément, puis
  cellule aléatoire bornée dans ce pays.** Pas de notion de cellule-frontière
  géométrique (aucune géométrie commune entre deux maillages séparés, cf.
  adjacence explicite ci-dessus) — même repli que la règle de placement
  Sprint B pour un parent sans position connue.
- **Âge préservé à la traversée, jamais remis à zéro.** `1 tick = 1 an`
  (Sprint C) est une unité propre à CHAQUE pays, mais l'habitant qui migre
  ne doit ni rajeunir ni vieillir instantanément du seul fait de changer de
  pays. `ne_au_tick` dans le pays de destination est recalculé pour que
  `tick_actuel_destination − ne_au_tick_destination` égale l'âge réel de
  l'habitant au moment du départ — jamais une remise à zéro.
- **La ligne `placements` d'origine est conservée, marquée « émigré »,
  distincte de la mort.** Contrairement à la migration intra-pays (qui met à
  jour `cellule_id` sur la même ligne, même monde), la migration
  transfrontière change de `monde_id` — la clé primaire actuelle
  `(enfant_id, monde_id)` interdit de réutiliser la même ligne. Décision
  explicite de garder un historique complet (« qui est parti où et quand »)
  plutôt que de supprimer silencieusement la ligne d'origine ou de
  détourner le champ `mort_au_tick`/`vivant` qui signifierait à tort que
  l'habitant est mort. Un champ `emigre` distinct est ajouté ; toutes les
  requêtes qui comptent la population/testent l'éligibilité d'un pays
  (mortalité, reproduction, migration, comptage) gagnent un filtre
  `emigre = 0` en plus du filtre `vivant = 1` déjà en place, pour qu'un
  émigré (vivant mais parti) ne soit plus jamais compté dans son pays
  d'origine.
- **Tout couple actif est dissous avant le départ** — même motif que la mort
  (Sprint C), pour la même raison : un couple ne peut jamais avoir ses deux
  membres dans des mondes différents.
- **Verrouillage inter-pays à l'écriture, par timeout — pas par ordre trié.**
  L'écriture de la migration transfrontière touche deux pays (origine +
  destination) qui peuvent avoir chacun un tick en cours (scheduler
  in-process indépendant, Sprint C). **Correction (revue du plan
  d'implémentation)** : une première version de ce document proposait un
  ordre d'acquisition trié par `monde_id` pour éliminer l'interblocage —
  c'est inexact, puisque le verrou du pays D'ORIGINE est déjà tenu en entrée
  du tick (`executer_tick`), AVANT même de savoir qu'une migration
  transfrontière aura lieu : l'ordre d'acquisition n'est donc jamais neutre,
  et deux tics concurrents faisant le mouvement inverse l'un de l'autre (A→B
  et B→A au même instant) restent en interblocage classique malgré un tri.
  Mécanisme retenu à la place : l'acquisition du verrou du pays destination
  se fait avec un **timeout court** (`asyncio.wait_for`, quelques secondes) ;
  en cas de timeout, CETTE émigration précise échoue proprement (capturée
  dans `avertissements`, l'habitant reste dans son pays d'origine ce tick,
  retentera au tick suivant), sans jamais bloquer indéfiniment ni
  interbloquer.
- **Reproduction/couples transfrontières, synchronisation des ticks,
  diplomatie/guerre/ressources entre pays, rendu carte fédérée**
  explicitement hors périmètre — voir section dédiée en fin de document.

## Modèle de données

Nouvelles tables (même base SQLite `world_engine.db`, même style que les
tables existantes) :

```sql
CREATE TABLE IF NOT EXISTS federations (
    id TEXT PRIMARY KEY,             -- uuid4().hex
    nom TEXT,
    createur_cle_api TEXT NOT NULL,
    cree_le TEXT
)

CREATE TABLE IF NOT EXISTS federation_pays (
    federation_id TEXT NOT NULL,     -- FK federations.id, cascade à la suppression
    monde_id TEXT NOT NULL,          -- FK mondes.id
    cle_api TEXT NOT NULL,           -- propriétaire du pays au moment du rattachement
    nom TEXT,                        -- nom d'affichage optionnel, propre à CETTE fédération
    rattache_le TEXT,
    PRIMARY KEY (federation_id, monde_id)
)
CREATE INDEX idx_federation_pays_monde ON federation_pays(monde_id)

CREATE TABLE IF NOT EXISTS federation_adjacences (
    federation_id TEXT NOT NULL,     -- FK federations.id, cascade à la suppression
    monde_id_a TEXT NOT NULL,        -- normalisé : monde_id_a < monde_id_b (tri string)
    monde_id_b TEXT NOT NULL,
    declaree_le TEXT,
    PRIMARY KEY (federation_id, monde_id_a, monde_id_b)
)

-- Extension de la table `placements` existante (Sprint B/C) :
ALTER TABLE placements ADD COLUMN emigre INTEGER NOT NULL DEFAULT 0
ALTER TABLE placements ADD COLUMN emigre_au_tick INTEGER
ALTER TABLE placements ADD COLUMN emigre_vers_monde_id TEXT
```

- Suppression d'une fédération : cascade sur `federation_pays` et
  `federation_adjacences` — **ne touche jamais** `mondes`, `cellules`,
  `placements`, `couples`, `horloges`.
- Détacher un pays (`DELETE` d'une ligne `federation_pays`) : cascade
  applicative sur les lignes `federation_adjacences` de cette fédération
  impliquant ce `monde_id` (des deux côtés, `monde_id_a` ou `monde_id_b`).
- `federation_adjacences` stockée **normalisée** (une seule ligne par paire
  non ordonnée, `monde_id_a < monde_id_b` par tri de chaîne) — la lecture
  filtre sur `monde_id_a = ? OR monde_id_b = ?`, jamais besoin d'insérer les
  deux sens.
- Un pays peut apparaître dans `federation_pays` pour plusieurs
  `federation_id` distincts (pas de contrainte d'unicité sur `monde_id`
  seul).
- Toutes les requêtes existantes de comptage/éligibilité de population sur
  `placements` (mortalité, reproduction, formation de couple, éligibilité à
  la migration) sont étendues d'un filtre `emigre = 0`, en plus du filtre
  `vivant = 1` déjà en place.

## Mécanique de migration transfrontière (extension de l'étape 4 du tick)

Reprend l'étape 4 (Migration) du tick Sprint C, insérée juste avant le repli
existant, pour chaque habitant vivant (`vivant=1 AND emigre=0`) d'une cellule
jugée saturée :

1. Résoudre l'ensemble des pays adjacents à ce pays : union des paires de
   `federation_adjacences` sur toutes les fédérations dont ce `monde_id` est
   membre. Vide si le pays n'est dans aucune fédération, ou dans des
   fédérations sans adjacence déclarée le concernant.
2. Si cet ensemble est non vide : jet à probabilité faible (constante fixée
   au plan d'implémentation, plus faible que la probabilité de migration
   intra-pays) pour franchir une frontière.
   - **Succès** : pays destination tiré uniformément dans l'ensemble
     résolu à l'étape 1 ; cellule destination tirée aléatoirement bornée
     `[0, nb_cellules_destination-1]`. Traitement complet ci-dessous ; cet
     habitant ne repasse pas par la migration intra-pays ce tick.
   - **Échec, ou ensemble vide** : repli exact sur la migration intra-pays
     Sprint C, **inchangée**.
3. Traitement des migrations transfrontières décidées à l'étape 2, dans
   l'ordre :
   1. **Résoudre TOUS les verrous destination avant toute dissolution de
      couple** — pas émigrant par émigrant comme une première version de ce
      document le décrivait. Pour chaque pays destination distinct parmi les
      émigrants décidés (dédupliqué : un même pays destination n'est
      verrouillé qu'une fois, même si plusieurs émigrants y vont), tenter le
      verrou avec un timeout court (voir correction ci-dessus). Timeout
      dépassé → toutes les émigrations vers CE pays échouent proprement
      (`avertissements`), l'habitant reste chez lui. **Correction (revue
      finale de branche, Important corrigé)** : une première version faisait
      l'inverse — décider la dissolution du couple dès l'INTENTION de migrer,
      avant même de savoir si le verrou serait obtenu. En conditions réelles,
      un émigrant dont le verrou timeoutait restait chez lui (correct) mais
      son couple était quand même dissous (incorrect — il n'était jamais
      parti). La dissolution n'est donc décidée qu'une fois le verrou
      destination confirmé.
   2. Pour chaque émigrant dont le verrou a été obtenu : si l'habitant a un
      couple `actif=1`, le dissoudre (`actif=0`,
      `dissous_au_tick=tick_actuel+1`), même motif que la mort (Sprint C).
   3. Calculer l'âge au départ : `age = (tick_actuel + 1) − ne_au_tick`
      (placement d'origine).
   4. Marquer la ligne `placements` d'origine : `emigre=1`,
      `emigre_au_tick=tick_actuel+1`, `emigre_vers_monde_id=<destination>`.
      `vivant` reste `1` (l'habitant n'est pas mort) ; `mort_au_tick` reste
      `NULL`.
   5. Insérer une nouvelle ligne `placements` dans le pays destination :
      `cellule_id=<cellule tirée>`, `ne_au_tick = tick_actuel_destination −
      age`, `vivant=1`, `emigre=0`, `mort_au_tick=NULL`.
   6. **Transférer la propriété de l'enfant** (Correction, revue finale de
      branche, Important corrigé) : la ligne `enfants` de l'habitant change
      de `cle_api` pour celle du propriétaire du pays destination. Sans ça,
      un migrant entre deux pays de `cle_api` différentes ne pouvait plus
      jamais se reproduire dans son nouveau pays — `genome_moteur` résout
      ses parents par `cle_api`, et sa ligne `enfants` restait celle du
      tenant d'origine (échec silencieux, juste un avertissement). Décision
      utilisateur : « il vit maintenant là-bas, c'est l'habitant de ce
      tenant ». Cette écriture n'a lieu QUE pour un émigrant dont le verrou
      a été confirmé (jamais pour un émigrant resté chez lui après
      timeout) — la chaîne de consentement tient mécaniquement : le
      rattachement (déjà propriétaire-only) et l'adjacence (déjà
      membre-only) sont les actes de consentement du pays destination ;
      cette conséquence de transfert d'un habitant n'ajoute aucune capacité
      nouvelle côté destination, seul le tenant D'ORIGINE peut déclencher sa
      propre migration en faisant avancer son propre tick.
   7. Une fois toutes les écritures de ce pays destination appliquées,
      libérer son verrou — **avant** la phase de naissances du tick (voir
      correction suivante), pas après.
4. **Verrous destination libérés avant la boucle de naissances, pas après**
   (Correction, revue finale de branche, Important corrigé) : une première
   version tenait les verrous destination jusqu'à la toute fin du tick, ce
   qui incluait les appels HTTP vers `personnages` déclenchés par les
   naissances (jusqu'à 30 s de timeout chacun) — un tick avec plusieurs
   naissances pouvait bloquer un pays adjacent pendant toute cette durée.
   Aucun mécanisme des naissances ne dépend des écritures de migration
   (un émigrant est déjà retiré des `vivants` avant la formation de couples/
   reproduction de ce tick), donc les verrous destination sont libérés dès
   que les écritures de migration sont posées, bien avant la boucle de
   naissances.
5. Toute erreur isolée à cette étape (échec d'écriture) est capturée et
   ajoutée aux `avertissements` du résumé du tick d'origine — ne fait jamais
   échouer le tick entier, même motif que le reste de Sprint C.

## Contrat API

Nouveau routeur `/federation` dans `main.py`, même style que `/genome`,
`/spatial`, `/horloge` : cloisonné par `cle_api` selon les règles de
permission ci-dessus, 404 sur id absent ou permission refusée (jamais 403).

### `POST /federation`

Params : `nom` (optionnel). Crée une fédération vide. `createur_cle_api` =
la `cle_api` appelante (stocké, jamais renvoyé — voir correction ci-dessous).
Réponse : `{id, nom, cree_le}`.

**Correction (revue finale de branche, Critical corrigé)** : une première
version de ce document renvoyait `createur_cle_api` dans cette réponse, et
`createur_cle_api`/`cle_api` par pays dans les réponses `GET` ci-dessous —
exécuté en conditions réelles, ça permettait à n'importe quel membre d'une
fédération de lire la clé API brute d'un autre membre (ou de la créatrice)
et de s'en servir pour usurper entièrement ce tenant (créer/lire/supprimer
ses mondes et enfants) — contournement complet du cloisonnement de la
brique, dans la fonctionnalité dont l'objet même est de mélanger des
tenants. Décision utilisateur : **ces champs ne sont plus jamais renvoyés
sur le fil HTTP**, dans aucune réponse `/federation/*`. Les vérifications de
permission internes (`_federation_visible`, etc.) continuent de comparer les
`cle_api` réelles côté serveur — seule la sérialisation change. Les formes
de réponse ci-dessous sont corrigées en conséquence.

### `POST /federation/{id}/rattacher`

Params : `monde_id` (requis), `nom` (optionnel, nom d'affichage dans cette
fédération). Exige que la `cle_api` appelante soit propriétaire de
`monde_id`. 404 si la fédération ou le monde est absent, ou si la `cle_api`
appelante n'est pas propriétaire de `monde_id`. Réponse : `{federation_id,
monde_id, nom, rattache_le}`.

### `POST /federation/{id}/detacher`

Params : `monde_id` (requis). Exige que la `cle_api` appelante soit
propriétaire de `monde_id`. Retire la ligne `federation_pays` et toutes les
lignes `federation_adjacences` de cette fédération impliquant ce
`monde_id`. 404 si la fédération est absente ou si `monde_id` n'est pas
membre. Réponse : `{federation_id, monde_id, detache: true}`.

### `POST /federation/{id}/adjacence`

Params : `monde_id_a`, `monde_id_b` (requis). Exige que la `cle_api`
appelante possède au moins un pays membre de cette fédération. 404 si la
fédération est absente, ou si `monde_id_a`/`monde_id_b` ne sont pas tous
deux déjà membres de cette fédération. Réponse : `{federation_id,
monde_id_a, monde_id_b, declaree_le}` (paire normalisée dans la réponse,
quel que soit l'ordre fourni en entrée).

### `GET /federation/{id}`

Exige que la `cle_api` appelante soit créatrice ou propriétaire d'au moins
un pays membre. Réponse : `{id, nom, cree_le, pays: [{monde_id, nom,
rattache_le}], adjacences: [{monde_id_a, monde_id_b}]}` — jamais de
`cle_api`, voir correction ci-dessus. 404 si absente ou permission refusée.

### `GET /federation/{id}/etat`

Même permission que ci-dessus. Réponse : `{federation_id, pays: [{monde_id,
population_vivante}], population_totale}` — `population_vivante` par pays =
`COUNT(*) WHERE vivant=1 AND emigre=0` sur ses `placements`. 404 idem.

### `GET /federation`

Liste des fédérations où la `cle_api` appelante est créatrice ou membre :
`[{id, nom, cree_le}]` — jamais de `cle_api`, voir correction ci-dessus.

### `DELETE /federation/{id}`

Exige que la `cle_api` appelante soit créatrice. Détache tous les pays
(cascade `federation_pays` + `federation_adjacences`), supprime la ligne
`federations`. Ne supprime aucun monde. 204 si supprimée, 404 si absente ou
permission refusée.

## Repli honnête

- Fédération/monde/pays absent, ou permission refusée (mauvaise `cle_api`
  pour l'acte demandé) → 404 partout, jamais 403, jamais confondu avec un
  422 de forme (même motif que le reste de la brique).
- `POST /federation/{id}/adjacence` avec un `monde_id_a`/`monde_id_b` pas
  encore rattaché à cette fédération → 404 (pas d'adjacence entre pays non
  membres).
- Une migration transfrontière échouée à l'écriture (verrou, erreur SQLite)
  n'annule jamais le tick d'origine — capturée dans `avertissements`.
- Un habitant ne migre jamais deux fois dans le même tick (transfrontière et
  intra-pays sont mutuellement exclusifs par construction, cf. mécanique
  ci-dessus).
- Un habitant émigré (`emigre=1`) n'est plus jamais éligible à la
  mortalité/reproduction/migration/comptage de population de son pays
  d'origine, mais sa ligne reste lisible (historique, jamais supprimée).
- Suppression d'une fédération : jamais de suppression en cascade vers
  `mondes`/`cellules`/`placements`/`couples`/`horloges` — uniquement les
  tables propres à la fédération.
- Verrou du pays destination acquis avec timeout court — un interblocage
  potentiel se résout par échec isolé et propre de cette émigration
  (`avertissements`), jamais par un blocage indéfini du tick.

## Tests prévus

- `test_stockage_federation.py` (nouveau) : CRUD SQLite des 3 nouvelles
  tables en isolation, cascade de suppression/détachement.
- `test_federation.py` (nouveau, routes) :
  - cloisonnement des 4 endpoints d'écriture (rattacher exige la `cle_api`
    du pays ; détacher idem ; adjacence exige une `cle_api` membre ;
    suppression exige la `cle_api` créatrice) ;
  - 404 cohérents : fédération absente, monde absent, permission refusée,
    adjacence sur un pays non membre ;
  - une fédération peut mélanger des `cle_api` différentes sans fuite de
    données au-delà de l'agrégat consenti (`GET .../etat` ne révèle que les
    compteurs, jamais les identifiants d'habitants d'un pays qu'on ne
    possède pas) ;
  - un pays membre de 2 fédérations distinctes agrège bien les adjacences
    des deux au moment de la résolution des destinations ;
  - suppression d'une fédération : les mondes/pays sous-jacents existent
    toujours après (vérifié via `/spatial/mondes/{id}`).
- `test_horloge_moteur.py` (étendu) :
  - déterminisme de la migration transfrontière (même seed, deux exécutions
    isolées → mêmes résultats) ;
  - jamais de double migration (un habitant qui franchit une frontière ne
    repasse jamais par la migration intra-pays le même tick, et
    inversement) ;
  - âge préservé après émigration (`tick_actuel_destination −
    ne_au_tick_destination` égale l'âge au départ, à un tick près) ;
  - couple actif dissous avant l'émigration ;
  - ligne `placements` d'origine jamais supprimée après émigration,
    `vivant` reste `1`, `mort_au_tick` reste `NULL` ;
  - population d'un pays d'origine exclut bien un émigré
    (`vivant=1 AND emigre=0`) alors que la ligne existe toujours ;
  - scénario bout-en-bout : deux pays rattachés à une fédération, adjacence
    déclarée, plusieurs ticks avancés sur chacun indépendamment, au moins
    une migration transfrontière observée sur un nombre de ticks suffisant.

## Manifest

Nouvelles capacités `federation_creer`, `federation_rattacher`,
`federation_detacher`, `federation_adjacence_declarer`, `federation_lire`,
`federation_etat_lire`, `federation_lister`, `federation_supprimer` —
exposées par défaut à l'assistant, conformément à
[[feedback-exposer-nouvelles-fonctionnalites-assistant]].

## Hors périmètre de ce sprint

- Reproduction/couples transfrontières — un couple ne peut jamais avoir ses
  deux membres dans des mondes différents, aucun changement sur `couples`.
- Synchronisation des ticks entre pays d'une même fédération — chaque pays
  reste totalement autonome.
- Diplomatie, guerre, échanges de ressources entre pays.
- Rendu visuel d'une carte fédérée — `world-engine` reste une brique backend
  pure (JSON), même principe que Sprint B.
- Sprint E (mise à l'échelle, décision Redis vs RabbitMQ) — attend toujours
  le volume réel mesuré avec C+D en conditions réelles, voir
  [[backlog-world-engine-genome-cosmique-phases-suivantes]].

## Comment reprendre

Prochaine étape : plan d'implémentation détaillé (skill `writing-plans`),
puis exécution. Après ce sprint : Sprint E (mise à l'échelle) reste à
brainstormer une fois le volume réel mesuré avec C+D.

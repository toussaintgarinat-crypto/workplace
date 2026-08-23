# World Engine — Horloge de simulation (Sprint C)

**Date** : 2026-08-23
**Statut** : design approuvé, plan d'implémentation à venir

## Contexte

Suite de [world-engine-maillage-spatial-design](2026-08-23-world-engine-maillage-spatial-design.md).
Sprints A (persistance des lignées) et B (maillage spatial Voronoï, mondes
forkables) sont codés+revus+poussés. Ce sprint ajoute la **Brique 3** du
rapport d'architecture initial (« Horloge ») : une simulation temporelle par
ticks qui fait vivre un monde déjà généré — vieillissement/mortalité,
reproduction, migration, évolution des ressources.

### Décomposition actée en brainstorming

L'ambition complète évoquée en brainstorming (population à l'échelle de
centaines de milliers d'habitants, mondes fédérés composés de sous-mondes/pays)
dépasse largement ce qu'un seul sprint peut absorber sans risque — bâtir la
queue de traitement et le modèle hiérarchique par-dessus une mécanique de tick
jamais testée aurait forcé à tout défaire si cette mécanique s'avérait fausse
(déjà vu sur Sprint A : le bug DAG n'était visible qu'à la composition finale).
Même philosophie que Génome→Spatial (« prouver avant d'investir ») : le
chantier est découpé en 3 sprints ordonnés, décidés avec l'utilisateur :

- **Sprint C (ce document)** — la mécanique du tick elle-même, sur UN monde
  non fédéré, à volume modéré (dizaines à centaines d'habitants). Scheduler
  in-process, pas de queue.
- **Sprint D** — mondes fédérés (hiérarchie pays→monde), une fois la mécanique
  de tick prouvée correcte.
- **Sprint E** — mise à l'échelle (traitement vectorisé, queue de tâches
  Redis/RabbitMQ, migration de stockage éventuelle) une fois le volume réel
  mesuré en conditions réelles avec C+D. **C'est ce sprint, pas celui-ci, qui
  tranchera Redis vs RabbitMQ** — la question reste différée une 3e fois,
  faute de volume réel à ce stade.

## Décisions de conception (issues du brainstorming)

- **1 tick = 1 an narratif** — unité simple, cohérente avec les dates de
  naissance déjà stockées en années, lisible sans qu'il faille des milliers de
  ticks pour observer un changement de génération.
- **Déclenchement double** : un endpoint manuel (`POST /horloge/{id}/tick`,
  utile pour tester/déboguer un monde précis) ET un scheduler automatique
  in-process, **opt-in par monde** (`demarrer`/`arreter`) — un monde nouvellement
  créé ou forké reste en tick manuel tant qu'on ne l'active pas explicitement.
- **Âge et statut vivant/mort portés par le placement, pas par l'enfant.** Un
  enfant peut être placé dans plusieurs mondes (Sprint B, forks divergents) :
  l'âge et la mort doivent donc être propres à CHAQUE timeline. Un même enfant
  peut être vivant dans un monde et mort dans un fork de ce même monde,
  simultanément — c'est la suite logique de la philosophie des forks déjà
  actée en Sprint B, pas une nouvelle idée.
- **Mortalité probabiliste**, pas un couperet net à âge fixe : passé un âge
  minimum, probabilité de mourir croissante à chaque tick suivant. Modulée par
  le niveau de technologie de la cellule (plus de technologie ⇒ espérance de
  vie plus longue) — décision explicite de coupler mortalité et économie de
  ressources plutôt que de les traiter indépendamment.
- **Technologie dérivée des ressources récoltées**, pas du temps qui passe
  seul ni de la population brute : chaque cellule a son propre niveau de
  technologie (pas un niveau par monde — cohérent avec le fait que ressources
  et migration sont déjà raisonnées par cellule depuis Sprint B), alimenté en
  consommant une fraction du stock de ressources disponible localement.
- **Couples formés et dissous par hasard**, pas permanents jusqu'à la mort :
  à chaque tick, les adultes F/M célibataires vivants d'une même cellule ont
  une probabilité de former un couple ; les couples existants ont une
  probabilité de se dissoudre. Simule le hasard/destin plutôt qu'un
  appariement rigide à vie.
- **Deux voies de naissance** : couples actifs (probabilité de naissance par
  tick, donc une probabilité de non-naissance intrinsèque à chaque tentative)
  ET rencontres occasionnelles entre célibataires (probabilité indépendante,
  plus faible — l'« accident »/« plan d'un soir » demandé). Les deux
  produisent un enfant par le même mécanisme que `POST /genome/croiser`
  (réutilisé en interne), pas un système de naissance parallèle.
- **Migration poussée par la rareté** : un habitant a une probabilité de
  migrer vers une cellule voisine si sa cellule est saturée (population vivante
  élevée relativement à ses ressources restantes) — pas une migration à
  probabilité fixe indépendante du contexte.
- **Ressources à stock numérique**, pas seulement qualitatif : régénération
  naturelle par tick, moins consommation proportionnelle à la population
  vivante et à l'investissement technologique, plafonnée, jamais négative.
  Champ nouveau (`ressources_stock`), le champ qualitatif existant de Sprint B
  (`ressources`, liste de types présents) reste inchangé pour la compatibilité.
- **Naissance automatique sans saisie humaine possible** : `POST
  /genome/croiser` exige aujourd'hui que l'appelant fournisse toujours
  lieu/heure/décalage UTC de l'enfant (« jamais deviné »). Une naissance
  déclenchée par le tick n'a personne pour les fournir à cet instant — décision
  explicite : ces valeurs sont **dérivées déterministiquement de la cellule**
  (position (x,y) convertie en latitude/longitude par une formule fixe, heure
  et décalage UTC tirés du RNG seedé du monde), jamais héritées telles quelles
  du parent (éviterait que toute une lignée partage la même heure de
  naissance, étrange narrativement).
- **Fédération de mondes (pays→monde) explicitement hors périmètre** — notée
  ci-dessus comme Sprint D, changerait le modèle spatial plat de Sprint B et
  doit attendre que la mécanique de tick soit prouvée sur un monde simple.
- **Mise à l'échelle (centaines de milliers d'habitants, traitement vectorisé,
  queue Redis/RabbitMQ) explicitement hors périmètre** — notée comme Sprint E,
  à concevoir une fois le volume réel mesuré avec C+D en conditions réelles.

## Modèle de données

Extensions additives de `briques/world-engine/stockage_spatial.py` — aucune
table ni colonne existante modifiée en place, cohérent avec le principe déjà
appliqué en Sprint B (le fork copie des lignes, jamais une régénération).

```sql
CREATE TABLE IF NOT EXISTS horloges (
    monde_id TEXT PRIMARY KEY,       -- FK mondes.id, cascade à la suppression
    tick_actuel INTEGER NOT NULL DEFAULT 0,
    actif INTEGER NOT NULL DEFAULT 0,        -- 0/1 : scheduler in-process opt-in
    intervalle_secondes INTEGER,             -- NULL si jamais démarré
    derniere_execution TEXT                  -- ISO8601, NULL si jamais exécuté
)

-- Extension de la table `placements` existante (Sprint B) :
ALTER TABLE placements ADD COLUMN ne_au_tick INTEGER NOT NULL DEFAULT 0
ALTER TABLE placements ADD COLUMN vivant INTEGER NOT NULL DEFAULT 1
ALTER TABLE placements ADD COLUMN mort_au_tick INTEGER

CREATE TABLE IF NOT EXISTS couples (
    id TEXT PRIMARY KEY,
    monde_id TEXT NOT NULL,
    cellule_id INTEGER NOT NULL,
    habitant_a_id TEXT NOT NULL,
    habitant_b_id TEXT NOT NULL,
    forme_au_tick INTEGER NOT NULL,
    actif INTEGER NOT NULL DEFAULT 1,
    dissous_au_tick INTEGER
)
CREATE INDEX idx_couple_monde ON couples(monde_id)

-- Extension de la table `cellules` existante (Sprint B) :
ALTER TABLE cellules ADD COLUMN ressources_stock TEXT NOT NULL DEFAULT '{}'  -- JSON {ressource: quantite}
ALTER TABLE cellules ADD COLUMN niveau_technologie REAL NOT NULL DEFAULT 0.0
```

- Suppression d'un monde : cascade étendue à `horloges` et `couples` (même
  motif que `cellules`/`placements` déjà en cascade).
- Fork d'un monde : copie la ligne `horloges` du monde source avec le même
  `tick_actuel`, mais **`actif` remis à 0** — un fork ne démarre jamais
  silencieusement son propre scheduler ; copie aussi les couples actifs
  (référencent des `habitant_id` qui existent bien dans le fork puisque les
  placements sont dupliqués).
- Un habitant n'a au plus qu'un couple `actif=1` à la fois (contrainte
  applicative, vérifiée au moment de la formation — pas une contrainte SQL
  stricte, pour rester dans le style simple des tables existantes).

## Mécanique d'un tick

Un tick avance un monde d'une unité. Traité cellule par cellule, dans cet
ordre (l'ordre compte : les ressources doivent être à jour avant que la
technologie n'en consomme, la mortalité doit précéder la migration pour ne
jamais faire migrer un habitant déjà mort ce tick) :

1. **Ressources.** Pour chaque ressource de `ressources_stock` : nouveau stock
   = stock actuel + régénération naturelle (fraction fixe d'un plafond) −
   consommation (proportionnelle au nombre d'habitants vivants placés sur la
   cellule), borné à `[0, plafond]`.
2. **Technologie.** `niveau_technologie` progresse d'une fraction des
   ressources consommées à l'étape 1 (formule simple, plafonnée) — jamais
   négatif.
3. **Mortalité.** Pour chaque habitant vivant de la cellule : âge =
   `tick_actuel + 1 − ne_au_tick`. Passé un âge minimum, probabilité de mort
   croissante avec l'âge, réduite par `niveau_technologie` de la cellule
   (espérance de vie plus longue). Si mort : `vivant=0`,
   `mort_au_tick=tick_actuel+1`, et tout couple actif impliquant cet habitant
   est dissous (`actif=0`, `dissous_au_tick`).
4. **Migration.** Cellule jugée « saturée » si sa population vivante est
   élevée relativement à son stock de ressources total restant (seuil
   configurable). Chaque habitant vivant non mort à l'étape 3 a alors une
   probabilité de migrer vers une cellule voisine tirée au hasard parmi
   `voisins` — le placement est mis à jour (nouvelle `cellule_id`), `ne_au_tick`
   ne change pas (l'âge suit la personne, pas la cellule).
5. **Couples.** D'abord dissolution probabiliste des couples actifs restants ;
   ensuite formation probabiliste de nouveaux couples parmi les adultes F/M
   célibataires vivants de la cellule (appariement aléatoire s'il y a plusieurs
   candidats des deux sexes).
6. **Reproduction.** Deux voies indépendantes, toutes deux appellent en
   interne la même fonction que `POST /genome/croiser` (appel de fonction
   Python direct, pas de round-trip HTTP) avec `parent_a`/`parent_b` en
   `ReferenceParent` et lieu/heure/utc_offset de l'enfant dérivés de la
   cellule (voir décision ci-dessus) :
   - Chaque couple actif tente une naissance avec une probabilité fixe par
     tick (donc une probabilité de non-naissance intrinsèque).
   - Chaque paire de célibataires F/M compatibles restants (non en couple) a
     une probabilité indépendante, plus faible, de produire un enfant
     (rencontre occasionnelle).
   Un nouvel enfant est placé automatiquement sur la cellule de ses parents
   avec `ne_au_tick = tick_actuel + 1`.

Toute erreur d'écriture isolée (ex. échec de persister une naissance) ne fait
jamais échouer le tick entier — capturée, ajoutée aux `avertissements` du
résumé renvoyé, même motif que les échecs partiels déjà tolérés en Sprint A/B.

Les valeurs exactes (âge minimum de mortalité/fécondité, probabilités de
mort/dissolution/formation de couple/naissance, taux de régénération et
plafond des ressources, seuil de saturation déclenchant la migration) sont
fixées dans le plan d'implémentation, pas ce document — ce sont des constantes
ajustables, pas des choix de mécanisme.

## Contrat API

Nouveau routeur `/horloge` dans `main.py`, même style que `/genome` et
`/spatial` : cloisonné par `cle_api`, 404 sur `monde_id` absent ou d'une autre
clé (jamais 403, jamais confondu avec un 422 de forme).

### `POST /horloge/{monde_id}/tick`

Avance ce monde d'exactement 1 tick. Réponse :
`{tick_actuel, naissances, morts, migrations, couples_formes, couples_dissous,
niveau_technologie_moyen, avertissements}`. 404 si le monde est absent/autre
clé.

### `POST /horloge/{monde_id}/demarrer`

Params : `intervalle_secondes` (requis, borné). Active le mode automatique —
le scheduler in-process déclenchera un tick sur ce monde chaque fois que
`intervalle_secondes` s'est écoulé depuis `derniere_execution`. Réponse :
`{monde_id, actif: true, intervalle_secondes}`. 404 si le monde est
absent/autre clé.

### `POST /horloge/{monde_id}/arreter`

Désactive le mode automatique (`actif=0`). N'affecte pas `tick_actuel` — les
ticks déjà passés restent acquis. Réponse : `{monde_id, actif: false}`. 404
idem.

### `GET /horloge/{monde_id}`

État courant : `{monde_id, tick_actuel, actif, intervalle_secondes,
derniere_execution}`. 404 idem.

### Scheduler in-process

Une tâche de fond (APScheduler, ou boucle `asyncio` périodique — décision
d'implémentation, pas de nouveau service/conteneur) vérifie à intervalle fixe
court (ex. toutes les 5-10s) les horloges avec `actif=1` dont
`derniere_execution + intervalle_secondes` est dépassé, et déclenche un tick
pour chacune. Aucune queue externe : le volume visé pour ce sprint (dizaines à
centaines d'habitants, quelques mondes actifs) ne le justifie pas — à
réexaminer en Sprint E avec le volume réel mesuré.

## Repli honnête

- `monde_id` absent ou d'une autre `cle_api` → 404 partout, jamais confondu
  avec un 422 de forme (même motif que le reste de la brique).
- Un tick ne peut jamais planter à mi-chemin d'une cellule à cause d'une seule
  naissance/migration ratée — chaque sous-étape isolée, erreurs collectées
  dans `avertissements`, jamais un 500.
- Un habitant ne migre jamais deux fois dans le même tick (l'étape 4 traite
  chaque habitant une seule fois par passage, sur son état de cellule au
  début du tick — pas de re-lecture après migration dans la même passe).
- Un habitant mort à l'étape 3 n'est jamais éligible à la migration (étape 4)
  ni à la reproduction (étape 6) du même tick.

## Tests prévus

- Déterminisme : même `seed` de monde + même `tick_actuel` de départ ⇒ mêmes
  résultats (naissances/morts/migrations identiques) sur deux exécutions
  isolées.
- Pas de double-traitement d'un habitant migré dans le même tick.
- Cloisonnement `cle_api` sur les 4 nouveaux endpoints `/horloge`.
- Fork : la ligne `horloges` copiée reprend `tick_actuel` du monde source mais
  a `actif=0`, quel que soit l'état du monde source au moment du fork.
- Scénario bout-en-bout : créer un monde, peupler quelques cellules (via
  `genome_croiser` + `monde_id`), avancer plusieurs ticks manuellement,
  vérifier que la population évolue de façon non triviale (au moins une
  naissance ou une mort sur un nombre de ticks suffisant).
- Mortalité jamais négative pour un habitant déjà mort (pas de double
  décrément, pas de ressuscitation implicite).

## Comment reprendre

Prochaine étape après ce sprint : Sprint D (mondes fédérés, hiérarchie
pays→monde) — à brainstormer une fois cette mécanique de tick prouvée et
poussée. Sprint E (mise à l'échelle, décision Redis/RabbitMQ) attend le
volume réel mesuré avec C+D en conditions réelles.

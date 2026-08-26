# Pont Studio↔world-engine — registre de personnages persistant

**Date** : 2026-08-26
**Statut** : design approuvé, plan d'implémentation à venir

## Contexte

Idée exprimée par l'utilisateur après la clôture du Sprint E de world-engine
(mise à l'échelle du scheduler) : faire de `world-engine` un registre vivant
des personnages Studio qui reviennent d'une histoire à l'autre, au lieu de
fiches jetables recréées à chaque série. Correspond à la Brique 4 du rapport
d'architecture original de world-engine (« Compilateur de packs »),
envisagée dès le Sprint D mais jamais reprise depuis.

Ancrage technique existant : `briques/studio` et `briques/world-engine`
dépendent tous les deux de `briques/personnages` (5900) — jamais l'inverse,
et jamais l'un de l'autre directement. `world-engine/personnages_client.py`
donne déjà le motif à suivre pour l'appel HTTP inter-briques (jamais
d'import de code, jamais de donnée inventée en cas d'indisponibilité —
propagation d'une exception dédiée). Ce document conçoit le pont
`studio → world-engine`, qui suit exactement le même motif.

## Objectif

1. Permettre à un personnage récurrent d'une série Studio de devenir un
   habitant persistant d'un monde world-engine dédié à cette série, sur
   décision explicite de l'utilisateur.
2. Faire avancer ce monde dans le temps au rythme de l'écriture (un tick par
   chapitre), pour qu'il y ait un historique simulé (âge, position, mort
   éventuelle) à raconter quand le personnage revient.
3. Proposer cet historique à l'utilisateur avant l'écriture d'un chapitre où
   ce personnage réapparaît, sans jamais l'imposer.

## Décisions de conception

- **Isolation par série, pas par famille.** Chaque série Studio a son propre
  monde world-engine, complètement isolé — même des autres séries de la
  même famille. Décision utilisateur explicite : pas de mélange de
  personnages entre séries, quitte à ce qu'un personnage qui change de
  série reparte sans continuité de son monde précédent.
- **Récurrence = casting formel OU seuil objectif de 3 chapitres.** Un
  personnage de la distribution structurée (`serie.personnages`, casté
  explicitement par l'utilisateur avec rôle/description) est éligible
  immédiatement. Un personnage seulement extrait du texte par
  `_recolter_canon` devient éligible à sa 3ᵉ apparition dans des chapitres
  distincts — nécessite un compteur d'apparitions par nom, absent
  aujourd'hui (`canon.personnages` est un ensemble dédoublonné, pas un
  compteur).
- **Nouveau point d'entrée « fondateur solo » côté world-engine**, plutôt
  que de détourner `/genome/croiser` avec 2 parents synthétiques inventés.
  `/genome/croiser` exige des données de naissance réelles de 2 parents
  (« jamais devinées ») — un personnage de fiction n'a ni date, ni heure, ni
  lieu de naissance réels, seulement nom/rôle/description. Décision
  utilisateur explicite : plutôt qu'une fiction de 2 parents inventés pour
  réutiliser l'endpoint existant, une vraie capacité world-engine dédiée à
  ce cas (moins rapide à livrer, plus honnête conceptuellement).
- **Déclenchement manuel, pas automatique.** L'éligibilité est détectée
  automatiquement, mais la fondation d'un habitant world-engine attend une
  validation explicite de l'utilisateur — cohérent avec la philosophie
  « agent PROPOSE, humain DÉCIDE » déjà en place dans `studio.py`.
- **Un tick par chapitre écrit.** Le temps simulé suit le rythme narratif :
  pas d'horloge autonome en continu (`/horloge/{mid}/demarrer`) découplée de
  l'écriture, pour que le temps simulé et le temps narratif ne divergent
  jamais de façon incompréhensible pour l'utilisateur.
- **Retour proposé, jamais injecté automatiquement.** Quand un personnage
  lié réapparaît dans la distribution prévue d'un chapitre, son état
  world-engine (âge, position, vivant/mort) est présenté comme suggestion de
  faits acquis, exactement comme le canon existant est présenté à
  l'utilisateur — jamais fusionné directement dans `canon.acquis` sans
  validation.
- **Mort simulée signalée, jamais silencieuse.** Si l'état renvoyé par
  world-engine est `mort_au_tick`, le pont le formule explicitement comme
  fait proposé (« X est mort dans le monde simulé, à tel âge, tel lieu »).
  L'utilisateur choisit de l'intégrer (le personnage meurt aussi dans la
  fiction) ou de l'ignorer — dans ce dernier cas, le personnage est détaché
  silencieusement de `habitants` : plus aucune proposition future pour ce
  nom, il redevient une fiche Studio ordinaire.
- **Le lien personnage↔habitant vit dans une 3ᵉ table dédiée côté Studio**
  (`stockage_pont.py`, nouveau, même motif que `stockage_federation.py`
  côté world-engine : nouvelles tables dans la base SQLite déjà existante de
  la brique, pas un nouveau service). Ni `serie.personnages` (Studio) ni la
  fiche d'un enfant (world-engine) ne portent directement cette référence —
  décision utilisateur explicite, contre la proposition initiale (porter le
  lien directement sur la fiche personnage Studio), pour garder la
  responsabilité du lien isolée des deux modèles de données existants.
- **Studio est l'appelant HTTP, world-engine reste ignorant de Studio.**
  Respecte le sens de dépendance déjà en place
  (`studio → world-engine → personnages`, jamais l'inverse). Un
  `world_engine_client.py` nouveau côté Studio, même motif que
  `personnages_client.py` côté world-engine.

## Composants

**`briques/world-engine` (nouveau code)**

- `POST /genome/fonder` — body `{monde_id, description, prenoms, nom,
  sexe?}`. En interne : appelle
  `personnages_client.recherche_inverse(description)` pour un thème
  plausible (même mécanisme que la mutation existante dans
  `executer_croisement`), crée et stocke directement un « enfant » fondateur
  sans passer par un croisement à 2 parents, le place sur une cellule du
  monde (réutilise la logique de placement de `_cellule_naissance`, sans
  influence de position d'un parent). Renvoie `{eid, cellule_id, theme}`.
  `monde_id` introuvable ou d'une autre clé API → 404, `personnages`
  indisponible → 502, mêmes contrats que `genome_croiser`.
- `GET /genome/enfants/{eid}` gagne un champ `simulation` (rétrocompatible,
  `null` si l'enfant n'est placé sur aucun monde) : `{monde_id, cellule_id,
  ne_au_tick, age_actuel_ticks, vivant}`, lu directement depuis
  `placements`/l'horloge du monde (même service, pas de nouvel appel HTTP
  interne). Comble un manque réel de l'API actuelle : aujourd'hui, aucune
  route ne permet de lire l'état simulé d'un habitant précis par son `eid`
  sans connaître déjà sa cellule (seule `spatial_cellule_lire` liste les
  enfants d'une cellule donnée).

**`briques/studio` (nouveau code)**

- `stockage_pont.py` : deux tables dans la base SQLite déjà existante de la
  brique.
  - `mondes_serie` : `serie_id → monde_id` — le monde world-engine d'une
    série, créé une seule fois (au premier personnage fondé de cette
    série), via l'endpoint `/spatial/mondes` déjà existant, avec un maillage
    par défaut modeste (ex. 8 cellules génériques) — détail technique, pas
    un choix narratif exposé à l'utilisateur.
  - `habitants` : `(serie_id, nom_cle) → eid`, `lie_le` — le lien
    personnage↔habitant. `nom_cle` = même normalisation que `_cle_perso`
    (existant) pour rester cohérent avec le rapprochement script⇄fiche déjà
    en place.
- `world_engine_client.py` : appels HTTP vers world-engine (`/genome/fonder`,
  `/spatial/mondes`, `/horloge/{mid}/tick`, `GET /genome/enfants/{eid}` pour
  l'état simulé) — jamais d'import de code, exception dédiée
  `WorldEngineIndisponible` en cas d'échec réseau, même motif que
  `PersonnagesIndisponible`.
- `canon.apparitions : {nom_cle: n}` — nouveau compteur, incrémenté par
  `_fusion_canon` à chaque chapitre pour chaque nom déjà vu (en plus de la
  déduplication existante dans `canon.personnages`). C'est ce qui rend le
  seuil de 3 chapitres vérifiable.

## Flux détaillé

**Entrée (proposition → fondation)**

1. Après génération d'un chapitre, si un nom franchit le seuil (casté
   formellement dans `serie.personnages`, ou `canon.apparitions[nom_cle] ==
   3`) et n'a pas déjà de ligne dans `habitants` → Studio l'ajoute à une
   liste « éligibles, à proposer » retournée avec la réponse du chapitre.
2. L'utilisateur valide l'entrée d'un personnage précis depuis le front
   Studio → Studio crée le monde de la série s'il n'existe pas encore
   (`mondes_serie`), appelle `/genome/fonder`, stocke `(serie_id, nom_cle) →
   eid` dans `habitants`.

**Cycle temporel**

- Chaque nouveau chapitre généré pour une série qui a déjà un monde
  (`mondes_serie` non vide pour cette série) déclenche un
  `POST /horloge/{mid}/tick` juste après la génération du chapitre — un
  tick par chapitre, indépendamment du nombre de personnages liés.

**Retour (réapparition)**

1. Avant de générer un chapitre, Studio croise la distribution prévue avec
   `habitants` : tout personnage lié présent dans la distribution → Studio
   lit `GET /genome/enfants/{eid}` pour son champ `simulation` (âge,
   cellule/position, vivant ou `mort_au_tick`).
2. Ces faits sont présentés à l'utilisateur comme suggestions de
   `canon.acquis`, avec la même mécanique d'affichage que le canon existant
   — jamais injectés directement.
3. Faits acceptés → rejoignent `canon.acquis` normalement, influencent
   l'écriture comme n'importe quel fait acquis.
4. Cas mort : proposition explicite (« X est mort dans le monde simulé, à
   tel âge, tel lieu ») ; refusée → détachement silencieux de `habitants`,
   plus aucune proposition future pour ce nom.

**Gestion d'erreurs**

Si world-engine est indisponible (réseau/timeout) à n'importe quelle étape
(fondation, tick, lecture d'état) → repli honnête : le chapitre se génère
quand même sans bloc de suggestions world-engine, aucune donnée inventée,
aucune exception qui casse l'écriture — même philosophie que
`_recolter_canon` (`except Exception: return`, no-op).

## Hors périmètre

- Pont bidirectionnel (world-engine → Studio, ex. générer du contenu
  narratif à partir d'événements de simulation marquants) — c'est la
  direction inverse envisagée par la Brique 4 du rapport d'architecture
  original, pas demandée ici. Reste une piste future.
- Front de visualisation de world-engine (mondes, population, migrations,
  généalogies) — idée associée exprimée par l'utilisateur, jugée secondaire
  au pont lui-même. Reste à reprendre séparément.
- Modification du modèle de mortalité/vieillissement de world-engine — le
  pont consomme l'état existant de l'horloge de simulation tel quel, ne
  change aucune mécanique de simulation.
- Migration/fédération entre mondes de séries différentes — l'isolation par
  série exclut par construction toute mécanique de migration
  transfrontière (Sprint D) entre les mondes de ce pont.

## Tests

- **world-engine** : nouveau test pour `/genome/fonder` — crée un enfant
  sans croisement, place bien sur une cellule du monde, 404 si `monde_id`
  inconnu ou d'une autre clé API, 502 si `personnages` indisponible (même
  contrat que `genome_croiser`) ; nouveau test pour le champ `simulation` de
  `GET /genome/enfants/{eid}` — `null` sans placement, rempli et cohérent
  après fondation puis un ou plusieurs ticks (`vivant`/`mort_au_tick` selon
  l'issue de l'horloge).
- **studio** : `test_stockage_pont.py` (CRUD des 2 tables, isolation par
  `serie_id`) ; `test_pont_eligibilite.py` (le compteur `canon.apparitions`
  monte bien, seuil à 3, casting formel = éligible immédiatement) ;
  `test_pont_entree.py` (mock du client HTTP world-engine : fondation
  réussie, monde créé une seule fois pour la série, 2ᵉ personnage réutilise
  le même monde) ; `test_pont_retour.py` (suggestions générées à partir d'un
  état mocké, y compris le cas mort et son détachement) ;
  `test_pont_indisponible.py` (world-engine down → chapitre généré quand
  même, aucune suggestion, pas de crash).

## Risques / limites connues

- Le seuil de 3 chapitres et l'isolation stricte par série sont des choix
  utilisateur assumés, pas dérivés d'une mesure — à ajuster si l'usage réel
  révèle un seuil mal calibré ou un besoin de continuité inter-séries non
  anticipé.
- `/genome/fonder` introduit une 2ᵉ voie de création d'habitant à côté de
  `/genome/croiser`, avec un contrat volontairement proche mais un chemin de
  code distinct — à surveiller pour ne pas diverger silencieusement des
  garanties de `genome_croiser` (placement, gestion d'erreurs) au fil des
  évolutions futures de l'un ou l'autre.

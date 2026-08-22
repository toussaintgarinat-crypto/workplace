# World Engine — Génome Cosmique (breed_profiles)

**Date** : 2026-08-22
**Statut** : design approuvé, plan d'implémentation à venir

## Contexte

Idée de départ : un « World Engine » (générateur procédural d'univers/dynasties)
bâti sur 4 briques (Génome, Spatial, Horloge, Compilateur). Avant d'investir dans
la simulation temporelle, la cartographie ou une queue (RabbitMQ n'existe nulle
part dans Workplace aujourd'hui — Redis oui, via `core/horloge.py` et
`oria-stack`), l'utilisateur veut prouver le premier maillon : le croisement de
deux profils cosmiques pour produire un « enfant » (génération n+1).

Ce prototype s'appuie sur le moteur `briques/personnages` qui vient d'être
resynchronisé avec le standalone [portrait-cosmique](https://github.com/toussaintgarinat-crypto/portrait-cosmique)
(carte astro complète : 10 corps, points évolutifs, maisons, aspects, dominantes —
capacité `personnage_theme_complet` + `personnage_portrait_generer` enrichi).

Décision de choix d'infra : reportée. Ni Redis ni RabbitMQ n'ont leur place dans
ce prototype stateless — le tick/simulation ne se pose que si ce premier maillon
prouve que le croisement produit un résultat intéressant.

## Contrainte de conception (issue de l'échange avec l'utilisateur)

Astrologiquement, un enfant n'a pas de date de naissance déductible de ses
parents. Deux approches ont été écartées en cours de discussion :

- **Mixer directement les positions planétaires des parents** → produit un thème
  qui ne correspond à aucune vraie configuration astronomique. Rejeté.
- **Faire porter l'hérédité par la date** (dérivée mathématiquement des dates
  parentales) ou **par le lieu** (moyenne géographique) → l'utilisateur a explicitement
  écarté ces mécanismes : dans un jeu à pouvoirs héréditaires, la logique de jeu
  gérera l'hérédité ailleurs ; ce prototype n'a pas à porter cette responsabilité.

**Décision retenue** : le thème brut de l'enfant est calculé à une **vraie date**,
avec une **vraie astronomie**, totalement indépendante des parents. L'hérédité
n'apparaît qu'en **post-traitement narratif** : on compare après coup le thème
enfant déjà calculé aux thèmes parents.

## Flux de croisement

`POST /genome/croiser` sur la nouvelle brique `world-engine` (port 6220) :

1. **Reçoit** : 2 fiches parents (même forme que `FicheHolistique` de
   `personnages` : prénoms/nom/date/heure/lieu), le nom de l'enfant, le **lieu de
   naissance de l'enfant** (lat/long/utc_offset — fourni par l'appelant, jamais
   deviné ni moyenné), et `mutation_rate` (float 0.0–1.0, défaut 0.10).
2. **Appelle** `POST /holistique/portrait` sur `personnages`
   (`host.docker.internal:5900`) pour chaque parent → traditions + portrait +
   theme_complet réels de A et B.
3. **Fusionne** les traits dominants des 2 parents (archétype, forces, dominante
   planète×signe) en une description texte. Avec probabilité `mutation_rate`,
   injecte un trait supplémentaire absent des deux parents (pool de mots-clés tiré
   des tables `significations.py` non présentes dans les traits des parents).
4. **Envoie** cette description à `POST /holistique/recherche-inverse` (capacité
   déjà existante de `personnages`) → récupère un **signe** cible fiable
   (`signes[0]["signe"]`).

   ⚠️ Correction faite pendant la conception : le champ `exemple_date` de cette
   route n'est **pas** exploitable tel quel comme date machine — c'est un champ
   d'affichage humain qui peut valoir une vraie date ISO, un simple `"JJ/MM"` sans
   année, du texte libre (« vers le 22 décembre » pour les signes à cheval sur le
   nouvel an), ou `None`. World-engine ne l'utilise donc pas : il n'exploite que
   le champ structuré `signes[0]["signe"]`.
5. **Convertit** ce signe en jour/mois via une **petite table statique interne à
   world-engine** (les 12 plages de dates du zodiaque occidental — savoir
   calendaire public, indépendant du moteur astro de `personnages`), associée à
   une **année** choisie sans signification d'hérédité (paramètre optionnel
   `annee_enfant` ; défaut = année courante si absent — même logique que le lieu :
   un choix pratique, pas un mécanisme génétique).
6. **Recalcule** le vrai thème de l'enfant à cette date construite + le lieu
   fourni par l'appelant, via `POST /holistique/portrait` sur `personnages` —
   thème 100% indépendant, astronomiquement réel.
7. **Compare** les 10 corps (`theme_complet.dix_corps`) de l'enfant à ceux de
   chaque parent (signe/élément par corps) → étiquette chacun : hérité de A,
   hérité de B, commun aux deux, ou mutation (ne correspond à aucun parent).
8. **Répond** : parents (traditions/portrait/theme_complet), enfant (idem), le
   tableau d'hérédité par corps, un résumé chiffré (ex. 6/10 hérités de A, 2/10 de
   B, 2/10 mutation), et `mutation_survenue: bool`.

## Architecture

Brique `briques/world-engine/`, calquée sur le squelette FastAPI standard des
autres briques :

- CORS via `CORS_ORIGINS`, auth par clé (`API_KEYS` + `WORLD_ENGINE_KEY` fusionnée
  pour l'intégration Cœur, même motif que `PERSONNAGES_KEY`).
- `depends_on: ["personnages"]` dans `manifest.json` — dépendance runtime
  assumée et documentée (le prototype ne duplique pas le moteur astro).
- **Stateless uniquement** pour cette version : aucune persistance des enfants
  générés. Rejouer des croisements sur plusieurs générations (n+2) est
  explicitement hors périmètre — à reconsidérer seulement si ce premier maillon
  prouve son intérêt.
- Une seule capacité manifest : `genome_croiser` (`action: false` — c'est une
  analyse, rien n'est stocké), `POST /genome/croiser`.

## Repli honnête

- `personnages` injoignable → **502** explicite, jamais de donnée inventée pour
  compenser.
- Fiche parent sans date de naissance valide → la 422 de `personnages` est
  propagée telle quelle.
- `recherche-inverse` ne reconnaît aucun trait dans la description fusionnée
  (`signes` vide) → **422** (« impossible de dériver un signe pour l'enfant à
  partir de cette description »), jamais de repli sur un signe arbitraire —
  romprait la décision de ne jamais deviner sans base.

## Tests

- Fusion des traits parents → description : déterministe hors injection de
  mutation (aléatoire injecté via une instance `random.Random` passée en
  paramètre, pour un test reproductible avec seed fixe).
- Composition de la route testée avec les appels à `personnages` mockés (pas
  besoin du stack Docker qui tourne pour lancer la suite).
- Filet manifeste↔route (même motif que `briques/personnages/test_manifest_capacites.py`) :
  chaque capacité du manifest pointe une route réellement montée.

## Hors périmètre de ce prototype

- Persistance des enfants générés / lignées multi-générations.
- Simulation temporelle, ticks, queue (Redis ou RabbitMQ) — décision reportée
  jusqu'à preuve que le croisement produit un résultat narrativement intéressant.
- Cartographie spatiale (hexagones/Voronoï), arbres technologiques, conflits de
  factions — phases 2 et 3 du rapport d'architecture initial, non abordées ici.

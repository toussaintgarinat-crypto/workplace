# Brique `jeu-factions` — moteur de combat temps réel (sous-projet 2/5)

## Contexte

Le spec [`2026-07-29-jeu-factions-design.md`](2026-07-29-jeu-factions-design.md) (sous-projet
1/5, livré) pose une décomposition en cinq du jeu holistique et exclut explicitement le
combat temps réel : la résolution des zones de signe y est une simple comparaison de stats
automatique à un tick planifié (asyncio, `TICK_INTERVAL_HOURS`), pas un moteur d'action.

Ce spec est le sous-projet 2/5 : remplacer cette résolution automatique des **zones de
signe** par du vrai combat temps réel joué — déplacement 2D, sorts, cooldowns, mobs/boss —
dans l'esprit WoW (vue du dessus, tab-cible/zone d'effet, pas de netcode 3D). Décision de
cadrage (revue avec l'opérateur) :

- Vue du dessus, positionnement 2D continu, pas de grille.
- 100 % PvE (aucun PvP — cohérent avec le non-objectif déjà posé au sous-projet 1).
- Zone entière partagée mais **shardée** en plusieurs instances plafonnées (pas une seule
  boucle sans limite — cf. Sharding ci-dessous), pour rester jouable sur l'infra actuelle
  (un seul process HP, pas d'infra multi-joueurs dédiée — sous-projet 4).
- Client : Phaser 3 chargé par `<script src=cdn>`, **pas de build** — même motif « front
  autonome » que toutes les autres briques Workplace, juste avec une vraie bibliothèque de
  jeu au lieu de vanilla Canvas (rendu/collision/animation à la main aurait été trop de
  travail pour un ressenti correct).
- Reste dans la brique `jeu-factions` existante (port 6210) : le combat a besoin d'un accès
  étroit et permanent aux personnages/zones/compétences déjà stockés là ; le séparer en
  brique à part forcerait une synchronisation réseau constante pour un état qui change
  10 fois par seconde.

## Non-objectifs

- **Pas de PvP.** Uniquement joueurs contre mobs/boss.
- **Pas d'anti-triche poussé.** Le serveur reste autoritaire sur la position et les dégâts
  (le client n'envoie que des intentions, jamais une position qu'il impose), mais pas de
  détection d'anomalies statistiques, de rate-limiting fin par joueur, etc. — cercle privé
  de confiance, pas un serveur public (le sous-projet 4, infra multi-joueurs publique,
  posera ces questions le cas échéant).
- **Pas de carte à obstacles.** Arène rectangulaire bornée, sans tiles/collision de terrain
  ni pathfinding pour les mobs (ils vont en ligne droite vers leur cible).
- **Pas d'historique de combat détaillé.** Comme avant : `resolutions` note l'issue
  (victoire, contributions par guilde), pas un replay coup par coup.
- **Ne touche pas à la résolution des voies d'archétype/groupes.** Le flux « groupes ciblant
  une étape d'archétype » (spec sous-projet 1, tick asyncio, comparaison de stats) reste
  **inchangé** par ce spec — seules les **zones de signe** passent en combat joué. Faire
  aussi jouer les étapes d'archétype en temps réel serait un scope naturel pour un futur
  incrément, mais n'a pas été validé ici.
- **Pas de rendu 3D, pas d'assets graphiques custom.** Formes géométriques simples
  (cercles/rectangles colorés par élément/signe) pour joueurs et mobs en v1 — pas de sprite
  art.

## Architecture

Nouveaux modules dans `briques/jeu-factions/`, même motif « cœur pur + coquille I/O fine »
que `zones.py::calculer_resolution` déjà dans le code :

- `combat_moteur.py` — **fonction pure**, zéro I/O : `avancer_tick(etat, actions_en_attente)
  -> (nouvel_etat, evenements)`. Déplacement, collision par cercles, cooldowns, résolution
  des sorts, dégâts, mort de mob. 100 % testable en pytest sans WebSocket ni asyncio réel.
- `combat.py` — orchestration : une instance = un `asyncio.Task` qui appelle
  `avancer_tick` à fréquence fixe (`COMBAT_TICK_HZ`) et diffuse l'état aux WebSockets
  connectés de cette instance. Gère aussi le cycle de vie des instances (création,
  assignation, fermeture après grâce — cf. Sharding).
- `mobs.py` — seed des mobs/boss par zone (même motif que `zones.ZONES_SEED` /
  `archetypes.ARCHETYPES_SIGNATURE` : données de référence fixes, chargées au démarrage).
- `front_combat.html` — nouveau front dédié (Phaser 3 CDN), séparé de `front.html` existant
  (qui reste la vue simple : créer un personnage, lister les zones). `front.html` gagne un
  lien « Rejoindre le combat » par zone qui ouvre `front_combat.html?zone=<id>`.

État runtime (positions, PV courants, cooldowns, effets actifs) vit **en mémoire du
process**, dans un dict Python tenu par `combat.py` — jamais en SQLite pendant la partie
(un `UPDATE` à 10 Hz par joueur serait un goulet d'étranglement inutile). Persisté en base
seulement aux événements significatifs : mob/boss tué (→ `resolutions`,
`scores_zone_guilde`), zone marquée `vaincue` pour la première fois.

Conséquence directe : l'état de combat **ne survit pas à un redémarrage du process** — un
joueur en cours de combat lors d'un déploiement doit se reconnecter et reprend une nouvelle
instance. Acceptable pour ce cadrage (pas d'infra multi-joueurs publique à ce stade).

## Modèle de données

Nouvelle table (seed au démarrage, même motif que `zones`/`zones_archetype`) :

```sql
CREATE TABLE mobs_zone (
    id TEXT PRIMARY KEY,
    zone_id TEXT NOT NULL REFERENCES zones(id),
    nom TEXT NOT NULL,
    role TEXT NOT NULL,              -- 'mob' | 'boss' (une zone a exactement 1 boss)
    pv_max INTEGER NOT NULL,
    degats_attaque INTEGER NOT NULL,
    cooldown_attaque_s REAL NOT NULL,
    portee_aggro INTEGER NOT NULL,   -- unités d'arène : distance de déclenchement
    portee_attaque INTEGER NOT NULL
);
```

`competences` (table existante, sous-projet 1) reçoit un effet réel — les compétences
débloquées n'étaient jusqu'ici que nom + texte + condition, sans comportement. Migration
`ALTER TABLE` idempotente (vérifiée via `PRAGMA table_info`, motif déjà utilisé ailleurs
dans le repo pour les colonnes ajoutées après coup) :

```sql
ALTER TABLE competences ADD COLUMN effet_type TEXT;      -- degats | soin | bouclier | etourdissement | dot
ALTER TABLE competences ADD COLUMN magnitude INTEGER;
ALTER TABLE competences ADD COLUMN portee INTEGER;
ALTER TABLE competences ADD COLUMN cooldown_s REAL;
```

Colonnes nullable : une compétence seedée avant ce spec (`effet_type IS NULL`) reste
affichable dans `GET /personnages/{id}/competences` mais n'est simplement pas utilisable en
combat (ignorée côté client — pas d'erreur serveur). Le seed de `archetypes.py` est étendu
pour remplir ces colonnes pour les 10 voies.

`resolutions` et `scores_zone_guilde` (tables existantes) sont réutilisées telles quelles :
un mob/boss tué logue une `resolution` avec `contributions` = dégâts cumulés par guilde
pendant l'instance, exactement comme l'ancienne résolution par tick.

Pas de nouvelle table pour les instances/joueurs-en-combat : c'est de l'état runtime, pas
persisté (cf. Architecture).

## Boucle de simulation (`combat_moteur.avancer_tick`, pure)

Entrée : `etat` (positions/PV/cooldowns de tous les joueurs et mobs de l'instance) +
`actions_en_attente` (liste des intentions reçues depuis le tick précédent). Sortie :
nouvel état + liste d'événements (`mob_touche`, `mob_tue`, `joueur_touche`,
`joueur_ko`).

1. **Déplacement** : chaque joueur avec une intention `deplacement` avance d'un pas fixe
   dans la direction demandée (vitesse constante, pas d'accélération), borné aux limites de
   l'arène (`COMBAT_ARENE_TAILLE`).
2. **Cooldowns** : décrémentés du temps écoulé depuis le tick précédent.
3. **Sorts** : pour chaque intention `sort` reçue ce tick, dans l'ordre de réception —
   vérifie que le cooldown de la compétence est prêt et que la cible est dans `portee`
   (distance euclidienne serveur-side, jamais fait confiance au client) ; sinon **no-op
   silencieux** (pas d'erreur — juste ignoré, comme l'assignation à une zone déjà vaincue
   dans le spec sous-projet 1). Applique l'effet (dégâts/soin/bouclier/étourdissement/dot),
   pose le cooldown.
4. **IA des mobs** : un mob dont un joueur est entré dans `portee_aggro` cible le joueur le
   plus proche ; s'il est dans `portee_attaque` et que son cooldown est prêt, inflige
   `degats_attaque`. Pas de pathfinding (déplacement en ligne droite vers la cible s'il n'y
   est pas encore).
5. **Morts** : PV ≤ 0 → mob retiré de l'instance (événement `mob_tue` ; si c'était le boss,
   événement `boss_tue`) ou joueur passe en état `ko` (ne peut plus agir, reste visible,
   pas de perte de progression — pas de pénalité de mort dans ce spec).

## Sharding et cycle de vie d'une instance

- Rejoindre le combat d'une zone assigne le joueur à une instance ouverte de cette zone
  dont l'effectif est < `JEU_FACTIONS_INSTANCE_CAPACITE` (défaut 30) ; sinon une nouvelle
  instance est créée (nouveau `asyncio.Task`, nouveau boss/mobs frais depuis `mobs_zone`).
- Une instance vide (dernier joueur déconnecté) pendant `COMBAT_INSTANCE_GRACE_S` (défaut
  30 s) est fermée : `asyncio.Task` annulée, mémoire libérée.
- **Le boss tué marque `zones.etat = 'vaincue'` globalement la première fois seulement**
  (repris tel quel comme marqueur d'historique/tableau de bord — cf. spec sous-projet 1,
  "le score reste purement informatif, pas de possession exclusive"). Ça ne bloque **pas**
  les autres instances de cette zone, ni la même instance pour plus tard : le boss
  **respawn** après `COMBAT_BOSS_RESPAWN_S` (défaut 60 s) dans l'instance où il a été tué,
  pour permettre de rejouer/farmer — cohérent avec l'absence de possession exclusive déjà
  actée.

## Intégration avec l'existant

- `zones.resoudre_toutes_zones()` et son appel depuis `tick.py` sont **retirés** — les
  zones de signe ne sont plus résolues passivement. `tick.py` continue de résoudre les
  **groupes/archétypes** (hors scope ici, cf. Non-objectifs).
- `PATCH /personnages/{id}/zone` **change de sens** : ce n'était qu'une assignation
  persistante qui pilotait la résolution passive ; celle-ci disparaissant, la route est
  conservée mais devient purement cosmétique (« dernière zone visitée », affichée par
  défaut dans le front) — elle ne fait plus entrer en combat. Entrer en combat se fait
  uniquement en ouvrant la connexion WebSocket ci-dessous.
- `GET /zones` / `GET /zones/{id}` inchangées (liste, état, scores cumulés).

## API — WebSocket

```
WS /zones/{zone_id}/combat?personnage_id=<id>&api_key=<clé>
```

La clé passe en **query param**, pas en en-tête `X-API-Key` : le `WebSocket` natif du
navigateur ne permet pas de poser d'en-têtes personnalisés à la connexion (contrainte
implémentée dans tous les navigateurs, pas une limite FastAPI) — même motif déjà utilisé
par le Cœur pour transporter `PERSONNAGES_KEY`/`GEO_KEY` en `?api_key=` dans les iframes du
dashboard (`core/routers/dashboard.py`). Le personnage doit appartenir au compte
authentifié par cette clé (sinon fermeture immédiate de la connexion, code `4401` — pas de
401 HTTP classique possible une fois le WebSocket établi). À la connexion, le serveur
assigne l'instance (création si besoin) et renvoie un premier message `etat` complet.

**Serveur → client**, un message JSON par tick :
```json
{"type": "etat", "horodatage": "...", "joueurs": [...], "mobs": [...], "evenements": [...]}
```

**Client → serveur**, envoyé dès qu'une intention existe (pas nécessairement à chaque
tick) :
```json
{"type": "deplacement", "direction": {"x": 0.7, "y": -0.7}}
{"type": "sort", "competence_id": "...", "cible_id": "..."}
```

Déconnexion (fermeture WS, réseau coupé) → le joueur est retiré de l'instance au tick
suivant (pas de timeout séparé à gérer : la perte de la connexion WebSocket est le signal).

## Client (`front_combat.html`)

- Clé API lue avec le même motif que `front.html` (`localStorage.getItem('jeu_factions_cle')`),
  transmise en `?api_key=` dans l'URL de connexion WebSocket (cf. ci-dessus).
- Phaser 3 via CDN (`<script src="https://cdn.jsdelivr.net/npm/phaser@.../phaser.min.js">`),
  scène unique : arène vue du dessus, joueurs/mobs en formes géométriques colorées
  (couleur = élément du signe pour les joueurs).
- HUD minimal : barre de vie du joueur, barre de vie du boss si engagé, sorts débloqués
  (lus via `GET /personnages/{id}/competences`, filtrés sur `effet_type IS NOT NULL`) en
  barre de raccourcis avec cooldown visuel.
- Déplacement clavier (flèches/WASD) → envoie `deplacement` au serveur à chaque frame où la
  direction change. Clic sur un sort + clic sur une cible → envoie `sort`.

## Configuration (env)

| Variable | Défaut | Rôle |
|---|---|---|
| `COMBAT_TICK_HZ` | `10` | fréquence de la boucle de simulation par instance |
| `JEU_FACTIONS_INSTANCE_CAPACITE` | `30` | joueurs max par instance avant sharding |
| `COMBAT_INSTANCE_GRACE_S` | `30` | délai avant fermeture d'une instance vide |
| `COMBAT_BOSS_RESPAWN_S` | `60` | délai de réapparition du boss après sa mort |
| `COMBAT_ARENE_TAILLE` | `800` | taille (unités) du carré d'arène |

## Tests

- `combat_moteur.avancer_tick` (pure, sans WebSocket ni asyncio réel) : déplacement borné
  aux limites de l'arène, cooldown qui bloque un sort réutilisé trop tôt, sort hors portée
  = no-op silencieux, dégâts appliqués et mob tué à PV ≤ 0, plusieurs sorts au même tick
  résolus dans l'ordre de réception, IA mob qui n'attaque que dans sa portée d'aggro.
- Sharding : instance à capacité pleine → nouvelle instance créée ; instance vidée puis
  grâce écoulée → tâche fermée (mock du temps, pas de vrai `sleep` dans les tests).
- Migration `competences` : `ALTER TABLE` idempotent (rejouable sans erreur), compétence
  sans `effet_type` (seedée avant ce spec) reste lisible sans crasher le combat.
- Boss tué : `zones.etat` passe à `vaincue` la première fois seulement, `resolutions` et
  `scores_zone_guilde` mis à jour, boss respawn après `COMBAT_BOSS_RESPAWN_S` dans la même
  instance.
- WebSocket (via le `TestClient` de FastAPI, qui supporte les WS) : connexion avec
  `personnage_id` d'un autre compte → rejet ; connexion valide → premier message `etat`
  reçu ; déconnexion → joueur retiré de l'instance au tick suivant.

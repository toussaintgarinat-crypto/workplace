# Brique `jeu-factions` — progression idle (S216, sous-projet 3/5)

## Contexte

Le backlog [`S216-S220-jeu-factions-sous-projets-restants.md`](../../sprints/S216-S220-jeu-factions-sous-projets-restants.md)
pose la question ouverte : qu'est-ce qui progresse pendant l'absence du joueur ? Trois options
étaient posées (ressource au temps écoulé, file de missions, multiplicateur de progression
d'archétype). Décision : **multiplicateur de progression d'archétype pour les personnages non
engagés dans un combat actif, sur la voie déjà entamée** — option la plus proche du système
existant (`progression_archetype`), au prix d'une tension à border explicitement : « en combat
actif » est un état qui ne vit qu'en mémoire, dans `combat.py` (instances `asyncio` +
connexions WebSocket), jamais persisté.

Ce spec est le sous-projet 3/5. Réutilise les mécaniques déjà en place pour les voies
d'archétype (sous-projet 1 : `archetypes.py`, `groupes.py`, `tick.py`) — n'ajoute aucune
nouvelle boucle serveur, aucun changement à `combat_moteur.py`/`combat.py`.

## Non-objectifs

- **Pas de nouvelle monnaie/économie.** Un seul type de gain (bonus de progression
  d'archétype), pas de ressource dépensable séparée — cf. hors-périmètre déjà posé au
  backlog.
- **Pas de notifications.** Le bonus se lit au retour du joueur (chargement de
  `front.html`), comme le reste de la brique — pas de push/websocket dédié pour prévenir
  d'un gain.
- **Ne touche pas aux zones de signe.** Le bonus idle ne s'applique **qu'aux voies
  d'archétype** (`progression_archetype`). Les zones restent 100 % combat joué
  (sous-projet 2) — aucune notion d'idle n'y est introduite. C'est ce choix de périmètre,
  et non une vérification de l'état runtime de `combat.py`, qui garantit qu'un personnage
  en train de jouer une zone n'accumule pas aussi un bonus idle par ailleurs : les deux
  systèmes ne se recouvrent jamais.
- **Ne touche pas à `combat_moteur.py`/`combat.py`.** Aucune lecture de leur état en
  mémoire (instances, connexions) — non nécessaire vu le point précédent.
- **Pas de nouvelle boucle serveur.** Le calcul du bonus est une fonction pure, lue à la
  demande. Le tick existant (`tick.py::boucle_tick`, 24 h) continue de tourner à la même
  cadence qu'avant ce spec — il est *enrichi*, pas dupliqué.
- **Pas de détection fine de présence.** Un heartbeat simple (onglet ouvert), pas de
  distinction focus/blur, pas de multi-onglet à dédupliquer.

## Mécanique

**Présence.** Le front envoie `POST /presence` (authentifié `X-API-Key`, comme le reste de
la brique) toutes les 30 s tant que `front.html` est ouvert. Ça met à jour
`joueurs.derniere_presence` — la présence est une notion **par compte** (`cle_api`), pas par
personnage : un joueur avec plusieurs personnages est "présent" ou "absent" globalement,
il ne dirige pas activement un personnage en particulier en dehors du combat joué.

**Calcul du bonus (fonction pure, `archetypes.py`).**

```python
def bonus_idle(derniere_presence: str | None, maintenant: datetime, taux_par_heure: float,
                plafond_heures: float) -> int:
    ...
```

`derniere_presence=None` (jamais de heartbeat, ex. compte tout juste créé) → bonus `0`, pas
un plafond par défaut. Sinon : `points = taux_par_heure * min(heures_ecoulees, plafond_heures)`,
arrondi à l'entier inférieur. Plafonné à `plafond_heures = TICK_INTERVAL_HOURS` (réutilise la
constante déjà dans `tick.py` plutôt qu'un nouveau paramètre — le bonus ne peut jamais
dépasser "un cycle de tick d'absence", cohérent avec le point d'application ci-dessous).

**Où le bonus s'applique.** Aujourd'hui, `calculer_resolution` (fonction pure) somme les
stats de **tous** les membres du groupe (carries compris) pour comparer à `difficulte_pve` —
seule la marque `vaincue` est ensuite restreinte à ceux dont c'est la prochaine étape
(`groupes.py`, motif déjà en place). Le bonus idle représente la progression **personnelle**
d'un personnage sur sa propre voie pendant son absence — il ne doit donc jamais profiter à un
carry (un carry idle sur son propre compte n'aide pas la voie d'un autre). Pour ça,
`calculer_resolution` gagne un paramètre optionnel `bonus_par_membre: dict[str, int] | None`
(fonction toujours pure), ajouté à la somme d'un membre uniquement s'il y figure.
`groupes.resoudre_groupes_actifs()` (le tick existant, appelé par `boucle_tick`, cadence
**inchangée**) construit ce dict avec `{mid: bonus_idle(...)}` **uniquement** pour les membres
dont `A.prochaine_etape(mid, archetype) == zone_archetype_id` — jamais pour un carry. Le
bonus est calculé à la lecture, au moment du tick — il n'est jamais stocké comme un solde à
part : si le tick résout l'étape, elle passe `vaincue` comme avant ; sinon, le prochain tick
recalculera un nouveau bonus à partir de la présence à ce moment-là (pas d'accumulation
infinie entre deux ticks — cohérent avec le plafond à un cycle).

**Un joueur absent plusieurs jours** accumule un bonus à chaque passage du tick (24 h par
défaut), chacun plafonné à un cycle — pas un seul gros crédit borné à l'ouverture, plusieurs
crédits successifs pendant l'absence. Aucune boucle nouvelle : `boucle_tick` tournait déjà
avant ce spec pour résoudre les groupes, que le joueur soit présent ou non.

## Modèle de données

```sql
ALTER TABLE joueurs ADD COLUMN derniere_presence TEXT;
```

Migration idempotente (même motif que `_migrer_colonnes_effet_competences` dans
`stockage.py` : vérifiée via `PRAGMA table_info`, pas d'erreur si déjà présente). Nullable —
un joueur jamais vu en présence (créé directement en base, ou avant ce spec) a
`derniere_presence IS NULL`, traité comme "bonus nul" par `bonus_idle`, pas comme une
absence infinie.

Aucune nouvelle table : pas de file, pas de solde à part (cf. Mécanique — le bonus est
recalculé à chaque tick, jamais persisté entre deux résolutions).

## API

```
POST /presence
```
Authentifié `X-API-Key` (même motif que les autres routes de la brique). Body vide. Met à
jour `joueurs.derniere_presence` à l'instant de la requête pour le compte authentifié.
Réponse `{"ok": true}`.

```
GET /personnages
```
Inchangé dans son contrat existant, **enrichi** : chaque personnage dont la prochaine étape
d'archétype est connue gagne un champ `bonus_idle_actuel` (entier, calculé à la lecture via
`bonus_idle(...)` sur la présence du compte authentifié — même fonction que celle utilisée
par le tick, pas une deuxième formule). Purement informatif : ce nombre n'est *consommé* que
lors du prochain passage du tick, pas à cette lecture.

## Client (`front.html`)

- Heartbeat : `setInterval(() => fetch('/presence', {method: 'POST', headers: entetes()}), 30_000)`
  démarré au chargement de la page, tant que `cleApi` est renseignée.
- La liste "Mes personnages" affiche, pour un personnage engagé sur une voie (a une
  prochaine étape), la ligne existante enrichie : `+N vers la prochaine étape (voie
  d'archétype)` en plus du nom/zone déjà affichés — pas de nouvelle section, pas de
  `front_idle.html` séparé (contenu trop mince pour le justifier, contrairement à
  `front_combat.html` qui embarque Phaser).

## Configuration (env)

Aucune nouvelle variable : `taux_par_heure` (proposé : `2`) est une constante dans
`archetypes.py`, pas un env var — c'est un paramètre d'équilibrage produit, pas un réglage
d'infra (contrairement à `TICK_INTERVAL_HOURS`, réutilisé tel quel comme plafond). Ajustable
en dur si le retour terrain le demande, sans sur-anticiper un besoin de configuration externe.

## Tests

- `bonus_idle` (pure) : `derniere_presence=None` → `0` ; écart en dessous d'une heure → `0`
  (arrondi entier) ; écart au-delà de `plafond_heures` → plafonné, pas linéaire au-delà ;
  taux appliqué correctement pour un écart intermédiaire.
- `calculer_resolution` (pure) : sans `bonus_par_membre` (ou `None`), comportement identique
  à avant ce spec (non-régression) ; avec un bonus sur un membre absent de `membres_stats`,
  ignoré silencieusement ; avec un bonus sur un membre présent, ajouté à sa contribution
  avant sommation du total.
- `resoudre_groupes_actifs()` : un membre dont c'est la prochaine étape et dont le bonus
  idle comble l'écart à `difficulte_pve` fait passer l'étape `vaincue` alors que ses stats
  brutes seules ne suffisaient pas ; un membre « carry » (pas sa prochaine étape) ne
  reçoit jamais de bonus dans `bonus_par_membre` (même s'il compte dans la somme du groupe
  comme aujourd'hui).
- `POST /presence` : met à jour `derniere_presence` ; rejette une clé API invalide (401,
  même motif que les autres routes).
- `GET /personnages` : `bonus_idle_actuel` présent et cohérent avec `bonus_idle(...)` pour
  un personnage engagé ; absent ou `0` pour un personnage sans prochaine étape (toutes voies
  déjà vaincues) ou sans historique de présence.
- Migration `derniere_presence` : idempotente (rejouable sans erreur), colonne absente
  traitée comme `NULL` pour un joueur existant avant ce spec.

# S175 — Récurrence RRULE réellement expansée (brique agenda)

**Date** : 2026-07-16
**Statut** : design validé (brainstorm), prêt pour plan d'implémentation
**Roadmap** : `docs/sprints/S174-S180-roadmap-agenda-best-in-class.md` — S175 (ex-S172)
**Prédécesseur** : S174 rappels par personne (mergé `main` `9922f58`)

## 1. Problème

Le champ `Event.recurrence_rule` (`String(500)`, migration 0001) existe depuis le début
mais **rien ne l'exploite** : il est stocké tel quel, jamais expansé. Un événement
« tous les lundis » n'apparaît qu'une fois, à sa date de départ, dans le dashboard, dans
l'agrégation multi-calendriers (`services/agregation.evenements_agreges`) et dans le
briefing proactif du Cœur (`core/proactif._check_agenda`). C'est le principal manque
fonctionnel face à TimeTree / Google Agenda / Fantastical, tous centrés sur la récurrence.

Objectif du sprint : rendre la récurrence **vraie** — une règle RRULE se déplie en
occurrences visibles sur la fenêtre consultée, avec les gestes d'édition attendus d'un
agenda familial (modifier toute la série, sauter une occurrence, déplacer/renommer une
occurrence isolée).

## 2. Décisions de conception (validées au brainstorm 2026-07-16)

1. **Occurrences virtuelles au read-time** (pas de matérialisation en base). L'`Event`
   maître porte le `recurrence_rule` ; l'expansion se fait à la lecture avec
   `dateutil.rrule` sur la fenêtre `[debut, fin]` demandée. Standard Google/CalDAV : zéro
   duplication, la série se modifie d'un coup, pas de dérive.
2. **Exceptions livrées ce sprint** : série entière (créer/modifier/supprimer) + **EXDATE**
   (sauter une occurrence) + **override d'une occurrence** (déplacer/renommer juste
   celle-là). **Hors périmètre → fast-follow** : « celle-ci et les suivantes » (scission de
   série).
3. **Sous-ressources par série** : participants, rappels perso (S174), RSVP, chat,
   pièces jointes, journal d'activité restent portés par l'Event maître et valent pour
   toutes ses occurrences. Un override d'occurrence hérite des sous-ressources de son
   parent (il ne recopie rien).

## 3. Modèle de données

Migration **0007_recurrence** (SQLite dev/tests + Postgres prod, comme les précédentes).

### 3.1 Colonnes ajoutées sur `events`

| Colonne | Type | Sémantique |
|---|---|---|
| `exdates` | `JSON` NOT NULL default `[]` | Dates d'occurrences supprimées de la série (liste d'ISO-8601 UTC naïf, chacune = début d'une occurrence exclue). Ignoré si l'event n'est pas récurrent. |
| `recurrence_parent_id` | `String(36)` NULL, FK `events.id` ondelete CASCADE, index | Non-NULL ⇒ cet event est un **override d'occurrence** d'un maître. NULL ⇒ event normal ou maître. |
| `recurrence_date` | `DateTime` NULL | Pour un override : la date d'occurrence d'origine qu'il remplace (le RECURRENCE-ID). NULL pour un maître/non-récurrent. |

Contrainte unique `(recurrence_parent_id, recurrence_date)` : au plus un override par
occurrence. Supprimer le maître supprime ses overrides (CASCADE) et ses sous-ressources
(déjà CASCADE).

### 3.2 Invariants

- Un **maître récurrent** : `recurrence_rule` non-NULL, `recurrence_parent_id` NULL.
- Un **override** : `recurrence_parent_id` non-NULL, `recurrence_date` non-NULL,
  `recurrence_rule` toujours NULL (un override ne se re-répète pas).
- Un override est **toujours filtré hors des requêtes de liste directes** (il n'a pas de vie
  propre dans le calendrier) : il n'apparaît que réinjecté par l'expansion à la place de
  l'occurrence qu'il remplace. Voir §5.

## 4. `services/recurrence.py` — validation + expansion

Nouveau module, seule brique qui connaît `dateutil.rrule`. Interface étroite :

```python
def valider_rrule(rule: str) -> str
    # Parse via icalendar/dateutil, rejette FREQ absent, SECONDLY/MINUTELY/HOURLY
    # (bruit pour un agenda humain) et RRULE non bornée + COUNT > MAX. Renvoie la
    # règle normalisée (sans préfixe "RRULE:"). Lève ValueError → 422 côté API.

def expanser(maitre: Event, debut: datetime, fin: datetime,
             exdates: list[datetime], overrides: dict[datetime, Event]) -> list[Occurrence]
    # Déplie le maître sur [debut, fin]. Pour chaque date produite par la règle :
    #   - si dans exdates → sautée
    #   - si dans overrides → on émet l'override (déjà un Event à part entière)
    #   - sinon → occurrence virtuelle clonant le maître, décalée à cette date
    #     (end_at = start_at + durée du maître), avec identité d'occurrence.
```

**Bornage de sécurité** : `MAX_OCCURRENCES` (ex. 366) par fenêtre pour ne jamais expanser
une série infinie sans borne haute. La fenêtre `[debut, fin]` la limite déjà en pratique ;
le cap protège l'appel sans `fin` (rare).

**Identité d'occurrence** (critique — cf. §6 proactif) : chaque occurrence virtuelle expose
- `id` = `id` du maître (inchangé, pour éditer la série / cibler les sous-ressources) ;
- `occurrence_start` = date de début de CETTE occurrence (ISO). C'est la clé qui distingue
  deux occurrences d'un même maître. Un override porte son propre `id` réel **et**
  `occurrence_start` = sa `recurrence_date` (pour que le front sache quelle case il remplace).

Un event non récurrent traverse `expanser` en se renvoyant lui-même avec
`occurrence_start = start_at` — chemin unifié, pas de branche spéciale chez l'appelant.

## 5. Points de lecture câblés

Trois chemins lisent des events ; tous passent désormais par l'expansion, **en excluant les
overrides des requêtes directes** (`recurrence_parent_id IS NULL`) puis en les réinjectant
via `expanser`.

1. **`services/agregation.evenements_agreges`** (surface `/service`, consommée par le
   dashboard **et** le proactif du Cœur via `agenda.lister_evenements`). Pour chaque
   calendrier : charger les maîtres, charger d'un coup les overrides des maîtres de la
   fenêtre (une requête `recurrence_parent_id IN (...)`), appeler `expanser`. L'enrichissement
   existant (calendrier / étiquette / couleur / participants+rappels S174) s'applique à
   chaque occurrence. **Attention N+1** : la dette S174 (participants requêtés par event)
   est aggravée par l'expansion → on charge participants/labels par lot avant la boucle.
2. **`routers/events.list_events`** (`GET /calendars/{cal_id}/events`, appli web front).
   Même logique, un seul calendrier.
3. Les lectures unitaires (`GET /events/{id}`) renvoient le **maître** tel quel (règle
   comprise) — pas d'expansion, c'est l'objet d'édition.

## 6. Proactif du Cœur (`core/proactif._check_agenda`)

`_check_agenda` itère déjà `agenda.lister_evenements` → il verra automatiquement les
occurrences une fois §5.1 câblé. **Un seul changement obligatoire** : la clé de
dédoublonnage `cle = f"agenda:{id}:{uid}:{m}"` doit incorporer l'occurrence, sinon deux
occurrences du même maître se dédupliquent entre elles et une seule notifie. Nouvelle clé :
`f"agenda:{id}:{occurrence_start}:{uid}:{m}"`. `_rappels_dus` calcule déjà le décalage à
partir de `start_at` de l'objet reçu — comme chaque occurrence expose son propre `start_at`,
le calcul « minutes avant début » est correct occurrence par occurrence sans autre
changement. (Le fichier consomme le champ `start_at` déjà présent ; `occurrence_start` sert
uniquement à la clé de dédup.)

## 7. API d'édition — portée (scope)

L'édition/suppression d'un event récurrent prend un paramètre de **portée**. On l'ajoute aux
endpoints d'écriture qui existent déjà (`PATCH`/`DELETE` sur `routers/events.py` et sur la
surface `/service`), en query `?scope=`, défaut `all` (rétro-compat : un event non récurrent
ignore le paramètre).

| scope | PATCH | DELETE |
|---|---|---|
| `all` (défaut) | modifie le maître → toute la série suit | supprime maître + overrides + sous-ressources |
| `this` | crée/rebranche un **override** pour l'occurrence ciblée (déplacer/renommer celle-là) | ajoute la date à `exdates` (sauter l'occurrence) |

`scope=this` exige d'identifier l'occurrence : query `?occurrence=<ISO start>`. Si l'ISO ne
correspond à aucune occurrence produite par la règle → 422. Créer un override sur une
occurrence déjà exclue par `exdates` → 422 (incohérent). Modifier un override existant
(re-PATCH `this` sur la même date) met à jour l'override en place (contrainte unique).

**Hors périmètre** : `scope=this_and_following` (scission). Renverra 422 « non supporté » ce
sprint, documenté comme fast-follow.

## 8. Front — appli web agenda (`templates_app.py` / `routers/app_web.py`)

Aucune UI de récurrence aujourd'hui. Ajouts :

1. **Éditeur de récurrence** dans la modale event : sélecteur « Ne se répète pas / Chaque
   jour / Chaque semaine / Chaque mois / Chaque année » + intervalle (« tous les N ») +
   pour l'hebdo, cases des jours (L M M J V S D) + fin de récurrence (« jamais / le
   {date} / après N occurrences »). Le front compose la string RRULE ; le back la valide
   (§4). On couvre FREQ DAILY/WEEKLY/MONTHLY/YEARLY + INTERVAL + BYDAY + UNTIL/COUNT —
   suffisant pour la parité familiale, pas de BYSETPOS/BYMONTHDAY exotiques ce sprint.
2. **Badge « ↻ » ** sur les occurrences d'une série dans la grille (repère visuel TimeTree).
3. **Dialogue de portée** à l'édition/suppression d'une occurrence : « Cet événement / Toute
   la série » (le « et les suivants » sera ajouté au fast-follow). Mappe sur `scope`.

Le front reste en templates Python server-rendered (pas de framework JS) comme l'existant.

## 9. Assistant / surface `/service` (LLM)

- `POST /service/events` accepte déjà les champs français ; on ajoute `recurrence` optionnel
  (string RRULE ou une forme simplifiée « chaque semaine le lundi » que l'outil LLM traduit).
  Décision : l'outil LLM passe une **RRULE** directement (le prompt de l'assistant sait la
  composer) — pas de mini-DSL à maintenir côté brique. Validation identique (§4).
- `PATCH`/`DELETE /service/events/{id}` acceptent `scope` + `occurrence` comme §7, pour que
  l'assistant puisse dire « décale la réu de ce lundi » (→ `scope=this`) vs « supprime la
  réu hebdo » (→ `scope=all`).

## 10. Découpage TDD proposé (détaillé dans le plan)

1. `services/recurrence.py` : `valider_rrule` (tests des cas rejetés/normalisés).
2. `services/recurrence.py` : `expanser` — non-récurrent, DAILY/WEEKLY/MONTHLY/YEARLY,
   INTERVAL, BYDAY, UNTIL/COUNT, EXDATE, override, cap, fenêtre.
3. Migration 0007 + colonnes ORM + schémas (`EventOut.occurrence_start`, `exdates`).
4. Câblage lecture : `evenements_agreges` (+ correctif lot participants/labels) et
   `list_events`.
5. API portée : `PATCH`/`DELETE` `?scope=&occurrence=` sur `events.py` et `/service`.
6. Proactif : clé de dédup par occurrence (+ test occurrences multiples).
7. Front : éditeur de récurrence + badge ↻ + dialogue de portée.
8. Surface `/service` : `recurrence` en création, `scope` en édition (outils LLM).
9. README brique + roadmap : S175 code-complet.

## 11. Tests & non-régression

- Suites cibles : agenda **152/152** (S174) + les nouveaux tests recurrence ; cœur
  **438/438** (le seul changement Cœur = clé de dédup, test dédié).
- Cas limites explicitement testés : série sans `fin` (cap), EXDATE sur une date hors règle
  (no-op), override puis EXDATE de la même date (422), event non récurrent inchangé,
  occurrence à cheval sur la borne de fenêtre, all-day récurrent.

## 12. Hors périmètre (fast-follow / sprints ultérieurs)

- `scope=this_and_following` (scission de série).
- RRULE exotiques (BYSETPOS, BYMONTHDAY multiples, BYWEEKNO).
- Fuseaux par event (l'agenda est Europe/Paris, cf. `services/horaires`).
- La dette S174 non-récurrence listée dans le roadmap (gating sous-ressources pré-S174,
  backfill one-shot…) reste hors de ce sprint sauf le N+1 participants aggravé par
  l'expansion, traité ici par nécessité (§5.1).

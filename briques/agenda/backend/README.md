# Brique Agenda — Calendrier multi-personne

Service calendrier, dual-mode :
1. **S2S (assistant)** — dialecte privé à clé `AGENDA_KEY`, pinné sur l'utilisateur `"perso"`.
2. **Web app autonome** (`/app`) — application servie à `http://localhost:8400/app` (S172+), login PKCE contre `calendar-app` (client Keycloak indépendant du Cœur), permettant à d'autres personnes (ex. Marina) d'accéder à des calendriers partagés sans jamais accéder au rest du Cœur.

## Configuration pour l'appli `/app`

Pour que l'appli web autonome fonctionne réellement (et non pas afficher une liste vide), définir à la **première mise en route** (dans le `.env` ou la docker-compose) :

```bash
AUTH_ENABLED=true
KEYCLOAK_AUDIENCE=calendar-app
KEYCLOAK_URL=http://localhost:8080        # (ou votre URL réelle)
KEYCLOAK_REALM=forge
```

Defaults : `AUTH_ENABLED=false` ; `KEYCLOAK_AUDIENCE=""` (désactive la vérification d'audience — définir explicitement pour renforcer l'isolation).

## Script one-off : `lier_compte_perso.py`

Avant que l'utilisateur principal puisse voir ses calendriers dans `/app`, lancer une fois (après sa première connexion à `/app`) :

```bash
cd briques/agenda/backend
python3 lier_compte_perso.py <sub-keycloak>
```

Le `<sub-keycloak>` s'obtient après une première connexion à `/app` → copier le `sub` du payload décodé du JWT (ex. jwt.io).

**Ce que fait le script** : ajoute une ligne `CalendarMember(role="owner")` sur chaque calendrier actuellement épinglé `"perso"` (posé par le dialecte S2S). Sans cela, la table `Calendar` reste propriété du pseudo-utilisateur `"perso"`, et le vrai compte Keycloak n'y accède pas.

**Idempotent** : peut être relancé plusieurs fois sans dupliquer les lignes.

## Deux chemins S2S distincts depuis le Cœur (S173)

1. **Outils câblés de l'assistant** (`core/agenda.py`, ex. `agenda_creer_evenement`) — envoie
   `X-User-Id` (identité réelle posée par `contexte_tenant`, S121/S173 : sub Keycloak si
   connu — web via la session S171, Telegram via `briques/connexion` déjà câblé — sinon
   `"perso"`), et `Authorization: Bearer {CALENDAR_SERVICE_TOKEN}` si ce dernier est
   configuré. **C'est ce chemin que S173 rend « par utilisateur réel ».**
2. **Capacités dynamiques par manifest** (S168, `core/outils_communs.py::_entetes_brique`)
   — 8 capacités agenda découvertes automatiquement, envoie `X-API-Key: {AGENDA_KEY}` +
   `X-Compte-Id: {ADMIN_COMPTE_ID}` (défaut `"admin"`). **Reste pinné**, hors périmètre de
   S173 (ADR `docs/decisions/2026-07-13-surface-de-service-role-admin.md`, sert toutes les
   briques pilotables par manifest, pas seulement l'agenda).

⚠️ **Risque croisé à surveiller à l'activation LIVE** : une fois `AUTH_ENABLED=true` posé
(prérequis de la section précédente, pour que `/app` authentifie réellement), le chemin 1
(`X-User-Id` seul, sans `X-API-Key`) exigera un token — si `CALENDAR_SERVICE_TOKEN` n'est
**pas aussi** configuré à ce moment-là, les appels agenda de l'assistant/Telegram
échoueront en 401. Poser les trois variables ensemble (`AUTH_ENABLED`,
`KEYCLOAK_AUDIENCE`, `CALENDAR_SERVICE_TOKEN`) au même moment, à la vérification LIVE
finale (fin de S180).

## Routes principales

- `GET /calendars` — liste les calendriers accessibles (owner + partagés)
- `POST /calendars` — créer un calendrier
- `GET/PATCH/DELETE /calendars/{id}` — consulter/modifier/supprimer
- `GET /calendars/{id}/events`, `POST /calendars/{id}/events` — CRUD événements
- `GET /calendars/{id}/labels`, `POST /calendars/{id}/labels` — CRUD étiquettes
- `POST /calendars/{id}/invitations` — créer une invitation de partage
- `GET /invitations/{token}/page` — page d'acceptation (standalone)
- `POST /invitations/{token}/accept` — accepter l'invitation, devenir membre
- `GET /app` — page HTML/JS de l'appli autonome (vanilla, PKCE, localStorage refresh_token)

## S174 — Rappels par personne

Un événement a un défaut de rappels (`Event.rappels`, minutes avant le début), mais
chaque participant peut avoir SON propre réglage. C'est `EventParticipant.rappels`
(colonne JSON nullable) qui porte ce override, à trois états :

- **`NULL`** — hérite du défaut de l'événement (`Event.rappels`). État initial d'un
  participant fraîchement ajouté.
- **`[]`** — aucun rappel, choix explicite (« ne me préviens pas pour celui-là »).
- **`[m, …]`** — override personnel (liste de minutes avant le début, propre à cette
  personne).

`services/rappels.py::rappels_effectifs(participant_rappels, event_rappels)` résout ces
trois états en la liste réellement due — `participant_rappels` s'il n'est pas `None`,
sinon `event_rappels`. C'est cette valeur résolue (`rappels_effectifs`) qui apparaît
dans `participants[].rappels_effectifs` de `/service/events` (`services/agregation.py`),
consommée par le proactif du Cœur.

**Participants**

- Le créateur d'un événement est **auto-ajouté comme participant** (`status="accepted"`)
  à la création, quel que soit le chemin d'écriture (`POST /calendars/{id}/events` ou
  `/service/events`) — voir `services/participants_auto.py::assurer_participant`
  (idempotent, sans commit propre, composé dans la transaction de création).
- `POST /events/{id}/participants/all` invite d'un coup **tous les membres du
  calendrier** de l'événement comme participants `status="pending"` (rappels hérités,
  `rappels=NULL`) — idempotent, n'ajoute que les manquants.
- Le réglage personnel des rappels se pose via
  `PATCH /events/{id}/participants/{user_id}` avec un champ `rappels` (présent, même
  `[]`, = réglage explicite ; absent du corps = inchangé). Le même endpoint accepte aussi
  `status` pour le RSVP (accepted/declined/maybe), qui journalise une entrée `rsvp`.

**Profils affichables (`UserProfile`)**

Table `user_profiles` (clé primaire `user_id` = sub Keycloak ou `"perso"`) qui résout un
identifiant technique en nom lisible + couleur de pastille, sans aucun appel réseau au
runtime :

- `POST /profiles/me` sème/rafraîchit le profil de l'appelant à partir des claims de SON
  propre token (`name` > `preferred_username` > `sub`). Appelé par l'appli `/app` juste
  après le login.
- `GET /profiles?user_ids=…` (CSV) résout une liste d'identifiants en
  `{user_id, display_name, avatar_color}` — avec des défauts honnêtes pour les inconnus
  (« Toi » pour le propriétaire local `AGENDA_USER_ID`, sinon l'id brut ; couleur dérivée
  d'un hash stable de l'id sur une palette commune au front).

**Journal d'activité (`event_activity_log`)**

Table `event_activity_log` (FK `event_id` en CASCADE) qui journalise qui a fait quoi sur
un événement, avec `user_nom` **snapshoté** au moment de l'action (robuste si le profil
change ou disparaît ensuite). `GET /events/{id}/activity` expose le fil, le plus récent
en premier (`services/journal.py::consigner`, actions : `event_created`, `event_updated`,
`rsvp`, `comment`…).

⚠️ **La suppression d'un événement n'est PAS journalisée** (pas d'entrée
`event_deleted`) : le fil est *par événement*, et la suppression retire l'événement (donc
son propre fil, par CASCADE) en même temps — il n'y a nulle part où afficher une entrée
« supprimé » une fois l'événement parti.

**Rappels poussés par le Cœur — pastille 🔔 vs canaux liés**

Le proactif du Cœur (`core/proactif.py::_check_agenda`) lève un rappel **par
participant** dû (dédoublonné par `(événement, personne, minutes)`), pas seulement pour
le propriétaire local :

- Le propriétaire local (`agenda.USER_ID`, alias `"perso"`) est le seul à recevoir la
  **pastille 🔔** visible (mémoire proactive locale, `_ajouter`).
- Pour les autres participants, le rappel part uniquement via
  `_pousser_messagerie(registre, titre, corps, utilisateur=uid)`, qui appelle
  `POST /pousser` sur la brique connexion. C'est **la brique connexion qui résout** les
  canaux liés de cette personne (`correspondance.cibles_pour`) et envoie sur chacun
  d'eux. Repli honnête : si la personne n'a **aucun** canal lié/configuré, la réponse est
  `envoyes: 0` (pas une erreur) — le rappel n'est simplement poussé nulle part, sans
  jamais planter le proactif.

## S175 — Récurrence (RRULE)

Un événement porte une règle de récurrence iCalendar dans `Event.recurrence_rule`
(ex. `FREQ=WEEKLY;BYDAY=MO`, `FREQ=DAILY;INTERVAL=2`). La règle est **expansée à la
lecture** (occurrences virtuelles, jamais matérialisées en base) — modèle standard
Google/CalDAV : la série se modifie d'un coup, aucune duplication, pas de dérive.

**Expansion (`services/recurrence.py`, pur + `services/occurrences.py`, orchestration).**
`valider_rrule` normalise/valide la règle à la création/modification (rejette une FREQ
absente ou trop fine — `SECONDLY`/`MINUTELY`/`HOURLY`). `expanser(maitre, debut, fin,
exdates, overrides)` déplie le maître sur la fenêtre demandée (`dateutil.rrule`), borné
par `MAX_OCCURRENCES=366` pour une série sans fin. Chaque occurrence porte son propre
`start_at` **et** un `occurrence_start` (le RECURRENCE-ID) qui l'identifie. Les trois
chemins de lecture passent par là : `GET /calendars/{id}/events`, l'agrégation
`/service/events` (dashboard + briefing) et — indirectement — le proactif du Cœur.

**Exceptions.** Deux mécanismes, portés par le maître :

- **EXDATE** (`Event.exdates`, liste JSON d'ISO) : occurrences sautées.
- **Override** (`Event.recurrence_parent_id` + `recurrence_date`) : un event-exception qui
  remplace UNE occurrence (déplacée/renommée). Contrainte unique
  `(recurrence_parent_id, recurrence_date)` = au plus un override par occurrence ; il
  n'est jamais listé directement, seulement réinjecté par l'expansion. Un EXDATE sur une
  occurrence déjà « override » supprime aussi l'override (pas de ligne morte).

**Portée d'édition.** `PATCH`/`DELETE` sur `/events/{id}` et `/service/events/{id}`
acceptent `?scope=all|this` (+ `?occurrence=<ISO>` pour `this`) :

| scope | PATCH | DELETE |
|-------|-------|--------|
| `all` (défaut) | modifie le maître → toute la série | supprime maître + overrides (CASCADE) |
| `this` | crée/maj un override de l'occurrence | ajoute la date aux `exdates` |

`scope` hors `{all, this}` → **422** (une faute de frappe ne retombe jamais sur « toute la
série »). L'`occurrence` est un identifiant *aware* (renvoyé par l'API en Europe/Paris) :
recoercé en naïf UTC seulement s'il est aware (`services/occurrences.occurrence_naive`),
pour ne pas décaler l'identité d'une occurrence au changement d'heure été/hiver.

**Sous-ressources par série.** Participants, rappels perso (S174), RSVP, chat, journal
d'activité restent portés par le maître et valent pour toutes ses occurrences (un fil par
série, comme TimeTree). Un override hérite des sous-ressources de son parent.

**Proactif.** La clé de dédoublonnage inclut désormais l'occurrence
(`agenda:{id}:{occurrence_start}:{personne}:{minutes}`) — sinon deux occurrences d'une
même série se dédoubleraient entre elles et une seule notifierait.

**Front (`/app`).** Sélecteur de répétition (`#ev-recurrence` :
jamais/jour/semaine/mois/année), badge ↻ sur les occurrences récurrentes, et un dialogue
de portée « Cet événement / Toute la série » à l'enregistrement/suppression. L'identité de
l'occurrence cliquée est tracée via `data-occ` (les occurrences virtuelles partagent l'id
du maître) pour cibler la bonne occurrence.

**Hors périmètre (fast-follow)** : `scope=this_and_following` (scission de série) ;
RRULE exotiques (`BYSETPOS`, `BYMONTHDAY` multiples, `BYWEEKNO`) ; fuseau par événement.

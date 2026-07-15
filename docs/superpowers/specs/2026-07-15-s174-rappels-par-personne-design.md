# S174 — Rappels par personne + présence/chat exposés + journal d'activité — Design

Premier sprint du roadmap agenda « best-in-class »
(`docs/sprints/S174-S180-roadmap-agenda-best-in-class.md`), lancé après l'épopée
identité multi-utilisateur du Cœur (S171→S173, mergée dans `main`). But : corriger le
point le plus critiqué de TimeTree — `Event.rappels` est un champ **unique partagé** par
tous les participants — en le rendant réglable **par personne**, et exposer au dashboard
la présence et le chat qui existent déjà en base mais n'ont jamais eu d'UI.

**Régime de preuve** : LIVE différé à la fin de S180 (décision utilisateur 2026-07-15).
Ce sprint est code + tests natifs + revue + commit ; aucune vérification Docker/navigateur
réel. Voir la liste LIVE à reprendre dans l'épopée identité.

## Constat de départ (vérifié au lancement, 2026-07-15)

- `briques/agenda/backend/models/orm.py` : `Event.rappels: list[int]` (JSON, non-null,
  défaut `[]`) — un seul jeu de « minutes avant » partagé. `EventParticipant`
  (pending/accepted/declined/maybe) et `EventComment` (chat par event) existent mais
  n'ont **aucune UI confirmée** et `EventComment` n'est exposé nulle part au dashboard.
- **Un événement est créé sans aucun participant** : `routers/events.py` ne pose aucune
  ligne `EventParticipant` ; celles-ci ne naissent que via `POST
  /events/{id}/participants`. Seul `Event.created_by` (chaîne) identifie l'auteur.
- `EventParticipant.user_id` / `EventComment.user_id` sont des chaînes brutes (sub
  Keycloak après S171→S173, ou `perso`) : **aucune table de profils** pour résoudre un
  nom affichable.
- Côté Cœur, `core/proactif.py::_check_agenda` boucle sur les events et pousse **un seul**
  rappel, câblé en dur sur `agenda.USER_ID = "perso"` (`core/agenda.py:19`). Le push
  messagerie passe par `core/proactif.py::_pousser_messagerie` → `POST /pousser` de la
  brique connexion.
- **Déjà résolu, ne pas reconstruire** : `briques/connexion/main.py::pousser` prend un
  `utilisateur` et route via `correspondance.cibles_pour(utilisateur)` vers **tous** les
  canaux liés de cette personne (Telegram, etc.), avec repli honnête (`envoyes: 0` si
  aucun canal). Le « canal de notif par personne » n'a donc **rien à coder** : seul le
  Cœur, pinné sur `perso`, doit apprendre à pousser par participant.

## Décisions de design (validées avec l'utilisateur 2026-07-15)

1. **Destinataires = hybride.** Le rappel personnel vit sur `EventParticipant` ;
   `created_by` devient participant automatiquement à la création ; un bouton « inviter
   tous les membres » ajoute d'un tap tous les `CalendarMember` du calendrier.
2. **Noms affichés = table `UserProfile` locale** (dans la brique agenda), semée au login
   PKCE `calendar-app` depuis les claims du token Keycloak. Résolution locale, zéro appel
   réseau au runtime, robuste hors-ligne. C'est la « notion de personne » que le roadmap
   cherchait.
3. **Journal d'activité = table + écriture + fil par event.** On crée la table, on l'écrit
   sur les actions S174 (create/update/delete event, RSVP, commentaire) et on l'expose en
   fil d'activité par événement dans le dashboard.
4. **`Event.rappels` conservé** comme « défaut de l'événement » (pas supprimé) pour la
   rétro-compatibilité. Le backfill crée un participant `created_by` pour les events
   existants.

## 1. Modèle de données (brique agenda) — migration Alembic `0006`

### a) `EventParticipant.rappels` — override personnel
Nouvelle colonne `rappels: list[int] | None` (JSON, **nullable**), sémantique à trois
états :
- `null` → **hérite** de `Event.rappels` (le défaut de l'événement).
- `[]` → **aucun** rappel (choix explicite, distinct de « hérite »).
- `[60, 1440]` → override personnel (minutes avant le début).

`Event.rappels` **reste** tel quel (non-null, défaut `[]`) et joue le rôle de défaut de
l'événement.

**Résolution des rappels effectifs** d'un participant :
```
rappels_effectifs(participant, event) =
    participant.rappels  if participant.rappels is not None
    else event.rappels
```

### b) `UserProfile` — nouvelle table
| colonne        | type            | notes                                            |
|----------------|-----------------|--------------------------------------------------|
| `user_id`      | String(255) PK  | sub Keycloak, ou `perso`                         |
| `display_name` | String(255)     | ex. « Marina », « Toi »                          |
| `avatar_color` | String(20)      | pastille couleur, défaut assigné déterministe    |
| `updated_at`   | DateTime        | `onupdate=func.now()`                            |

Alimentée par upsert au login PKCE (`routers/app_web.py`, après échange du code) depuis
`name` ou, à défaut, `preferred_username` du token. `perso` semé à « Toi » au premier
besoin. `avatar_color` : si absent des claims, dérivé d'un hash stable de `user_id` sur
une petite palette (mêmes couleurs que les calendriers).

### c) `event_activity_log` — nouvelle table
| colonne      | type           | notes                                                   |
|--------------|----------------|---------------------------------------------------------|
| `id`         | String(36) PK  | uuid                                                     |
| `event_id`   | FK events CASCADE | supprimer l'event purge son journal                  |
| `user_id`    | String(255)    | auteur de l'action                                      |
| `user_nom`   | String(255)    | **snapshot** du nom au moment de l'action (robuste)     |
| `action`     | String(30)     | `event_created`/`event_updated`/`event_deleted`/`rsvp`/`comment` |
| `details`    | JSON nullable  | payload libre (ex. `{"champ": "start_at", "avant": …}`) |
| `created_at` | DateTime       | `server_default=func.now()`                             |

Gabarit repris de `AuditLogs` de Forge
(`briques/forge/forge/core/app/models/generated.py:288`).

### d) Backfill (dans la migration `0006`)
Pour chaque `Event` existant **sans** aucun `EventParticipant`, créer une ligne
`EventParticipant(event_id, user_id=event.created_by, status="accepted", rappels=null)`.
Résultat : le modèle « destinataire = participant » devient uniforme, et le comportement
legacy (`event.rappels` poussé à `perso`) est strictement préservé (le participant hérite
du défaut de l'event). Aucune ligne `UserProfile` ni `event_activity_log` n'est backfillée.

## 2. Recipients hybrides (routers agenda)

- **Auto-participant** : `POST /calendars/{id}/events` crée, dans la même transaction que
  l'event, `EventParticipant(user_id=created_by, status="accepted")`. Écrit aussi une
  entrée `event_created` au journal.
- **Inviter tous les membres** : nouveau `POST /events/{id}/participants/all` → pour chaque
  `CalendarMember` du calendrier de l'event pas déjà participant, crée
  `EventParticipant(user_id, status="pending", rappels=null)`. Idempotent (ignore les
  doublons). Renvoie la liste des participants.
- **Réglage rappel perso** : `PATCH /events/{id}/participants/{user_id}` accepte désormais
  un champ optionnel `rappels: list[int] | None` (en plus de `status`). Met à jour la
  colonne ; `null` explicite = revenir à l'héritage.

## 3. Cœur — rappels par personne

### `core/agenda.py`
Le GET `/service/events` de la brique renvoie déjà des events enrichis. On l'**étend**
pour inclure, par event, `participants: [{user_id, status, rappels_effectifs}]` où
`rappels_effectifs` applique la résolution ci-dessus. `core/agenda.py::lister_evenements`
transmet ce champ tel quel (aucune logique métier ajoutée côté client).

### `core/proactif.py`
- `_check_agenda` boucle désormais sur `event["participants"]` (repli : si un event legacy
  arrivait sans participants, retomber sur `{created_by ou perso}` avec `event.rappels`).
  Pour chaque participant et chaque minute due
  (`_rappels_dus` réutilisé sur `rappels_effectifs`) :
  - **push messagerie** : `_pousser_messagerie(registre, titre, corps, utilisateur=<participant.user_id>)`.
  - **badge 🔔 dashboard** : uniquement si `participant.user_id == agenda.USER_ID`
    (`perso`) — les autres personnes ne consultent pas le dashboard du Cœur ; leur canal
    est la messagerie.
  - **dédup** : clé `agenda:{event_id}:{user_id}:{minutes}` (dimension participant ajoutée).
- `_pousser_messagerie` prend un paramètre `utilisateur` (défaut `agenda.USER_ID` pour
  rétro-compat) et le passe à `{"utilisateur": utilisateur, "texte": …}` du `/pousser`.
  Le reste (résolution des canaux) est déjà géré par la brique connexion.

## 4. Dashboard agenda (`templates_app.py` / `routers/app_web.py`)

Tout se greffe sur l'appli autonome `/app` livrée en S172 (port 8400, login PKCE
`calendar-app`). Dans la **modale d'événement**, quatre blocs, tous alimentés par les noms
et pastilles de `UserProfile` :

- **Présence** : liste des participants + statut (✓ accepté / ✗ refusé / ? peut-être /
  ⏳ en attente), pastille couleur, bouton RSVP pour soi-même, bouton « inviter tous les
  membres ».
- **Rappels par personne** : chaque participant voit/règle **son** rappel (hérite du défaut
  de l'event / aucun / minutes personnalisées). L'utilisateur courant peut éditer sa
  propre ligne.
- **Chat** (`EventComment`) : fil des messages + champ d'envoi. Rafraîchi en temps réel via
  le **SSE déjà présent** dans la brique. Ajout seul en S174 (pas d'édition/suppression).
- **Fil d'activité** : `GET /events/{id}/activity` (nouveau, lecture) affiché sous le chat,
  liste antéchronologique lisible (« Marina a accepté — il y a 2h »).

Endpoints de lecture nouveaux consommés par l'UI : `GET /events/{id}/activity`, et un moyen
de résoudre les profils (soit `GET /profiles?user_ids=…`, soit profils inclus dans les
réponses participants/comments — tranché au plan). Écriture du journal branchée sur les
routers `events` (create/update/delete), `participants` (rsvp) et `comments` (comment).

## 5. Découpage en unités (pour le plan)

1. **Modèle + migration `0006`** (colonnes, tables, backfill) + tests de migration.
2. **UserProfile** : modèle, upsert au login, endpoint(s) de résolution, seed `perso`.
3. **Recipients hybrides** : auto-participant à la création, `participants/all`, `rappels`
   sur le PATCH participant.
4. **Journal d'activité** : écriture sur events/participants/comments, `GET .../activity`.
5. **`/service/events` enrichi** (participants + rappels_effectifs).
6. **Cœur** : `_check_agenda` multi-participants, `_pousser_messagerie(utilisateur=…)`,
   dédup par participant, badge 🔔 réservé `perso`.
7. **Dashboard** : présence, rappels perso, chat, fil d'activité.

## 6. Tests (natifs, TDD)

**Brique agenda** — migration + backfill (event legacy → 1 participant accepted, rappels
hérités) ; résolution `rappels_effectifs` (null→hérite, []→aucun, liste→override) ;
auto-participant à la création ; `participants/all` idempotent ; PATCH `rappels` ;
UserProfile upsert au login + seed `perso` ; écriture du journal sur chaque action + `GET
.../activity` ; `/service/events` porte bien `participants`/`rappels_effectifs`.

**Cœur** — `_check_agenda` pousse un rappel par participant dû ; dédup
`{event}:{user}:{minutes}` ; badge 🔔 seulement pour `perso` ; `_pousser_messagerie`
transmet le bon `utilisateur` ; repli event legacy sans participants.

Cibles : suite core et suite agenda toutes vertes (comme S172/S173 : 432/432 core,
109/109 agenda + nouveaux tests).

## 7. Hors périmètre

- Récurrence RRULE (S175), PWA / push web (S178), digest (S178).
- Édition/suppression de commentaires (chat = ajout seul).
- Journal d'activité **global** (le fil est par event ; les rows suivent le CASCADE de
  l'event supprimé — assumé pour S174).
- Résolution de nom via l'admin API Keycloak au runtime (écartée au profit de la table
  locale).
- Restaurant et chemin manifest `ADMIN_COMPTE_ID` (ADR agenda-surface-de-service, hors
  sujet).

## Références

- Roadmap : `docs/sprints/S174-S180-roadmap-agenda-best-in-class.md`
- Épopée identité (préalable) :
  `docs/sprints/S171-S173-epopee-identite-multiutilisateur-coeur.md`
- ADR surface de service agenda :
  `docs/decisions/2026-07-14-agenda-surface-de-service.md`
- Gabarit journal : `briques/forge/forge/core/app/models/generated.py:288` (`AuditLogs`)

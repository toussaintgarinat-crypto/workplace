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

## S176 — Listes de courses/tâches partagées + cartes de fidélité

Sous-système **autonome** façon Bring! (migration `0008`, 6 tables). Une liste
(`ShoppingList`, `kind` = `courses` | `taches`) n'est **pas** rattachée à un calendrier :
elle a ses propres membres (`ShoppingListMember`, owner/editor/viewer), ses invitations par
lien (`ShoppingListInvitation`, miroir des calendriers), ses articles (`ShoppingItem`) et son
catalogue tap-to-add (`CatalogItem`). Accès gaté par `require_list_access` (404 si insuffisant).

**Catalogue** : ~55 items FR intégrés (emoji + rayon) semés **une fois** au démarrage
(`services/catalogue.py::semer_catalogue`, idempotent). Le catalogue d'une liste =
intégrés ∪ items perso mémorisés (taper un article hors catalogue le mémorise → tap-to-add
la fois suivante). Rayons FR fixes (ordre d'affichage dans `RAYONS`).

**Endpoints** :
- `GET/POST /lists`, `GET/PATCH/DELETE /lists/{id}`, `GET /lists/{id}/members`,
  `POST /lists/{id}/invitations`, `POST /lists/invitations/{token}/accept`.
- `GET/POST /lists/{id}/items`, `PATCH/DELETE /lists/{id}/items/{item_id}` (cochage pose
  `checked_by`/`checked_at`), `POST /lists/{id}/items/clear-checked` (anti-doublon façon
  Bring! : un article actif de même nom n'est pas dupliqué).
- `GET /lists/{id}/catalog` (groupé par rayon), `GET /sse/lists/{id}` (temps réel).
- `GET/POST/GET/PATCH/DELETE /loyalty-cards` (cartes personnelles, isolées par propriétaire).

**Temps réel** : canal SSE dédié `list:{id}:changes` (`publish_list_change`) ; le front
(onglet « Listes ») branche un `EventSource` — l'auth SSE passe le JWT en query
(`?access_token=`, `get_current_user_sse`) car `EventSource` ne peut pas poser d'en-tête.

**Push par personne** : sur ajout/cochage, la brique émet best-effort vers `connexion
/pousser` pour les autres membres (voir ADR `2026-07-16-listes-push-evenementiel`).
Config au déploiement : `CONNEXION_URL` (base du pont, ex.
`http://host.docker.internal:5870`) + `CONNEXION_KEY` (X-API-Key). Vides ⇒ push désactivé
(repli honnête, jamais bloquant).

**Cartes de fidélité** : `LoyaltyCard` (personnelle : `user_id`, `enseigne`, `numero`,
`format`, `couleur`). Le front (onglet « Cartes ») affiche le code-barres plein écran via un
générateur **vanilla embarqué** `static/barcode.js` (Code128 + EAN-13 en SVG, **aucun CDN**).
`qr` reste dans l'enum mais retombe sur l'affichage du numéro (génération QR = fast-follow).

**Outils LLM** (manifest v1.2.0, identité pinnée `perso`) : `courses_consulter`,
`courses_creer_liste`, `courses_ajouter`, `courses_cocher` sous `/service/lists…`.

**⚠️ Migration 0008** : les tests unitaires utilisent `create_all` (pas Alembic). Smoke-tester
`alembic upgrade 0008` / `downgrade` sur **Postgres** avant déploiement (comme pour 0007).

**Hors périmètre (fast-follow)** : génération QR des cartes ; outils LLM pour les cartes ;
import de recettes ; templates de listes sauvegardées ; quantités structurées.

## S177 — Sondages de disponibilité (façon Doodle)

Sous-système **autonome** (migration `0009`, 3 tables : `AvailabilityPoll`, `PollSlot`,
`PollVote`). L'organisateur propose des créneaux, chacun vote par créneau
(`oui` / `si_besoin` / `non`), puis on **finalise** sur un créneau — ce qui **crée un
`Event`** dans l'agenda (le plus vs Doodle : la boucle sondage→agenda) avec les votants
« oui » ayant un compte pré-ajoutés comme participants.

**Participation = lien public à jeton + membres**. Le vote passe par `share_token` (la
capacité du lien) : un invité vote sans compte en donnant juste un nom, un membre connecté
voit son vote attribué à son profil (`get_optional_user` = auth facultative). Un **bulletin**
couvre tout le sondage : à la soumission on **remplace** tous les votes de l'identité
(`voter_id` membre, sinon `guest_key` invité renvoyé pour rééditer) → un bulletin par personne.

**Endpoints** :
- Gestion (organisateur, `require_owned_poll` → 404 sinon) : `GET/POST /polls`,
  `GET/PATCH/DELETE /polls/{id}`, `POST /polls/{id}/slots`, `DELETE /polls/{id}/slots/{slot_id}`,
  `POST /polls/{id}/finalize` `{slot_id, calendar_id?}`.
- Vote public par jeton : `GET /polls/token/{share_token}` (grille + tallies, ne renvoie
  jamais le token), `POST /polls/token/{share_token}/vote` `{nom?, guest_key?, votes:[…]}`.
- Page HTML de vote autonome (sans compte) : `GET /polls/p/{share_token}` (`page_sondage`,
  sur le modèle de `page_invitation`).
- Temps réel : `GET /sse/polls/{share_token}` (jeton = capacité, pas d'auth) sur le canal
  `poll:{id}:changes` (`publish_poll_change`) — la grille se met à jour en direct.

**Outils LLM** (manifest **v1.3.0**) : `sondage_consulter`, `sondage_creer`,
`sondage_finaliser` (gaté `action:true`) sous `/service/polls…`.

**Front** : onglet « 📊 Sondages » (liste, création, grille de résultats, copier le lien,
retenir un créneau) dans `/app`.

**⚠️ Migration 0009** : tests = `create_all` ; smoke-tester `alembic upgrade 0009` /
`downgrade` sur **Postgres** avant déploiement (comme 0007/0008).

**Hors périmètre (fast-follow)** : notifier les votants à la finalisation (push par
personne façon S174/S176) ; tri auto pondérant `si_besoin` ; créneaux journée entière ;
fermeture auto à `expires_at` (aujourd'hui le lien expire pour voter, le sondage reste
consultable).

## S178 — PWA + push web + digest

**PWA installable** : `/app` est servie comme une vraie app installable — Web App Manifest
(`GET /app/manifest.webmanifest`), service worker (`GET /app/sw.js`, scope `/app`), icônes
192/512/maskable générées (`GET /app/icone-{taille}.png`), raccourcis (« Nouvel événement »,
« Listes », « Sondages »). Le SW ne fait que du **cache d'app-shell minimal** (`/app`) + de
l'affichage de notification sur `push` (aucune requête réseau interceptée/rejouée) — pas de
mise en cache des données métier.

**Push web = 5ᵉ canal** (à côté de 🔔+Telegram+WhatsApp+Discord), câblé comme adaptateur
`webpush` dans la brique `connexion` (voir `briques/connexion/README.md`). Côté agenda,
`GET /push/cle_publique` sert la clé **publique** VAPID (pas de secret), et
`POST`/`DELETE /push/appareils` (authentifiés Bearer, `Depends(get_current_user)`) relaient
best-effort vers `connexion` en forçant `utilisateur` depuis le **`sub` du token**, jamais
depuis le corps envoyé par le navigateur — un appareil ne peut pas s'enregistrer pour
quelqu'un d'autre. Anti-intrusif : l'onglet **⚙️ Réglages → 🔔 Notifications** ne demande la
permission navigateur **que sur clic** (« Activer les notifications sur cet appareil ») ;
« Couper sur cet appareil » désabonne localement puis `DELETE /push/appareils`. Si un
endpoint répond 404/410 à l'envoi (abonnement mort — désinstallation, expiration navigateur),
`connexion` le **purge automatiquement** du magasin.

**Digest quotidien/hebdo** (`POST /digests/executer`, gardé par `DIGEST_KEY`, appelé par
l'horloge du Cœur — `core/proactif.py:_check_digest`, à chaque tick, idempotent) : composé
localement (`services/digest.py`, gabarit **déterministe, sans LLM** — texte court pour le
push, HTML pour l'email), envoyé en push (`connexion /pousser`) et/ou email
(`mail 6030 /mail/envoyer`) selon les préférences du profil. **Off par défaut**
(`digest_cadence="off"`) — l'utilisateur l'active explicitement via
`PATCH /profiles/me/notifs` (cadence `quotidien`/`hebdo`, `digest_push`, `digest_email`,
`heures_calmes`). Idempotence par (utilisateur, jour) via `dernier_digest_quotidien` /
`dernier_digest_hebdo` sur `UserProfile` — un appel répété au même tick ne renvoie rien deux
fois ; le digest hebdo ne part que le lundi.

**Heures calmes** (`services/heures_calmes.py`, plage `HH:MM-HH:MM`, gère l'enjambement de
minuit) : respectées à la fois par le digest et par les notifications par-personne des listes
de S176 (`services/notifications.py`). **Pas encore branchées sur le rappel temps réel
d'événement du Cœur** (`_check_agenda`) — fast-follow explicite, pas un oubli.

**Env** (`config.py`) :
- `VAPID_PUBLIC_KEY` — clé publique VAPID, **même valeur** que côté `connexion`. Vide ⇒
  `/push/cle_publique` renvoie une clé vide, le front n'active pas le bouton.
- `DIGEST_KEY` — clé interne gardant `POST /digests/executer`. Vide ⇒ 503 (digest désactivé).
- `DIGEST_HEURE` (def. `7`) — heure locale avant laquelle l'endpoint ne fait rien (appelé à
  chaque tick, se contente de sortir tôt).
- `DIGEST_TZ` (def. `Europe/Paris`) — fuseau de référence pour l'heure d'envoi et le calcul
  jour/semaine.
- `MAIL_URL` / `MAIL_KEY` — base + `X-API-Key` de la brique mail 6030. Vide ⇒ email du
  digest désactivé (repli honnête), le push reste possible indépendamment.

**⚠️ Migration 0010** (`email`, `digest_cadence`, `digest_push`, `digest_email`,
`heures_calmes`, `dernier_digest_quotidien`, `dernier_digest_hebdo` sur `user_profiles`) :
tests = `create_all` ; smoke-tester `alembic upgrade 0010` / `downgrade` sur **Postgres**
avant déploiement (comme 0007/0008/0009).

**Limites honnêtes** :
- **iOS** ne supporte le Web Push **qu'après "Ajouter à l'écran d'accueil"** (pas depuis
  Safari onglet) — limitation de la plateforme, pas de la brique.
- **Offline = lecture dégradée seulement** : le SW sert l'app-shell en cache, pas les
  données ; sans réseau, `/app` s'ouvre mais les appels API échouent normalement (pas de
  synchronisation différée / file d'attente offline dans ce sprint).
- Heures calmes du **rappel temps réel** d'événement (`_check_agenda` côté Cœur) = **fast-
  follow**, pas livré ici (seuls le digest et les notifs de listes S176 les respectent).

**Hors périmètre (fast-follow)** : purge auto smoke-testée en conditions réelles (aujourd'hui
prouvée par test unitaire uniquement) ; génération des clés VAPID (à faire une fois au
déploiement, `web-push generate-vapid-keys` ou équivalent) ; `pywebpush` à ajouter à l'image
Docker `connexion` (dépendance optionnelle, repli honnête si absente) ; heures calmes sur le
rappel temps réel du Cœur ; widgets/raccourcis au-delà des 3 shortcuts du manifest.

## S180 — Chiffrement au repos

Le contenu humain sensible est chiffré au repos (AES-GCM) de façon transparente via
les `TypeDecorator` de `crypto.py` : titres/descriptions/lieux d'événements, contenu
des commentaires, positions de présence (lat/lon) et leurs libellés de position
(`label`), emails (profils + invitations), noms affichables (`display_name`),
numéro/note de carte de fidélité, sondages (titre/desc/lieu + voter_name), journal
d'activité (user_nom + details), items et noms de listes.

**Non chiffré** (interrogé/trié/capacité) : dates, clés de jointure, jetons
(`ics_token`/`share_token`/tokens d'invitation), `external_id`, `Label.name`,
`LoyaltyCard.enseigne`, couleurs/emoji/enums.

**Clé** : `AGENDA_ENCRYPTION_KEY` (dédiée) ; à défaut, sous-clé HKDF dérivée de
`VAULT_SECRET` (distincte de la clé du coffre OAuth). Sans aucune des deux, toute
écriture chiffrée lève (fail-closed).

**Déploiement (RESTE, LIVE différé)** :
- Poser `AGENDA_ENCRYPTION_KEY` en prod (ou s'appuyer sur `VAULT_SECRET` déjà présent).
- Smoke **obligatoire** avant bascule : `alembic upgrade 0012` puis `alembic downgrade 0011`
  sur une copie **Postgres** des données (les tests utilisent `create_all`, pas la migration ;
  la migration exige qu'une clé soit configurée au moment de l'`upgrade`).
- Défense en profondeur (hors code) : volume de la base sur disque chiffré — à ajouter
  au runbook `MIGRATION-HP.md`.

**Fast-follow** : rotation de clé réelle (l'enveloppe versionnée v1 la prépare) ;
chiffrer aussi les **pièces jointes** fichiers (`EventAttachment` dans `ATTACHMENTS_DIR`,
non couvert par le chiffrement de colonnes) ; chiffrer aussi `EventAttachment.filename`
(métadonnée en clair, avec le contenu des pièces jointes déjà différé) ; géocoder
`Event.location` au write avant chiffrement.

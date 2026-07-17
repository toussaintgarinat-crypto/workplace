# S179 — Géoloc légère éphémère (Présence) + abonnement webcal (ICS)

**Date** : 2026-07-17
**Brique** : agenda (backend `briques/agenda/backend`)
**Roadmap** : [S174→S180 agenda best-in-class] — S179 (avant-dernier sprint ; S180 = chiffrement au repos)
**Statut** : design validé avec l'utilisateur, prêt pour plan d'implémentation.

## Objectif

Rendre l'agenda du Cœur comparable à FamilyWall sur deux points restants, **sans jamais
dériver vers du tracking** :

1. **Présence** : partage de position **ponctuel, éphémère, opt-in** — une position à la
   fois par personne, expiration courte, aucun historique. Deux usages : carte familiale
   « où est chacun » **et** « je suis en route » rattaché à un événement.
2. **Abonnement webcal (ICS)** : une URL secrète par utilisateur, lecture seule, à coller
   dans Apple Calendar / Google Agenda / Outlook — le flux se met à jour tout seul côté
   client. But familial : Marina voit l'agenda du Cœur dans son iPhone sans rien installer.

Décisions produit validées :
- Géoloc = **les deux** (check-in familial autonome + partage lié aux events).
- Rétention = **éphémère, une position à la fois**, expiration courte, **zéro historique**.
- ICS = **abonnement webcal (flux vivant)**, lecture seule (pas de téléchargement figé,
  pas d'import entrant).
- Carte = **approche A** : données de présence dans la brique agenda, carte rendue dans la
  PWA `/app` en réutilisant le **stack Leaflet vendoré** de la brique geo (fonds IGN
  Géoplateforme + OSM, déjà acceptés par le projet). On ne fait **pas** porter l'identité
  familiale à la brique geo (sa tenancy = clé API, pas l'identité Keycloak).

## Contexte technique (existant réutilisé)

- Identité : `UserProfile` (user_id, display_name, avatar_color, email) — semé au login
  depuis les claims Keycloak. Résolution 100 % locale.
- Accès calendriers : `GET /events` applique déjà la portée « calendriers que l'user peut
  voir » (possédés + partagés). Le flux ICS **réutilise cette même portée**.
- SSE : `services/pubsub.py` + `routers/sse.py`, motif canal `list:{id}:changes` /
  `poll:{token}` avec `get_current_user_sse` (token en query). La présence ajoute
  `presence:changes`.
- Horloge du Cœur : `core/proactif.py` fait déjà des passes périodiques (rappels, digest,
  purge). La purge des positions expirées s'y greffe.
- Leaflet vendoré : `briques/geo/static/{leaflet.js,leaflet.css,leaflet.markercluster.js}`
  (zéro CDN) + fonds `tile.openstreetmap.org` et `data.geopf.fr` (IGN Géoplateforme,
  service public FR, sans clé). Motif de carte **déjà accepté** dans le projet.
- Aucune CSP posée sur l'agenda `/app` → embarquer Leaflet + tuiles fonctionne comme dans
  la brique geo.
- Anti-usurpation : motif S178 (`POST /push/appareils`) — `user_id` **forcé au sub
  Keycloak**, jamais lu du corps ; prouvé par un test dédié. Repris à l'identique ici.
- Onglets `/app` actuels : 📅 Agenda · 🛒 Listes · 📊 Sondages · 💳 Cartes · ⚙️ Réglages.
  On ajoute **📍 Présence**.
- Migrations à `0010` → S179 = **`0011`**. Manifest actuel v1.3.0 → **v1.4.0**.

## Architecture

Deux sous-systèmes **indépendants** dans la brique agenda, sans toucher S174–S178.

### Sous-système 1 — Présence (positions éphémères)

**Modèle (migration `0011`) — table `live_positions`** : une ligne **par personne** au
maximum (upsert).

| Colonne       | Type                          | Notes |
|---------------|-------------------------------|-------|
| `user_id`     | String(255), **PK**           | sub Keycloak. Une position active max par personne ; repartager remplace. |
| `latitude`    | Float, non-null               | |
| `longitude`   | Float, non-null               | |
| `accuracy_m`  | Float, nullable               | précision GPS renvoyée par le navigateur. |
| `label`       | String(255), nullable         | optionnel (« à la maison »), vide par défaut. |
| `scope`       | Enum `famille` \| `event`     | visibilité. |
| `event_id`    | String(36), FK events ondelete CASCADE, nullable | requis si `scope=event`. |
| `expires_at`  | DateTime, **index**, non-null | au-delà : plus affichée + purgée. |
| `updated_at`  | DateTime                      | |

**Flux** :
- **Capture** : bouton dans l'onglet 📍 → `navigator.geolocation.getCurrentPosition`
  (opt-in au clic, **one-shot**, aucun `watchPosition`/suivi de fond). L'utilisateur choisit
  la **portée** :
  - `famille` : visible de **tous les membres**, `expires_at` = maintenant + `ttl_minutes`
    (défaut **60 min**).
  - `event` : visible des **seuls participants de l'event**, `expires_at` = **fin de
    l'event** (`Event.end_at`).
- **Endpoints** (auth `get_current_user` ; `user_id` **forcé au sub**, jamais du corps) :
  - `POST /presence` — upsert : `{lat, lon, accuracy?, label?, scope, event_id?, ttl_minutes?}`.
    Valide : `scope=event` ⇒ `event_id` fourni et l'appelant est participant de l'event
    (sinon 403/422). `ttl_minutes` borné (ex. 1..1440) et ignoré si `scope=event`.
  - `DELETE /presence` — coupure 1-clic (« ne plus partager ») : supprime la ligne de
    l'appelant.
  - `GET /presence` — positions **non expirées visibles par moi** : toutes les `famille` +
    les `event` des events où je suis participant. Jointure `UserProfile` → `display_name`
    + `avatar_color`. La distance est calculée **côté client** (pas de position de
    l'observateur envoyée au serveur).
- **Temps réel** : canal SSE `presence:changes` (broadcast best-effort via `pubsub`) émis
  sur POST/DELETE → la carte se rafraîchit. Réutilise `get_current_user_sse`.
- **Purge** : positions expirées **filtrées à la lecture** ET **purgées** par une passe de
  `core/proactif.py` (comme la purge idempotence digest S178).
- **Définition « membres/famille »** : tous les `UserProfile` connus (toute personne ayant
  ouvert l'agenda). Choix pragmatique de l'instance auto-hébergée mono-famille ; les groupes
  familiaux explicites sont un fast-follow noté.

### Sous-système 2 — Flux ICS / webcal

- `UserProfile.ics_token` (String, nullable, **unique**) : jeton du flux, généré à la
  première demande, révocable.
- **Endpoints** :
  - `GET /ics/cle` (auth) → renvoie/crée le `ics_token` + l'URL
    `webcal://<host>/ics/{token}.ics` à coller dans le client calendrier.
  - `POST /ics/regenerer` (auth) → nouveau jeton, révoque l'ancien.
  - `GET /ics/{token}.ics` — **public** (jeton = capacité, aucune auth Keycloak),
    `Content-Type: text/calendar; charset=utf-8`. Résout token → user (404 si inconnu),
    puis émet un `VCALENDAR` des events des calendriers que cet user peut voir (**même
    portée d'accès que `GET /events`**).
- **Générateur pur `services/ics.py`** (aucune I/O, testable isolément) : produit le texte
  `VCALENDAR` depuis une liste d'events. Un `VEVENT` par event :
  - `UID` = id de l'event ; `DTSTAMP` ; `SUMMARY` (title) ; `DESCRIPTION` ; `LOCATION`.
  - `DTSTART`/`DTEND` avec `TZID=Europe/Paris`, ou `VALUE=DATE` (date nue) si `all_day`.
  - Récurrence : **`RRULE` + `EXDATE` émis directement** (pas d'expansion serveur — le
    client agenda expanse, comportement standard et robuste). Les overrides
    (`recurrence_parent_id` non-NULL) → `VEVENT` séparé avec `RECURRENCE-ID` pointant la
    `recurrence_date`.
  - Échappement RFC 5545 (`\`, `;`, `,`, `\n`), pliage de lignes à 75 octets facultatif.
- Lecture seule ; **aucune écriture entrante** (pas d'import ICS — hors scope).

## Surface LLM — manifest **v1.4.0**

- `presence_consulter` (niveau 0) — « qui a partagé sa position, où, vu quand ».
- `ics_lien` (niveau 0) — donne à l'utilisateur son URL d'abonnement webcal.
- **Pas** d'outil LLM de partage de position : le partage reste une action humaine
  explicite au clic (permission géoloc du navigateur), cohérent avec la ligne anti-intrusive.
- `test_manifest_capacites` mis à jour (set attendu + politique de gates ; les deux nouveaux
  sont niveau 0, non gatés).

## Front `/app`

- Nouvel onglet **📍 Présence** :
  - Carte **Leaflet** (assets vendorés **copiés** de `briques/geo/static` vers
    `briques/agenda/backend/static`), fonds **IGN Géoplateforme** par défaut + **OSM** en
    repli (même config que geo).
  - Marqueurs nom + `avatar_color` des membres ayant partagé ; popup « vu il y a N min ·
    distance · **ouvrir dans Plans/Maps** » (URI `geo:lat,lon` avec repli lien OSM
    `https://www.openstreetmap.org/?mlat=…&mlon=…`).
  - Boutons **« Partager ma position »** (choix famille / pour un event) et **« Arrêter »**.
  - Rafraîchi par SSE `presence:changes`.
- **Fiche d'événement** (modale existante S174) : si des participants ont partagé
  `scope=event` pour cet event, mini-liste « en route » + lien vers la carte.
- Onglet **⚙️ Réglages** : bloc **Abonnement calendrier** — afficher/copier l'URL webcal +
  bouton **Régénérer**.

## Garde-fous anti-intrusifs (ligne S178 tenue)

- Rien ne se déclenche sans clic ; la géoloc passe par la **permission OS explicite** du
  navigateur.
- **Une seule position à la fois** par personne ; **expiration courte automatique** +
  **coupure 1-clic** + **purge** par l'horloge ; **aucun historique**.
- Vocabulaire « **partager ma position** » / « en route » — jamais « suivi » ni « tracking ».
- La position de l'observateur n'est jamais envoyée au serveur (distance calculée côté
  client).
- Jeton ICS **révocable** ; flux **lecture seule**.

## Tests

- **`services/ics.py` (pur)** : event simple, all-day (`VALUE=DATE`), récurrent
  (`RRULE`+`EXDATE`), override (`RECURRENCE-ID`), échappement des caractères spéciaux, TZID.
- **Endpoint `.ics`** : accès par token valide, **portée = events visibles seulement**,
  404 sur token inconnu, `Content-Type` correct.
- **Présence** : upsert **remplace** (une ligne/personne) ; `user_id` **forcé** (test
  anti-usurpation façon S178) ; filtre d'**expiration** à la lecture ; portée `event` =
  participants **only** (un non-participant ne voit pas) ; `DELETE` supprime ; purge horloge.
- **Migration `0011`** : smoke `alembic upgrade/downgrade` sur **Postgres** avant
  déploiement (les tests tournent sur `create_all`).

## Hors scope (fast-follow noté)

- Import ICS **entrant** (écriture depuis un flux externe).
- Partage **en direct** rafraîchi (fenêtre X min, façon Google Maps).
- **Historique** de positions.
- **Groupes familiaux explicites** (aujourd'hui « famille » = tous les `UserProfile`).
- Carte à **tuiles auto-hébergées** (brique/serveur de tuiles dédié).
- **Push** « X partage sa position » (best-effort connexion `/pousser`).
- **Géocodage** de `Event.location` texte → lat/lon.

## Déploiement (rappels)

- Migration `0011` : smoke `alembic upgrade/downgrade` sur Postgres.
- Aucune nouvelle dépendance externe attendue (Leaflet vendoré copié, ICS = génération
  texte pure, géoloc = API navigateur). Vérifier qu'aucun paquet Python supplémentaire
  n'est requis pour l'ICS (génération manuelle RFC 5545, pas de lib tierce imposée).
- LIVE différé : suivre [[feedback-live-differe-fin-s180]] — preuves groupées après S180.

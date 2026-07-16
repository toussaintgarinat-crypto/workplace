# S178 — PWA + push web + widgets + digest — design

Statut : **validé avec l'utilisateur le 2026-07-16**. Sprint de la roadmap agenda
best-in-class (`docs/sprints/S174-S180-roadmap-agenda-best-in-class.md`). LIVE différé à
la fin de S180 (mémoire « LIVE différé jusqu'à fin S180 »).

## But

Donner à la brique agenda un **canal de notification mobile** sans app native :
l'application web autonome `/app` (port 8400, login PKCE `calendar-app`, voir
`docs/superpowers/specs/2026-07-15-s172-agenda-application-autonome-design.md`) devient
une **PWA installable** qui reçoit des **notifications push web**. Les rappels par
personne (S174) et les notifs de listes (S176) — qui transitent déjà par le pont
`connexion /pousser` — arrivent alors **aussi** en push web, sans modifier leur code. On
ajoute un **digest** quotidien/hebdo (façon Cozi) en push court + email riche, et des
**raccourcis** PWA (« widgets »).

## Principe directeur : anti-intrusif (non négociable)

Décision produit validée : **rien ne se déclenche sans une action explicite de
l'utilisateur, et tout se désactive aussi vite.**

- Aucune demande de permission à l'ouverture de `/app`. La demande d'autorisation
  navigateur n'apparaît **que** sur clic « Activer les notifications sur cet appareil ».
- Coupure **en un clic, par appareil** : supprime l'enregistrement serveur *et*
  `unsubscribe()` le navigateur → plus aucun push.
- Interrupteur **global** dans le panneau 🔔 (couper partout).
- Digest en **`off` par défaut** : ne part que sur demande explicite.
- **Heures calmes** : aucune notif dans la plage définie par la personne.
- **Purge automatique** d'un appareil qui ne répond plus (HTTP 410 Gone / 404).

Terminologie : on parle d'**« appareil »** (device push), jamais d'« abonnement » — pour
éviter toute confusion avec un abonnement payant. Le seul opt-in nommé est le **digest**.

## Contexte technique constaté (2026-07-16)

- Toutes les notifs par-personne passent par **`connexion /pousser`** (`briques/connexion/main.py:158`)
  qui, via `correspondance.cibles_pour(utilisateur)`, fanout sur chaque **réseau lié et
  configuré** (adaptateurs `telegram`, `whatsapp`, `discord`, `email_sms` —
  `briques/connexion/adaptateurs.py:299`). Ajouter un réseau = ajouter un adaptateur +
  l'enregistrer ; `/pousser` le prend en compte automatiquement.
- Les notifs de listes S176 vivent **dans la brique agenda** (`services/notifications.py`,
  POST best-effort vers `/pousser`). Les rappels d'événements vivent **dans le Cœur**
  (`core/proactif.py` : `_check_agenda` → `_pousser_messagerie` → `/pousser`).
- `UserProfile` (agenda) porte aujourd'hui `display_name` + `color`, semés au login depuis
  les claims Keycloak (S174, `POST /profiles/me`).
- Front `/app` = `templates_app.page_app` (`briques/agenda/backend/templates_app.py`),
  sert du HTML/JS, login PKCE, consomme l'API REST en Bearer. `static/` déjà monté
  (`barcode.js`).
- Brique mail 6030 : `POST /mail/composer` **crée un brouillon** (n'envoie pas) ;
  `envoi.envoyer(compte, a, sujet, corps)` (`briques/mail/envoi.py:45`) est le primitif
  d'envoi. Un chemin d'**envoi direct** est nécessaire pour le digest (voir §4).

## Architecture — vue d'ensemble

```
Navigateur /app (PWA)
  │  1. clic "Activer" → Notification.requestPermission()
  │  2. SW.pushManager.subscribe(VAPID_PUBLIC_KEY) → PushSubscription
  │  3. POST /push/appareils  (Bearer Keycloak)
  ▼
Brique agenda (8400)
  │  relaie {utilisateur: sub, appareil} + CONNEXION_KEY
  ▼
Brique connexion (pont)  ── stocke l'appareil dans la correspondance (reseau="webpush")
  ▲
  │  /pousser {utilisateur, texte}   (déjà appelé par S174 Cœur + S176 agenda)
  │  fanout: telegram + webpush + …
  ▼
Adaptateur webpush (pywebpush + VAPID) → POST endpoint navigateur → SW `push` event → Notification
```

## §1 — PWA installable (`/app`)

**Web App Manifest** servi à `GET /app/manifest.webmanifest` (route agenda, `include_in_schema=False`) :
`name: "Agenda"`, `short_name`, `start_url: "/app"`, `scope: "/app"`,
`display: "standalone"`, `background_color`/`theme_color` (thème sombre/or existant),
`icons` (192×192, 512×512, + une variante `purpose: "maskable"`), `shortcuts` (§2).

**Icônes** : PNG générés **localement** au build/au boot (aucun CDN, règle projet) — glyphe
simple (initiale « A » ou emoji 📅) sur fond thème. Servies depuis `static/`.

**Service worker** `GET /app/sw.js` (Content-Type `application/javascript`, en-tête
**`Service-Worker-Allowed: /`**) :
- `install`/`activate` : cache minimal de l'app-shell (`/app`, `static/*`) pour un
  démarrage **hors-ligne dégradé** (lecture seule du dernier état ; pas de sync offline —
  hors périmètre).
- `push` : lit le payload JSON `{titre, corps, url, tag}` → `showNotification`.
- `notificationclick` : `clients.openWindow` / focus sur `url` (deep-link `/app`).

Le `<link rel="manifest">` et l'enregistrement `navigator.serviceWorker.register('/app/sw.js')`
sont ajoutés dans `page_app`.

## §2 — Widgets = raccourcis PWA

Tableau `shortcuts` du manifest → **« ＋ Événement »**, **« 🛒 Listes »**, **« 📊 Sondages »**,
chacun `url` deep-linkant vers la vue `/app` correspondante (réutilise l'état de vue
existant / le hash de navigation). Quasi-gratuit une fois le manifest posé. Pas de code
serveur dédié.

## §3 — Push web : adaptateur `webpush` dans **connexion**

### connexion
- Dépendance : `pywebpush`. Clés VAPID en env : `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`,
  `VAPID_SUBJECT` (mailto/URL). Non configuré ⇒ adaptateur `configure()==False` (repli
  honnête, jamais d'erreur).
- **Adaptateur `webpush`** (`nom="webpush"`) enregistré dans `_ADAPTATEURS` +
  `_ORDRE_DEFAUT`. `envoyer(id_externe, texte)` : `id_externe` = l'appareil sérialisé
  (endpoint + clés `p256dh`/`auth`) ; envoie via `pywebpush` un payload JSON. Sur réponse
  **410/404** → signale l'appareil comme mort (purge, voir stockage).
- **Stockage des appareils** : chaque appareil est une **cible de correspondance**
  `(reseau="webpush", id_externe=<appareil sérialisé>)` rattachée à l'utilisateur → `/pousser`
  le fanout **automatiquement**. (Un utilisateur peut avoir N appareils = N cibles webpush.)
- **Endpoints** (clé API, comme les autres endpoints admin de connexion) :
  - `POST /push/appareils` `{utilisateur, appareil}` → enregistre la cible.
  - `DELETE /push/appareils` `{appareil}` (ou son endpoint) → retire la cible.
  - `GET /push/cle_publique` (**public**, lecture seule) → renvoie `VAPID_PUBLIC_KEY` (une
    clé publique est publique par nature ; nécessaire au navigateur pour `subscribe`).
- Purge : à l'envoi, un 410/404 retire la cible de la correspondance (best-effort).

### agenda
- `POST /push/appareils` (Bearer Keycloak) `{appareil}` → relaie à connexion
  `POST /push/appareils` avec `{utilisateur: current_user.sub, appareil}` + `CONNEXION_KEY`.
- `DELETE /push/appareils` (Bearer) `{appareil}` → relaie le retrait.
- `GET /push/cle_publique` (Bearer ou public) → sert la clé publique VAPID. La brique agenda
  garde `VAPID_PUBLIC_KEY` dans sa **config** (même valeur que connexion) ; **la clé privée
  ne quitte jamais connexion**.

### front `page_app`
- Bouton « 🔔 **Activer les notifications sur cet appareil** » (dans le panneau 🔔, §5).
- Au clic : `Notification.requestPermission()` → si accordé, `registration.pushManager.subscribe({userVisibleOnly:true, applicationServerKey})` avec la clé publique VAPID → `POST /push/appareils`.
- « Couper sur cet appareil » : `subscription.unsubscribe()` + `DELETE /push/appareils`.
- État affiché : activé / coupé / non supporté (repli honnête si le navigateur ne supporte pas le Web Push, ex. iOS < 16.4 hors écran d'accueil).

### Bénéfice
Les rappels S174 (Cœur) et notifs de listes S176 (agenda) passent **déjà** par `/pousser`
→ ils arrivent en push web **sans aucune modification de leur code**.

## §4 — Digest quotidien/hebdo (dans agenda)

### Modèle
`UserProfile` étendu (**migration 0010**, valeurs par défaut = comportement actuel) :
- `email` (nullable) — semé depuis les claims Keycloak au login (comme `display_name`).
- `digest_cadence` : `off` | `quotidien` | `hebdo` — **défaut `off`**.
- `digest_push` (bool, défaut `true`) — le digest part-il en push web ?
- `digest_email` (bool, défaut `false`) — le digest part-il en email ?
- `heures_calmes` (nullable, ex. `"22:00-07:00"`).

### Composition
`services/digest.py` (aussi pur que possible — reçoit les données, rend le texte) : pour
une personne, compose son résumé de la **journée** (cadence quotidien) ou de la **semaine**
(hebdo) : ses événements où elle participe + items de listes en attente + sondages ouverts.
Sortie : **texte court** (push) + **HTML** (email).

### Déclenchement
`POST /digests/executer?cadence=quotidien|hebdo` (clé interne `DIGEST_KEY`), appelé par
l'**horloge du Cœur** (mécanisme périodique S29 déjà utilisé pour `/sonder` et les checks
proactifs) le matin. L'endpoint :
1. sélectionne les profils dont `digest_cadence == cadence` ;
2. pour chacun, si **pas** dans ses heures calmes et pas déjà envoyé aujourd'hui
   (idempotence, voir ci-dessous), compose le digest ;
3. envoie : push via `/pousser` si `digest_push` ; email via mail 6030 si `digest_email`
   **et** `email` présent.
4. **Hebdo** : envoyé un jour fixe (ex. lundi) ; l'endpoint no-op les autres jours pour la
   cadence hebdo.

**Idempotence** : marqueur « dernier digest (user, cadence) envoyé le <date> » (colonne sur
`UserProfile` ou petite table `DigestLog`) → deux appels le même jour n'envoient qu'une
fois. Choix tranché à l'implémentation (préférence : colonnes `dernier_digest_quotidien` /
`dernier_digest_hebdo` sur `UserProfile`, pas de table).

### Email via brique mail 6030
Le digest a besoin d'un **envoi direct** (pas d'un brouillon). Options, à trancher au plan :
- (préféré) ajouter à la brique mail un endpoint d'**envoi direct** `POST /mail/envoyer`
  `{a, sujet, corps_html}` s'appuyant sur `envoi.envoyer(...)` (repli simulé honnête si
  aucune boîte réelle configurée, comme le reste de la brique) ;
- sinon composer via `/mail/composer` puis envoyer le brouillon (2 appels).
Le corps HTML est **fabriqué par le digest** (pas de LLM — c'est un gabarit déterministe).

## §5 — Réglages UI (panneau 🔔 dans `/app`)

Nouveau panneau « 🔔 Notifications » : état + bouton activer/couper le push **sur cet
appareil**, interrupteur **global**, cadence du digest (off/quotidien/hebdo), toggles
**push** / **email** du digest, plage d'**heures calmes**. Persistés via `POST /profiles/me`
(étendu) ou un `PATCH /profiles/me` dédié aux préférences de notif.

**Pas d'outil LLM** pour le digest dans ce sprint (réglage purement UI — décision validée).
Noté en fast-follow si le besoin « active mon digest hebdo » à la voix apparaît.

## Portée des heures calmes (limite assumée de ce sprint)

Les heures calmes sont respectées pour **le digest** et **les pushes émis par la brique
agenda** (listes S176, digest). Le **rappel d'événement temps-réel part de `core/proactif.py`**
(hors brique agenda) : y appliquer les heures calmes suppose que le Cœur lise
`UserProfile.heures_calmes` de l'agenda → **fast-follow noté**, hors périmètre S178.

## Sécurité / gating

- `GET /push/cle_publique` : la clé publique VAPID est publique par nature (OK exposée).
- `POST/DELETE /push/appareils` agenda : **Bearer Keycloak** obligatoire ; l'utilisateur ne
  peut enregistrer/retirer que **ses** appareils (`utilisateur = current_user.sub`, jamais
  depuis le corps de requête).
- connexion `/push/appareils` : clé API (comme les autres endpoints admin).
- `POST /digests/executer` : clé interne `DIGEST_KEY` (jamais public — sinon spam).
- Payload push : pas de données sensibles au-delà du titre/résumé déjà visibles dans l'app.

## Tests

- **connexion** : adaptateur `webpush` — envoi (pywebpush mické), purge sur 410/404,
  `configure()` sans clés VAPID, fanout via `/pousser` (telegram + webpush ensemble),
  endpoints `/push/appareils` + `/push/cle_publique`.
- **agenda** : relai `/push/appareils` (auth Bearer, `utilisateur` forcé au sub, pas au
  corps), `services/digest.py` (composition pure quotidien/hebdo, listes/sondages inclus),
  `/digests/executer` (filtrage cadence, idempotence, heures calmes, hebdo jour fixe),
  extension `UserProfile` + semis email au login, migration 0010.
- **mail** (si endpoint d'envoi direct ajouté) : `POST /mail/envoyer` réel + simulé honnête.
- **PWA** : manifest servi valide, `sw.js` servi avec le bon Content-Type + en-tête de
  scope. (Le comportement runtime du SW — push/notificationclick — est testé manuellement
  à la vérif LIVE fin S180 ; noté.)
- Suites existantes (agenda ~261, cœur 439) restent vertes.

## Migrations & déploiement

- **Migration 0010** (agenda) : colonnes `UserProfile` (`email`, `digest_cadence`,
  `digest_push`, `digest_email`, `heures_calmes`, marqueurs d'idempotence).
- Env nouveaux : `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT` (connexion) ;
  `VAPID_PUBLIC_KEY`, `DIGEST_KEY` (agenda). Générés au déploiement.
- **RESTE avant déploiement** : smoke `alembic upgrade/downgrade 0010` sur **Postgres**
  (les tests utilisent `create_all`) ; générer les clés VAPID ; câbler l'appel périodique
  du digest dans l'horloge du Cœur.

## Hors périmètre / fast-follow

- Heures calmes sur le **rappel temps-réel du Cœur** (`core/proactif.py`).
- Outil LLM `digest_reglages` (piloter le digest à la voix).
- Sync offline réelle du SW (écriture hors-ligne) — ici seulement lecture dégradée.
- PWA du **dashboard du Cœur** (port 5100) — ce sprint = brique agenda seulement.
- Push web iOS : ne fonctionne qu'une fois `/app` **ajoutée à l'écran d'accueil**
  (limite Safari) — documenté, repli honnête si non supporté.
- Digest riche : pièces jointes, images d'events, personnalisation avancée du gabarit HTML.
```

# S181 — Accès distant du cercle privé (design)

**Date** : 2026-07-18
**Statut** : validé en brainstorming, prêt pour plan d'implémentation
**Mémoire liée** : `sprint-s181-acces-distant-cercle-prive`, `smarina-multiuser-live-differe`

## Objectif

Permettre à un membre du **cercle privé** (Toussaint, Marina, famille) de se connecter au
Cœur **depuis n'importe où** via le mesh NetBird, et d'**enrôler un nouvel appareil** au mesh
par un **QR code** généré depuis l'admin du Cœur.

Deux parties indépendantes, livrables séparément :

- **Partie A** — Login Keycloak joignable via le **domaine mesh** (`workplaceagenda.duckdns.org`).
- **Partie B** — Onboarding mesh par **QR** (setup key NetBird usage-unique, générée à la demande).

## Décision d'architecture (rappel, verrouillée)

Deux flux d'invitation **distincts**, jamais mélangés :
- **Cercle privé** (ce sprint) → mesh NetBird + solution complète. Le QR porte une **setup key NetBird**.
- **Client** (épic séparée, plus tard) → accès public HTTPS vers un **tenant isolé**, jamais sur le mesh.

## Décisions de ce cadrage

1. **Domaine unique** : `KC_HOSTNAME` = le domaine. Toussaint accède au Cœur via
   `https://workplaceagenda.duckdns.org/dashboard` **même depuis le Mac**. On ne maintient PAS
   le login par IP LAN en parallèle (Keycloak 26 gère mal deux issuers ; inutile ici).
2. **Partie B = génération à la demande** : le Cœur crée une **clé neuve usage-unique** par
   invitation via l'API NetBird (PAT `nbp_...`), plutôt qu'afficher un QR d'une clé statique.
3. **NetBird = Cloud** : management `app.netbird.io`, API `https://api.netbird.io` (FQDN du HP
   = `debian.netbird.cloud`, plan gratuit 5 pairs). PAT owner validé (`GET /api/users` → 200,
   `GET /api/setup-keys` → 200). Groupe `auto_groups` par défaut = **"All"** (`d7p6raifadhs73fvql9g`).

---

## Partie A — Login Keycloak distant (domaine unique)

### Constat de risque (dé-risqué)

Le risque « issuer/hostname » redouté au cadrage est **mineur** après lecture du code :
`shared/workplace_auth.verify_token` appelle `jwt.decode` **sans** paramètre `issuer` → le claim
`iss` **n'est jamais validé**. La validation repose uniquement sur les **clés JWKS**, qui sont
**indépendantes de `KC_HOSTNAME`** (Keycloak signe avec les clés du realm quel que soit le
hostname). Conséquence : la validation JWKS et l'échange de code peuvent rester **internes**
(`keycloak:8080`) ; seule la **redirection navigateur** doit pointer sur le domaine.

Aucune brique ne valide `iss` (agenda/`calendar-app` passe par le même `verify_token`).

### Changements

**1. Cœur — séparer URL navigateur / URL serveur** (`core/auth.py`, `core/routers/auth.py`)

- `core/auth.py` : ajouter
  `KEYCLOAK_PUBLIC_URL = os.environ.get("KEYCLOAK_PUBLIC_URL", KEYCLOAK_URL)`.
  Fallback sur `KEYCLOAK_URL` → **comportement inchangé** si la variable n'est pas définie
  (rollback = ne pas la définir). Motif identique à `briques/agenda/backend/config.py:14`.
- `core/routers/auth.py:37` : construire l'URL de redirection `/auth` (301 navigateur) depuis
  `auth.KEYCLOAK_PUBLIC_URL` au lieu de `auth.KEYCLOAK_URL`.
- **Inchangé** : `_token_endpoint()` (`core/auth.py:109`) et `KC` (JWKS, `core/auth.py:59`)
  restent sur `KEYCLOAK_URL` **interne** → l'échange de code S2S et la validation JWKS ne
  dépendent ni de Caddy ni du DNS mesh.
- `redirect_uri` : déjà dérivé dynamiquement de l'hôte de la requête
  (`request.url_for("auth_callback")` + `--proxy-headers`) → pointe le domaine automatiquement.
  Aucun changement.

**2. Caddy** (`outils/mesh-https`, variante DuckDNS live sur le HP)

- Ajouter un bloc exposant Keycloak sur le domaine, port décalé +10000 :
  `https://workplaceagenda.duckdns.org:18080 → reverse_proxy localhost:8080`,
  TLS via l'`acme_dns duckdns` déjà en place (même cert Let's Encrypt).
- ⚠️ Le repo `outils/mesh-https/*` est **désynchronisé** du HP (les fichiers live portent déjà
  le domaine + l'agenda 8400→18400, cf. `f609ed5`, non répercuté au repo). Le plan devra
  **réconcilier repo ↔ HP** pour ce fichier avant/pendant l'édition.

**3. Keycloak** (conteneur `keycloak`, realm `forge`)

- `KC_HOSTNAME = https://workplaceagenda.duckdns.org:18080` (hostname v2, URL complète) → issuer
  et URLs frontend = le domaine.
- `KC_PROXY_HEADERS = xforwarded` : Caddy termine le TLS et proxifie en HTTP → Keycloak doit
  faire confiance aux `X-Forwarded-*` pour reconstruire scheme/host. `KC_HTTP_ENABLED=true`
  (déjà le cas derrière Caddy).
- Client `assistant-app` (realm `forge`) : s'assurer que
  `redirectUri = https://workplaceagenda.duckdns.org/auth/callback` **et** le webOrigin
  correspondant sont présents (memory `f609ed5` indique qu'ils ont été ajoutés — **à vérifier**
  au début de l'implémentation, sinon `kcadm`).
- ⚠️ Effet attendu : l'admin console Keycloak par IP LAN brute redirigera vers le domaine —
  **acceptable** (décision « domaine unique »). `kcadm` en direct (localhost/token) reste OK.

**4. Env** (`core/docker-compose.override.yml`, scopé core, HP-local, non commité)

- Ajouter `KEYCLOAK_PUBLIC_URL=https://workplaceagenda.duckdns.org:18080`.
- Conserver `KEYCLOAK_URL=http://192.168.1.89:8080` (ou `http://keycloak:8080`) **interne**.

### Rollback Partie A

Retirer `KEYCLOAK_PUBLIC_URL` (fallback interne) + rétablir `KC_HOSTNAME` précédent + retirer
le bloc Caddy `:18080`, puis restart core + keycloak.

### Vérification e2e Partie A

1. Depuis un contexte **mesh-only** (ou en forçant la résolution du domaine sur l'IP mesh) :
   ouvrir `https://workplaceagenda.duckdns.org/dashboard` → redirection `/auth` vers
   `…:18080` → saisie `Toussaint` / mot de passe → callback → session → `/dashboard` 200.
2. Vérifier que l'agenda charge (443 events déchiffrés, comme aujourd'hui) : la validation JWKS
   passe malgré l'issuer = domaine (preuve que le dé-risquage tient).

---

## Partie B — Onboarding mesh par QR

### Composants

**1. Client NetBird** (`core/netbird.py`, nouveau module isolé)

- Config (env, gitignoré) : `NETBIRD_API_URL=https://api.netbird.io`,
  `NETBIRD_API_TOKEN=nbp_...`, `NETBIRD_INVITE_GROUP_ID=d7p6raifadhs73fvql9g` (groupe "All"),
  `NETBIRD_SETUP_KEY_EXPIRES=86400` (24 h par défaut).
- Fonction `creer_setup_key(nom) -> dict` : `POST /api/setup-keys` avec
  `{"name": nom, "type": "one-off", "expires_in": <exp>, "usage_limit": 1,
    "auto_groups": [group_id], "ephemeral": false}`. Header `Authorization: Token <PAT>`.
  Renvoie `{key, expires, name}`. Gestion d'erreur : jamais de 500 nu → message clair si le
  PAT manque/expire (401) ou l'API est injoignable.
- **SPIKE** (à faire au câblage) : confirmer les champs **requis** exacts du `POST /setup-keys`
  (notamment si `auto_groups` est obligatoire) via un appel réel, avant de figer le payload.

**2. Endpoint admin** (`core/routers/invite.py`, nouveau)

- `POST /admin/inviter-proche` (corps : `{nom}`) → appelle `creer_setup_key` → renvoie
  `{key, expires, management_url}`.
- **Garde** : exige une **session valide** (réutilise `exiger_session`/cookie du Cœur). L'accès
  n'est donc offert qu'à un utilisateur déjà loggé (le cockpit admin). Pas de nouveau rôle pour
  ce sprint (compte unique aujourd'hui) ; note pour plus tard : restreindre au rôle owner.

**3. Front — section admin du dashboard** (React, Cœur)

- Bouton « **Inviter un proche** » dans une section admin → appelle `/admin/inviter-proche` →
  affiche un **QR** (lib QR client-side, embarquée — pas de CDN) + les instructions pas-à-pas :
  *installer l'app NetBird → rejoindre avec la clé → ouvrir `…/dashboard`*.
- **SPIKE** (à faire au câblage) : déterminer ce que le QR encode **exactement**. L'app mobile
  NetBird ne scanne pas forcément une clé nativement ; hypothèse de travail = le QR encode la
  **chaîne setup key** (scan → copie), management URL affichée à côté. À confirmer sur l'app
  réelle avant de figer.

### Sécurité Partie B

- PAT `nbp_...` **uniquement** dans l'env gitignoré du HP (comme `DUCKDNS_TOKEN`). Jamais commité,
  jamais renvoyé au front (seule la setup key générée transite).
- Clés **usage-unique** + expiration courte → surface d'abus minimale, révocable côté NetBird.

### Vérification e2e Partie B

1. Cliquer « Inviter un proche » → `GET /api/setup-keys` montre une **nouvelle** clé one-off
   `used=0` → QR rendu.
2. (Toussaint) enrôler un appareil test avec la clé → `netbird status` : peers count +1 ;
   la clé passe `used=1`.

---

## Hors périmètre (YAGNI)

- Gestion multi-invités dans l'UI (liste/révocation) : révocation via le dashboard NetBird.
- Flux « client / tenant isolé » : épic séparée.
- Nouveau rôle admin Keycloak : compte unique aujourd'hui, garde = session valide.
- Lier_compte_perso / 2e compte Marina : c'est **S182** (multi-user agenda), pas ce sprint.

## Ordre d'implémentation

Partie A d'abord (valeur immédiate, aucun secret externe), puis Partie B (PAT déjà en main).

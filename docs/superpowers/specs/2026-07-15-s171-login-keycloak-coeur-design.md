# S171 — Login Keycloak réel pour le dashboard du Cœur

Sous-sprint 1/3 de [[epopee-identite-multiutilisateur-coeur]] (`docs/sprints/S171-S173-epopee-identite-multiutilisateur-coeur.md`),
préalable bloquant du roadmap agenda `docs/sprints/S171-S177-roadmap-agenda-best-in-class.md`.

## But

Donner au Cœur (`core/`) une vraie authentification utilisateur pour son dashboard.
Aujourd'hui `core/routers/dashboard.py` est monté sans aucune dépendance d'auth
(`core/main.py:83`) : accès direct, aucune notion de « qui regarde ». Impossible de
distinguer l'utilisateur principal de Marina sans ça — préalable à tout le reste de
l'épopée (S172 provisioning, S173 routage) et du roadmap agenda (S171 rappels/personne).

## Contexte technique constaté

- **Aucun login au Cœur aujourd'hui.** `core/main.py` ne pose aucun middleware d'auth ;
  `core/contexte_tenant.py` (S121) capte des en-têtes `X-User-Id`/`X-Org-ID` s'ils sont
  présents mais ne les vérifie **jamais** — n'importe quel appelant peut se prétendre
  n'importe qui. Le seul vrai login visible dans le dashboard est celui de Forge, en
  iframe, géré entièrement par Forge/Oria (indépendant du Cœur).
- **La plomberie de propagation existe déjà (S121).** `core/contexte_tenant.py` porte
  l'identité de l'appelant le long d'un tour de requête via des `ContextVar`s
  (`_utilisateur`, `_org_id`, `_user_token`), posées par la dépendance
  `lire_contexte_tenant` et lues par les clients S2S sortants (`entetes_agenda()` envoie
  déjà `X-User-Id` à chaque appel vers la brique agenda, cf. `core/agenda.py:31`). Cette
  dépendance est câblée sur `usine`/`assistant`/`agenda`/`profil` (`core/main.py:82-86`)
  mais **pas sur `dashboard`**. Ce qui manque n'est donc pas la propagation, mais une
  authentification qui produise une identité fiable à propager.
- **Un client OIDC prêt à l'emploi existe déjà et n'est câblé nulle part.**
  `oria-stack/infra/keycloak/realms/forge-realm.json:128-222` déclare `assistant-app`
  (realm `forge`) : `publicClient`, PKCE S256, mappers `nom`/`avatarEmoji`. Ses
  `redirectUris` (`http://localhost:8300/*`) sont obsolètes — le Cœur tourne en réalité
  sur `5100:5000` (`core/docker-compose.yml:9-10`), pas 8300.
- **`shared/workplace_auth.py`** (S120) est la lib JWT Keycloak partagée du monorepo,
  déjà utilisée par l'agenda (`briques/agenda/backend/auth.py`). Son propre docstring
  d'exemple utilise littéralement `realm="forge", audience="assistant-app"` — la cible
  était déjà anticipée, jamais construite.
- Le realm `oria` (`oria-stack/oria/keycloak/oria-realm.json`) existe aussi mais est
  vide et sans client pertinent pour le Cœur — écarté au profit de `forge`.

## Approches considérées

1. **Réutiliser `forge`/`assistant-app` (retenue).** Corriger les `redirectUris` du
   client existant, réutiliser `shared/workplace_auth.py` tel quel. Zéro nouveau client
   Keycloak, zéro nouvelle lib d'auth — juste le câblage manquant côté Cœur.
2. **Nouveau realm/client dédié au Cœur.** Écarté : duplique ce qui existe déjà pour
   rien, et le realm `forge` est déjà la référence multi-app du projet (netbird-client,
   forge-app, calendar-app y cohabitent).
3. **Auth locale (compte/mot de passe en base, façon restaurant).** Écarté : le choix de
   scope déjà tranché avec l'utilisateur est « vrais comptes Keycloak », pas une auth
   maison ; dupliquerait un système que Keycloak fait déjà bien.

## Design

### Flux d'authentification

Authorization Code + PKCE, standard OIDC, sans rien changer côté Keycloak (le client est
déjà `publicClient` + PKCE S256) :

- `GET /auth/login` : génère `code_verifier`/`code_challenge`, pose un cookie
  court-terme signé contenant le `code_verifier` + un `state` anti-CSRF, redirige vers
  `{KEYCLOAK_URL}/realms/forge/protocol/openid-connect/auth`.
- `GET /auth/callback` : vérifie `state`, échange `code` contre `access_token` +
  `refresh_token` (`POST .../token`), valide l'`access_token` via
  `shared.workplace_auth.verify_token` (`realm="forge", audience="assistant-app"`), pose
  le cookie de session, redirige vers `/dashboard`.
- `POST /auth/logout` : invalide le cookie de session ; redirection optionnelle vers
  l'`end_session_endpoint` Keycloak pour clore aussi la session SSO.

### Session

Cookie de session unique, signé (`itsdangerous`, motif `Starlette SessionMiddleware`),
`HttpOnly`, `Secure` (désactivable en dev local http), `SameSite=Lax`. Contenu :
`sub` (identité Keycloak), `nom`/`avatarEmoji` (claims déjà mappés par le client), et le
`refresh_token` **chiffré** (réutilise le motif AES-GCM déjà en place pour les tokens
OAuth agenda, `briques/agenda/backend/vault.py`, plutôt qu'introduire un second schéma de
chiffrement dans le monorepo).

L'`access_token` (durée de vie 300 s, `accessTokenLifespan: 300` du realm) n'est **pas**
mis en cookie : à chaque requête protégée, `core/auth.py` vérifie sa fraîcheur en
mémoire process (cache léger par `sub`, TTL aligné sur l'expiration) et le rafraîchit
silencieusement via le `refresh_token` du cookie si expiré, sans aller-retour navigateur.
Refresh token invalide/expiré ⇒ 302 vers `/auth/login`.

Pas de table de session en base : l'état vit uniquement dans le cookie navigateur
(refresh token chiffré) + un cache mémoire process pour l'access token. Un redémarrage du
Cœur ne perd donc pas les sessions actives (le cookie survit côté client, le prochain
accès repeuple le cache via un refresh silencieux) — seule une expiration/révocation
côté Keycloak, ou la purge du cookie, force un nouveau login. Limite assumée : sans
table de session, pas de « déconnecter tous les appareils » côté Cœur (seul le logout
Keycloak natif, hors périmètre S171, le permettrait) — acceptable pour un usage
personnel/foyer à quelques comptes.

### Portée volontairement étroite

Seul `dashboard.router` reçoit la nouvelle dépendance (`core/main.py:83`,
`app.include_router(dashboard.router, dependencies=[Depends(exiger_session)])`).
`usine`/`assistant`/`agenda`/`profil` gardent `lire_contexte_tenant` tel quel :

- Le bot Telegram, la boucle `proactif`, et les appels S2S internes (outils LLM) ne
  passent pas par un navigateur et n'ont pas de session Keycloak — ils continuent
  d'utiliser l'identité de service actuelle, inchangée.
- Coupler l'identité de session à `contexte_tenant` pour CES routers (pour que
  l'assistant/l'agenda sachent réellement qui parle depuis le dashboard, au lieu du
  défaut `"perso"`) est le travail de **S173** (routage S2S par utilisateur réel), pas
  de S171. S171 se limite à : un humain peut-il s'authentifier, et le Cœur sait-il who's
  who une fois connecté au dashboard.

### Nouveaux fichiers

- `core/auth.py` : `KeycloakSettings`, `exiger_session` (dépendance FastAPI), logique de
  session/cookie/refresh. Mirroir structurel de `briques/agenda/backend/auth.py`.
- `core/routers/auth.py` : les 3 routes (`/auth/login`, `/auth/callback`,
  `/auth/logout`).
- `core/config.py` : nouvelles variables `KEYCLOAK_URL`, `KEYCLOAK_REALM=forge`,
  `KEYCLOAK_AUDIENCE=assistant-app`, `SESSION_SECRET_KEY` (signature cookie),
  `AUTH_ENABLED` (permet de désactiver en dev local, motif déjà utilisé par l'agenda).

### Modifications

- `oria-stack/infra/keycloak/realms/forge-realm.json` : `redirectUris` de
  `assistant-app` → `http://localhost:5100/auth/callback` (dev) + URL prod HP à ajouter
  au déploiement.
- `core/main.py` : montage de `auth.router` (sans dépendance, ce sont les routes de
  login elles-mêmes) + dépendance de session sur `dashboard.router`.

### Erreurs & cas limites

- Keycloak injoignable au callback → page d'erreur explicite (pas de 500 nu), lien
  retour `/auth/login`.
- `state` invalide/absent au callback → 400, pas de fuite d'info sur la raison exacte.
- Session valide mais refresh token révoqué côté Keycloak (déconnexion admin) → 302 vers
  login au prochain rafraîchissement nécessaire.
- `AUTH_ENABLED=false` (dev local) : `exiger_session` renvoie un utilisateur factice
  (`sub="anonymous"`), même motif que `AUTH_ENABLED` dans l'agenda — permet de développer
  sans Keycloak qui tourne.

## Tests

- `shared.workplace_auth.verify_token` déjà testé côté agenda — réutilisé tel quel, pas
  de nouveau test unitaire sur la vérification JWT elle-même.
- Nouveaux tests `core/` : JWKS mocké (même motif que les tests agenda existants) ;
  roundtrip pose/lecture du cookie de session (signature, chiffrement refresh token) ;
  `/dashboard` sans cookie → 302 `/auth/login` ; `/dashboard` avec session valide → 200 ;
  `/dashboard` avec access token expiré + refresh token valide → 200 (refresh
  transparent, pas de redirection) ; `/dashboard` avec refresh token invalide → 302.
- Non-régression : `assistant`/`agenda`/`profil`/`usine` continuent de répondre sans
  session (suite `make test-core` existante ne doit montrer aucune régression).

## Hors périmètre (S171)

- Provisioning du compte Marina → S172.
- Faire réellement suivre l'identité de session jusqu'à l'agenda/restaurant (remplacer
  le pinning `AGENDA_USER_ID`/`ADMIN_COMPTE_ID`) → S173.
- UI de gestion de compte (changement de mot de passe, etc.) → délégué à Keycloak
  lui-même (pages Keycloak natives), pas reconstruit dans le dashboard.

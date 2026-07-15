# S172 — L'agenda comme application autonome + invitation de Marina

Sous-sprint 2/3 de [[epopee-identite-multiutilisateur-coeur]] (`docs/sprints/S171-S173-epopee-identite-multiutilisateur-coeur.md`),
préalable bloquant du roadmap agenda `docs/sprints/S174-S180-roadmap-agenda-best-in-class.md`.

## But

Le cadrage initial de S172 (voir le document d'épopée) prévoyait de provisionner le
compte Keycloak de Marina côté Cœur (`assistant-app`, realm `forge`), sur le modèle du
gabarit S23 (`client_provisioning.py`). En rediscutant avec l'utilisateur, le vrai besoin
est différent : **l'agenda doit devenir une application à part entière**, utilisable (a)
par l'assistant en S2S (déjà le cas) et (b) par d'autres personnes en direct — mais
*sans* leur donner accès au reste du Cœur. Ce document remplace le cadrage initial de
S172.

## Découverte de contexte — un système existe déjà, dormant

En explorant `briques/agenda/backend/` pour préparer le provisioning, il s'avère qu'un
système multi-personnes par calendrier existe **déjà dans le code**, présent depuis le
commit initial du repo mais jamais mis en avant ni exercé :

- **`CalendarMember`** (rôles `owner`/`editor`/`viewer`) + **`CalendarInvitation`**
  (email, token, expiration) — `briques/agenda/backend/models/orm.py`,
  `routers/invitations.py`, `routers/members.py`.
- Un client Keycloak dédié **`calendar-app`** (realm `forge`,
  `registrationAllowed: true`), totalement indépendant du client `assistant-app` utilisé
  par le dashboard du Cœur (S171) — un JWT `calendar-app` ne passe pas l'audience
  attendue par `core/auth.py`. Accès agenda ≠ accès au reste du Cœur, garanti par
  construction, sans rien à ajouter.
- Une page d'invitation autonome déjà fonctionnelle
  (`GET /invitations/{token}/page`, `templates.py`) : lien → login/inscription Keycloak
  (PKCE fait main, aucune dépendance externe) → `POST /invitations/{token}/accept` →
  devient `CalendarMember`.
- Le dialecte S2S de l'assistant (`X-API-Key == AGENDA_KEY`, S168, pinné sur
  `AGENDA_USER_ID="perso"`) est indépendant de tout ça et reste inchangé.

**Ce qui manque réellement** : l'UI de l'agenda (vue mois/semaine, TimeTree, Google
Sync) n'est *pas* une application à part — elle est codée en dur à l'intérieur de
`core/routers/dashboard.py` (un onglet du dashboard monolithique du Cœur, ~1000+ lignes
HTML/JS mêlées dans un fichier de 200 Ko). Donc même avec une invitation acceptée,
Marina n'aurait aujourd'hui nulle part où aller pour voir son agenda.

**Piège découvert en creusant** : `Calendar.user_id` est toujours `"perso"` aujourd'hui
(posé par le dialecte S2S). Si l'utilisateur principal se connectait à la nouvelle appli
avec son vrai compte `calendar-app` (sub Keycloak réel, différent de `"perso"`), il ne
serait reconnu propriétaire d'aucun calendrier existant (`get_user_role` compare
`cal.user_id == user_id`). Il faut un pont explicite (voir plus bas), sans toucher au
pinning `"perso"` du S2S assistant.

## Décisions actées avec l'utilisateur

- **Gate d'accès** : pas de nouveau rôle Keycloak à inventer côté Cœur — l'audience JWT
  différente entre `assistant-app` et `calendar-app` suffit déjà à séparer les deux
  mondes.
- **Provisioning de Marina** : abandon du gabarit `client_provisioning.py`/API admin
  Keycloak. Réutilisation telle quelle du système `CalendarInvitation`/`accept` déjà
  codé — pas de nouveau module de provisioning.
- **Onglet agenda du dashboard Cœur** : remplacé par une iframe vers la nouvelle appli
  autonome (même motif que Studio/Forge déjà embarqués en iframe), suppression du code
  dupliqué de `dashboard.py`.
- **Pont perso → compte réel** : script one-off lancé à la main (jamais exposé en
  route HTTP), pas de bouton self-service dans l'appli — évite qu'un compte quelconque
  puisse s'auto-attribuer la propriété d'un calendrier `"perso"`.
- **Périmètre fonctionnel v1** : liste des calendriers accessibles, vue mois/semaine des
  événements, créer/éditer/supprimer un événement, étiquettes, bouton inviter
  (propriétaire seulement). TimeTree (pont lecture seule) et Google Sync restent des
  vues *admin* réservées au dashboard du Cœur — pas portées dans l'appli autonome pour
  l'instant.
- **Envoi de l'invitation** : manuel (le propriétaire copie/transmet le lien
  lui-même) — pas d'intégration à la brique mail pour une seule personne à inviter.

## Architecture

Nouvelle appli servie **par la brique agenda elle-même**, même app FastAPI, même port
`8400` — qui est déjà exactement le `redirectUris` réservé à `calendar-app` dans
`forge-realm.json` (`http://localhost:8400/*`), aucun nouveau port/service/compose à
créer. HTML/JS **vanilla, sans build step**, même style que la page d'invitation
existante (PKCE fait main, token gardé en mémoire navigateur, appels à l'API REST
**déjà existante** via `Authorization: Bearer` — aucun changement backend nécessaire sur
les routes CRUD, elles acceptent déjà un JWT via `get_current_user`).

```
Marina                      Toi (primaire)                  Assistant (LLM)
  |                              |                                |
  | ouvre lien d'invitation      | ouvre /app (calendar-app)       | X-API-Key=AGENDA_KEY
  | -> login/inscription KC      | -> login KC (1re fois)          | sub="perso" (pinné)
  | -> accept -> CalendarMember  | -> lier_compte_perso.py (once)  |
  | (role viewer/editor)         | -> CalendarMember(role=owner)   |
  v                              v                                v
        API REST agenda existante (/calendars, /events, /members, /invitations)
```

### Nouveaux fichiers

- `briques/agenda/backend/routers/app_web.py` — sert le HTML/JS de l'appli
  (`GET /app`), même motif que `routers/invitations.py` pour la page d'acceptation.
- `briques/agenda/backend/templates_app.py` — le gabarit HTML/JS : login PKCE, liste
  calendriers, vue mois/semaine, formulaire créer/éditer événement, étiquettes, bouton
  inviter (visible seulement si rôle `owner`).
- `briques/agenda/backend/scripts/lier_compte_perso.py` — script one-off : prend le
  `sub` Keycloak réel de l'utilisateur principal (obtenu après sa première connexion) et
  ajoute une ligne `CalendarMember(role="owner")` sur chaque calendrier actuellement
  épinglé `"perso"`. Idempotent (vérifie l'absence de ligne avant insertion, même motif
  que `add_member`).

### Session côté navigateur

La page d'invitation existante ne garde le token qu'en mémoire JS (usage ponctuel,
une seule action). L'appli, elle, sert un usage quotidien : le `refresh_token` est donc
gardé en `localStorage` (persiste entre rechargements/fermetures d'onglet), et l'access
token est rafraîchi silencieusement au chargement — même logique de rafraîchissement que
`core/auth.py::exiger_session`, mais côté client puisqu'il n'y a ni cookie ni session
serveur ici (appels JSON directs avec `Authorization: Bearer`). Refresh token
invalide/expiré ⇒ retour à l'écran de login.

### Modifications

- `core/routers/dashboard.py` — l'onglet agenda devient une iframe
  (`url_brique("agenda", ...)` vers `/app`, même motif S128 que les autres briques
  embarquées), suppression du JS/HTML dupliqué.
- Pas de changement sur `oria-stack/infra/keycloak/realms/forge-realm.json` — le client
  `calendar-app` est déjà correctement configuré (PKCE, `registrationAllowed`,
  `redirectUris`).
- Pas de changement sur `briques/agenda/backend/auth.py`/`utils/access.py` — le contrôle
  d'accès `owner`/`editor`/`viewer` existant est réutilisé tel quel.

## Erreurs & cas limites

- JWT invalide/expiré, Keycloak injoignable → l'appli redirige vers l'écran de login
  (même logique que `get_current_user`, jamais de 500 nu exposé).
- Invitation expirée/déjà utilisée/calendrier introuvable → déjà géré par le code
  existant (`410`/`409`/`404` dans `accept_invitation`/`require_calendar_access`), rien à
  changer.
- Script `lier_compte_perso.py` relancé deux fois → idempotent, ne duplique pas la ligne
  `CalendarMember`.
- Avant que le script tourne, l'utilisateur principal connecté via `calendar-app` voit une
  liste de calendriers vide — attendu, à documenter dans le README de la brique.

## Tests

Point important découvert en creusant : **`invitations.py`, `members.py` et
`calendars.py` n'ont aujourd'hui aucun test** (`briques/agenda/backend/tests/` n'a pas de
`test_invitations.py`/`test_members.py`/`test_calendars.py`) — ce système existe depuis
le commit initial mais n'a jamais été exercé. On comble ce trou en même temps que le
nouveau travail plutôt que de construire par-dessus du code jamais vérifié :

- `test_calendars.py` : CRUD + contrôle d'accès par rôle (`owner`/`editor`/`viewer`).
- `test_members.py` : ajout/suppression de membre, contrôle d'accès (`owner` seulement),
  doublon → 409.
- `test_invitations.py` : cycle complet créer → accepter → devenir membre ; cas
  expirée (410), déjà utilisée (409), calendrier introuvable (404).
- `test_lier_compte_perso.py` : le script one-off — idempotence, bon rôle posé, ne
  touche pas aux calendriers d'autres `user_id`.
- `test_app_web.py` : smoke test sur la nouvelle route `GET /app` (200, HTML bien
  formé).
- Le flux OIDC PKCE navigateur (login réel de Marina et de l'utilisateur principal)
  reste vérifié manuellement en LIVE, comme pour S171 — pas automatisable sans
  navigateur.

## Hors périmètre (S172)

- TimeTree/Google Sync dans l'appli autonome — restent des vues admin du dashboard Cœur.
- Envoi automatique de l'email d'invitation (brique mail) — lien transmis manuellement.
- Routage S2S par identité réelle pour l'assistant (remplacer le pinning
  `AGENDA_USER_ID="perso"`) → S173, inchangé par ce sprint.
- Gérer plus de deux personnes (au-delà de Marina) — le système `CalendarInvitation`
  le permet déjà nativement, aucun travail supplémentaire nécessaire si le besoin se
  présente.

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

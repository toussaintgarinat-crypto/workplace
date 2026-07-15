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

## Dialecte S2S (inchangé)

L'assistant Cœur continue d'accéder l'agenda via `X-API-Key: {AGENDA_KEY}`, pinné sur `AGENDA_USER_ID="perso"`. Aucune modification ici, aucun impact sur ce chemin.

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

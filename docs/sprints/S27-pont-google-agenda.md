# Sprint S27 — Pont Google Agenda (sync consentie, pull one-way)

> **Statut** : ✅ **CODE LIVRÉ + PROUVÉ OFFLINE** (24 tests + E2E HTTP) — **2026-06-09**.
> **Reste LIVE** (honnêteté) : projet Google Cloud (client_id/secret) + consentement réel
> + pull d'un vrai compte Google. Bloqué sur des credentials Google à fournir.

## Objectif

Brancher la brique **Agenda** (port 8400) sur **Google Agenda** d'un utilisateur, de façon
**consentie et révocable**. Incrément volontairement resserré (cf. règle anti-dispersion S20) :
**pull one-way** Google → brique, idempotent, sans push ni suppression. Le coffre de tokens
chiffrés est **rapatrié de `workspace/assistant`** (`vault.py`) et adapté au SQLAlchemy 2.0
async de la brique.

## Décisions actées

- **Consentement explicite** : l'utilisateur ouvre l'URL Google (`/google/connect`), accepte ;
  **révocable** à tout moment (`DELETE /google/disconnect` purge le coffre).
- **Pull one-way d'abord** : on lit Google, on ne pousse rien et on ne supprime rien chez Google.
  Le push bidirectionnel est une évolution, pas ce sprint.
- **Idempotence** : un événement Google déjà importé (même `external_id`) est **mis à jour**, pas
  dupliqué. Les événements **`source="manuel"`** (saisis dans la brique) ne sont **jamais** touchés.
- **Calendrier dédié** : les events Google atterrissent dans un calendrier `« Google »` propre à
  l'utilisateur (créé une seule fois), distinct de ses calendriers manuels.
- **Sans SDK Google** : on parle directement aux endpoints HTTP OAuth/Calendar via `httpx` (déjà
  présent). Aucune nouvelle dépendance runtime.
- **Secret obligatoire** : `VAULT_SECRET` requis dès qu'on stocke un token ; le coffre lève sinon
  (jamais de token en clair par accident). Pont **désactivé** (503) si `GOOGLE_CLIENT_ID/SECRET`
  absents.

## Ce qui a été livré (code)

### Coffre de tokens — `backend/vault.py` (+ table `UserToken`)
- AES-GCM (clé = SHA-256 du `VAULT_SECRET`), nonce 12o préfixé au chiffré.
- `encrypt/decrypt`, `upsert_token`, `get_access_token`, `get_refresh_token`, `delete_token`.
- Subtilité : un `refresh_token` absent à l'upsert **ne doit pas écraser** celui déjà stocké
  (Google ne le renvoie qu'au 1er consentement).
- Table `user_tokens` : `(user_id, provider)` unique, tokens en `LargeBinary`, `expires_at`, `scope`.

### Flux OAuth — `backend/services/google_oauth.py`
- `build_auth_url(state)` : `access_type=offline` + `prompt=consent` (garantit le refresh_token),
  `state` = identité de l'utilisateur.
- `exchange_code(code)` / `refresh_access_token(refresh)` : échange/renouvellement, sortie normalisée.

### Sync — `backend/services/google_calendar.py`
- `_valid_access_token` : renvoie un access_token valide, **auto-refresh** si expiré (et range le neuf).
- `map_google_event` : projette un item Google (timed/all-day, annulés ignorés) sur le modèle `Event`.
- `_get_or_create_google_calendar`, `upsert_events` (idempotent), `sync_user` (orchestration).

### Router — `backend/routers/google_sync.py` (`/google/*`)
- `GET /google/connect` → URL de consentement · `GET /google/callback` → échange + stockage
- `GET /google/status` → connecté + expiration · `POST /google/sync` → pull (timeMin/timeMax)
- `DELETE /google/disconnect` → purge (révocation)

### Modèle — `Event.source` (`manuel`/`google`) + `Event.external_id` (clé d'idempotence)
### Config / compose — `VAULT_SECRET`, `GOOGLE_CLIENT_ID/SECRET`, `GOOGLE_REDIRECT_URI`, `GOOGLE_SCOPE`

## Preuves OFFLINE (2026-06-09)

- **24 tests verts** (`pytest`) : coffre (round-trip, mauvaise clé échoue, secret requis, upsert
  préserve le refresh, purge), mapping (timed/all-day/annulé/sans-date/sans-titre), idempotence
  (create→re-sync update sans doublon, titre mis à jour, manuel intact, calendrier créé 1×),
  auto-refresh (expiré→refresh→rangé, sans refresh→erreur, non connecté→erreur, vivant→direct),
  OAuth (URL offline+state, exchange normalisé, erreur, refresh).
- **E2E HTTP** (TestClient, Google mocké) : status `False` → connect (URL Google) → callback `200`
  → status `True` → sync#1 `{created:2}` → sync#2 `{created:0, updated:2}` (idempotent) →
  disconnect `True` → status `False`.

## Reste à prouver LIVE (honnêteté technique)

1. **Projet Google Cloud** : créer un OAuth client (type Web), scope `calendar.readonly`, et
   enregistrer l'URI de redirection (= `GOOGLE_REDIRECT_URI`, à l'octet près).
2. **Consentement réel** : ouvrir l'URL `/google/connect`, accepter, vérifier le callback range
   bien access+refresh chiffrés en base.
3. **Pull réel** : `POST /google/sync` contre un vrai compte, vérifier les events dans le
   calendrier `« Google »` et l'idempotence sur re-sync.
4. **Durcissement state** (sécurité) : le `state` du callback porte aujourd'hui l'identité en clair.
   En déploiement, le remplacer par un state opaque vérifié (anti-CSRF) — noté ici, hors incrément.

## Hors périmètre (évolutions)

- Push brique → Google (bidirectionnel), suppression propagée, sync incrémentale (syncToken),
  multi-calendriers Google, déclencheur périodique (cron) — déclencheur réel = l'assistant perso.

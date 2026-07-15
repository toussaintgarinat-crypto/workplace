# S173 — Routage S2S par utilisateur réel — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Faire en sorte que le chat web de l'assistant (dashboard du Cœur) attribue les événements/rappels d'agenda au vrai utilisateur Keycloak connecté, au lieu du défaut `"perso"` — le chemin Telegram est déjà câblé (rien à coder), seul le chemin web manque.

**Architecture:** `core/routers/assistant.py::assistant_chat` lit déjà un champ optionnel `corps.utilisateur` et le pose dans `contexte_tenant` (lu ensuite par `core/agenda.py` pour le S2S). On ajoute une petite fonction pure `_resoudre_utilisateur(corps, request)` : priorité au `utilisateur` explicite du corps (Telegram/S2S, inchangé), sinon on tente de lire le sub de la session S171 (nouvelle fonction `auth.sub_session_optionnel`), sinon `None` (défaut `"perso"` inchangé côté agenda).

**Tech Stack:** FastAPI, cookies chiffrés AES-GCM (motif S171 existant), pytest.

## Global Constraints

- Ne pas modifier `core/contexte_tenant.py`, `core/agenda.py`, `briques/connexion/{correspondance.py,pont.py,main.py}` — déjà corrects, le chemin Telegram fonctionne déjà de bout en bout.
- Ne pas modifier `core/outils_communs.py::_entetes_brique`/`ADMIN_COMPTE_ID` — hors périmètre (ADR `docs/decisions/2026-07-13-surface-de-service-role-admin.md` déjà tranché, sert toutes les briques manifest).
- Ne pas toucher au restaurant.
- `sub_session_optionnel` ne doit **jamais** lever d'exception ni bloquer — cookie absent/corrompu ⇒ `None`, pas de vérification de fraîcheur du token Keycloak (ce n'est pas un point de sécurité ici, `require_calendar_access` reste le vrai contrôle d'accès côté agenda).
- Noms de fonctions en français dans `core/` (convention déjà en place).
- Tests : suivre le motif déjà en place dans `core/test_auth.py` (helper `_fake_request(cookies: dict) -> Request` pour construire une requête Starlette avec cookies, sans lancer de vrai serveur).
- Run tests : `cd core && python3 -m pytest test_auth.py test_assistant_routes.py -v` puis la suite complète `python3 -m pytest -v` (426 tests avant ce sprint — aucune régression attendue).

---

## File Structure

- **Modify** `core/auth.py` — ajoute `sub_session_optionnel(request: Request) -> str | None`.
- **Modify** `core/test_auth.py` — 3 nouveaux tests pour cette fonction.
- **Modify** `core/routers/assistant.py` — ajoute l'import `auth`, la fonction pure `_resoudre_utilisateur(corps: dict, request: Request) -> str | None`, ajoute `request: Request` au handler `assistant_chat`, remplace `utilisateur = corps.get("utilisateur")` par `utilisateur = _resoudre_utilisateur(corps, request)`.
- **Create** `core/test_assistant_routes.py` — teste `_resoudre_utilisateur` directement (aucun besoin de `TestClient`/mock du flux SSE : la fonction est pure).
- **Modify** `briques/agenda/backend/README.md` — corrige la description du dialecte S2S (deux chemins distincts, pas un seul) + note le risque croisé `AUTH_ENABLED`/`CALENDAR_SERVICE_TOKEN`.
- **Modify** `briques/connexion/README.md` — retire l'avertissement devenu faux (« `/assistant/chat` n'isole pas... pas de paramètre d'utilisateur ») et met à jour la convention de liaison (vrai sub Keycloak, pas une étiquette libre).

---

### Task 1: `sub_session_optionnel` — lecture optionnelle de la session S171

**Files:**
- Modify: `core/auth.py`
- Test: `core/test_auth.py`

**Interfaces:**
- Consomme : `dechiffrer_cookie` (existant, `core/auth.py`), `COOKIE_SESSION` (existant, constante `core/auth.py`).
- Produces: `sub_session_optionnel(request: Request) -> str | None` — utilisé par Task 2.

- [ ] **Step 1: Écrire les tests (échouent — la fonction n'existe pas)**

Ajouter à la fin de `core/test_auth.py` :

```python
def test_sub_session_optionnel_cookie_valide():
    cookie = auth.chiffrer_cookie({"sub": "marina", "refresh_token": "rt-1"})
    r = auth.sub_session_optionnel(_fake_request({auth.COOKIE_SESSION: cookie}))
    assert r == "marina"


def test_sub_session_optionnel_pas_de_cookie():
    assert auth.sub_session_optionnel(_fake_request({})) is None


def test_sub_session_optionnel_cookie_corrompu():
    r = auth.sub_session_optionnel(_fake_request({auth.COOKIE_SESSION: "pas-un-cookie-valide"}))
    assert r is None
```

(`_fake_request` est déjà défini plus haut dans ce fichier — réutilisé tel quel, aucune modification nécessaire.)

- [ ] **Step 2: Lancer les tests pour vérifier l'échec**

Run: `cd core && python3 -m pytest test_auth.py -v -k sub_session_optionnel`
Expected: FAIL avec `AttributeError: module 'auth' has no attribute 'sub_session_optionnel'`

- [ ] **Step 3: Implémenter**

Dans `core/auth.py`, ajouter (après la fonction `exiger_session`, fin de fichier) :

```python
def sub_session_optionnel(request: Request) -> str | None:
    """Sub Keycloak de la session S171 si le cookie est présent et valide, sinon `None`.

    Volontairement léger : pas de vérification de fraîcheur du token (pas un point de
    sécurité — sert seulement à attribuer « pour qui » dans le chat de l'assistant ; le
    vrai contrôle d'accès reste `require_calendar_access` côté agenda, inchangé).
    Cookie absent ou corrompu ⇒ `None`, jamais d'exception ni de blocage (S173)."""
    session = dechiffrer_cookie(request.cookies.get(COOKIE_SESSION))
    return session.get("sub") if session else None
```

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent**

Run: `cd core && python3 -m pytest test_auth.py -v`
Expected: PASS (tous les tests du fichier, y compris les 3 nouveaux)

- [ ] **Step 5: Commit**

```bash
git add core/auth.py core/test_auth.py
git commit -m "feat(coeur): sub_session_optionnel — lecture non-bloquante de la session S171 (S173)"
```

---

### Task 2: Priorité d'identité dans le chat de l'assistant

**Files:**
- Modify: `core/routers/assistant.py`
- Test: `core/test_assistant_routes.py` (nouveau fichier)

**Interfaces:**
- Consomme : `auth.sub_session_optionnel(request: Request) -> str | None` (Task 1).
- Produces : `_resoudre_utilisateur(corps: dict, request: Request) -> str | None` — fonction pure, testable sans `TestClient` ni mock du flux SSE.

- [ ] **Step 1: Écrire le test (échoue — la fonction n'existe pas)**

Créer `core/test_assistant_routes.py` :

```python
"""Priorité d'identité du chat de l'assistant (S173) : `utilisateur` explicite du corps
(Telegram/S2S) prime toujours sur la session web ; la session ne sert que de repli.

Fonction pure, testée directement — pas besoin de TestClient ni de mocker le flux SSE
(le reste du handler `assistant_chat` est inchangé par ce sprint).

$ cd core && python3 -m pytest test_assistant_routes.py -v
"""
import os

os.environ.setdefault("VAULT_SECRET", "test-secret-0123456789")
os.environ.setdefault("GATEWAY_KEY", "test")
os.environ.setdefault("AUTH_SESSION_SECRET", "test-session-secret-0123456789")

import auth  # noqa: E402
from routers.assistant import _resoudre_utilisateur  # noqa: E402
from test_auth import _fake_request  # noqa: E402


def test_utilisateur_explicite_du_corps_garde_la_priorite():
    cookie = auth.chiffrer_cookie({"sub": "marina", "refresh_token": "rt-1"})
    corps = {"utilisateur": "telegram-perso"}
    r = _resoudre_utilisateur(corps, _fake_request({auth.COOKIE_SESSION: cookie}))
    assert r == "telegram-perso"


def test_pas_de_corps_mais_session_valide_utilise_le_sub():
    cookie = auth.chiffrer_cookie({"sub": "marina", "refresh_token": "rt-1"})
    r = _resoudre_utilisateur({}, _fake_request({auth.COOKIE_SESSION: cookie}))
    assert r == "marina"


def test_ni_corps_ni_session_renvoie_none():
    r = _resoudre_utilisateur({}, _fake_request({}))
    assert r is None
```

- [ ] **Step 2: Lancer le test pour vérifier l'échec**

Run: `cd core && python3 -m pytest test_assistant_routes.py -v`
Expected: FAIL avec `ImportError: cannot import name '_resoudre_utilisateur' from 'routers.assistant'`

- [ ] **Step 3: Implémenter**

Dans `core/routers/assistant.py`, ajouter l'import (dans le bloc d'imports existant, ordre alphabétique déjà en place — juste après `import agenda`) :

```python
import auth
```

Ajouter la fonction, juste avant `async def assistant_chat(corps: dict):` (ligne ~78) :

```python
def _resoudre_utilisateur(corps: dict, request: Request) -> str | None:
    """Identité à poser dans `contexte_tenant` pour ce tour de conversation.

    Priorité : `utilisateur` explicite du corps (Telegram/S2S, S78 — déjà résolu par
    `briques/connexion` ou un appelant S2S) > sub de la session web S171 si présente >
    `None` (défaut `"perso"` inchangé côté agenda). Jamais bloquant : une session
    absente/corrompue ne fait pas échouer le chat, elle retombe simplement au défaut."""
    return corps.get("utilisateur") or auth.sub_session_optionnel(request)
```

Modifier la signature du handler (import `Request` déjà disponible via `fastapi` — l'ajouter à l'import existant `from fastapi import APIRouter, File, HTTPException, UploadFile`) :

```python
from fastapi import APIRouter, File, HTTPException, Request, UploadFile
```

```python
async def assistant_chat(corps: dict, request: Request):
```

Remplacer la ligne existante :

```python
    utilisateur = corps.get("utilisateur")
```

par :

```python
    utilisateur = _resoudre_utilisateur(corps, request)
```

(Le reste du handler — `if utilisateur: contexte_tenant.definir_contexte(utilisateur=utilisateur)` et tout ce qui suit — reste **inchangé**.)

- [ ] **Step 4: Lancer le test pour vérifier qu'il passe**

Run: `cd core && python3 -m pytest test_assistant_routes.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Lancer la suite complète pour vérifier l'absence de régression**

Run: `cd core && python3 -m pytest -v`
Expected: PASS (426 tests d'avant + 3 (Task 1) + 3 (Task 2) = 432, 0 échec)

- [ ] **Step 6: Commit**

```bash
git add core/routers/assistant.py core/test_assistant_routes.py
git commit -m "feat(coeur): chat web attribue le sub de session si aucun utilisateur explicite (S173)"
```

---

### Task 3: Documentation — risque croisé + convention d'identité

**Files:**
- Modify: `briques/agenda/backend/README.md`
- Modify: `briques/connexion/README.md`

**Interfaces:**
- Aucune (documentation pure, pas de code, pas de test).

- [ ] **Step 1: Corriger la description du dialecte S2S de l'agenda + noter le risque croisé**

Dans `briques/agenda/backend/README.md`, remplacer la section :

```markdown
## Dialecte S2S (inchangé)

L'assistant Cœur continue d'accéder l'agenda via `X-API-Key: {AGENDA_KEY}`, pinné sur `AGENDA_USER_ID="perso"`. Aucune modification ici, aucun impact sur ce chemin.
```

par :

```markdown
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
```

- [ ] **Step 2: Corriger l'avertissement devenu faux + la convention de liaison**

Dans `briques/connexion/README.md`, remplacer le bloc :

```markdown
> ⚠️ **Limite honnête (v0.1.0).** `/assistant/chat` n'isole pas les permissions par
> utilisateur (pas de paramètre d'utilisateur, identité globale). Le mapping multi-utilisateur
> sert au routage / journal / consentement **côté brique**, et on injecte un message *système*
> « qui parle » au début de chaque conversation. Une vraie isolation par utilisateur côté
> noyau est un sprint ultérieur.
```

par :

```markdown
> **Depuis S173** : le champ `utilisateur` envoyé à `/assistant/chat` est bien lu par le
> Cœur (`contexte_tenant`) et détermine l'identité utilisée pour les appels S2S vers
> l'agenda (`X-User-Id`) — les rappels/événements créés via l'assistant sont donc
> attribués à la bonne personne, pas seulement mentionnés dans un message système. Reste
> vrai : ceci ne remplace pas un contrôle d'accès complet par utilisateur sur toutes les
> briques (agenda seulement pour l'instant), et le mapping ci-dessous sert toujours de
> point d'entrée pour ça.
```

Remplacer les deux exemples `curl` de la section « Relier un interlocuteur » :

```bash
curl -X POST localhost:5870/correspondances \
  -H 'Content-Type: application/json' \
  -d '{"reseau":"telegram","id_externe":"123456","utilisateur":"toi@workplace"}'

# ou par code de liaison communiqué par l'interlocuteur :
curl -X POST localhost:5870/correspondances \
  -d '{"code":"A1B2C3","utilisateur":"toi@workplace"}'
```

par :

```bash
# `utilisateur` doit être le vrai sub Keycloak `calendar-app` de la personne (obtenu
# après sa 1re connexion à l'agenda /app, cf. briques/agenda/backend/README.md) — pas
# une étiquette libre : c'est ce qui permet à un rappel créé via Telegram de rejoindre
# le bon compte agenda (S173).
curl -X POST localhost:5870/correspondances \
  -H 'Content-Type: application/json' \
  -d '{"reseau":"telegram","id_externe":"123456","utilisateur":"<sub-keycloak-reel>"}'

# ou par code de liaison communiqué par l'interlocuteur :
curl -X POST localhost:5870/correspondances \
  -d '{"code":"A1B2C3","utilisateur":"<sub-keycloak-reel>"}'
```

- [ ] **Step 3: Commit**

```bash
git add briques/agenda/backend/README.md briques/connexion/README.md
git commit -m "docs(s173): deux chemins S2S agenda distincts, risque croisé AUTH_ENABLED/CALENDAR_SERVICE_TOKEN, convention sub Keycloak pour /correspondances"
```

---

## Vérification manuelle LIVE (différée à la fin de S180)

Comme convenu ([[feedback-live-differe-fin-s180]]), aucune vérification Docker/navigateur
réelle maintenant. À faire au sprint de preuve final, une fois `AUTH_ENABLED=true` +
`KEYCLOAK_AUDIENCE=calendar-app` + `CALENDAR_SERVICE_TOKEN` posés ensemble :

1. Lier le compte Telegram de l'utilisateur principal (et de Marina) à leur vrai sub via
   `POST /correspondances` (`briques/connexion`).
2. Depuis Telegram, demander à l'assistant de créer un rappel → vérifier qu'il apparaît
   dans `/app` avec le bon propriétaire (`CalendarMember.user_id` = le sub lié).
3. Depuis le chat web du dashboard (connecté via S171), même vérification sans passer par
   `corps.utilisateur` — la session doit suffire.
4. Vérifier qu'un message Telegram d'un interlocuteur non lié reçoit toujours l'accueil
   avec code de liaison (non-régression du flux de consentement existant).

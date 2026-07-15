# S172 — L'agenda comme application autonome + invitation de Marina — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Donner à l'agenda (`briques/agenda/backend/`) une application web autonome, servie par la brique elle-même, authentifiée par le client Keycloak `calendar-app` (indépendant du dashboard du Cœur) — pour que Marina puisse l'utiliser via le système d'invitation déjà codé, sans jamais avoir accès au reste du Cœur.

**Architecture:** Le backend agenda a déjà tout le nécessaire (CRUD calendriers/événements/étiquettes, `CalendarMember`/`CalendarInvitation`, JWT `get_current_user`) mais n'a **aucun test** sur cette partie et **aucune UI** en dehors de la page d'acceptation d'invitation. Ce plan (1) comble le trou de tests sur le code existant (calendriers/membres/invitations), (2) ajoute un script one-off qui relie le compte Keycloak réel de l'utilisateur principal à ses calendriers `"perso"`, (3) construit une nouvelle page `/app` (vanilla HTML/JS, PKCE, même port 8400) qui consomme l'API REST existante, et (4) remplace l'onglet agenda du dashboard du Cœur par une iframe vers cette page.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, SQLite en mémoire pour les tests (fixture `db` existante), HTML/JS vanilla sans build step (même motif que `templates.py`).

## Global Constraints

- Ne jamais toucher au dialecte S2S de l'assistant (`AGENDA_KEY`/`AGENDA_USER_ID="perso"` dans `briques/agenda/backend/auth.py`/`config.py`) — aucune régression sur ce chemin.
- Ne pas modifier `oria-stack/infra/keycloak/realms/forge-realm.json` — le client `calendar-app` est déjà correctement configuré (PKCE, `registrationAllowed: true`, `redirectUris: http://localhost:8400/*`).
- Réutiliser `get_current_user`/`require_calendar_access`/les schémas Pydantic existants tels quels — ne pas les modifier.
- Style vanilla HTML/JS sans build step, même motif que `briques/agenda/backend/templates.py` (littéraux JSON injectés à la place de marqueurs `%%…%%`, PKCE écrit à la main).
- Dans `core/`, noms de fonctions en français ; dans `briques/agenda/backend/`, garder l'anglais (convention déjà en place dans ce dossier : `list_events`, `get_current_user`, etc.).
- Tests agenda : appeler les fonctions de route **directement** avec la fixture `db` + un dict `user` (motif déjà en place dans `tests/test_labels.py`, `tests/test_timetree_routes.py`) — pas de `TestClient`, pas de mock JWKS (ces tests contournent `get_current_user` en appelant la route directement).
- `pytest.ini` : `asyncio_mode = auto`, `testpaths = tests` — lancer avec `cd briques/agenda/backend && python3 -m pytest tests/ -v`.
- Documents/commentaires (`attachments.py`/`comments.py`) restent hors périmètre de la nouvelle appli v1 (non demandés dans le design approuvé) ; TimeTree/Google Sync restent des vues admin du dashboard du Cœur, inchangées par ce plan.

---

## File Structure

- **Create** `briques/agenda/backend/tests/test_calendars.py` — CRUD + contrôle d'accès par rôle (code existant, non testé).
- **Create** `briques/agenda/backend/tests/test_members.py` — ajout/suppression de membre (code existant, non testé).
- **Create** `briques/agenda/backend/tests/test_invitations.py` — cycle créer → accepter → membre (code existant, non testé).
- **Create** `briques/agenda/backend/lier_compte_perso.py` — script one-off + fonction testable `lier_compte_perso(sub, db)`.
- **Create** `briques/agenda/backend/tests/test_lier_compte_perso.py`.
- **Create** `briques/agenda/backend/templates_app.py` — gabarit HTML/JS de l'appli (`page_app`).
- **Create** `briques/agenda/backend/routers/app_web.py` — route `GET /app`.
- **Create** `briques/agenda/backend/tests/test_app_web.py` — smoke test de la route.
- **Modify** `briques/agenda/backend/main.py` — monte `app_web.router`.
- **Modify** `core/urls_ui.py` — ajoute `"AGENDA": (8400, "/app")` à `BRIQUES_UI`.
- **Modify** `core/routers/dashboard.py` — l'onglet agenda devient une iframe ; suppression du JS/HTML mort (calendrier + modale événement + mini-gestion étiquettes), Google Sync/TimeTree inchangés.

---

### Task 1: Tests calendriers (code existant, non testé)

**Files:**
- Test: `briques/agenda/backend/tests/test_calendars.py`

**Interfaces:**
- Consomme : `routers.calendars.{list_calendars,create_calendar,get_calendar,update_calendar,delete_calendar}` (déjà codés), `models.schemas.{CalendarCreate,CalendarUpdate}`, fixture `db` (`tests/conftest.py`).

- [ ] **Step 1: Écrire les tests**

Créer `briques/agenda/backend/tests/test_calendars.py` :

```python
"""CRUD calendriers + contrôle d'accès par rôle (owner/editor/viewer).

On appelle les fonctions de route directement avec la session de test, comme
test_labels.py / test_timetree_routes.py — pas de TestClient, pas de JWT.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from models.orm import Calendar, CalendarMember
from models.schemas import CalendarCreate, CalendarUpdate
from routers import calendars as R

OWNER = {"sub": "perso"}
AUTRE = {"sub": "marina-sub"}


async def _cal(db, user_id="perso", name="Perso") -> Calendar:
    cal = Calendar(user_id=user_id, name=name, is_default=True)
    db.add(cal)
    await db.commit()
    await db.refresh(cal)
    return cal


@pytest.mark.asyncio
async def test_create_calendar_devient_owner(db):
    out = await R.create_calendar(CalendarCreate(name="Perso"), db=db, user=OWNER)
    assert out.name == "Perso"
    assert out.role == "owner"


@pytest.mark.asyncio
async def test_list_calendars_separe_owned_et_membre(db):
    cal_owned = await _cal(db, user_id="perso", name="Perso")
    cal_partage = await _cal(db, user_id="perso", name="Famille")
    db.add(CalendarMember(calendar_id=cal_partage.id, user_id="marina-sub", role="editor"))
    await db.commit()

    lst_owner = await R.list_calendars(db=db, user=OWNER)
    assert {c.name: c.role for c in lst_owner} == {"Perso": "owner", "Famille": "owner"}

    lst_marina = await R.list_calendars(db=db, user=AUTRE)
    assert {c.name: c.role for c in lst_marina} == {"Famille": "editor"}


@pytest.mark.asyncio
async def test_get_calendar_refuse_sans_acces(db):
    cal = await _cal(db)
    with pytest.raises(HTTPException) as exc:
        await R.get_calendar(cal.id, db=db, user=AUTRE)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_update_calendar_exige_editor_minimum(db):
    cal = await _cal(db)
    db.add(CalendarMember(calendar_id=cal.id, user_id="marina-sub", role="viewer"))
    await db.commit()
    with pytest.raises(HTTPException) as exc:
        await R.update_calendar(cal.id, CalendarUpdate(name="Nouveau nom"), db=db, user=AUTRE)
    assert exc.value.status_code == 404

    out = await R.update_calendar(cal.id, CalendarUpdate(name="Nouveau nom"), db=db, user=OWNER)
    assert out.name == "Nouveau nom"


@pytest.mark.asyncio
async def test_delete_calendar_exige_owner(db):
    cal = await _cal(db)
    db.add(CalendarMember(calendar_id=cal.id, user_id="marina-sub", role="editor"))
    await db.commit()
    with pytest.raises(HTTPException) as exc:
        await R.delete_calendar(cal.id, db=db, user=AUTRE)
    assert exc.value.status_code == 404

    await R.delete_calendar(cal.id, db=db, user=OWNER)
    with pytest.raises(HTTPException):
        await R.get_calendar(cal.id, db=db, user=OWNER)
```

- [ ] **Step 2: Lancer les tests**

Run: `cd briques/agenda/backend && python3 -m pytest tests/test_calendars.py -v`
Expected: **PASS** — `routers/calendars.py` existe déjà et implémente ce comportement ; ce test caractérise du code jamais exercé jusqu'ici. Si un test échoue, c'est un vrai bug du code existant à corriger dans `routers/calendars.py` (ne pas modifier le test pour le faire coller à un bug).

- [ ] **Step 3: Commit**

```bash
git add briques/agenda/backend/tests/test_calendars.py
git commit -m "test(agenda): couvre calendars.py (CRUD + accès par rôle), jamais testé jusqu'ici"
```

---

### Task 2: Tests membres (code existant, non testé)

**Files:**
- Test: `briques/agenda/backend/tests/test_members.py`

**Interfaces:**
- Consomme : `routers.members.{list_members,add_member,remove_member}`, `models.schemas.MemberAdd`.

- [ ] **Step 1: Écrire les tests**

Créer `briques/agenda/backend/tests/test_members.py` :

```python
"""Membres d'un calendrier — ajout/suppression, contrôle d'accès owner-only."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from models.orm import Calendar, CalendarMember
from models.schemas import MemberAdd
from routers import members as R

OWNER = {"sub": "perso"}
MARINA = {"sub": "marina-sub"}


async def _cal(db) -> Calendar:
    cal = Calendar(user_id="perso", name="Perso", is_default=True)
    db.add(cal)
    await db.commit()
    await db.refresh(cal)
    return cal


@pytest.mark.asyncio
async def test_add_member_par_owner(db):
    cal = await _cal(db)
    out = await R.add_member(cal.id, MemberAdd(user_id="marina-sub", role="editor"), db=db, user=OWNER)
    assert out.user_id == "marina-sub" and out.role == "editor"

    lst = await R.list_members(cal.id, db=db, user=OWNER)
    assert [m.user_id for m in lst] == ["marina-sub"]


@pytest.mark.asyncio
async def test_add_member_refuse_si_pas_owner(db):
    cal = await _cal(db)
    db.add(CalendarMember(calendar_id=cal.id, user_id="marina-sub", role="editor"))
    await db.commit()
    with pytest.raises(HTTPException) as exc:
        await R.add_member(cal.id, MemberAdd(user_id="autre", role="viewer"), db=db, user=MARINA)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_add_member_doublon_409(db):
    cal = await _cal(db)
    await R.add_member(cal.id, MemberAdd(user_id="marina-sub", role="viewer"), db=db, user=OWNER)
    with pytest.raises(HTTPException) as exc:
        await R.add_member(cal.id, MemberAdd(user_id="marina-sub", role="editor"), db=db, user=OWNER)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_remove_member(db):
    cal = await _cal(db)
    await R.add_member(cal.id, MemberAdd(user_id="marina-sub", role="viewer"), db=db, user=OWNER)
    await R.remove_member(cal.id, "marina-sub", db=db, user=OWNER)
    assert await R.list_members(cal.id, db=db, user=OWNER) == []


@pytest.mark.asyncio
async def test_remove_member_introuvable_404(db):
    cal = await _cal(db)
    with pytest.raises(HTTPException) as exc:
        await R.remove_member(cal.id, "jamais-invite", db=db, user=OWNER)
    assert exc.value.status_code == 404
```

- [ ] **Step 2: Lancer les tests**

Run: `cd briques/agenda/backend && python3 -m pytest tests/test_members.py -v`
Expected: **PASS** (code existant). Un échec révèle un bug réel dans `routers/members.py` à corriger.

- [ ] **Step 3: Commit**

```bash
git add briques/agenda/backend/tests/test_members.py
git commit -m "test(agenda): couvre members.py (ajout/suppression, accès owner-only)"
```

---

### Task 3: Tests invitations (code existant, non testé)

**Files:**
- Test: `briques/agenda/backend/tests/test_invitations.py`

**Interfaces:**
- Consomme : `routers.invitations.{list_invitations,create_invitation,get_invitation,accept_invitation}`, `models.schemas.InvitationCreate`.

- [ ] **Step 1: Écrire les tests**

Créer `briques/agenda/backend/tests/test_invitations.py` :

```python
"""Cycle complet d'invitation : créer → consulter → accepter → devenir membre.

Cas limites : expirée, déjà utilisée, calendrier introuvable.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from models.orm import Calendar, CalendarInvitation
from models.schemas import InvitationCreate
from routers import invitations as R

OWNER = {"sub": "perso"}
MARINA = {"sub": "marina-sub"}


async def _cal(db) -> Calendar:
    cal = Calendar(user_id="perso", name="Famille", is_default=True)
    db.add(cal)
    await db.commit()
    await db.refresh(cal)
    return cal


@pytest.mark.asyncio
async def test_cycle_complet_invitation(db):
    cal = await _cal(db)
    inv = await R.create_invitation(
        cal.id, InvitationCreate(email="marina@example.fr", role="editor"), db=db, user=OWNER
    )
    assert inv.role == "editor" and inv.used_at is None

    lu = await R.get_invitation(inv.token, db=db)
    assert lu.calendar_name == "Famille"

    res = await R.accept_invitation(inv.token, db=db, user=MARINA)
    assert res == {"calendar_id": cal.id}

    lst = await R.list_invitations(cal.id, db=db, user=OWNER)
    assert lst[0].used_at is not None


@pytest.mark.asyncio
async def test_accept_invitation_deja_utilisee_409(db):
    cal = await _cal(db)
    inv = await R.create_invitation(cal.id, InvitationCreate(role="viewer"), db=db, user=OWNER)
    await R.accept_invitation(inv.token, db=db, user=MARINA)
    with pytest.raises(HTTPException) as exc:
        await R.accept_invitation(inv.token, db=db, user={"sub": "quelqu-un-d-autre"})
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_accept_invitation_expiree_410(db):
    cal = await _cal(db)
    inv = CalendarInvitation(
        calendar_id=cal.id, role="viewer", created_by="perso",
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    db.add(inv)
    await db.commit()
    await db.refresh(inv)
    with pytest.raises(HTTPException) as exc:
        await R.accept_invitation(inv.token, db=db, user=MARINA)
    assert exc.value.status_code == 410


@pytest.mark.asyncio
async def test_get_invitation_introuvable_404(db):
    with pytest.raises(HTTPException) as exc:
        await R.get_invitation("token-inexistant", db=db)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_list_invitations_refuse_si_pas_owner(db):
    cal = await _cal(db)
    with pytest.raises(HTTPException) as exc:
        await R.list_invitations(cal.id, db=db, user=MARINA)
    assert exc.value.status_code == 404
```

- [ ] **Step 2: Lancer les tests**

Run: `cd briques/agenda/backend && python3 -m pytest tests/test_invitations.py -v`
Expected: **PASS** (code existant). Un échec révèle un bug réel dans `routers/invitations.py` à corriger — c'est précisément le système que Marina va utiliser, donc tout bug trouvé ici doit être corrigé avant de continuer.

- [ ] **Step 3: Commit**

```bash
git add briques/agenda/backend/tests/test_invitations.py
git commit -m "test(agenda): couvre invitations.py (cycle créer/accepter, expirée, doublon)"
```

---

### Task 4: Script one-off `lier_compte_perso.py`

**Files:**
- Create: `briques/agenda/backend/lier_compte_perso.py`
- Test: `briques/agenda/backend/tests/test_lier_compte_perso.py`

**Interfaces:**
- Produces: `async def lier_compte_perso(sub: str, db: AsyncSession) -> list[str]` (retourne les ids de calendriers liés ; idempotent).
- Consumes: `db.AsyncSessionLocal`, `models.orm.{Calendar,CalendarMember}`.

- [ ] **Step 1: Écrire le test (échoue — le fichier n'existe pas encore)**

Créer `briques/agenda/backend/tests/test_lier_compte_perso.py` :

```python
"""Script one-off (S172) : relie un compte Keycloak réel aux calendriers "perso"."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from lier_compte_perso import lier_compte_perso
from models.orm import Calendar, CalendarMember


async def _cal(db, user_id="perso", name="Perso") -> Calendar:
    cal = Calendar(user_id=user_id, name=name, is_default=True)
    db.add(cal)
    await db.commit()
    await db.refresh(cal)
    return cal


@pytest.mark.asyncio
async def test_lie_uniquement_les_calendriers_perso(db):
    perso = await _cal(db, user_id="perso", name="Perso")
    autre = await _cal(db, user_id="quelqu-un-d-autre", name="PasMoi")

    lies = await lier_compte_perso("mon-sub-reel", db)

    assert lies == [perso.id]
    membres = (await db.execute(select(CalendarMember))).scalars().all()
    assert len(membres) == 1
    assert membres[0].calendar_id == perso.id
    assert membres[0].user_id == "mon-sub-reel"
    assert membres[0].role == "owner"


@pytest.mark.asyncio
async def test_idempotent(db):
    perso = await _cal(db, user_id="perso", name="Perso")

    premier = await lier_compte_perso("mon-sub-reel", db)
    second = await lier_compte_perso("mon-sub-reel", db)

    assert premier == [perso.id]
    assert second == []  # déjà lié, rien à refaire
    membres = (await db.execute(select(CalendarMember))).scalars().all()
    assert len(membres) == 1  # pas de doublon
```

- [ ] **Step 2: Lancer le test pour vérifier l'échec**

Run: `cd briques/agenda/backend && python3 -m pytest tests/test_lier_compte_perso.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'lier_compte_perso'`

- [ ] **Step 3: Implémenter**

Créer `briques/agenda/backend/lier_compte_perso.py` :

```python
"""Script one-off (S172) : relie le compte Keycloak réel de l'utilisateur principal aux
calendriers actuellement épinglés "perso" (posé par le dialecte S2S de l'assistant,
cf. `config.AGENDA_USER_ID`). Sans ce pont, un vrai compte `calendar-app` ne serait
reconnu propriétaire d'aucun calendrier existant (`utils.access.get_user_role` compare
`Calendar.user_id == user_id`).

Lancé une seule fois à la main, jamais exposé en route HTTP (cf. design S172 :
docs/superpowers/specs/2026-07-15-s172-agenda-application-autonome-design.md).

Usage :
  cd briques/agenda/backend && python3 lier_compte_perso.py <sub-keycloak>

Le <sub-keycloak> s'obtient après une première connexion à /app : décoder le payload du
access_token (ex. jwt.io), champ "sub".
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.orm import Calendar, CalendarMember


async def lier_compte_perso(sub: str, db: AsyncSession) -> list[str]:
    """Ajoute CalendarMember(role="owner") pour `sub` sur chaque calendrier "perso" qui
    n'a pas déjà de ligne pour ce sub. Idempotent (relançable sans dupliquer). Retourne
    les ids des calendriers nouvellement liés."""
    cals = (await db.execute(select(Calendar).where(Calendar.user_id == "perso"))).scalars().all()
    lies: list[str] = []
    for cal in cals:
        existant = (await db.execute(
            select(CalendarMember).where(
                CalendarMember.calendar_id == cal.id,
                CalendarMember.user_id == sub,
            )
        )).scalar_one_or_none()
        if existant:
            continue
        db.add(CalendarMember(calendar_id=cal.id, user_id=sub, role="owner"))
        lies.append(cal.id)
    await db.commit()
    return lies


async def _main(sub: str) -> None:
    from db import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        lies = await lier_compte_perso(sub, db)
    print(f"{len(lies)} calendrier(s) lié(s) : {lies}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 lier_compte_perso.py <sub-keycloak>")
        sys.exit(1)
    asyncio.run(_main(sys.argv[1]))
```

- [ ] **Step 4: Lancer le test pour vérifier qu'il passe**

Run: `cd briques/agenda/backend && python3 -m pytest tests/test_lier_compte_perso.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add briques/agenda/backend/lier_compte_perso.py briques/agenda/backend/tests/test_lier_compte_perso.py
git commit -m "feat(agenda): script one-off lier_compte_perso (S172)"
```

---

### Task 5: Page `/app` — coquille + authentification PKCE + liste des calendriers

**Files:**
- Create: `briques/agenda/backend/templates_app.py`
- Create: `briques/agenda/backend/routers/app_web.py`
- Test: `briques/agenda/backend/tests/test_app_web.py`
- Modify: `briques/agenda/backend/main.py`

**Interfaces:**
- Produces: `templates_app.page_app(kc_url: str, kc_realm: str, kc_client_id: str) -> str`.
- Produces: route `GET /app` (HTML, `include_in_schema=False`).
- Consumes (côté navigateur, fetch direct sur l'API REST déjà existante) : `GET /calendars`, `POST /calendars`.

- [ ] **Step 1: Écrire le test (échoue — les fichiers n'existent pas)**

Créer `briques/agenda/backend/tests/test_app_web.py` :

```python
"""Smoke test de la page /app (S172) — HTML bien formé, pas de dépendance réseau."""

from __future__ import annotations

import pytest

from routers.app_web import app_page


@pytest.mark.asyncio
async def test_app_page_contient_la_config_keycloak():
    resp = await app_page()
    assert resp.status_code == 200
    corps = resp.body.decode()
    assert "calendar-app" in corps
    assert "<title>" in corps
```

- [ ] **Step 2: Lancer le test pour vérifier l'échec**

Run: `cd briques/agenda/backend && python3 -m pytest tests/test_app_web.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'routers.app_web'`

- [ ] **Step 3: Implémenter le gabarit HTML/JS**

Créer `briques/agenda/backend/templates_app.py` :

```python
"""Page HTML de l'application agenda autonome (S172) — /app.

Auto-suffisante, comme `templates.py` (page d'invitation) : aucune dépendance externe,
PKCE écrit à la main. Contrairement à la page d'invitation (usage ponctuel), l'appli sert
un usage quotidien : le refresh_token est gardé en localStorage (persiste entre
rechargements), rafraîchi silencieusement au chargement — même logique que
`core/auth.py::exiger_session`, mais côté client (pas de cookie/session serveur ici,
appels JSON directs en `Authorization: Bearer`).
"""

import json

_PAGE = r"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Agenda</title>
<style>
  :root { color-scheme: light dark; }
  * { box-sizing: border-box; }
  body { margin: 0; min-height: 100vh; font: 15px/1.5 system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
         background: #0f172a; color: #e2e8f0; }
  header { display: flex; align-items: center; justify-content: space-between; gap: 12px;
           padding: 14px 20px; border-bottom: 1px solid #2d3148; }
  header h1 { font-size: 18px; margin: 0; }
  main { padding: 20px; max-width: 960px; margin: 0 auto; }
  .card { background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 20px; }
  .centre { display: grid; place-items: center; min-height: 70vh; }
  button { border: 0; border-radius: 8px; background: #3b82f6; color: #fff; font-size: 14px;
           font-weight: 600; padding: 9px 16px; cursor: pointer; }
  button:hover { background: #2563eb; }
  button.ghost { background: transparent; border: 1px solid #334155; color: #e2e8f0; }
  select, input { background: #141a26; color: #e2e8f0; border: 1px solid #2d3148; border-radius: 8px;
                  padding: 7px 10px; font-size: 14px; }
  .muted { color: #94a3b8; font-size: 13px; }
  .err { color: #f87171; }
  .barre { display: flex; align-items: center; gap: 10px; margin-bottom: 16px; flex-wrap: wrap; }
</style>
</head>
<body>
<header>
  <h1>📅 Agenda</h1>
  <div id="entete-droite"></div>
</header>
<main id="main"><div class="centre muted">Chargement…</div></main>
<script>
const KC = %%KC%%;
const REDIRECT = location.origin + location.pathname;
const LS_REFRESH = "agenda_refresh_token";
let ACCESS_TOKEN = null;

const b64url = (buf) => btoa(String.fromCharCode(...new Uint8Array(buf)))
  .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const rand = (n) => { const a = new Uint8Array(n); crypto.getRandomValues(a); return b64url(a.buffer); };
const sha256 = (s) => crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
const esc = (s) => (s || "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function afficherLogin() {
  document.getElementById("main").innerHTML =
    '<div class="centre"><div class="card" style="text-align:center">' +
    '<p>Connecte-toi pour voir ton agenda.</p>' +
    '<button id="btn-login">Se connecter</button></div></div>';
  document.getElementById("btn-login").onclick = login;
  document.getElementById("entete-droite").innerHTML = "";
}

async function login() {
  const verifier = rand(32), state = rand(16);
  sessionStorage.setItem("pkce_verifier", verifier);
  sessionStorage.setItem("pkce_state", state);
  const challenge = b64url(await sha256(verifier));
  const p = new URLSearchParams({
    client_id: KC.clientId, response_type: "code", scope: "openid",
    redirect_uri: REDIRECT, state, code_challenge: challenge, code_challenge_method: "S256",
  });
  location.href = `${KC.url}/realms/${KC.realm}/protocol/openid-connect/auth?${p}`;
}

async function echangerCode(code) {
  const verifier = sessionStorage.getItem("pkce_verifier");
  const body = new URLSearchParams({
    grant_type: "authorization_code", code, redirect_uri: REDIRECT,
    client_id: KC.clientId, code_verifier: verifier,
  });
  return tokenRequest(body);
}

async function rafraichir(refreshToken) {
  const body = new URLSearchParams({
    grant_type: "refresh_token", client_id: KC.clientId, refresh_token: refreshToken,
  });
  return tokenRequest(body);
}

async function tokenRequest(body) {
  const r = await fetch(`${KC.url}/realms/${KC.realm}/protocol/openid-connect/token`, {
    method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body,
  });
  if (!r.ok) return null;
  return r.json();
}

function poserSession(tokens) {
  ACCESS_TOKEN = tokens.access_token;
  localStorage.setItem(LS_REFRESH, tokens.refresh_token);
}

function deconnecter() {
  localStorage.removeItem(LS_REFRESH);
  ACCESS_TOKEN = null;
  afficherLogin();
}

async function api(path, opts = {}) {
  const headers = Object.assign({ Authorization: "Bearer " + ACCESS_TOKEN }, opts.headers || {});
  const r = await fetch(path, Object.assign({}, opts, { headers }));
  if (r.status === 401) { deconnecter(); throw new Error("session expirée"); }
  if (!r.ok) throw new Error("erreur " + r.status);
  if (r.status === 204) return null;
  return r.json();
}

async function demarrer() {
  const params = new URLSearchParams(location.search);
  const code = params.get("code"), state = params.get("state");

  if (code) {
    if (state !== sessionStorage.getItem("pkce_state")) { afficherLogin(); return; }
    const tokens = await echangerCode(code);
    history.replaceState({}, "", REDIRECT);
    if (!tokens) { afficherLogin(); return; }
    poserSession(tokens);
    await chargerApp();
    return;
  }

  const refresh = localStorage.getItem(LS_REFRESH);
  if (!refresh) { afficherLogin(); return; }
  const tokens = await rafraichir(refresh);
  if (!tokens) { afficherLogin(); return; }
  poserSession(tokens);
  await chargerApp();
}

async function chargerApp() {
  document.getElementById("entete-droite").innerHTML =
    '<button class="ghost" id="btn-logout">Se déconnecter</button>';
  document.getElementById("btn-logout").onclick = deconnecter;
  await chargerCalendriers();
}

demarrer();
</script>
</body>
</html>"""


def page_app(kc_url: str, kc_realm: str, kc_client_id: str) -> str:
    return _PAGE.replace(
        "%%KC%%",
        json.dumps({"url": kc_url, "realm": kc_realm, "clientId": kc_client_id}),
    )
```

Note : `chargerCalendriers()` est référencée mais pas encore définie — normal, elle arrive au Step suivant (Task 6). Cette page seule affiche déjà l'écran de login et gère la session ; `chargerCalendriers` sera ajoutée dans le même fichier par la tâche suivante (elle ne casse rien ici puisque `demarrer()` n'est appelée qu'au chargement du navigateur, pas par le test — le test ne vérifie que le HTML statique).

Créer `briques/agenda/backend/routers/app_web.py` :

```python
"""Application web autonome de l'agenda (S172) — /app.

Sert la page HTML/JS de `templates_app.page_app` : login PKCE contre `calendar-app`
(indépendant du dashboard du Cœur), consomme l'API REST déjà existante en
`Authorization: Bearer`. Cf. design :
docs/superpowers/specs/2026-07-15-s172-agenda-application-autonome-design.md
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from config import settings
from templates_app import page_app

router = APIRouter(tags=["app"])


@router.get("/app", response_class=HTMLResponse, include_in_schema=False)
async def app_page():
    kc_url = settings.KEYCLOAK_PUBLIC_URL or settings.KEYCLOAK_URL
    return HTMLResponse(page_app(kc_url, settings.KEYCLOAK_REALM, settings.KEYCLOAK_CLIENT_ID))
```

- [ ] **Step 4: Monter le routeur**

Modifier `briques/agenda/backend/main.py` — ajouter l'import et le montage (après `from routers.attachments import router as attachments_router`, avant `from routers.calendars import ...` pour rester trié alphabétiquement comme les imports existants) :

```python
from routers.app_web import router as app_web_router
```

Et après `app.include_router(health_router)` :

```python
app.include_router(app_web_router)
```

- [ ] **Step 5: Lancer le test pour vérifier qu'il passe**

Run: `cd briques/agenda/backend && python3 -m pytest tests/test_app_web.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add briques/agenda/backend/templates_app.py briques/agenda/backend/routers/app_web.py briques/agenda/backend/tests/test_app_web.py briques/agenda/backend/main.py
git commit -m "feat(agenda): page /app — coquille + login PKCE calendar-app (S172)"
```

---

### Task 6: Liste des calendriers + sélection

**Files:**
- Modify: `briques/agenda/backend/templates_app.py`

**Interfaces:**
- Consumes: `GET /calendars` (natif, déjà existant, renvoie `[{id,name,color,role,...}]`).
- Produces (variables JS globales utilisées par Task 7): `CALENDARS` (liste), `CAL_ACTIF` (id du calendrier sélectionné).

- [ ] **Step 1: Ajouter le rendu de la liste des calendriers**

Dans `briques/agenda/backend/templates_app.py`, insérer avant la ligne `demarrer();` (juste après la fonction `chargerApp`, en la complétant) :

```javascript
let CALENDARS = [];
let CAL_ACTIF = null;

async function chargerCalendriers() {
  try {
    CALENDARS = await api("/calendars");
  } catch (e) {
    document.getElementById("main").innerHTML = '<p class="err">Erreur : ' + esc(e.message) + "</p>";
    return;
  }
  if (!CALENDARS.length) {
    document.getElementById("main").innerHTML =
      '<div class="card"><p class="muted">Aucun agenda partagé avec toi pour l\\'instant.</p></div>';
    return;
  }
  if (!CAL_ACTIF || !CALENDARS.some((c) => c.id === CAL_ACTIF)) CAL_ACTIF = CALENDARS[0].id;
  rendreBarre();
  await chargerVue();
}

function rendreBarre() {
  const options = CALENDARS.map((c) =>
    `<option value="${esc(c.id)}" ${c.id === CAL_ACTIF ? "selected" : ""}>${esc(c.name)} (${esc(c.role)})</option>`
  ).join("");
  const role = (CALENDARS.find((c) => c.id === CAL_ACTIF) || {}).role;
  document.getElementById("main").innerHTML =
    '<div class="barre">' +
    `<select id="sel-cal">${options}</select>` +
    (role === "owner" ? '<button id="btn-inviter">Inviter</button>' : "") +
    '</div><div id="zone-vue"></div>';
  document.getElementById("sel-cal").onchange = (e) => { CAL_ACTIF = e.target.value; chargerVue(); };
  const btnInviter = document.getElementById("btn-inviter");
  if (btnInviter) btnInviter.onclick = ouvrirModaleInviter;
}

async function chargerVue() {
  document.getElementById("zone-vue").innerHTML = '<p class="muted">À venir.</p>';
}
```

- [ ] **Step 2: Étendre le test smoke pour vérifier la présence de la fonction**

Modifier `briques/agenda/backend/tests/test_app_web.py`, ajouter à la fin du fichier :

```python
@pytest.mark.asyncio
async def test_app_page_contient_le_chargement_des_calendriers():
    resp = await app_page()
    corps = resp.body.decode()
    assert "chargerCalendriers" in corps
    assert "/calendars" in corps
```

- [ ] **Step 3: Lancer les tests**

Run: `cd briques/agenda/backend && python3 -m pytest tests/test_app_web.py -v`
Expected: PASS (3 tests)

- [ ] **Step 4: Commit**

```bash
git add briques/agenda/backend/templates_app.py briques/agenda/backend/tests/test_app_web.py
git commit -m "feat(agenda): liste + sélection de calendrier dans l'appli /app (S172)"
```

---

### Task 7: Vue mois/semaine + CRUD événement + étiquettes

**Files:**
- Modify: `briques/agenda/backend/templates_app.py`

**Interfaces:**
- Consumes: `GET /calendars/{id}/events?start=&end=`, `POST /calendars/{id}/events`, `PATCH /events/{id}`, `DELETE /events/{id}`, `GET /calendars/{id}/labels`, `POST /calendars/{id}/labels`.
- Consumes (Task 6): `CALENDARS`, `CAL_ACTIF`.

- [ ] **Step 1: Remplacer `chargerVue` par la vraie vue mois/semaine + modale événement**

Dans `briques/agenda/backend/templates_app.py`, remplacer la fonction `chargerVue` (ajoutée en Task 6) par :

```javascript
const JOURS_COURT = ["Lun","Mar","Mer","Jeu","Ven","Sam","Dim"];
const MOIS = ["janvier","février","mars","avril","mai","juin","juillet","août","septembre","octobre","novembre","décembre"];
const COULEURS = ["#5865F2","#3B82F6","#22c55e","#eab308","#f97316","#ef4444","#ec4899","#a855f7"];

let calRef = new Date();
let EVENTS_CACHE = [];
let LABELS_CACHE = [];
let modalCouleur = "#5865F2";
let modalLabelId = "";

function ymd(d) { const p = (n) => String(n).padStart(2, "0"); return d.getFullYear()+"-"+p(d.getMonth()+1)+"-"+p(d.getDate()); }
function isoToLocal(iso) { const d = new Date(iso); const p = (n) => String(n).padStart(2, "0"); return d.getFullYear()+"-"+p(d.getMonth()+1)+"-"+p(d.getDate())+"T"+p(d.getHours())+":"+p(d.getMinutes()); }
function localToIso(v) { return v ? new Date(v).toISOString() : null; }
function lundiDe(d) { const x = new Date(d); const j = (x.getDay()+6)%7; x.setDate(x.getDate()-j); x.setHours(0,0,0,0); return x; }
function memeJour(a, b) { return a.getFullYear()===b.getFullYear() && a.getMonth()===b.getMonth() && a.getDate()===b.getDate(); }
function fmtHeure(iso) { const d = new Date(iso); return String(d.getHours()).padStart(2,"0")+":"+String(d.getMinutes()).padStart(2,"0"); }
function eventsDuJour(d) { return EVENTS_CACHE.filter((e) => memeJour(new Date(e.start_at), d)).sort((a,b) => new Date(a.start_at)-new Date(b.start_at)); }

async function chargerVue() {
  const zone = document.getElementById("zone-vue");
  zone.innerHTML = '<p class="muted">Chargement…</p>';
  const first = new Date(calRef.getFullYear(), calRef.getMonth(), 1);
  const debut = lundiDe(first), fin = new Date(debut); fin.setDate(fin.getDate()+42);
  try {
    EVENTS_CACHE = await api(`/calendars/${encodeURIComponent(CAL_ACTIF)}/events?start=${debut.toISOString()}&end=${fin.toISOString()}`);
    LABELS_CACHE = await api(`/calendars/${encodeURIComponent(CAL_ACTIF)}/labels`);
  } catch (e) {
    zone.innerHTML = '<p class="err">Erreur : ' + esc(e.message) + "</p>";
    return;
  }
  let h = '<div class="barre">' +
    '<button class="ghost" id="mois-prec">‹</button>' +
    `<strong>${MOIS[calRef.getMonth()]} ${calRef.getFullYear()}</strong>` +
    '<button class="ghost" id="mois-suiv">›</button>' +
    '<button id="btn-nouveau" style="margin-left:auto">+ Rendez-vous</button>' +
    "</div>";
  h += '<div style="display:grid;grid-template-columns:repeat(7,1fr);gap:1px;background:#2d3148;border:1px solid #2d3148;border-radius:10px;overflow:hidden">';
  for (const j of JOURS_COURT) h += `<div style="background:#161b27;color:#7c83ff;font-size:11px;font-weight:700;text-align:center;padding:6px 0">${j}</div>`;
  const today = new Date();
  for (let i = 0; i < 42; i++) {
    const d = new Date(debut); d.setDate(d.getDate()+i);
    const autre = d.getMonth() !== calRef.getMonth();
    const jevts = eventsDuJour(d);
    h += `<div style="background:${autre ? "#10141d" : "#141a26"};min-height:88px;padding:4px;cursor:pointer" data-jour="${ymd(d)}">` +
      `<div style="font-size:11px;color:${memeJour(d, today) ? "#5865F2" : "#94a3b8"}">${d.getDate()}</div>`;
    for (const e of jevts.slice(0, 3)) {
      const c = e.color || "#5865F2";
      h += `<div data-evt="${e.id}" style="background:${c};color:#fff;font-size:11px;border-radius:4px;padding:1px 4px;margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${e.all_day ? "" : esc(fmtHeure(e.start_at))+" "}${esc(e.title)}</div>`;
    }
    if (jevts.length > 3) h += `<div style="font-size:10px;color:#64748b">+${jevts.length-3}</div>`;
    h += "</div>";
  }
  h += "</div>";
  zone.innerHTML = h;
  document.getElementById("mois-prec").onclick = () => { calRef.setMonth(calRef.getMonth()-1); calRef = new Date(calRef); chargerVue(); };
  document.getElementById("mois-suiv").onclick = () => { calRef.setMonth(calRef.getMonth()+1); calRef = new Date(calRef); chargerVue(); };
  document.getElementById("btn-nouveau").onclick = () => ouvrirModaleEvent(null, ymd(new Date()));
  zone.querySelectorAll("[data-evt]").forEach((el) => el.addEventListener("click", (ev) => { ev.stopPropagation(); ouvrirModaleEvent(el.dataset.evt, null); }));
  zone.querySelectorAll("[data-jour]").forEach((el) => el.addEventListener("click", () => ouvrirModaleEvent(null, el.dataset.jour)));
}

function fermerModaleEvent() {
  const m = document.getElementById("modale"); if (m) m.remove();
}

function ouvrirModaleEvent(id, dateYMD) {
  const ev = id ? EVENTS_CACHE.find((e) => e.id === id) : null;
  let dStart, dEnd;
  if (ev) { dStart = isoToLocal(ev.start_at); dEnd = isoToLocal(ev.end_at); }
  else { dStart = dateYMD + "T09:00"; dEnd = dateYMD + "T10:00"; }
  modalCouleur = (ev && ev.color) || "#5865F2";
  modalLabelId = (ev && ev.label_id) || "";
  const palette = COULEURS.map((c) => `<span data-c="${c}" style="display:inline-block;width:20px;height:20px;border-radius:50%;background:${c};cursor:pointer;border:2px solid ${c===modalCouleur?"#fff":"transparent"}"></span>`).join(" ");
  const labelOptions = '<option value="">Aucune</option>' + LABELS_CACHE.map((l) => `<option value="${esc(l.id)}" ${l.id===modalLabelId?"selected":""}>${esc(l.name)}</option>`).join("");
  const html =
    '<div id="modale" style="position:fixed;inset:0;background:#000a;display:grid;place-items:center;z-index:10">' +
    '<div class="card" style="width:100%;max-width:420px">' +
    `<h3 style="margin-top:0">${ev ? "Modifier" : "Nouveau rendez-vous"}</h3>` +
    `<div style="margin-bottom:10px"><input id="ev-titre" placeholder="Titre" style="width:100%" value="${ev ? esc(ev.title) : ""}"></div>` +
    `<div style="display:flex;gap:8px;margin-bottom:10px"><input id="ev-debut" type="datetime-local" value="${dStart}"><input id="ev-fin" type="datetime-local" value="${dEnd}"></div>` +
    `<div style="margin-bottom:10px"><input id="ev-lieu" placeholder="Lieu (optionnel)" style="width:100%" value="${ev && ev.location ? esc(ev.location) : ""}"></div>` +
    `<div style="margin-bottom:10px"><label class="muted">Étiquette</label><select id="ev-label" style="width:100%">${labelOptions}</select></div>` +
    `<div style="margin-bottom:14px">${palette}</div>` +
    '<div style="display:flex;gap:8px;justify-content:flex-end">' +
    (ev ? '<button id="btn-suppr" style="background:#ef4444">Supprimer</button>' : "") +
    '<button class="ghost" id="btn-annuler">Annuler</button>' +
    `<button id="btn-enregistrer">${ev ? "Enregistrer" : "Créer"}</button>` +
    "</div></div></div>";
  document.body.insertAdjacentHTML("beforeend", html);
  document.querySelectorAll("#modale [data-c]").forEach((el) => el.onclick = () => {
    modalCouleur = el.dataset.c;
    document.querySelectorAll("#modale [data-c]").forEach((s) => s.style.borderColor = s.dataset.c===modalCouleur ? "#fff" : "transparent");
  });
  document.getElementById("btn-annuler").onclick = fermerModaleEvent;
  document.getElementById("btn-enregistrer").onclick = () => enregistrerEvent(id);
  if (ev) document.getElementById("btn-suppr").onclick = () => supprimerEvent(id);
}

async function enregistrerEvent(id) {
  const corps = {
    title: document.getElementById("ev-titre").value.trim(),
    start_at: localToIso(document.getElementById("ev-debut").value),
    end_at: localToIso(document.getElementById("ev-fin").value),
    location: document.getElementById("ev-lieu").value.trim() || null,
    color: modalCouleur,
    label_id: document.getElementById("ev-label").value || "",
    all_day: false,
  };
  if (!corps.title) { alert("Donne un titre."); return; }
  try {
    if (id) {
      await api(`/events/${encodeURIComponent(id)}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(corps) });
    } else {
      await api(`/calendars/${encodeURIComponent(CAL_ACTIF)}/events`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(corps) });
    }
    fermerModaleEvent();
    await chargerVue();
  } catch (e) { alert("Échec : " + e.message); }
}

async function supprimerEvent(id) {
  if (!confirm("Supprimer cet événement ?")) return;
  try {
    await api(`/events/${encodeURIComponent(id)}`, { method: "DELETE" });
    fermerModaleEvent();
    await chargerVue();
  } catch (e) { alert("Échec : " + e.message); }
}
```

- [ ] **Step 2: Étendre le test smoke**

Modifier `briques/agenda/backend/tests/test_app_web.py`, ajouter :

```python
@pytest.mark.asyncio
async def test_app_page_contient_la_modale_evenement():
    resp = await app_page()
    corps = resp.body.decode()
    assert "ouvrirModaleEvent" in corps
    assert "enregistrerEvent" in corps
```

- [ ] **Step 3: Lancer les tests**

Run: `cd briques/agenda/backend && python3 -m pytest tests/test_app_web.py -v`
Expected: PASS (4 tests)

- [ ] **Step 4: Commit**

```bash
git add briques/agenda/backend/templates_app.py briques/agenda/backend/tests/test_app_web.py
git commit -m "feat(agenda): vue mois + CRUD événement + étiquettes dans /app (S172)"
```

---

### Task 8: Bouton « Inviter » (owner seulement)

**Files:**
- Modify: `briques/agenda/backend/templates_app.py`

**Interfaces:**
- Consumes: `POST /calendars/{id}/invitations` (natif, existant, renvoie `{token, ...}`).
- Consumes (Task 6): `ouvrirModaleInviter` référencée par `rendreBarre()`.

- [ ] **Step 1: Ajouter la modale d'invitation**

Dans `briques/agenda/backend/templates_app.py`, ajouter (avant `demarrer();`) :

```javascript
function ouvrirModaleInviter() {
  const html =
    '<div id="modale" style="position:fixed;inset:0;background:#000a;display:grid;place-items:center;z-index:10">' +
    '<div class="card" style="width:100%;max-width:420px">' +
    '<h3 style="margin-top:0">Inviter quelqu\\'un</h3>' +
    '<div style="margin-bottom:10px"><input id="inv-email" placeholder="Email (optionnel, pour info)" style="width:100%"></div>' +
    '<div style="margin-bottom:14px"><select id="inv-role" style="width:100%"><option value="viewer">Lecture seule</option><option value="editor">Lecture et écriture</option></select></div>' +
    '<div id="inv-resultat"></div>' +
    '<div style="display:flex;gap:8px;justify-content:flex-end;margin-top:10px">' +
    '<button class="ghost" id="btn-annuler">Fermer</button>' +
    '<button id="btn-creer-invit">Créer le lien</button>' +
    "</div></div></div>";
  document.body.insertAdjacentHTML("beforeend", html);
  document.getElementById("btn-annuler").onclick = fermerModaleEvent;
  document.getElementById("btn-creer-invit").onclick = creerInvitation;
}

async function creerInvitation() {
  const email = document.getElementById("inv-email").value.trim() || null;
  const role = document.getElementById("inv-role").value;
  try {
    const inv = await api(`/calendars/${encodeURIComponent(CAL_ACTIF)}/invitations`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, role }),
    });
    const lien = location.origin + "/invitations/" + inv.token + "/page";
    document.getElementById("inv-resultat").innerHTML =
      '<p class="muted">Envoie ce lien à la personne invitée :</p>' +
      `<input readonly style="width:100%" value="${esc(lien)}" onclick="this.select()">`;
  } catch (e) { alert("Échec : " + e.message); }
}
```

- [ ] **Step 2: Étendre le test smoke**

Modifier `briques/agenda/backend/tests/test_app_web.py`, ajouter :

```python
@pytest.mark.asyncio
async def test_app_page_contient_le_bouton_inviter():
    resp = await app_page()
    corps = resp.body.decode()
    assert "ouvrirModaleInviter" in corps
    assert "/invitations" in corps
```

- [ ] **Step 3: Lancer les tests**

Run: `cd briques/agenda/backend && python3 -m pytest tests/test_app_web.py -v`
Expected: PASS (5 tests)

- [ ] **Step 4: Lancer toute la suite agenda pour vérifier l'absence de régression**

Run: `cd briques/agenda/backend && python3 -m pytest tests/ -v`
Expected: PASS (tous les tests, anciens et nouveaux)

- [ ] **Step 5: Commit**

```bash
git add briques/agenda/backend/templates_app.py briques/agenda/backend/tests/test_app_web.py
git commit -m "feat(agenda): bouton inviter (owner) dans /app — réutilise le système existant (S172)"
```

---

### Task 9: Enregistrer l'agenda dans `BRIQUES_UI` du Cœur

**Files:**
- Modify: `core/urls_ui.py`

**Interfaces:**
- Produces: `url_brique("AGENDA", scheme, host)` résout désormais vers `{scheme}://{host}:8400/app`.

- [ ] **Step 1: Ajouter l'entrée**

Dans `core/urls_ui.py`, dans le dict `BRIQUES_UI` (après `"RESTAURANT": (6010, "/"),` par exemple, ordre libre) :

```python
    "AGENDA":        (8400, "/app"),      # appli agenda autonome (calendar-app, S172)
```

- [ ] **Step 2: Vérifier qu'il n'y a pas de régression sur les tests du Cœur**

Run: `cd core && python3 -m pytest test_dashboard.py -v`
Expected: PASS (aucune régression — `BRIQUES_UI` n'est lu qu'à la demande via `url_brique`)

- [ ] **Step 3: Commit**

```bash
git add core/urls_ui.py
git commit -m "feat(core): enregistre AGENDA dans BRIQUES_UI (port 8400, S172)"
```

---

### Task 10: Remplacer l'onglet agenda du dashboard par une iframe

**Files:**
- Modify: `core/routers/dashboard.py`

**Interfaces:**
- Consumes: `url_brique("AGENDA", scheme, host)` (Task 9).
- Ne touche pas aux blocs Google Sync (`g-panel`, `chargerGoogle`) ni TimeTree (`tt-panel`, `chargerTimeTree`), qui restent inchangés.

- [ ] **Step 1: Remplacer le HTML du calendrier (grille + boutons) par une iframe**

Dans `core/routers/dashboard.py`, remplacer le bloc (dans `<div class="view" id="vue-agenda">`, entre le `<h2>` et les divs `event-modal`/`label-modal`) :

```html
      <div style="display:flex;gap:8px">
        <button class="btn" style="opacity:.85" onclick="ouvrirGestionEtiquettes()">🏷 Étiquettes</button>
        <button class="btn" onclick="ouvrirModaleEvent(null, null)">+ Nouveau rendez-vous</button>
      </div>
    </div>
    <div class="panel">
      <div id="g-panel" class="tt-panel" style="display:none"></div>
      <div id="tt-panel" class="tt-panel" style="display:none"></div>
      <div class="cal-toolbar">
        <div class="cal-nav">
          <button class="cal-fleche" onclick="calNav(-1)" title="Précédent">‹</button>
          <button class="btn" onclick="calAujourdhui()">Aujourd'hui</button>
          <button class="cal-fleche" onclick="calNav(1)" title="Suivant">›</button>
          <span id="cal-label" class="cal-label"></span>
        </div>
        <div class="cal-modes">
          <button class="cal-mode active" id="cal-mode-mois" onclick="calMode('mois')">Mois</button>
          <button class="cal-mode" id="cal-mode-semaine" onclick="calMode('semaine')">Semaine</button>
        </div>
      </div>
      <div id="cal-legende" class="cal-legende" style="display:none"></div>
      <div id="cal-conteneur" class="cal-conteneur"><span class="liv-sub">Chargement…</span></div>
    </div>
  </div>
  <div id="event-modal"></div>
  <div id="label-modal"></div>
```

par :

```html
      <a class="btn ghost" href="__AGENDA_UI_URL__" target="_blank" rel="noopener">Ouvrir dans un onglet ↗</a>
    </div>
    <div class="panel" style="padding:0;overflow:hidden">
      <div id="g-panel" class="tt-panel" style="display:none"></div>
      <div id="tt-panel" class="tt-panel" style="display:none"></div>
      <iframe id="agenda-iframe" title="Agenda"
        style="width:100%;height:calc(100vh - 200px);min-height:520px;border:0;border-radius:12px"></iframe>
    </div>
  </div>
```

(le `<div style="display:flex;gap:8px">...</div>` contenant les deux anciens boutons disparaît : leurs fonctionnalités vivent désormais dans l'appli autonome.)

Note : les classes CSS devenues inutilisées (`.cal-toolbar`, `.cal-grid`, `.ev-*`, etc.,
lignes ~228-294 du fichier) sont **volontairement laissées en place** — de la CSS morte
ne casse rien, et les isoler proprement du reste de la feuille de style partagée
demanderait un tri manuel risqué pour un bénéfice nul. À nettoyer plus tard si quelqu'un
retouche cette zone pour une autre raison.

- [ ] **Step 2: Supprimer le JS mort (calendrier, modale événement, mini-gestion étiquettes)**

Dans `core/routers/dashboard.py`, supprimer intégralement les trois blocs délimités par leurs commentaires de section, du début de `// ── Agenda ───` jusqu'à (non inclus) `// ── Pont Google Agenda ───` :
- `// ── Agenda ───...` (définitions `JOURS_COURT`, `MOIS`, `CALENDARS`, `chargerAgenda`, `rendreMois`, `rendreSemaine`, etc.)
- `// ── Modale événement (créer / éditer + documents + commentaires) ───...`
- `// ── Mini-gestion des étiquettes (panneau depuis la toolbar) ───...`

Les blocs `// ── Pont Google Agenda ───` et `// ── Pont TimeTree ───` qui suivent restent **inchangés**.

- [ ] **Step 3: Ajouter le chargement paresseux de l'iframe agenda**

Dans `core/routers/dashboard.py`, juste après le bloc `// ── Mail (client mail intégré, brique 6030) ─── ... function chargerMail() { ... }`, ajouter :

```javascript
// ── Agenda (appli autonome, S172) : iframe chargée paresseusement au 1er affichage ──
const AGENDA_UI_URL = '__AGENDA_UI_URL__';
let agendaCharge = false;
function chargerAgenda() {
  if (agendaCharge) return;
  const f = document.getElementById('agenda-iframe');
  if (f) { f.src = AGENDA_UI_URL; agendaCharge = true; }
}
```

- [ ] **Step 4: Mettre à jour `switchVue` et l'injection d'URL**

Dans `core/routers/dashboard.py`, la ligne `if (v === 'agenda') { chargerAgenda(); chargerGoogle(); chargerTimeTree(); }` reste **telle quelle** (les trois fonctions coexistent : `chargerAgenda()` est désormais le chargeur d'iframe, `chargerGoogle()`/`chargerTimeTree()` gèrent toujours les panneaux admin).

Trouver la chaîne des `.replace("__MAIL_UI_URL__", ...)` (près de la fin de la fonction qui construit le HTML du dashboard, section signalée par le commentaire `# S128 — Les URLs des iframes`) et ajouter une ligne :

```python
.replace("__AGENDA_UI_URL__", u("AGENDA"))
```

- [ ] **Step 5: Lancer la suite de tests du Cœur**

Run: `cd core && python3 -m pytest -v`
Expected: PASS (426 tests + non-régression — aucun test ne référence les fonctions JS supprimées, elles ne sont testées qu'au niveau HTTP des routes Python)

- [ ] **Step 6: Commit**

```bash
git add core/routers/dashboard.py
git commit -m "refactor(core): onglet agenda du dashboard -> iframe vers l'appli autonome (S172)"
```

---

## Vérification manuelle LIVE (non automatisable)

Comme pour S171, le flux OIDC PKCE navigateur ne s'automatise pas sans navigateur réel. À vérifier manuellement une fois Keycloak + l'agenda + le Cœur lancés :

1. Ouvrir `http://localhost:8400/app` directement → écran de login → connexion Keycloak (`calendar-app`) → liste de calendriers vide (normal, avant le script one-off).
2. Lancer `cd briques/agenda/backend && python3 lier_compte_perso.py <ton-sub-reel>` → recharger `/app` → le(s) calendrier(s) `"perso"` apparaissent, rôle `owner`.
3. Créer/éditer/supprimer un événement, une étiquette → vérifier la persistance après rechargement.
4. Cliquer « Inviter » → copier le lien → l'ouvrir dans une fenêtre de navigation privée (simulant Marina) → s'inscrire (Keycloak `registrationAllowed`) → accepter l'invitation → vérifier l'accès au calendrier avec le bon rôle, et l'absence totale d'accès à `/dashboard` du Cœur avec ce compte.
5. Dans le dashboard du Cœur (`/dashboard`), onglet Agenda → vérifier que l'iframe charge bien `/app` et que Google Sync/TimeTree (si configurés) fonctionnent toujours comme avant.
6. Vérifier que l'assistant (S2S, `AGENDA_KEY`) peut toujours lire/créer des événements sur le calendrier `"perso"` sans changement de comportement.

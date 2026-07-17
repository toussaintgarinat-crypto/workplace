# S179 — Géoloc éphémère (Présence) + abonnement webcal (ICS) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ajouter à la brique agenda un partage de position **ponctuel/éphémère** (carte familiale + « en route » lié à un event) et un **abonnement webcal (ICS) lecture seule**, sans toucher S174–S178.

**Architecture:** Deux sous-systèmes indépendants dans `briques/agenda/backend`. La **présence** stocke une position éphémère par personne (`live_positions`, PK `user_id`, upsert), filtrée+purgée à l'expiration, rendue sur une carte Leaflet (assets vendorés copiés de la brique geo) dans l'onglet `/app`. L'**ICS** expose une URL secrète par utilisateur (`user_profiles.ics_token`) servant un `VCALENDAR` des calendriers accessibles, avec `RRULE`/`EXDATE`/`RECURRENCE-ID` émis directement. Les deux réutilisent `UserProfile`, `calendriers_accessibles`, le pub/sub SSE et la surface `/service` du manifest.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy async, Alembic, pytest-asyncio (SQLite en mémoire), Leaflet vendoré (JS pur, zéro CDN), API géoloc du navigateur.

## Global Constraints

- **Périmètre** : brique agenda uniquement. Ne pas modifier le comportement de S174–S178.
- **Migration** : `0011`, `down_revision = "0010"`.
- **Manifest** : passe à **`1.4.0`**. Toute capacité DOIT pointer une route réelle de
  `routers/service.py` sous `/service` (garanti par `tests/test_manifest_capacites.py`).
- **Anti-usurpation** : l'identité écrite/lue est TOUJOURS `user["sub"]` (token Keycloak),
  jamais un champ du corps. Motif S178 (`routers/push.py`).
- **Éphémère** : une position max par personne (PK `user_id`, l'upsert remplace) ;
  expiration **filtrée à la lecture** + **purge opportuniste** ; **aucun historique**.
- **Vocabulaire** : « partager ma position » / « en route ». Jamais « suivi » / « tracking ».
- **Zéro nouvelle dépendance Python** : ICS = génération texte RFC 5545 à la main ; Leaflet
  = copie d'assets vendorés ; géoloc = API navigateur.
- **Dates ICS** : les events sont stockés en **naïf UTC** → émettre en UTC suffixe `Z`
  (`YYYYMMDDTHHMMSSZ`) ; `all_day` → `VALUE=DATE` (`YYYYMMDD`). Pas de `VTIMEZONE`
  (raffinement assumé de la spec, plus robuste multi-clients).
- **Tests** : appeler les fonctions de route directement (pas de TestClient — monter
  `main.app` déclenche lifespan + libs vendored). Fixture `db` = SQLite mémoire
  (`tests/conftest.py`).
- **Style** : nommage + commentaires en français, cohérents avec le code existant.

---

## File Structure

- `models/orm.py` — **modifier** : `LivePosition` (nouvelle table) + `UserProfile.ics_token`.
- `alembic/versions/0011_geoloc_ics.py` — **créer** : migration 0011.
- `services/ics.py` — **créer** : générateur `VCALENDAR` pur (aucune I/O) + mapping ORM→vevent.
- `services/abonnement.py` — **créer** : jeton ICS (obtenir/régénérer/résoudre) + URLs.
- `services/presence.py` — **créer** : upsert / supprimer / positions visibles (+ purge).
- `routers/ics.py` — **créer** : `GET /ics/cle`, `POST /ics/regenerer`, `GET /ics/{token}.ics`.
- `routers/presence.py` — **créer** : `POST /presence`, `DELETE /presence`, `GET /presence`.
- `services/pubsub.py` — **modifier** : `publish_presence_change`.
- `routers/sse.py` — **modifier** : `GET /sse/presence`.
- `routers/service.py` — **modifier** : `GET /service/presence`, `GET /service/ics`.
- `manifest.json` (racine brique) — **modifier** : version 1.4.0 + 2 capacités.
- `tests/test_manifest_capacites.py` — **modifier** : set attendu + gates.
- `main.py` — **modifier** : `include_router` des 2 nouveaux routeurs.
- `templates_app.py` — **modifier** : onglet 📍 Présence + bloc webcal dans Réglages.
- `static/leaflet.js`, `static/leaflet.css`, `static/leaflet.markercluster.js` — **créer**
  (copie depuis `briques/geo/static/`).
- Tests neufs : `tests/test_ics_generateur.py`, `tests/test_ics_flux.py`,
  `tests/test_presence.py`, `tests/test_presence_front.py`.

---

### Task 1: Modèle `LivePosition` + colonne `ics_token` + migration 0011

**Files:**
- Modify: `briques/agenda/backend/models/orm.py`
- Create: `briques/agenda/backend/alembic/versions/0011_geoloc_ics.py`
- Test: `briques/agenda/backend/tests/test_presence_orm.py`

**Interfaces:**
- Produces: `LivePosition` (colonnes `user_id` PK, `latitude`, `longitude`, `accuracy_m`,
  `label`, `scope` ∈ {`famille`,`event`}, `event_id`, `expires_at`, `updated_at`) ;
  `UserProfile.ics_token: str | None` (unique).

- [ ] **Step 1: Écrire le test qui échoue**

Créer `tests/test_presence_orm.py` :

```python
"""S179 — la table live_positions et la colonne ics_token existent et fonctionnent."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select


@pytest.mark.asyncio
async def test_live_position_upsert_une_ligne_par_personne(db):
    from models.orm import LivePosition

    p = LivePosition(user_id="alice", latitude=48.85, longitude=2.35,
                     scope="famille", expires_at=datetime.utcnow() + timedelta(hours=1))
    db.add(p)
    await db.commit()

    rows = (await db.execute(select(LivePosition))).scalars().all()
    assert len(rows) == 1
    assert rows[0].user_id == "alice"
    assert rows[0].scope == "famille"
    assert rows[0].accuracy_m is None


@pytest.mark.asyncio
async def test_userprofile_a_un_ics_token(db):
    from models.orm import UserProfile

    prof = UserProfile(user_id="alice", display_name="Alice", ics_token="jeton-secret")
    db.add(prof)
    await db.commit()

    got = await db.get(UserProfile, "alice")
    assert got.ics_token == "jeton-secret"
```

- [ ] **Step 2: Lancer le test, vérifier l'échec**

Run: `cd briques/agenda/backend && python3 -m pytest tests/test_presence_orm.py -q`
Expected: FAIL (`ImportError: cannot import name 'LivePosition'` / `TypeError: 'ics_token' is an invalid keyword argument`).

- [ ] **Step 3: Ajouter `Float` à l'import SQLAlchemy de `orm.py`**

Dans `models/orm.py`, la ligne d'import des types SQLAlchemy contient déjà `String, Text,
DateTime, Boolean, Integer, JSON, ForeignKey, UniqueConstraint, LargeBinary, Enum, func`.
Ajouter `Float` à cette liste d'import (depuis `sqlalchemy`).

- [ ] **Step 4: Ajouter la colonne `ics_token` à `UserProfile`**

Dans `models/orm.py`, classe `UserProfile`, juste après le champ `updated_at` (ou avant),
ajouter :

```python
    # S179 : jeton du flux d'abonnement webcal (ICS). NULL tant que l'utilisateur n'a pas
    # demandé son lien ; révocable (régénérer = nouveau jeton, l'ancien cesse de résoudre).
    ics_token: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
```

- [ ] **Step 5: Ajouter la classe `LivePosition`**

Dans `models/orm.py`, à la fin du fichier (après les modèles S177), ajouter :

```python
# ── S179 : présence (position éphémère partagée) ──────────────────────────────

class LivePosition(Base):
    """Position éphémère partagée par une personne. UNE ligne max par personne
    (PK `user_id`) : repartager REMPLACE. `expires_at` borne la durée de vie ; au-delà,
    filtrée à la lecture puis purgée. Aucun historique conservé (ligne unique)."""

    __tablename__ = "live_positions"

    user_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    accuracy_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # famille = visible de tous les membres ; event = visible des seuls participants de
    # l'événement `event_id` (expiration = fin de l'event).
    scope: Mapped[str] = mapped_column(
        Enum("famille", "event", name="live_position_scope"), nullable=False, default="famille")
    event_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("events.id", ondelete="CASCADE"), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now())
```

- [ ] **Step 6: Créer la migration 0011**

Créer `alembic/versions/0011_geoloc_ics.py` :

```python
"""0011 — S179 : présence éphémère (live_positions) + jeton d'abonnement ICS.

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-17
"""
from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "live_positions",
        sa.Column("user_id", sa.String(255), primary_key=True),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("accuracy_m", sa.Float(), nullable=True),
        sa.Column("label", sa.String(255), nullable=True),
        sa.Column("scope", sa.Enum("famille", "event", name="live_position_scope"),
                  nullable=False, server_default="famille"),
        sa.Column("event_id", sa.String(36),
                  sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_live_positions_expires_at", "live_positions", ["expires_at"])
    op.add_column("user_profiles", sa.Column("ics_token", sa.String(64), nullable=True))
    op.create_unique_constraint("uq_user_profiles_ics_token", "user_profiles", ["ics_token"])


def downgrade() -> None:
    op.drop_constraint("uq_user_profiles_ics_token", "user_profiles", type_="unique")
    op.drop_column("user_profiles", "ics_token")
    op.drop_index("ix_live_positions_expires_at", table_name="live_positions")
    op.drop_table("live_positions")
    op.execute("DROP TYPE IF EXISTS live_position_scope")  # nettoyage enum Postgres
```

- [ ] **Step 7: Lancer le test, vérifier le succès**

Run: `cd briques/agenda/backend && python3 -m pytest tests/test_presence_orm.py -q`
Expected: PASS (2 passed).

- [ ] **Step 8: Commit**

```bash
git add briques/agenda/backend/models/orm.py \
        briques/agenda/backend/alembic/versions/0011_geoloc_ics.py \
        briques/agenda/backend/tests/test_presence_orm.py
git commit -m "feat(s179): modèle LivePosition + ics_token + migration 0011"
```

---

### Task 2: Générateur ICS pur `services/ics.py`

**Files:**
- Create: `briques/agenda/backend/services/ics.py`
- Test: `briques/agenda/backend/tests/test_ics_generateur.py`

**Interfaces:**
- Produces:
  - `generer_ics(events: list[dict], nom_calendrier: str = "Agenda") -> str` — texte
    `VCALENDAR` (lignes CRLF). Chaque event dict : `uid:str`, `title:str`, `start:datetime`,
    `end:datetime`, `all_day:bool`, `description:str|None`, `location:str|None`,
    `rrule:str|None`, `exdates:list[datetime]`, `recurrence_id:datetime|None`.
  - `event_en_vevent(e) -> dict` — mappe un ORM `Event` vers ce dict.

- [ ] **Step 1: Écrire les tests qui échouent**

Créer `tests/test_ics_generateur.py` :

```python
"""S179 — générateur ICS pur (RFC 5545). Aucune I/O : on lui passe des dicts."""
from __future__ import annotations

from datetime import datetime

from services.ics import event_en_vevent, generer_ics


def _evt(**kw):
    base = {"uid": "e1", "title": "Dîner", "start": datetime(2026, 7, 20, 19, 0, 0),
            "end": datetime(2026, 7, 20, 21, 0, 0), "all_day": False,
            "description": None, "location": None, "rrule": None,
            "exdates": [], "recurrence_id": None}
    base.update(kw)
    return base


def test_squelette_vcalendar():
    out = generer_ics([_evt()])
    assert out.startswith("BEGIN:VCALENDAR\r\n")
    assert out.rstrip().endswith("END:VCALENDAR")
    assert "VERSION:2.0" in out
    assert "BEGIN:VEVENT" in out and "END:VEVENT" in out
    assert "UID:e1" in out
    assert "SUMMARY:Dîner" in out
    assert "DTSTART:20260720T190000Z" in out
    assert "DTEND:20260720T210000Z" in out


def test_journee_entiere_value_date():
    out = generer_ics([_evt(all_day=True)])
    assert "DTSTART;VALUE=DATE:20260720" in out
    assert "DTEND;VALUE=DATE:20260720" in out


def test_recurrence_rrule_et_exdate():
    out = generer_ics([_evt(rrule="FREQ=WEEKLY;BYDAY=MO",
                            exdates=[datetime(2026, 7, 27, 19, 0, 0)])])
    assert "RRULE:FREQ=WEEKLY;BYDAY=MO" in out
    assert "EXDATE:20260727T190000Z" in out


def test_override_recurrence_id():
    out = generer_ics([_evt(recurrence_id=datetime(2026, 7, 27, 19, 0, 0))])
    assert "RECURRENCE-ID:20260727T190000Z" in out


def test_echappement_rfc5545():
    out = generer_ics([_evt(title="A; B, C\\D", description="ligne1\nligne2",
                            location="12, rue X")])
    assert "SUMMARY:A\\; B\\, C\\\\D" in out
    assert "DESCRIPTION:ligne1\\nligne2" in out
    assert "LOCATION:12\\, rue X" in out
```

- [ ] **Step 2: Lancer le test, vérifier l'échec**

Run: `cd briques/agenda/backend && python3 -m pytest tests/test_ics_generateur.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'services.ics'`).

- [ ] **Step 3: Écrire `services/ics.py`**

```python
"""Générateur ICS (RFC 5545) — S179. PUR : prend des dicts/ORM, renvoie du texte, aucune
I/O. Les dates sont émises en UTC suffixe `Z` (events stockés en naïf UTC) ; `all_day` →
`VALUE=DATE`. La récurrence (`RRULE`/`EXDATE`) est émise TELLE QUELLE — le client agenda
l'expanse (comportement standard, robuste)."""
from __future__ import annotations

from datetime import datetime


def _echapper(texte: str) -> str:
    """Échappement RFC 5545 : backslash d'abord, puis ; , et retours ligne."""
    return (texte.replace("\\", "\\\\").replace(";", "\\;")
            .replace(",", "\\,").replace("\n", "\\n").replace("\r", ""))


def _fmt_utc(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%SZ")


def _fmt_date(dt: datetime) -> str:
    return dt.strftime("%Y%m%d")


def _ligne(cles: str, valeur: str) -> str:
    return f"{cles}:{valeur}"


def _vevent(e: dict) -> list[str]:
    lignes = ["BEGIN:VEVENT", f"UID:{e['uid']}", f"DTSTAMP:{_fmt_utc(datetime.utcnow())}"]
    if e["all_day"]:
        lignes.append(f"DTSTART;VALUE=DATE:{_fmt_date(e['start'])}")
        lignes.append(f"DTEND;VALUE=DATE:{_fmt_date(e['end'])}")
    else:
        lignes.append(f"DTSTART:{_fmt_utc(e['start'])}")
        lignes.append(f"DTEND:{_fmt_utc(e['end'])}")
    lignes.append(_ligne("SUMMARY", _echapper(e["title"])))
    if e.get("description"):
        lignes.append(_ligne("DESCRIPTION", _echapper(e["description"])))
    if e.get("location"):
        lignes.append(_ligne("LOCATION", _echapper(e["location"])))
    if e.get("rrule"):
        lignes.append(f"RRULE:{e['rrule']}")
    if e.get("exdates"):
        lignes.append("EXDATE:" + ",".join(_fmt_utc(d) for d in e["exdates"]))
    if e.get("recurrence_id"):
        lignes.append(f"RECURRENCE-ID:{_fmt_utc(e['recurrence_id'])}")
    lignes.append("END:VEVENT")
    return lignes


def generer_ics(events: list[dict], nom_calendrier: str = "Agenda") -> str:
    lignes = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Workplace//Agenda//FR",
              "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
              _ligne("X-WR-CALNAME", _echapper(nom_calendrier))]
    for e in events:
        lignes.extend(_vevent(e))
    lignes.append("END:VCALENDAR")
    return "\r\n".join(lignes) + "\r\n"


def _as_dt(v) -> datetime:
    return v if isinstance(v, datetime) else datetime.fromisoformat(v)


def event_en_vevent(e) -> dict:
    """Mappe un ORM `Event` vers le dict attendu par `generer_ics`. Un event override
    (recurrence_parent_id non-NULL) porte un `recurrence_id` = sa `recurrence_date`."""
    return {
        "uid": e.id,
        "title": e.title or "",
        "start": e.start_at,
        "end": e.end_at,
        "all_day": bool(e.all_day),
        "description": e.description,
        "location": e.location,
        "rrule": e.recurrence_rule,
        "exdates": [_as_dt(x) for x in (e.exdates or [])],
        "recurrence_id": e.recurrence_date if e.recurrence_parent_id else None,
    }
```

- [ ] **Step 4: Lancer le test, vérifier le succès**

Run: `cd briques/agenda/backend && python3 -m pytest tests/test_ics_generateur.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add briques/agenda/backend/services/ics.py \
        briques/agenda/backend/tests/test_ics_generateur.py
git commit -m "feat(s179): générateur ICS pur (RRULE/EXDATE/RECURRENCE-ID, échappement RFC 5545)"
```

---

### Task 3: Jeton d'abonnement `services/abonnement.py` + routeur `routers/ics.py`

**Files:**
- Create: `briques/agenda/backend/services/abonnement.py`
- Create: `briques/agenda/backend/routers/ics.py`
- Modify: `briques/agenda/backend/main.py`
- Test: `briques/agenda/backend/tests/test_ics_flux.py`

**Interfaces:**
- Consumes: `services.ics.generer_ics`, `services.ics.event_en_vevent`,
  `services.agregation.calendriers_accessibles`, `services.profils`.
- Produces:
  - `abonnement.obtenir_ou_creer_token(db, user_id) -> str`
  - `abonnement.regenerer_token(db, user_id) -> str`
  - `abonnement.user_pour_token(db, token) -> str | None`
  - `abonnement.url_https(base, token) -> str`, `abonnement.url_webcal(base, token) -> str`
  - Routes : `GET /ics/cle`, `POST /ics/regenerer`, `GET /ics/{token}.ics`.

- [ ] **Step 1: Écrire les tests qui échouent**

Créer `tests/test_ics_flux.py` :

```python
"""S179 — abonnement webcal : jeton (idempotent/révocable) + flux .ics par capacité."""
from __future__ import annotations

from datetime import datetime

import pytest

from routers import ics as R
from services import abonnement


async def _cal_avec_event(db, user_id):
    from models.orm import Calendar, Event
    cal = Calendar(user_id=user_id, name="Perso")
    db.add(cal)
    await db.flush()
    db.add(Event(calendar_id=cal.id, title="Dîner", created_by=user_id,
                 start_at=datetime(2026, 7, 20, 19, 0, 0),
                 end_at=datetime(2026, 7, 20, 21, 0, 0)))
    await db.commit()
    return cal


@pytest.mark.asyncio
async def test_token_idempotent(db):
    t1 = await abonnement.obtenir_ou_creer_token(db, "alice")
    t2 = await abonnement.obtenir_ou_creer_token(db, "alice")
    assert t1 and t1 == t2


@pytest.mark.asyncio
async def test_regenerer_revoque_lancien(db):
    t1 = await abonnement.obtenir_ou_creer_token(db, "alice")
    t2 = await abonnement.regenerer_token(db, "alice")
    assert t2 != t1
    assert await abonnement.user_pour_token(db, t1) is None
    assert await abonnement.user_pour_token(db, t2) == "alice"


def test_url_webcal_remplace_le_schema():
    assert abonnement.url_webcal("https://agenda.example.com", "AAA") == \
        "webcal://agenda.example.com/ics/AAA.ics"
    assert abonnement.url_https("https://agenda.example.com/", "AAA") == \
        "https://agenda.example.com/ics/AAA.ics"


@pytest.mark.asyncio
async def test_flux_token_inconnu_404(db):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        await R.flux(token="nexistepas", db=db)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_flux_ne_contient_que_les_events_visibles(db):
    await _cal_avec_event(db, "alice")
    # Un event d'un AUTRE utilisateur (calendrier non partagé) ne doit pas fuiter.
    await _cal_avec_event(db, "bob")
    token = await abonnement.obtenir_ou_creer_token(db, "alice")
    resp = await R.flux(token=token, db=db)
    corps = resp.body.decode("utf-8")
    assert resp.media_type.startswith("text/calendar")
    assert corps.count("BEGIN:VEVENT") == 1
    assert "SUMMARY:Dîner" in corps
```

- [ ] **Step 2: Lancer le test, vérifier l'échec**

Run: `cd briques/agenda/backend && python3 -m pytest tests/test_ics_flux.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'services.abonnement'`).

- [ ] **Step 3: Écrire `services/abonnement.py`**

```python
"""Abonnement webcal (S179) : jeton ICS par utilisateur (capacité), stocké sur
`UserProfile.ics_token`. Génération/révocation + construction des URLs. Le jeton est la
SEULE porte du flux `.ics` (lecture seule) — régénérer invalide instantanément l'ancien."""
from __future__ import annotations

import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.orm import UserProfile
from services import profils


def _nouveau_token() -> str:
    return secrets.token_urlsafe(32)


async def _profil(db: AsyncSession, user_id: str) -> UserProfile:
    prof = await db.get(UserProfile, user_id)
    if prof is None:
        prof = await profils.upsert(db, user_id, profils.nom_affiche(user_id, None))
    return prof


async def obtenir_ou_creer_token(db: AsyncSession, user_id: str) -> str:
    prof = await _profil(db, user_id)
    if not prof.ics_token:
        prof.ics_token = _nouveau_token()
        await db.commit()
        await db.refresh(prof)
    return prof.ics_token


async def regenerer_token(db: AsyncSession, user_id: str) -> str:
    prof = await _profil(db, user_id)
    prof.ics_token = _nouveau_token()
    await db.commit()
    await db.refresh(prof)
    return prof.ics_token


async def user_pour_token(db: AsyncSession, token: str) -> str | None:
    if not token:
        return None
    prof = (await db.execute(
        select(UserProfile).where(UserProfile.ics_token == token))).scalar_one_or_none()
    return prof.user_id if prof else None


def url_https(base: str, token: str) -> str:
    return f"{base.rstrip('/')}/ics/{token}.ics"


def url_webcal(base: str, token: str) -> str:
    b = base.rstrip("/")
    for prefixe in ("https://", "http://"):
        if b.startswith(prefixe):
            b = b[len(prefixe):]
            break
    return f"webcal://{b}/ics/{token}.ics"
```

- [ ] **Step 4: Écrire `routers/ics.py`**

```python
"""Abonnement webcal (S179) : l'utilisateur récupère/régénère son lien (auth Bearer) ; le
flux `.ics` est PUBLIC — le jeton dans l'URL EST la capacité (motif SSE sondages). Lecture
seule : aucune écriture entrante."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from config import settings
from db import get_db
from models.orm import Event
from services import abonnement, ics
from services.agregation import calendriers_accessibles

router = APIRouter(tags=["ics"])


def _base(request: Request) -> str:
    return (settings.AGENDA_URL_PUBLIQUE or str(request.base_url)).rstrip("/")


def _liens(base: str, token: str) -> dict:
    return {"token": token, "https": abonnement.url_https(base, token),
            "webcal": abonnement.url_webcal(base, token)}


@router.get("/ics/cle")
async def cle(request: Request, db: AsyncSession = Depends(get_db),
              user: dict = Depends(get_current_user)):
    """Renvoie (en le créant au besoin) le lien d'abonnement webcal de l'appelant."""
    token = await abonnement.obtenir_ou_creer_token(db, user["sub"])
    return _liens(_base(request), token)


@router.post("/ics/regenerer")
async def regenerer(request: Request, db: AsyncSession = Depends(get_db),
                    user: dict = Depends(get_current_user)):
    """Régénère le jeton (révoque l'ancien) et renvoie le nouveau lien."""
    token = await abonnement.regenerer_token(db, user["sub"])
    return _liens(_base(request), token)


@router.get("/ics/{token}.ics")
async def flux(token: str, db: AsyncSession = Depends(get_db)):
    """Flux VCALENDAR des calendriers accessibles de l'utilisateur résolu par le jeton.
    PUBLIC (jeton = capacité) ; 404 si jeton inconnu (ne divulgue rien)."""
    uid = await abonnement.user_pour_token(db, token)
    if uid is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Flux introuvable")
    cals = await calendriers_accessibles(db, uid)
    ids = [c.id for c in cals]
    events = []
    if ids:
        events = (await db.execute(
            select(Event).where(Event.calendar_id.in_(ids)))).scalars().all()
    corps = ics.generer_ics([ics.event_en_vevent(e) for e in events])
    return Response(corps, media_type="text/calendar; charset=utf-8")
```

- [ ] **Step 5: Brancher le routeur dans `main.py`**

Dans `main.py`, ajouter l'import près des autres imports de routeurs :

```python
from routers.ics import router as ics_router
```

Et l'inclusion près des autres `include_router` (après `pwa_router`) :

```python
app.include_router(ics_router)
```

- [ ] **Step 6: Lancer le test, vérifier le succès**

Run: `cd briques/agenda/backend && python3 -m pytest tests/test_ics_flux.py -q`
Expected: PASS (5 passed).

- [ ] **Step 7: Commit**

```bash
git add briques/agenda/backend/services/abonnement.py \
        briques/agenda/backend/routers/ics.py briques/agenda/backend/main.py \
        briques/agenda/backend/tests/test_ics_flux.py
git commit -m "feat(s179): abonnement webcal — jeton révocable + flux .ics public par capacité"
```

---

### Task 4: Logique présence `services/presence.py`

**Files:**
- Create: `briques/agenda/backend/services/presence.py`
- Test: `briques/agenda/backend/tests/test_presence_service.py`

**Interfaces:**
- Consumes: `models.orm.LivePosition`, `models.orm.EventParticipant`, `services.profils`.
- Produces:
  - `upsert_position(db, user_id, *, latitude, longitude, expires_at, accuracy_m=None, label=None, scope="famille", event_id=None) -> LivePosition`
  - `supprimer_position(db, user_id) -> None`
  - `positions_visibles(db, user_id) -> list[dict]` (purge expirés ; renvoie `famille` +
    `event` où `user_id` est participant + les siennes ; enrichi `display_name`/`avatar_color`).

- [ ] **Step 1: Écrire les tests qui échouent**

Créer `tests/test_presence_service.py` :

```python
"""S179 — logique présence : upsert (une ligne/personne), purge, portée de visibilité."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from services import presence

FUTUR = datetime.utcnow() + timedelta(hours=1)
PASSE = datetime.utcnow() - timedelta(minutes=1)


@pytest.mark.asyncio
async def test_upsert_remplace_une_seule_ligne(db):
    from models.orm import LivePosition
    from sqlalchemy import select

    await presence.upsert_position(db, "alice", latitude=1.0, longitude=2.0, expires_at=FUTUR)
    await presence.upsert_position(db, "alice", latitude=3.0, longitude=4.0, expires_at=FUTUR)
    rows = (await db.execute(select(LivePosition))).scalars().all()
    assert len(rows) == 1
    assert rows[0].latitude == 3.0


@pytest.mark.asyncio
async def test_positions_visibles_filtre_et_purge_les_expires(db):
    from models.orm import LivePosition
    from sqlalchemy import select

    await presence.upsert_position(db, "vieux", latitude=1.0, longitude=1.0, expires_at=PASSE)
    await presence.upsert_position(db, "alice", latitude=2.0, longitude=2.0, expires_at=FUTUR)
    vis = await presence.positions_visibles(db, "bob")
    ids = {v["user_id"] for v in vis}
    assert ids == {"alice"}  # 'vieux' expiré → absent
    restants = (await db.execute(select(LivePosition))).scalars().all()
    assert {r.user_id for r in restants} == {"alice"}  # purgé de la base


@pytest.mark.asyncio
async def test_portee_event_visible_seulement_des_participants(db):
    from models.orm import Calendar, Event, EventParticipant

    cal = Calendar(user_id="alice", name="Perso")
    db.add(cal)
    await db.flush()
    evt = Event(calendar_id=cal.id, title="RDV", created_by="alice",
                start_at=datetime(2026, 7, 20, 9, 0, 0), end_at=FUTUR)
    db.add(evt)
    await db.flush()
    db.add(EventParticipant(event_id=evt.id, user_id="carol", status="accepted"))
    await db.commit()

    await presence.upsert_position(db, "alice", latitude=1.0, longitude=1.0,
                                   expires_at=FUTUR, scope="event", event_id=evt.id)

    vu_par_carol = {v["user_id"] for v in await presence.positions_visibles(db, "carol")}
    vu_par_dave = {v["user_id"] for v in await presence.positions_visibles(db, "dave")}
    assert "alice" in vu_par_carol       # participant → voit
    assert "alice" not in vu_par_dave    # non-participant → ne voit pas


@pytest.mark.asyncio
async def test_position_enrichie_du_profil(db):
    from services import profils

    await profils.upsert(db, "alice", "Alice", avatar_color="#123456")
    await presence.upsert_position(db, "alice", latitude=1.0, longitude=2.0, expires_at=FUTUR)
    vis = await presence.positions_visibles(db, "bob")
    assert vis[0]["display_name"] == "Alice"
    assert vis[0]["avatar_color"] == "#123456"


@pytest.mark.asyncio
async def test_supprimer_position(db):
    await presence.upsert_position(db, "alice", latitude=1.0, longitude=2.0, expires_at=FUTUR)
    await presence.supprimer_position(db, "alice")
    assert await presence.positions_visibles(db, "alice") == []
```

- [ ] **Step 2: Lancer le test, vérifier l'échec**

Run: `cd briques/agenda/backend && python3 -m pytest tests/test_presence_service.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'services.presence'`).

- [ ] **Step 3: Écrire `services/presence.py`**

```python
"""Présence éphémère (S179) : partage/retrait/lecture des positions. Une ligne par personne
(upsert). La lecture PURGE d'abord les positions expirées (opportuniste), puis renvoie
celles visibles par l'observateur : toutes les `famille`, les `event` des events où il est
participant, et les siennes. Enrichi du profil (nom + couleur). Aucun historique."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.orm import EventParticipant, LivePosition
from services import profils


async def upsert_position(db: AsyncSession, user_id: str, *, latitude: float, longitude: float,
                          expires_at: datetime, accuracy_m: float | None = None,
                          label: str | None = None, scope: str = "famille",
                          event_id: str | None = None) -> LivePosition:
    pos = await db.get(LivePosition, user_id)
    if pos is None:
        pos = LivePosition(user_id=user_id)
        db.add(pos)
    pos.latitude = latitude
    pos.longitude = longitude
    pos.accuracy_m = accuracy_m
    pos.label = label
    pos.scope = scope
    pos.event_id = event_id
    pos.expires_at = expires_at
    pos.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(pos)
    return pos


async def supprimer_position(db: AsyncSession, user_id: str) -> None:
    pos = await db.get(LivePosition, user_id)
    if pos is not None:
        await db.delete(pos)
        await db.commit()


async def positions_visibles(db: AsyncSession, user_id: str) -> list[dict]:
    now = datetime.utcnow()
    # Purge opportuniste : les positions expirées disparaissent dès la première lecture.
    await db.execute(delete(LivePosition).where(LivePosition.expires_at < now))
    await db.commit()

    rows = (await db.execute(
        select(LivePosition).where(LivePosition.expires_at >= now))).scalars().all()

    mes_events = set((await db.execute(
        select(EventParticipant.event_id).where(
            EventParticipant.user_id == user_id))).scalars().all())

    visibles = [p for p in rows
                if p.scope == "famille" or p.user_id == user_id
                or (p.scope == "event" and p.event_id in mes_events)]

    profs = await profils.resoudre(db, [p.user_id for p in visibles])
    return [{
        "user_id": p.user_id,
        "display_name": profs[p.user_id]["display_name"],
        "avatar_color": profs[p.user_id]["avatar_color"],
        "latitude": p.latitude,
        "longitude": p.longitude,
        "accuracy_m": p.accuracy_m,
        "label": p.label,
        "scope": p.scope,
        "event_id": p.event_id,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
        "expires_at": p.expires_at.isoformat(),
    } for p in visibles]
```

- [ ] **Step 4: Lancer le test, vérifier le succès**

Run: `cd briques/agenda/backend && python3 -m pytest tests/test_presence_service.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add briques/agenda/backend/services/presence.py \
        briques/agenda/backend/tests/test_presence_service.py
git commit -m "feat(s179): logique présence — upsert éphémère, purge, portée famille/event"
```

---

### Task 5: Routeur présence `routers/presence.py` + pub/sub

**Files:**
- Create: `briques/agenda/backend/routers/presence.py`
- Modify: `briques/agenda/backend/services/pubsub.py`
- Modify: `briques/agenda/backend/main.py`
- Test: `briques/agenda/backend/tests/test_presence.py`

**Interfaces:**
- Consumes: `services.presence`, `models.orm.Event`/`EventParticipant`,
  `services.pubsub.publish_presence_change`, `auth.get_current_user`.
- Produces:
  - `pubsub.publish_presence_change(event_type: str, payload: dict) -> None` (canal
    `presence:changes`).
  - Routes : `POST /presence`, `DELETE /presence`, `GET /presence`.
  - Schéma `PresenceEntree` (`lat`, `lon`, `accuracy?`, `label?`, `scope`, `event_id?`,
    `ttl_minutes?`).

- [ ] **Step 1: Écrire les tests qui échouent**

Créer `tests/test_presence.py` :

```python
"""S179 — routeur présence : sub forcé (anti-usurpation), portée event gardée, TTL famille."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException

from routers import presence as R
from routers.presence import PresenceEntree


@pytest.mark.asyncio
async def test_partage_famille_ttl_defaut(db, monkeypatch):
    monkeypatch.setattr(R, "publish_presence_change", _noop)
    out = await R.partager(PresenceEntree(lat=48.85, lon=2.35), db=db, user={"sub": "alice"})
    assert out["ok"] is True
    vis = await R.lister(db=db, user={"sub": "bob"})
    assert vis[0]["user_id"] == "alice"


@pytest.mark.asyncio
async def test_partage_force_le_sub_ignore_le_corps(db, monkeypatch):
    monkeypatch.setattr(R, "publish_presence_change", _noop)
    # Un user_id PIRATE injecté dans le corps est ignoré (extra='ignore' par défaut).
    body = PresenceEntree.model_validate({"lat": 1.0, "lon": 2.0, "user_id": "PIRATE"})
    assert not hasattr(body, "user_id")
    await R.partager(body, db=db, user={"sub": "alice"})
    vis = await R.lister(db=db, user={"sub": "alice"})
    assert {v["user_id"] for v in vis} == {"alice"}
    assert "PIRATE" not in str(vis)


@pytest.mark.asyncio
async def test_partage_event_exige_participation(db, monkeypatch):
    from models.orm import Calendar, Event

    monkeypatch.setattr(R, "publish_presence_change", _noop)
    cal = Calendar(user_id="owner", name="Perso")
    db.add(cal)
    await db.flush()
    evt = Event(calendar_id=cal.id, title="RDV", created_by="owner",
                start_at=datetime(2026, 7, 20, 9, 0, 0),
                end_at=datetime.utcnow() + timedelta(hours=2))
    db.add(evt)
    await db.commit()

    with pytest.raises(HTTPException) as exc:  # non-participant → 403
        await R.partager(PresenceEntree(lat=1.0, lon=2.0, scope="event", event_id=evt.id),
                         db=db, user={"sub": "intrus"})
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_partage_event_inconnu_404(db, monkeypatch):
    monkeypatch.setattr(R, "publish_presence_change", _noop)
    with pytest.raises(HTTPException) as exc:
        await R.partager(PresenceEntree(lat=1.0, lon=2.0, scope="event", event_id="nope"),
                         db=db, user={"sub": "alice"})
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_arreter_supprime(db, monkeypatch):
    monkeypatch.setattr(R, "publish_presence_change", _noop)
    await R.partager(PresenceEntree(lat=1.0, lon=2.0), db=db, user={"sub": "alice"})
    await R.arreter(db=db, user={"sub": "alice"})
    assert await R.lister(db=db, user={"sub": "alice"}) == []


async def _noop(*a, **k):
    return None
```

- [ ] **Step 2: Lancer le test, vérifier l'échec**

Run: `cd briques/agenda/backend && python3 -m pytest tests/test_presence.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'routers.presence'`).

- [ ] **Step 3: Ajouter `publish_presence_change` à `services/pubsub.py`**

À la fin de `services/pubsub.py`, ajouter :

```python
async def publish_presence_change(event_type: str, payload: dict) -> None:
    """Broadcast d'un changement de présence (partage/arrêt) aux clients SSE. Canal unique
    `presence:changes` (pas d'id — la carte recharge la liste visible). Best-effort."""
    if not settings.REDIS_URL:
        return
    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(settings.REDIS_URL)
        msg = json.dumps({"type": event_type, "data": payload})
        await r.publish("presence:changes", msg)
        await r.aclose()
    except Exception as exc:
        logger.warning("Redis publish (presence) failed: %s", exc)
```

- [ ] **Step 4: Écrire `routers/presence.py`**

```python
"""Présence éphémère (S179) : partager/arrêter/lister sa position. L'identité est TOUJOURS
`user["sub"]` (jamais le corps) — motif anti-usurpation S178. `scope=event` exige que
l'appelant soit participant de l'event et calque l'expiration sur la fin de l'event."""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from db import get_db
from models.orm import Event, EventParticipant
from services import presence
from services.pubsub import publish_presence_change

router = APIRouter(tags=["presence"])

TTL_DEFAUT_MIN = 60
TTL_MAX_MIN = 1440


class PresenceEntree(BaseModel):
    lat: float
    lon: float
    accuracy: float | None = None
    label: str | None = None
    scope: str = "famille"
    event_id: str | None = None
    ttl_minutes: int | None = None


@router.post("/presence")
async def partager(body: PresenceEntree, db: AsyncSession = Depends(get_db),
                   user: dict = Depends(get_current_user)):
    """Partage (ou rafraîchit) ma position. `scope=famille` (défaut) : visible de tous,
    expire après `ttl_minutes` (défaut 60, borné). `scope=event` : visible des participants,
    expire à la fin de l'event."""
    uid = user["sub"]
    if body.scope == "event":
        if not body.event_id:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail="event_id requis pour scope=event")
        evt = await db.get(Event, body.event_id)
        if evt is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Événement introuvable")
        part = (await db.execute(select(EventParticipant).where(
            EventParticipant.event_id == body.event_id,
            EventParticipant.user_id == uid))).scalar_one_or_none()
        if part is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="Non participant de cet événement")
        expires_at, scope, event_id = evt.end_at, "event", body.event_id
    else:
        ttl = body.ttl_minutes or TTL_DEFAUT_MIN
        ttl = max(1, min(ttl, TTL_MAX_MIN))
        expires_at, scope, event_id = datetime.utcnow() + timedelta(minutes=ttl), "famille", None

    await presence.upsert_position(db, uid, latitude=body.lat, longitude=body.lon,
                                   expires_at=expires_at, accuracy_m=body.accuracy,
                                   label=body.label, scope=scope, event_id=event_id)
    await publish_presence_change("shared", {"user_id": uid})
    return {"ok": True}


@router.delete("/presence")
async def arreter(db: AsyncSession = Depends(get_db),
                  user: dict = Depends(get_current_user)):
    """Arrête de partager ma position (coupure 1-clic)."""
    await presence.supprimer_position(db, user["sub"])
    await publish_presence_change("stopped", {"user_id": user["sub"]})
    return {"ok": True}


@router.get("/presence")
async def lister(db: AsyncSession = Depends(get_db),
                 user: dict = Depends(get_current_user)):
    """Positions non expirées visibles par moi (famille + events où je participe)."""
    return await presence.positions_visibles(db, user["sub"])
```

- [ ] **Step 5: Brancher le routeur dans `main.py`**

Dans `main.py`, ajouter l'import :

```python
from routers.presence import router as presence_router
```

Et l'inclusion (après `ics_router`) :

```python
app.include_router(presence_router)
```

- [ ] **Step 6: Lancer le test, vérifier le succès**

Run: `cd briques/agenda/backend && python3 -m pytest tests/test_presence.py -q`
Expected: PASS (5 passed).

- [ ] **Step 7: Commit**

```bash
git add briques/agenda/backend/routers/presence.py \
        briques/agenda/backend/services/pubsub.py briques/agenda/backend/main.py \
        briques/agenda/backend/tests/test_presence.py
git commit -m "feat(s179): endpoints présence (sub forcé, scope event gardé) + canal SSE"
```

---

### Task 6: SSE présence `GET /sse/presence`

**Files:**
- Modify: `briques/agenda/backend/routers/sse.py`
- Test: `briques/agenda/backend/tests/test_sse_presence.py`

**Interfaces:**
- Consumes: `auth.get_current_user_sse`, `settings.REDIS_URL`.
- Produces: route `GET /sse/presence` (EventSourceResponse ; canal `presence:changes`).

- [ ] **Step 1: Écrire le test qui échoue**

Créer `tests/test_sse_presence.py` :

```python
"""S179 — le flux SSE présence émet un 'connected' initial (sans Redis en test)."""
from __future__ import annotations

import json

import pytest
from starlette.requests import Request

from config import settings
from routers import sse


class _Req:
    async def is_disconnected(self):
        return True


@pytest.mark.asyncio
async def test_sse_presence_emet_connected(monkeypatch):
    monkeypatch.setattr(settings, "REDIS_URL", "", raising=False)
    resp = await sse.presence_sse(request=_Req(), user={"sub": "alice"})
    gen = resp.body_iterator
    premier = await gen.__anext__()
    data = json.loads(premier["data"])
    assert data["type"] == "connected"
```

- [ ] **Step 2: Lancer le test, vérifier l'échec**

Run: `cd briques/agenda/backend && python3 -m pytest tests/test_sse_presence.py -q`
Expected: FAIL (`AttributeError: module 'routers.sse' has no attribute 'presence_sse'`).

- [ ] **Step 3: Ajouter la route `presence_sse` à `routers/sse.py`**

À la fin de `routers/sse.py`, ajouter (calque `list_sse`, sans accès ressource — toute
personne connectée suit le canal famille) :

```python
@router.get("/sse/presence")
async def presence_sse(
    request: Request,
    user: dict = Depends(get_current_user_sse),
):
    """SSE — changements de présence (partage/arrêt) en temps réel. Canal `presence:changes`."""

    async def _generator():
        if not settings.REDIS_URL:
            yield {"data": json.dumps({"type": "connected"})}
            while not await request.is_disconnected():
                await asyncio.sleep(30)
                yield {"data": json.dumps({"type": "ping"})}
            return

        import redis.asyncio as aioredis

        r = aioredis.from_url(settings.REDIS_URL)
        pubsub = r.pubsub()
        channel = "presence:changes"
        await pubsub.subscribe(channel)
        yield {"data": json.dumps({"type": "connected"})}
        try:
            async for message in pubsub.listen():
                if await request.is_disconnected():
                    break
                if message["type"] == "message":
                    yield {"data": message["data"]}
        except Exception as exc:
            logger.warning("SSE error for presence: %s", exc)
        finally:
            await pubsub.unsubscribe(channel)
            await r.aclose()

    return EventSourceResponse(_generator())
```

- [ ] **Step 4: Lancer le test, vérifier le succès**

Run: `cd briques/agenda/backend && python3 -m pytest tests/test_sse_presence.py -q`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add briques/agenda/backend/routers/sse.py \
        briques/agenda/backend/tests/test_sse_presence.py
git commit -m "feat(s179): flux SSE présence (canal presence:changes)"
```

---

### Task 7: Capacités `/service` + manifest v1.4.0

**Files:**
- Modify: `briques/agenda/backend/routers/service.py`
- Modify: `briques/agenda/manifest.json`
- Modify: `briques/agenda/backend/tests/test_manifest_capacites.py`
- Test: `briques/agenda/backend/tests/test_service_presence_ics.py`

**Interfaces:**
- Consumes: `services.presence.positions_visibles`, `services.abonnement`.
- Produces: routes `GET /service/presence`, `GET /service/ics` ; capacités manifest
  `presence_consulter`, `ics_lien` (toutes deux niveau 0, `action: false`).

- [ ] **Step 1: Écrire les tests qui échouent**

Créer `tests/test_service_presence_ics.py` :

```python
"""S179 — surface /service : consultation présence + lien webcal (identité pinnée perso)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from routers import service as S

PERSO = {"sub": "perso"}


class _Req:
    base_url = "http://agenda.local/"


@pytest.mark.asyncio
async def test_service_presence_consulter(db):
    from services import presence
    await presence.upsert_position(db, "perso", latitude=1.0, longitude=2.0,
                                   expires_at=datetime.utcnow() + timedelta(hours=1))
    out = await S.service_presence_consulter(db=db, user=PERSO)
    assert any(p["user_id"] == "perso" for p in out)


@pytest.mark.asyncio
async def test_service_ics_lien(db):
    out = await S.service_ics_lien(request=_Req(), db=db, user=PERSO)
    assert out["token"]
    assert out["webcal"].startswith("webcal://")
    assert out["webcal"].endswith(f"/ics/{out['token']}.ics")


def test_manifest_v140_contient_les_capacites():
    manifest = json.loads((Path(__file__).resolve().parents[2] / "manifest.json").read_text())
    assert manifest["version"] == "1.4.0"
    noms = {c["nom"] for c in manifest["capacites"]}
    assert {"presence_consulter", "ics_lien"} <= noms
```

- [ ] **Step 2: Lancer le test, vérifier l'échec**

Run: `cd briques/agenda/backend && python3 -m pytest tests/test_service_presence_ics.py -q`
Expected: FAIL (`AttributeError: module 'routers.service' has no attribute 'service_presence_consulter'`).

- [ ] **Step 3: Ajouter les routes `/service` dans `routers/service.py`**

À la fin de `routers/service.py`, ajouter :

```python
# ── S179 : présence + abonnement webcal ───────────────────────────────────────
from services import abonnement as _abonnement  # noqa: E402
from services import presence as _presence  # noqa: E402


@router.get("/presence")
async def service_presence_consulter(db: AsyncSession = Depends(get_db),
                                     user: dict = Depends(get_current_user)):
    """Qui a partagé sa position (visible par l'identité pinnée), non expirées. Lecture seule."""
    return await _presence.positions_visibles(db, user["sub"])


@router.get("/ics")
async def service_ics_lien(request: Request, db: AsyncSession = Depends(get_db),
                           user: dict = Depends(get_current_user)):
    """URL d'abonnement webcal de l'agenda (à coller dans un client calendrier). Lecture seule."""
    base = (settings.AGENDA_URL_PUBLIQUE or str(request.base_url)).rstrip("/")
    token = await _abonnement.obtenir_ou_creer_token(db, user["sub"])
    return {"token": token, "https": _abonnement.url_https(base, token),
            "webcal": _abonnement.url_webcal(base, token)}
```

- [ ] **Step 4: Mettre à jour `manifest.json`**

Dans `briques/agenda/manifest.json` : passer `"version"` de `"1.3.0"` à `"1.4.0"`, et
ajouter ces deux objets à la fin du tableau `"capacites"` :

```json
{
  "nom": "presence_consulter",
  "description": "Liste les personnes ayant partagé leur position (carte familiale + « en route » sur un événement), non expirées. Renvoie nom, couleur, latitude/longitude, ancienneté. Lecture seule.",
  "methode": "GET",
  "chemin": "/service/presence",
  "params": {},
  "action": false
},
{
  "nom": "ics_lien",
  "description": "Donne à l'utilisateur son URL d'abonnement webcal (à coller dans Apple Calendar / Google Agenda / Outlook pour voir l'agenda du Cœur, lecture seule). Crée le jeton au besoin.",
  "methode": "GET",
  "chemin": "/service/ics",
  "params": {},
  "action": false
}
```

- [ ] **Step 5: Mettre à jour `tests/test_manifest_capacites.py`**

Dans `test_les_capacites_attendues`, ajouter au set `attendues` (après le bloc Sondages) :

```python
        # Présence + abonnement webcal (S179)
        "presence_consulter", "ics_lien",
```

La politique de gates (`test_politique_de_gates_agenda`) reste inchangée : les deux
nouvelles capacités sont `action: false`, donc l'ensemble des gardées ne change pas.

- [ ] **Step 6: Lancer les tests manifest + service, vérifier le succès**

Run: `cd briques/agenda/backend && python3 -m pytest tests/test_service_presence_ics.py tests/test_manifest_capacites.py -q`
Expected: PASS (tous verts — dont `test_chaque_capacite_pointe_une_route_reelle` qui valide
que `/service/presence` et `/service/ics` existent).

- [ ] **Step 7: Commit**

```bash
git add briques/agenda/backend/routers/service.py briques/agenda/manifest.json \
        briques/agenda/backend/tests/test_manifest_capacites.py \
        briques/agenda/backend/tests/test_service_presence_ics.py
git commit -m "feat(s179): capacités presence_consulter + ics_lien (manifest v1.4.0)"
```

---

### Task 8: Front `/app` — onglet 📍 Présence (carte Leaflet) + bloc webcal

**Files:**
- Create: `briques/agenda/backend/static/leaflet.js` (copie)
- Create: `briques/agenda/backend/static/leaflet.css` (copie)
- Create: `briques/agenda/backend/static/leaflet.markercluster.js` (copie)
- Modify: `briques/agenda/backend/templates_app.py`
- Test: `briques/agenda/backend/tests/test_presence_front.py`

**Interfaces:**
- Consumes: routes `GET/POST/DELETE /presence`, `GET /sse/presence`, `GET /ics/cle`,
  `POST /ics/regenerer` (via `fetch` authentifié dans la page). Assets Leaflet servis sous
  `/static/leaflet.*` (mount existant `main.py:108`).

- [ ] **Step 1: Copier les assets Leaflet vendorés depuis la brique geo**

```bash
cp briques/geo/static/leaflet.js briques/agenda/backend/static/leaflet.js
cp briques/geo/static/leaflet.css briques/agenda/backend/static/leaflet.css
cp briques/geo/static/leaflet.markercluster.js briques/agenda/backend/static/leaflet.markercluster.js
```

- [ ] **Step 2: Écrire le test qui échoue**

Créer `tests/test_presence_front.py` :

```python
"""S179 — la page /app expose l'onglet Présence, charge Leaflet et montre le bloc webcal."""
from __future__ import annotations

from pathlib import Path

from templates_app import page_app

HTML = page_app("https://kc.local", "oria", "calendar-app")


def test_assets_leaflet_copies():
    base = Path(__file__).resolve().parents[1] / "static"
    for f in ("leaflet.js", "leaflet.css", "leaflet.markercluster.js"):
        assert (base / f).exists(), f"asset manquant : {f}"


def test_onglet_presence_present():
    assert 'data-vue="presence"' in HTML
    assert "📍" in HTML


def test_charge_leaflet_et_bloc_webcal():
    assert "/static/leaflet.js" in HTML
    assert "/static/leaflet.css" in HTML
    assert "Abonnement" in HTML  # bloc webcal dans Réglages
```

- [ ] **Step 3: Lancer le test, vérifier l'échec**

Run: `cd briques/agenda/backend && python3 -m pytest tests/test_presence_front.py -q`
Expected: FAIL (`test_onglet_presence_present` : `data-vue="presence"` absent).

- [ ] **Step 4: Charger le CSS Leaflet dans le `<head>` de la page**

Dans `templates_app.py`, dans le `<head>` de la page (près des autres `<style>`/`<link>`),
ajouter la feuille de style Leaflet :

```html
<link rel="stylesheet" href="/static/leaflet.css">
```

- [ ] **Step 5: Ajouter le bouton d'onglet Présence**

Dans `templates_app.py`, dans `nav.innerHTML` (le bloc qui liste les boutons d'onglets),
ajouter le bouton Présence juste avant le bouton Réglages :

```javascript
    '<button data-vue="presence" onclick="montrerVue(\'presence\')">📍 Présence</button>' +
```

- [ ] **Step 6: Router la vue dans `montrerVue`**

Dans `templates_app.py`, dans la fonction `montrerVue`, ajouter la branche présence (à côté
des `else if (nom === "listes")` …) et fermer le SSE présence en quittant la vue :

```javascript
  else if (nom === "presence") vuePresence();
```

Et dans la ligne qui ferme les SSE des vues quittées (près de `if (nom !== "listes" &&
SSE_LISTE)`), ajouter :

```javascript
  if (nom !== "presence" && SSE_PRESENCE) { SSE_PRESENCE.close(); SSE_PRESENCE = null; }
```

- [ ] **Step 7: Ajouter la logique Présence (carte + partage + SSE)**

Dans `templates_app.py`, avant la balise `</script>` finale, ajouter :

```javascript
// ═══════════════ Présence éphémère (S179) ═══════════════
let SSE_PRESENCE = null, CARTE_PRESENCE = null, COUCHE_PRESENCE = null, LEAFLET_PRET = false;

function chargerLeaflet() {
  // Charge le JS Leaflet vendoré une seule fois (zéro CDN). Résout quand L est prêt.
  return new Promise((resolve) => {
    if (window.L) { resolve(); return; }
    const s = document.createElement("script");
    s.src = "/static/leaflet.js";
    s.onload = () => resolve();
    document.head.appendChild(s);
  });
}

async function vuePresence() {
  document.getElementById("vue").innerHTML =
    '<div class="barre"><strong>Présence</strong>' +
    '<button onclick="partagerPosition(\'famille\')">📍 Partager ma position</button>' +
    '<button onclick="arreterPosition()">Arrêter</button></div>' +
    '<div id="carte-presence" style="height:60vh;border-radius:8px;overflow:hidden"></div>' +
    '<div id="liste-presence" class="muted" style="margin-top:8px"></div>';
  await chargerLeaflet();
  // Fonds souverains : IGN Géoplateforme (sans clé) + OSM en repli (motif brique geo).
  const ign = L.tileLayer(
    "https://data.geopf.fr/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0" +
    "&LAYER=GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2&STYLE=normal&TILEMATRIXSET=PM" +
    "&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&FORMAT=image/png",
    { maxZoom: 19, attribution: "© IGN Géoplateforme" });
  const osm = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    { maxZoom: 19, attribution: "© OpenStreetMap" });
  CARTE_PRESENCE = L.map("carte-presence", { layers: [ign] }).setView([46.6, 2.4], 6);
  L.control.layers({ "Plan IGN": ign, "OpenStreetMap": osm }).addTo(CARTE_PRESENCE);
  COUCHE_PRESENCE = L.layerGroup().addTo(CARTE_PRESENCE);
  await chargerPresence();
  ouvrirSSEPresence();
}

async function chargerPresence() {
  let positions = [];
  try { positions = await api("/presence"); } catch (e) { return; }
  if (!COUCHE_PRESENCE) return;
  COUCHE_PRESENCE.clearLayers();
  const liste = document.getElementById("liste-presence");
  if (!positions.length) { if (liste) liste.textContent = "Personne ne partage sa position."; return; }
  const bornes = [];
  for (const p of positions) {
    const quand = new Date(p.updated_at).toLocaleTimeString("fr-FR",
      { hour: "2-digit", minute: "2-digit" });
    const osm = "https://www.openstreetmap.org/?mlat=" + p.latitude + "&mlon=" + p.longitude;
    L.circleMarker([p.latitude, p.longitude],
      { radius: 9, color: p.avatar_color, fillColor: p.avatar_color, fillOpacity: 0.8 })
      .bindPopup("<strong>" + p.display_name + "</strong><br>vu à " + quand +
        '<br><a href="' + osm + '" target="_blank" rel="noopener">Ouvrir dans Plans</a>')
      .addTo(COUCHE_PRESENCE);
    bornes.push([p.latitude, p.longitude]);
  }
  if (bornes.length) CARTE_PRESENCE.fitBounds(bornes, { maxZoom: 14, padding: [40, 40] });
  if (liste) liste.textContent = positions.length + " personne(s) en partage.";
}

function partagerPosition(scope, eventId) {
  if (!navigator.geolocation) { alert("Géolocalisation indisponible sur cet appareil."); return; }
  navigator.geolocation.getCurrentPosition(async (pos) => {
    const corps = { lat: pos.coords.latitude, lon: pos.coords.longitude,
                    accuracy: pos.coords.accuracy, scope: scope || "famille" };
    if (eventId) corps.event_id = eventId;
    try { await api("/presence", { method: "POST", body: JSON.stringify(corps) }); }
    catch (e) { alert("Partage impossible."); return; }
    await chargerPresence();
  }, () => alert("Position refusée."), { enableHighAccuracy: true, timeout: 10000 });
}

async function arreterPosition() {
  try { await api("/presence", { method: "DELETE" }); } catch (e) {}
  await chargerPresence();
}

function ouvrirSSEPresence() {
  if (SSE_PRESENCE) return;
  try {
    SSE_PRESENCE = new EventSource("/sse/presence?token=" + encodeURIComponent(JETON));
    SSE_PRESENCE.onmessage = () => chargerPresence();
  } catch (e) { SSE_PRESENCE = null; }
}
```

Note d'intégration : `api(...)` (helper fetch авторisé), `JETON` (l'access token pour le
paramètre SSE) et la structure de `vueX()`/`#vue`/`.barre`/`.muted` existent déjà dans
`templates_app.py` (repris de `vueListes`/`vueSondages`). Réutiliser les mêmes noms ; ne
pas en créer de nouveaux. Si le nom du jeton d'accès diffère (`JETON` vs autre), aligner sur
celui déjà utilisé par `ouvrir`/`api` dans le fichier.

- [ ] **Step 8: Ajouter le bloc « Abonnement calendrier » dans la vue Réglages**

Dans `templates_app.py`, dans la fonction qui rend la vue Réglages (`vueReglages`, celle qui
contient déjà le panneau 🔔 des notifications de S178), ajouter un bloc après le panneau
notifications :

```javascript
  html += '<div class="carte" style="margin-top:16px"><strong>📅 Abonnement calendrier</strong>' +
    '<p class="muted">Colle ce lien dans Apple Calendar / Google Agenda / Outlook ' +
    '(« S\'abonner à un calendrier ») pour voir cet agenda, en lecture seule.</p>' +
    '<input id="ics-url" readonly style="width:100%" value="…">' +
    '<div class="barre"><button onclick="copierICS()">Copier</button>' +
    '<button onclick="regenererICS()">Régénérer</button></div></div>';
```

Et les fonctions associées, avant `</script>` :

```javascript
async function chargerICS() {
  try {
    const r = await api("/ics/cle");
    const champ = document.getElementById("ics-url");
    if (champ) champ.value = r.webcal;
  } catch (e) {}
}

function copierICS() {
  const champ = document.getElementById("ics-url");
  if (champ) { champ.select(); navigator.clipboard && navigator.clipboard.writeText(champ.value); }
}

async function regenererICS() {
  if (!confirm("Régénérer le lien invalidera l'abonnement actuel. Continuer ?")) return;
  try {
    const r = await api("/ics/regenerer", { method: "POST" });
    const champ = document.getElementById("ics-url");
    if (champ) champ.value = r.webcal;
  } catch (e) {}
}
```

Appeler `chargerICS()` à la fin du rendu de `vueReglages` (après avoir injecté le HTML, comme
le panneau notifications appelle son propre chargement).

- [ ] **Step 9: Lancer le test, vérifier le succès**

Run: `cd briques/agenda/backend && python3 -m pytest tests/test_presence_front.py -q`
Expected: PASS (3 passed).

- [ ] **Step 10: Lancer TOUTE la suite agenda (non-régression)**

Run: `cd briques/agenda/backend && python3 -m pytest -q`
Expected: PASS (suite existante + neufs S179 ; ~294 précédents + nouveaux, aucun échec).

- [ ] **Step 11: Commit**

```bash
git add briques/agenda/backend/static/leaflet.js \
        briques/agenda/backend/static/leaflet.css \
        briques/agenda/backend/static/leaflet.markercluster.js \
        briques/agenda/backend/templates_app.py \
        briques/agenda/backend/tests/test_presence_front.py
git commit -m "feat(s179): onglet Présence (carte Leaflet souveraine) + bloc abonnement webcal"
```

---

## Notes de fin (RESTE avant déploiement — hors périmètre code)

- **Smoke Postgres** : `alembic upgrade 0011` puis `downgrade 0010` sur une base Postgres
  (les tests tournent sur `create_all` SQLite ; l'enum `live_position_scope` et la contrainte
  unique `ics_token` ne sont exercées qu'en Postgres).
- **`AGENDA_URL_PUBLIQUE`** doit être posée en prod pour que les URLs webcal soient absolues
  et correctes (sinon repli sur `request.base_url`).
- **LIVE différé** : suivre [[feedback-live-differe-fin-s180]] — preuves groupées après S180.
- **Fast-follow noté (spec §9)** : import ICS entrant ; partage en direct (fenêtre X min) ;
  historique ; groupes familiaux explicites ; tuiles auto-hébergées ; push « X partage sa
  position » ; géocodage de `Event.location`.

## Self-Review (fait)

- **Couverture spec** : présence (Tasks 1,4,5,6,8) ; ICS webcal (Tasks 1,2,3,8) ; surface LLM
  (Task 7) ; garde-fous anti-intrusifs (sub forcé T5, purge/expiration T4, jeton révocable T3,
  vocabulaire T8) ; tests + migration (chaque task) → toutes les sections de la spec ont une
  tâche.
- **Placeholders** : aucun `TODO`/`TBD` ; tout le code est fourni. Les points d'intégration
  front (`api`, `JETON`, `vueReglages`) référencent des symboles existants, signalés comme
  tels avec instruction d'alignement.
- **Cohérence des types** : `positions_visibles` renvoie partout le même dict (T4 défini,
  consommé T5/T7/T8) ; `generer_ics`/`event_en_vevent` signatures stables (T2→T3) ;
  `publish_presence_change(event_type, payload)` défini T5, consommé T5/monkeypatché tests ;
  `abonnement.*` signatures stables (T3→T7).

# S174 — Rappels par personne — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rendre les rappels d'agenda réglables **par personne**, exposer présence + chat au dashboard, et poser un journal d'activité — en s'appuyant sur l'identité multi-utilisateur livrée en S171→S173.

**Architecture:** La brique agenda (`briques/agenda/backend`, FastAPI + SQLAlchemy async) gagne trois éléments de données (`EventParticipant.rappels` nullable, tables `user_profiles` et `event_activity_log`), des recipients hybrides (créateur auto-participant + « inviter tous les membres »), l'enrichissement de `/service/events` avec les participants et leurs rappels effectifs, et l'UI correspondante dans l'appli `/app`. Le Cœur (`core/proactif.py`) apprend à pousser un rappel **par participant** (le `/pousser` de la brique connexion route déjà par utilisateur), en réservant la pastille 🔔 au propriétaire local.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy 2.0 async, Alembic, Pydantic v2, pytest / pytest-asyncio. Front = HTML/JS vanilla injecté par `templates_app.py`. Cœur = sqlite3 + httpx.

## Global Constraints

- **Régime de preuve : LIVE différé à la fin de S180.** Code + tests natifs + revue + commit uniquement. Aucun `docker`, navigateur réel, ni Keycloak/Postgres réel à lancer. (`feedback-live-differe-fin-s180`).
- **Rétro-compatibilité stricte** : un event mono-user « perso » sans participant explicite doit continuer à sonner exactement comme aujourd'hui (`event.rappels` → messagerie de `perso` + badge 🔔).
- **Sémantique `rappels` à trois états** : `None` = hérite du défaut de l'event ; `[]` = aucun rappel (explicite) ; `[m, …]` = override personnel. Réutiliser `normaliser_rappels` de `models/schemas.py` (trie, dédoublonne, borne 0..40320, ≤ 5, `None` reste `None`).
- **Tests appelés en direct** : le style du repo teste les fonctions de router **directement** (`await R.fonction(..., db=db, user={"sub": ...})`), sans `TestClient`. Fixture `db` = SQLite in-memory (`tests/conftest.py`), tables via `Base.metadata.create_all`.
- **Commandes de test** :
  - Brique agenda : `cd briques/agenda/backend && python3 -m pytest tests/<fichier> -v`
  - Cœur : `python3 -m pytest core/<fichier> -v` (depuis la racine du repo)
- **Identité `user` dans les routers** : dict avec clé `"sub"`. Le propriétaire local = `settings.AGENDA_USER_ID` (« perso »).
- **Commit** : un commit par tâche terminée (`feat(s174): …` ou `test(s174): …`). Terminer chaque message par les deux lignes `Co-Authored-By:` / `Claude-Session:` habituelles.

---

## File Structure

**Brique agenda** (`briques/agenda/backend/`) :
- `models/orm.py` — +colonne `EventParticipant.rappels`, +modèles `UserProfile`, `EventActivityLog`.
- `models/schemas.py` — +`rappels` sur `ParticipantStatusUpdate`, +`ProfileOut`, +`ActivityLogOut`.
- `alembic/versions/0006_rappels_par_personne.py` — **créé** : colonne + 2 tables (schéma seul, pas de data).
- `services/rappels.py` — **créé** : `rappels_effectifs()` (pur).
- `services/profils.py` — **créé** : upsert, résolution nom + couleur (`nom_affiche`, `couleur_pour`, `upsert`, `resoudre`).
- `services/journal.py` — **créé** : écriture d'une entrée d'activité (`consigner`).
- `services/backfill.py` — **créé** : `creer_participants_createurs(db)` idempotent (legacy events → participant créateur).
- `services/agregation.py` — modifié : `/service/events` porte `participants` + `rappels_effectifs`.
- `routers/participants.py` — modifié : `rappels` au PATCH, `POST …/participants/all`, auto-participant importé.
- `routers/profiles.py` — **créé** : `POST /profiles/me`, `GET /profiles`.
- `routers/activity.py` — **créé** : `GET /events/{id}/activity`.
- `routers/events.py`, `routers/service.py`, `routers/comments.py` — modifiés : auto-participant + écriture journal.
- `main.py` — modifié : inclut les nouveaux routers + backfill au lifespan.
- `templates_app.py` — modifié : blocs présence / rappels perso / chat / activité + `POST /profiles/me` au login.
- `tests/test_*.py` — **créés** : un fichier par unité.

**Cœur** (`core/`) :
- `core/proactif.py` — modifié : `_pousser_messagerie(utilisateur=…)`, `_check_agenda` par participant, `_dedup_pousse`.
- `core/test_proactif_par_personne.py` — **créé**.

---

## Task 1 : Couche de données (colonne + 2 tables + migration)

**Files:**
- Modify: `briques/agenda/backend/models/orm.py`
- Create: `briques/agenda/backend/alembic/versions/0006_rappels_par_personne.py`
- Test: `briques/agenda/backend/tests/test_orm_s174.py`

**Interfaces:**
- Produces : `EventParticipant.rappels: list[int] | None` ; modèle `UserProfile(user_id PK, display_name, avatar_color, updated_at)` ; modèle `EventActivityLog(id, event_id FK CASCADE, user_id, user_nom, action, details JSON, created_at)`.

- [ ] **Step 1: Écrire le test de round-trip ORM**

Créer `briques/agenda/backend/tests/test_orm_s174.py` :

```python
"""S174 — round-trip ORM : rappels par participant (3 états), profil, journal."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from models.orm import (
    Calendar,
    Event,
    EventActivityLog,
    EventParticipant,
    UserProfile,
)


async def _event(db) -> Event:
    cal = Calendar(user_id="perso", name="Perso", is_default=True)
    db.add(cal)
    await db.flush()
    debut = datetime(2030, 1, 1, 14, 0)
    evt = Event(calendar_id=cal.id, title="RDV", start_at=debut,
                end_at=debut + timedelta(hours=1), created_by="perso", rappels=[10])
    db.add(evt)
    await db.commit()
    await db.refresh(evt)
    return evt


@pytest.mark.asyncio
@pytest.mark.parametrize("valeur", [None, [], [60], [10, 1440]])
async def test_participant_rappels_persistent(db, valeur):
    evt = await _event(db)
    p = EventParticipant(event_id=evt.id, user_id="marina", status="pending", rappels=valeur)
    db.add(p)
    await db.commit()
    relu = (await db.execute(
        select(EventParticipant).where(EventParticipant.id == p.id)
    )).scalar_one()
    assert relu.rappels == valeur


@pytest.mark.asyncio
async def test_participant_rappels_defaut_none(db):
    evt = await _event(db)
    p = EventParticipant(event_id=evt.id, user_id="marina", status="pending")
    db.add(p)
    await db.commit()
    relu = (await db.execute(
        select(EventParticipant).where(EventParticipant.id == p.id)
    )).scalar_one()
    assert relu.rappels is None  # None = hérite (≠ [] = aucun)


@pytest.mark.asyncio
async def test_user_profile_round_trip(db):
    db.add(UserProfile(user_id="marina", display_name="Marina", avatar_color="#ec4899"))
    await db.commit()
    relu = (await db.execute(
        select(UserProfile).where(UserProfile.user_id == "marina")
    )).scalar_one()
    assert relu.display_name == "Marina" and relu.avatar_color == "#ec4899"


@pytest.mark.asyncio
async def test_activity_log_round_trip(db):
    evt = await _event(db)
    db.add(EventActivityLog(event_id=evt.id, user_id="perso", user_nom="Toi",
                            action="event_created", details={"titre": "RDV"}))
    await db.commit()
    relu = (await db.execute(
        select(EventActivityLog).where(EventActivityLog.event_id == evt.id)
    )).scalar_one()
    assert relu.action == "event_created" and relu.details == {"titre": "RDV"}
```

- [ ] **Step 2: Lancer le test — il échoue**

Run: `cd briques/agenda/backend && python3 -m pytest tests/test_orm_s174.py -v`
Expected: FAIL (`ImportError: cannot import name 'UserProfile'` / `EventActivityLog`, et `EventParticipant` n'a pas `rappels`).

- [ ] **Step 3: Ajouter la colonne et les deux modèles dans `models/orm.py`**

Dans la classe `EventParticipant`, après le champ `responded_at`, ajouter :

```python
    # Override personnel des rappels (minutes avant le début). NULL = hérite de
    # Event.rappels (le défaut de l'événement) ; [] = aucun rappel (choix explicite) ;
    # [10, 1440] = réglage propre à cette personne. Voir services/rappels.py.
    rappels: Mapped[list[int] | None] = mapped_column(JSON, nullable=True, default=None)
```

À la fin du fichier (après `UserToken`), ajouter les deux modèles :

```python
class UserProfile(Base):
    """Profil affichable d'un utilisateur (S174) : résout un user_id (sub Keycloak ou
    « perso ») en nom lisible + pastille couleur. Semé au login depuis les claims du
    token ; résolution 100 % locale (aucun appel réseau au runtime)."""

    __tablename__ = "user_profiles"

    user_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    avatar_color: Mapped[str] = mapped_column(String(20), nullable=False, default="#3B82F6")
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class EventActivityLog(Base):
    """Journal d'activité d'un événement (S174) : qui a changé quoi, quand. Gabarit
    repris d'AuditLogs (brique Forge). user_nom est un SNAPSHOT du nom au moment de
    l'action (robuste si le profil change/disparaît ensuite)."""

    __tablename__ = "event_activity_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    event_id: Mapped[str] = mapped_column(String(36), ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    user_nom: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
```

- [ ] **Step 4: Lancer le test — il passe**

Run: `cd briques/agenda/backend && python3 -m pytest tests/test_orm_s174.py -v`
Expected: PASS (tous).

- [ ] **Step 5: Écrire la migration Alembic 0006 (schéma seul)**

Créer `briques/agenda/backend/alembic/versions/0006_rappels_par_personne.py` :

```python
"""0006 — rappels par personne : EventParticipant.rappels + user_profiles + event_activity_log

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-15
"""

from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Override personnel des rappels. NULL par défaut = hérite du défaut de l'événement
    # (les participants existants ne changent donc pas de comportement).
    op.add_column(
        "event_participants",
        sa.Column("rappels", sa.JSON(), nullable=True),
    )
    op.create_table(
        "user_profiles",
        sa.Column("user_id", sa.String(length=255), primary_key=True),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("avatar_color", sa.String(length=20), nullable=False, server_default="#3B82F6"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_table(
        "event_activity_log",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("event_id", sa.String(length=36), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("user_nom", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=30), nullable=False),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("event_activity_log")
    op.drop_table("user_profiles")
    op.drop_column("event_participants", "rappels")
```

- [ ] **Step 6: Vérifier la cohérence de la chaîne de migrations**

Run: `cd briques/agenda/backend && python3 -c "import re,glob; revs={}; downs={}; [revs.setdefault(re.search(r'revision = \"(\d+)\"', open(f).read()).group(1), f) for f in glob.glob('alembic/versions/*.py')]; print('revisions:', sorted(revs))"`
Expected: liste incluant `'0006'`, sans doublon (`['0001','0002','0003','0004','0005','0006']`).

- [ ] **Step 7: Commit**

```bash
git add briques/agenda/backend/models/orm.py briques/agenda/backend/alembic/versions/0006_rappels_par_personne.py briques/agenda/backend/tests/test_orm_s174.py
git commit -m "feat(s174): couche données — rappels par participant + tables profil & journal"
```

---

## Task 2 : Backfill idempotent des participants créateurs

**Files:**
- Create: `briques/agenda/backend/services/backfill.py`
- Modify: `briques/agenda/backend/main.py`
- Test: `briques/agenda/backend/tests/test_backfill.py`

**Interfaces:**
- Produces : `async def creer_participants_createurs(db: AsyncSession) -> int` — pour chaque event **sans aucun participant**, crée `EventParticipant(user_id=event.created_by, status="accepted", rappels=None)`. Idempotent (re-run → 0). Renvoie le nombre de lignes créées.

- [ ] **Step 1: Écrire le test**

Créer `briques/agenda/backend/tests/test_backfill.py` :

```python
"""S174 — backfill : chaque event legacy sans participant reçoit un participant créateur."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from models.orm import Calendar, Event, EventParticipant
from services.backfill import creer_participants_createurs


async def _event(db, created_by="perso") -> Event:
    cal = Calendar(user_id=created_by, name="Perso", is_default=True)
    db.add(cal)
    await db.flush()
    debut = datetime(2030, 1, 1, 14, 0)
    evt = Event(calendar_id=cal.id, title="Legacy", start_at=debut,
                end_at=debut + timedelta(hours=1), created_by=created_by, rappels=[10])
    db.add(evt)
    await db.commit()
    await db.refresh(evt)
    return evt


@pytest.mark.asyncio
async def test_backfill_cree_le_createur(db):
    evt = await _event(db)
    n = await creer_participants_createurs(db)
    assert n == 1
    p = (await db.execute(
        select(EventParticipant).where(EventParticipant.event_id == evt.id)
    )).scalar_one()
    assert p.user_id == "perso" and p.status == "accepted" and p.rappels is None


@pytest.mark.asyncio
async def test_backfill_idempotent(db):
    await _event(db)
    assert await creer_participants_createurs(db) == 1
    assert await creer_participants_createurs(db) == 0  # 2ᵉ passage : rien à faire


@pytest.mark.asyncio
async def test_backfill_ignore_event_deja_pourvu(db):
    evt = await _event(db)
    db.add(EventParticipant(event_id=evt.id, user_id="marina", status="accepted"))
    await db.commit()
    assert await creer_participants_createurs(db) == 0  # a déjà un participant
```

- [ ] **Step 2: Lancer le test — il échoue**

Run: `cd briques/agenda/backend && python3 -m pytest tests/test_backfill.py -v`
Expected: FAIL (`ModuleNotFoundError: services.backfill`).

- [ ] **Step 3: Implémenter le backfill**

Créer `briques/agenda/backend/services/backfill.py` :

```python
"""Backfill idempotent (S174) : garantit que chaque événement a au moins un participant
(son créateur, accepté). Rend le modèle « destinataire = participant » uniforme pour les
événements créés avant S174. Appelé au démarrage (lifespan) ; une fois posé, re-run = 0.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.orm import Event, EventParticipant


async def creer_participants_createurs(db: AsyncSession) -> int:
    """Pour chaque event sans AUCUN participant, crée un participant créateur (accepté,
    rappels=None → hérite du défaut de l'event). Renvoie le nombre de lignes créées."""
    avec_participant = set(
        (await db.execute(select(EventParticipant.event_id).distinct())).scalars().all()
    )
    events = (await db.execute(select(Event))).scalars().all()
    cree = 0
    for e in events:
        if e.id in avec_participant:
            continue
        db.add(EventParticipant(id=str(uuid.uuid4()), event_id=e.id,
                                user_id=e.created_by, status="accepted", rappels=None))
        cree += 1
    if cree:
        await db.commit()
    return cree
```

- [ ] **Step 4: Lancer le test — il passe**

Run: `cd briques/agenda/backend && python3 -m pytest tests/test_backfill.py -v`
Expected: PASS.

- [ ] **Step 5: Câbler le backfill au démarrage**

Dans `briques/agenda/backend/main.py`, la fonction `lifespan` fait `await init_db()` puis `yield`. La fabrique de sessions est `AsyncSessionLocal` (dans `db.py`). Insérer le backfill **après** `await init_db()` et **avant** `logger.info("Calendar service started…")` :

```python
    # S174 : rend le modèle « destinataire = participant » uniforme pour les events
    # d'avant le sprint. Idempotent — quasi no-op après le premier démarrage.
    try:
        from db import AsyncSessionLocal
        from services.backfill import creer_participants_createurs
        async with AsyncSessionLocal() as _db:
            n = await creer_participants_createurs(_db)
            if n:
                logger.info("S174 backfill : %d participant(s) créateur(s) posé(s)", n)
    except Exception as ex:  # noqa: BLE001 — un backfill KO ne doit pas empêcher le boot
        logger.warning("S174 backfill ignoré : %s", ex)
```

- [ ] **Step 6: Vérifier que la suite agenda reste verte**

Run: `cd briques/agenda/backend && python3 -m pytest -q`
Expected: PASS (aucune régression ; le lifespan n'est pas monté par les tests unitaires).

- [ ] **Step 7: Commit**

```bash
git add briques/agenda/backend/services/backfill.py briques/agenda/backend/main.py briques/agenda/backend/tests/test_backfill.py
git commit -m "feat(s174): backfill idempotent — participant créateur pour les events legacy"
```

---

## Task 3 : Profils (résolution nom + couleur, upsert, endpoints)

**Files:**
- Create: `briques/agenda/backend/services/profils.py`
- Create: `briques/agenda/backend/routers/profiles.py`
- Modify: `briques/agenda/backend/models/schemas.py`, `briques/agenda/backend/main.py`
- Test: `briques/agenda/backend/tests/test_profils.py`

**Interfaces:**
- Produces :
  - `services/profils.py` : `couleur_pour(user_id: str) -> str` (pur, déterministe) ; `nom_affiche(user_id: str, profil: UserProfile | None) -> str` (pur) ; `async upsert(db, user_id, display_name, avatar_color=None) -> UserProfile` ; `async resoudre(db, user_ids: list[str]) -> dict[str, dict]` → `{user_id: {"user_id", "display_name", "avatar_color"}}`.
  - `routers/profiles.py` : `POST /profiles/me` (upsert depuis les claims), `GET /profiles?user_ids=a,b` → `list[ProfileOut]`.
  - `schemas.py` : `ProfileOut(user_id, display_name, avatar_color)`.

- [ ] **Step 1: Écrire le test**

Créer `briques/agenda/backend/tests/test_profils.py` :

```python
"""S174 — profils : résolution nom + couleur (défauts), upsert, endpoints."""

from __future__ import annotations

import pytest

from config import settings
from models.orm import UserProfile
from routers import profiles as R
from services import profils


def test_couleur_pour_est_deterministe():
    c1 = profils.couleur_pour("marina")
    assert c1 == profils.couleur_pour("marina")  # stable
    assert c1 in profils.PALETTE


def test_nom_affiche_defauts():
    settings.AGENDA_USER_ID = "perso"
    assert profils.nom_affiche("perso", None) == "Toi"       # propriétaire local
    assert profils.nom_affiche("marina", None) == "marina"   # inconnu → id brut
    p = UserProfile(user_id="marina", display_name="Marina", avatar_color="#ec4899")
    assert profils.nom_affiche("marina", p) == "Marina"      # profil connu


@pytest.mark.asyncio
async def test_upsert_cree_puis_met_a_jour(db):
    p = await profils.upsert(db, "marina", "Marina")
    assert p.display_name == "Marina" and p.avatar_color in profils.PALETTE
    p2 = await profils.upsert(db, "marina", "Marina D.")
    assert p2.display_name == "Marina D."  # même ligne, nom mis à jour


@pytest.mark.asyncio
async def test_resoudre_melange_connus_et_inconnus(db):
    await profils.upsert(db, "marina", "Marina")
    res = await profils.resoudre(db, ["marina", "perso"])
    assert res["marina"]["display_name"] == "Marina"
    assert res["perso"]["display_name"] == "Toi"  # défaut propriétaire


@pytest.mark.asyncio
async def test_post_profiles_me_depuis_claims(db):
    out = await R.upsert_me(db=db, user={"sub": "marina", "name": "Marina",
                                         "preferred_username": "marina_d"})
    assert out.display_name == "Marina" and out.user_id == "marina"


@pytest.mark.asyncio
async def test_post_profiles_me_repli_username(db):
    out = await R.upsert_me(db=db, user={"sub": "x", "preferred_username": "xx"})
    assert out.display_name == "xx"  # pas de `name` → preferred_username


@pytest.mark.asyncio
async def test_get_profiles_liste(db):
    await profils.upsert(db, "marina", "Marina")
    out = await R.list_profiles(user_ids="marina,perso", db=db,
                                user={"sub": "perso"})
    noms = {p.user_id: p.display_name for p in out}
    assert noms == {"marina": "Marina", "perso": "Toi"}
```

- [ ] **Step 2: Lancer le test — il échoue**

Run: `cd briques/agenda/backend && python3 -m pytest tests/test_profils.py -v`
Expected: FAIL (`ModuleNotFoundError: services.profils`).

- [ ] **Step 3: Implémenter `services/profils.py`**

```python
"""Profils affichables (S174) : résout un user_id (sub Keycloak / « perso ») en nom +
couleur, semé au login depuis les claims du token. Résolution 100 % locale."""

from __future__ import annotations

import hashlib

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models.orm import UserProfile

# Même palette que le front (templates_app.COULEURS) — pastilles cohérentes UI/back.
PALETTE = ["#5865F2", "#3B82F6", "#22c55e", "#eab308", "#f97316", "#ef4444", "#ec4899", "#a855f7"]


def couleur_pour(user_id: str) -> str:
    """Couleur de pastille déterministe pour un user_id (hash stable → palette)."""
    h = int(hashlib.md5(user_id.encode("utf-8")).hexdigest(), 16)
    return PALETTE[h % len(PALETTE)]


def nom_affiche(user_id: str, profil: UserProfile | None) -> str:
    """Nom lisible : profil connu > « Toi » pour le propriétaire local > user_id brut."""
    if profil and profil.display_name:
        return profil.display_name
    if user_id == settings.AGENDA_USER_ID:
        return "Toi"
    return user_id


async def upsert(db: AsyncSession, user_id: str, display_name: str,
                 avatar_color: str | None = None) -> UserProfile:
    """Crée ou met à jour le profil d'un utilisateur (nom + couleur)."""
    prof = await db.get(UserProfile, user_id)
    couleur = avatar_color or couleur_pour(user_id)
    if prof is None:
        prof = UserProfile(user_id=user_id, display_name=display_name, avatar_color=couleur)
        db.add(prof)
    else:
        prof.display_name = display_name
        if avatar_color:
            prof.avatar_color = avatar_color
    await db.commit()
    await db.refresh(prof)
    return prof


async def resoudre(db: AsyncSession, user_ids: list[str]) -> dict[str, dict]:
    """{user_id: {user_id, display_name, avatar_color}} pour chaque id, avec défauts
    pour les inconnus (« Toi » pour le propriétaire, sinon id brut ; couleur dérivée)."""
    uniques = list(dict.fromkeys(user_ids))
    if not uniques:
        return {}
    rows = (await db.execute(
        select(UserProfile).where(UserProfile.user_id.in_(uniques))
    )).scalars().all()
    connus = {p.user_id: p for p in rows}
    res: dict[str, dict] = {}
    for uid in uniques:
        p = connus.get(uid)
        res[uid] = {"user_id": uid, "display_name": nom_affiche(uid, p),
                    "avatar_color": p.avatar_color if p else couleur_pour(uid)}
    return res
```

- [ ] **Step 4: Ajouter `ProfileOut` dans `models/schemas.py`**

À la fin du fichier `models/schemas.py` :

```python
# ── Profils (S174) ────────────────────────────────────────────────────────────

class ProfileOut(BaseModel):
    user_id: str
    display_name: str
    avatar_color: str

    class Config:
        from_attributes = True
```

- [ ] **Step 5: Implémenter `routers/profiles.py`**

```python
"""Profils affichables — /profiles (S174). POST /profiles/me sème le profil de l'appelant
depuis les claims de son token ; GET /profiles résout une liste de user_ids en noms."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from db import get_db
from models.schemas import ProfileOut
from services import profils

router = APIRouter(tags=["profiles"])


@router.post("/profiles/me", response_model=ProfileOut)
async def upsert_me(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Enregistre/rafraîchit le profil de l'appelant depuis les claims de son token
    (name > preferred_username > sub). Appelé par l'appli /app juste après le login."""
    nom = user.get("name") or user.get("preferred_username") or user["sub"]
    return await profils.upsert(db, user["sub"], nom)


@router.get("/profiles", response_model=list[ProfileOut])
async def list_profiles(
    user_ids: str = Query(..., description="user_ids séparés par des virgules"),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Résout une liste de user_ids en {user_id, display_name, avatar_color} (défauts
    pour les inconnus). Alimente présence / chat / rappels côté dashboard."""
    ids = [u for u in user_ids.split(",") if u]
    resolus = await profils.resoudre(db, ids)
    return list(resolus.values())
```

- [ ] **Step 6: Inclure le router dans `main.py`**

Dans `briques/agenda/backend/main.py` : ajouter l'import `from routers.profiles import router as profiles_router` (près des autres imports de routers) et `app.include_router(profiles_router)` (près des autres `include_router`).

- [ ] **Step 7: Lancer le test — il passe**

Run: `cd briques/agenda/backend && python3 -m pytest tests/test_profils.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add briques/agenda/backend/services/profils.py briques/agenda/backend/routers/profiles.py briques/agenda/backend/models/schemas.py briques/agenda/backend/main.py briques/agenda/backend/tests/test_profils.py
git commit -m "feat(s174): profils — résolution nom+couleur, upsert au login, endpoints"
```

---

## Task 4 : Recipients hybrides (auto-participant, inviter tous, rappels perso)

**Files:**
- Modify: `briques/agenda/backend/routers/participants.py`, `briques/agenda/backend/routers/events.py`, `briques/agenda/backend/routers/service.py`, `briques/agenda/backend/models/schemas.py`
- Create: `briques/agenda/backend/services/membres.py`
- Test: `briques/agenda/backend/tests/test_participants_s174.py`

**Interfaces:**
- Consumes : `EventParticipant.rappels` (Task 1), `normaliser_rappels` (schemas).
- Produces :
  - `services/membres.py` : `async membres_du_calendrier(db, calendar_id) -> set[str]` = `{Calendar.user_id} ∪ {CalendarMember.user_id}`.
  - `services/participants_auto.py` : `async assurer_participant(db, event_id, user_id, status="accepted")` (idempotent, no-commit) — réutilisé par events/service routers.
  - `participants.py` : `POST /events/{id}/participants/all` ; `PATCH …/participants/{uid}` accepte `rappels`.
  - `schemas.py` : `ParticipantStatusUpdate` gagne `rappels: Optional[list[int]]` + `status` optionnel ; `ParticipantOut` gagne `rappels`.

- [ ] **Step 1: Écrire le test**

Créer `briques/agenda/backend/tests/test_participants_s174.py` :

```python
"""S174 — recipients hybrides : auto-participant, inviter tous, rappels perso."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from models.orm import Calendar, CalendarMember, Event, EventParticipant
from models.schemas import EventUpdate, ParticipantStatusUpdate
from routers import events as EV
from routers import participants as P
from services.membres import membres_du_calendrier

OWNER = {"sub": "perso"}


async def _cal(db) -> Calendar:
    cal = Calendar(user_id="perso", name="Perso", is_default=True)
    db.add(cal)
    await db.commit()
    await db.refresh(cal)
    return cal


@pytest.mark.asyncio
async def test_creation_event_ajoute_le_createur(db):
    cal = await _cal(db)
    debut = datetime(2030, 1, 1, 14, 0)
    evt = await EV.create_event(
        cal.id,
        EventUpdate(title="RDV", start_at=debut, end_at=debut + timedelta(hours=1)),
        db=db, user=OWNER,
    )
    parts = (await db.execute(
        select(EventParticipant).where(EventParticipant.event_id == evt.id)
    )).scalars().all()
    assert [(p.user_id, p.status) for p in parts] == [("perso", "accepted")]


@pytest.mark.asyncio
async def test_membres_du_calendrier(db):
    cal = await _cal(db)
    db.add(CalendarMember(calendar_id=cal.id, user_id="marina", role="editor"))
    await db.commit()
    assert await membres_du_calendrier(db, cal.id) == {"perso", "marina"}


@pytest.mark.asyncio
async def test_inviter_tous_les_membres(db):
    cal = await _cal(db)
    db.add(CalendarMember(calendar_id=cal.id, user_id="marina", role="editor"))
    await db.commit()
    debut = datetime(2030, 1, 1, 14, 0)
    evt = Event(calendar_id=cal.id, title="Diner", start_at=debut,
                end_at=debut + timedelta(hours=1), created_by="perso")
    db.add(evt)
    await db.commit()
    await db.refresh(evt)
    parts = await P.add_all_members(evt.id, db=db, user=OWNER)
    users = {p.user_id for p in parts}
    assert users == {"perso", "marina"}
    # Idempotent : 2ᵉ appel ne duplique pas.
    parts2 = await P.add_all_members(evt.id, db=db, user=OWNER)
    assert {p.user_id for p in parts2} == {"perso", "marina"}


@pytest.mark.asyncio
async def test_patch_rappels_perso(db):
    cal = await _cal(db)
    debut = datetime(2030, 1, 1, 14, 0)
    evt = Event(calendar_id=cal.id, title="RDV", start_at=debut,
                end_at=debut + timedelta(hours=1), created_by="perso")
    db.add(evt)
    db.add(EventParticipant(event_id=evt.id, user_id="marina", status="pending"))
    await db.commit()
    out = await P.update_participant_status(
        evt.id, "marina", ParticipantStatusUpdate(rappels=[60, 1440]), db=db, user=OWNER)
    assert out.rappels == [60, 1440]
    # rappels: [] efface (aucun) ; distinct de None (hérite).
    out2 = await P.update_participant_status(
        evt.id, "marina", ParticipantStatusUpdate(rappels=[]), db=db, user=OWNER)
    assert out2.rappels == []


@pytest.mark.asyncio
async def test_patch_status_seul_inchange_rappels(db):
    cal = await _cal(db)
    debut = datetime(2030, 1, 1, 14, 0)
    evt = Event(calendar_id=cal.id, title="RDV", start_at=debut,
                end_at=debut + timedelta(hours=1), created_by="perso")
    db.add(evt)
    db.add(EventParticipant(event_id=evt.id, user_id="marina", status="pending", rappels=[30]))
    await db.commit()
    out = await P.update_participant_status(
        evt.id, "marina", ParticipantStatusUpdate(status="accepted"), db=db, user=OWNER)
    assert out.status == "accepted" and out.rappels == [30]  # rappels non touchés
```

- [ ] **Step 2: Lancer le test — il échoue**

Run: `cd briques/agenda/backend && python3 -m pytest tests/test_participants_s174.py -v`
Expected: FAIL (`membres` absent, `add_all_members` absent, `ParticipantStatusUpdate` sans `rappels`).

- [ ] **Step 3: Étendre les schémas participants dans `models/schemas.py`**

Remplacer la classe `ParticipantStatusUpdate` par (statut désormais optionnel, + `rappels`) :

```python
class ParticipantStatusUpdate(BaseModel):
    status: Optional[str] = None
    # None = champ non fourni (rappels/status inchangés) ; pour rappels, [] = aucun,
    # [m,…] = override perso. Un PATCH peut ne toucher que l'un des deux.
    rappels: Optional[list[int]] = None

    @field_validator("status")
    @classmethod
    def valid_status(cls, v):
        if v is not None and v not in ("accepted", "declined", "maybe"):
            raise ValueError("status must be accepted, declined or maybe")
        return v

    @field_validator("rappels")
    @classmethod
    def _rappels(cls, v):
        return normaliser_rappels(v)
```

Dans `ParticipantOut`, ajouter le champ `rappels` :

```python
class ParticipantOut(BaseModel):
    id: str
    event_id: str
    user_id: str
    status: str
    rappels: Optional[list[int]] = None
    responded_at: Optional[datetime]

    class Config:
        from_attributes = True
```

- [ ] **Step 4: Créer `services/membres.py` et `services/participants_auto.py`**

`briques/agenda/backend/services/membres.py` :

```python
"""Résolution des membres d'un calendrier (S174) : propriétaire + membres partagés."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.orm import Calendar, CalendarMember


async def membres_du_calendrier(db: AsyncSession, calendar_id: str) -> set[str]:
    """user_ids ayant accès au calendrier : son propriétaire + tous ses membres."""
    users: set[str] = set()
    cal = await db.get(Calendar, calendar_id)
    if cal:
        users.add(cal.user_id)
    rows = (await db.execute(
        select(CalendarMember.user_id).where(CalendarMember.calendar_id == calendar_id)
    )).scalars().all()
    users.update(rows)
    return users
```

`briques/agenda/backend/services/participants_auto.py` :

```python
"""Auto-participant (S174) : garantit qu'un utilisateur est participant d'un event.
Sans commit (l'appelant commite) → composable dans la transaction de création d'event."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.orm import EventParticipant


async def assurer_participant(db: AsyncSession, event_id: str, user_id: str,
                              status: str = "accepted") -> None:
    """Ajoute (si absent) un participant pour cet event. Idempotent, ne commite pas."""
    existe = (await db.execute(
        select(EventParticipant.id).where(
            EventParticipant.event_id == event_id,
            EventParticipant.user_id == user_id,
        )
    )).scalar_one_or_none()
    if existe is None:
        db.add(EventParticipant(event_id=event_id, user_id=user_id, status=status))
```

- [ ] **Step 5: Auto-participant à la création d'event (`events.py` et `service.py`)**

Dans `routers/events.py::create_event`, après `db.add(evt)` et **avant** `await db.commit()`, insérer :

```python
    from services.participants_auto import assurer_participant
    await assurer_participant(db, evt.id, user["sub"])
```

(L'`evt.id` est déjà défini : `Event(...)` génère l'UUID à l'instanciation via `default=_uuid` appliqué au flush ; forcer un `await db.flush()` juste avant si `evt.id` est `None` à ce stade — vérifier dans le test que le participant est bien créé.)

> Détail SQLAlchemy : `default=_uuid` est appliqué au **flush**, pas à l'instanciation. Donc insérer `await db.flush()` après `db.add(evt)` pour matérialiser `evt.id`, puis `assurer_participant`, puis `commit`.

Même chose dans `routers/service.py::service_creer_evenement`, après `db.add(evt)` : `await db.flush()`, puis `from services.participants_auto import assurer_participant` / `await assurer_participant(db, evt.id, user["sub"])`, puis `commit`.

- [ ] **Step 6: Ajouter `POST /events/{id}/participants/all` et `rappels` au PATCH dans `routers/participants.py`**

Remplacer la fonction `update_participant_status` par (gère `status` et/ou `rappels`) :

```python
@router.patch("/events/{event_id}/participants/{participant_user_id}", response_model=ParticipantOut)
async def update_participant_status(
    event_id: str,
    participant_user_id: str,
    body: ParticipantStatusUpdate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    result = await db.execute(
        select(EventParticipant).where(
            EventParticipant.event_id == event_id,
            EventParticipant.user_id == participant_user_id,
        )
    )
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Participant not found")
    fournis = body.model_dump(exclude_unset=True)
    if "status" in fournis and fournis["status"] is not None:
        p.status = fournis["status"]
        p.responded_at = datetime.now(timezone.utc)
    if "rappels" in fournis:  # présent (même []) = réglage explicite ; absent = inchangé
        p.rappels = fournis["rappels"]
    await db.commit()
    await db.refresh(p)
    return p
```

Ajouter, après `add_participant`, la route « inviter tous les membres » :

```python
@router.post("/events/{event_id}/participants/all", response_model=list[ParticipantOut], status_code=status.HTTP_201_CREATED)
async def add_all_members(
    event_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Ajoute d'un tap tous les membres du calendrier de l'event comme participants
    (status=pending, rappels hérités). Idempotent : n'ajoute que les manquants."""
    from services.membres import membres_du_calendrier
    evt = await _get_event(event_id, db)
    membres = await membres_du_calendrier(db, evt.calendar_id)
    existants = set((await db.execute(
        select(EventParticipant.user_id).where(EventParticipant.event_id == event_id)
    )).scalars().all())
    for uid in membres - existants:
        db.add(EventParticipant(event_id=event_id, user_id=uid, status="pending"))
    await db.commit()
    result = await db.execute(
        select(EventParticipant).where(EventParticipant.event_id == event_id)
    )
    return result.scalars().all()
```

- [ ] **Step 7: Lancer le test — il passe**

Run: `cd briques/agenda/backend && python3 -m pytest tests/test_participants_s174.py -v`
Expected: PASS.

- [ ] **Step 8: Vérifier la non-régression des participants existants**

Run: `cd briques/agenda/backend && python3 -m pytest tests/test_service_agenda.py tests/test_participants_s174.py -q`
Expected: PASS (la création via `/service` ajoute désormais le créateur — vérifier qu'aucun test existant n'assied « 0 participant »).

- [ ] **Step 9: Commit**

```bash
git add briques/agenda/backend/routers/participants.py briques/agenda/backend/routers/events.py briques/agenda/backend/routers/service.py briques/agenda/backend/models/schemas.py briques/agenda/backend/services/membres.py briques/agenda/backend/services/participants_auto.py briques/agenda/backend/tests/test_participants_s174.py
git commit -m "feat(s174): recipients hybrides — créateur auto-participant, inviter tous, rappels perso"
```

---

## Task 5 : Journal d'activité (écriture + lecture)

**Files:**
- Create: `briques/agenda/backend/services/journal.py`, `briques/agenda/backend/routers/activity.py`
- Modify: `briques/agenda/backend/routers/events.py`, `briques/agenda/backend/routers/participants.py`, `briques/agenda/backend/routers/comments.py`, `briques/agenda/backend/models/schemas.py`, `briques/agenda/backend/main.py`
- Test: `briques/agenda/backend/tests/test_journal.py`

**Interfaces:**
- Consumes : `services.profils.resoudre` (snapshot du nom), `EventActivityLog` (Task 1).
- Produces :
  - `services/journal.py` : `async consigner(db, event_id, user_id, action, details=None)` (résout le nom, insère, no-commit) ; réutilisé par les routers.
  - `routers/activity.py` : `GET /events/{id}/activity` → `list[ActivityLogOut]` (antéchronologique).
  - `schemas.py` : `ActivityLogOut(id, event_id, user_id, user_nom, action, details, created_at)`.

- [ ] **Step 1: Écrire le test**

Créer `briques/agenda/backend/tests/test_journal.py` :

```python
"""S174 — journal d'activité : écriture (snapshot du nom) + lecture antéchronologique."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from models.orm import Calendar, Event
from routers import activity as A
from services import journal, profils


async def _event(db) -> Event:
    cal = Calendar(user_id="perso", name="Perso", is_default=True)
    db.add(cal)
    await db.flush()
    debut = datetime(2030, 1, 1, 14, 0)
    evt = Event(calendar_id=cal.id, title="RDV", start_at=debut,
                end_at=debut + timedelta(hours=1), created_by="perso")
    db.add(evt)
    await db.commit()
    await db.refresh(evt)
    return evt


@pytest.mark.asyncio
async def test_consigner_capture_le_nom(db):
    evt = await _event(db)
    await profils.upsert(db, "marina", "Marina")
    await journal.consigner(db, evt.id, "marina", "rsvp", {"statut": "accepted"})
    await db.commit()
    out = await A.list_activity(evt.id, db=db, user={"sub": "perso"})
    assert len(out) == 1
    assert out[0].user_nom == "Marina" and out[0].action == "rsvp"
    assert out[0].details == {"statut": "accepted"}


@pytest.mark.asyncio
async def test_consigner_nom_defaut_si_inconnu(db):
    evt = await _event(db)
    await journal.consigner(db, evt.id, "perso", "event_created")
    await db.commit()
    out = await A.list_activity(evt.id, db=db, user={"sub": "perso"})
    assert out[0].user_nom == "Toi"  # défaut propriétaire local


@pytest.mark.asyncio
async def test_list_activity_anterochronologique(db):
    evt = await _event(db)
    await journal.consigner(db, evt.id, "perso", "event_created")
    await journal.consigner(db, evt.id, "perso", "event_updated", {"champ": "start_at"})
    await db.commit()
    out = await A.list_activity(evt.id, db=db, user={"sub": "perso"})
    assert [a.action for a in out] == ["event_updated", "event_created"]  # plus récent d'abord
```

- [ ] **Step 2: Lancer le test — il échoue**

Run: `cd briques/agenda/backend && python3 -m pytest tests/test_journal.py -v`
Expected: FAIL (`services.journal` / `routers.activity` absents).

- [ ] **Step 3: Implémenter `services/journal.py`**

```python
"""Journal d'activité d'un événement (S174) : écrit une entrée en capturant le nom
affichable de l'auteur au moment de l'action (snapshot robuste). Ne commite pas."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from models.orm import EventActivityLog
from services import profils


async def consigner(db: AsyncSession, event_id: str, user_id: str, action: str,
                    details: dict | None = None) -> None:
    """Ajoute une entrée de journal (nom snapshoté). Actions : event_created,
    event_updated, event_deleted, rsvp, comment. L'appelant commite."""
    resolus = await profils.resoudre(db, [user_id])
    nom = resolus[user_id]["display_name"]
    db.add(EventActivityLog(event_id=event_id, user_id=user_id, user_nom=nom,
                            action=action, details=details))
```

- [ ] **Step 4: Ajouter `ActivityLogOut` dans `models/schemas.py`**

```python
# ── Journal d'activité (S174) ─────────────────────────────────────────────────

class ActivityLogOut(BaseModel):
    id: str
    event_id: str
    user_id: str
    user_nom: str
    action: str
    details: Optional[dict] = None
    created_at: datetime

    class Config:
        from_attributes = True
```

- [ ] **Step 5: Implémenter `routers/activity.py`**

```python
"""Journal d'activité — GET /events/{id}/activity (S174). Lecture seule, antéchronologique."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from db import get_db
from models.orm import Event, EventActivityLog
from models.schemas import ActivityLogOut

router = APIRouter(tags=["activity"])


@router.get("/events/{event_id}/activity", response_model=list[ActivityLogOut])
async def list_activity(
    event_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    evt = await db.get(Event, event_id)
    if not evt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    rows = (await db.execute(
        select(EventActivityLog)
        .where(EventActivityLog.event_id == event_id)
        .order_by(EventActivityLog.created_at.desc())
    )).scalars().all()
    return rows
```

- [ ] **Step 6: Câbler l'écriture dans les routers metier**

Inclure `from routers.activity import router as activity_router` + `app.include_router(activity_router)` dans `main.py`.

Dans `routers/events.py`, ajouter `from services.journal import consigner` en tête, puis :
- `create_event` : après `assurer_participant`, avant `commit` → `await consigner(db, evt.id, user["sub"], "event_created", {"titre": evt.title})`.
- `update_event` : après la boucle `setattr`, avant `commit` → `await consigner(db, evt.id, user["sub"], "event_updated", {"champs": list(data.keys())})`.
- `delete_event` : **avant** `await db.delete(evt)`, consigner puis commiter le log séparément n'a pas de sens (CASCADE le supprime). **Ne pas** journaliser la suppression dans `event_activity_log` (l'event disparaît, ses logs avec) ; à la place, laisser `event_deleted` hors journal par-event. *(Décision : le fil est par-event ; un event supprimé n'a plus de fil. Documenté dans le spec, § Hors périmètre.)*

Dans `routers/participants.py::update_participant_status`, après avoir modifié le statut (uniquement si `status` fourni), avant `commit` : `await consigner(db, event_id, user["sub"], "rsvp", {"statut": p.status})` (importer `consigner`).

Dans `routers/comments.py::create_comment`, après `db.add(c)`, avant `commit` : `from services.journal import consigner` / `await consigner(db, event_id, user["sub"], "comment", {"extrait": body.content[:80]})`.

- [ ] **Step 7: Lancer les tests concernés**

Run: `cd briques/agenda/backend && python3 -m pytest tests/test_journal.py tests/test_participants_s174.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add briques/agenda/backend/services/journal.py briques/agenda/backend/routers/activity.py briques/agenda/backend/routers/events.py briques/agenda/backend/routers/participants.py briques/agenda/backend/routers/comments.py briques/agenda/backend/models/schemas.py briques/agenda/backend/main.py briques/agenda/backend/tests/test_journal.py
git commit -m "feat(s174): journal d'activité — écriture (snapshot nom) + fil par event"
```

---

## Task 6 : `/service/events` enrichi (participants + rappels effectifs)

**Files:**
- Create: `briques/agenda/backend/services/rappels.py`
- Modify: `briques/agenda/backend/services/agregation.py`
- Test: `briques/agenda/backend/tests/test_rappels_effectifs.py`, `briques/agenda/backend/tests/test_service_participants.py`

**Interfaces:**
- Consumes : `EventParticipant.rappels`, `Event.rappels`.
- Produces :
  - `services/rappels.py` : `rappels_effectifs(participant_rappels, event_rappels) -> list[int]` (pur).
  - `evenements_agreges` : chaque dict d'event gagne `participants: [{user_id, status, rappels_effectifs}]`.

- [ ] **Step 1: Écrire les tests**

Créer `briques/agenda/backend/tests/test_rappels_effectifs.py` :

```python
"""S174 — résolution des rappels effectifs d'un participant (pur)."""

from services.rappels import rappels_effectifs


def test_none_herite_du_defaut_event():
    assert rappels_effectifs(None, [10, 1440]) == [10, 1440]


def test_liste_vide_signifie_aucun():
    assert rappels_effectifs([], [10]) == []


def test_override_personnel():
    assert rappels_effectifs([60], [10]) == [60]
```

Créer `briques/agenda/backend/tests/test_service_participants.py` :

```python
"""S174 — /service/events porte les participants + leurs rappels effectifs."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from models.orm import Calendar, Event, EventParticipant
from services.agregation import evenements_agreges


@pytest.mark.asyncio
async def test_agregation_expose_participants_et_rappels(db):
    cal = Calendar(user_id="perso", name="Perso", is_default=True)
    db.add(cal)
    await db.flush()
    debut = datetime(2030, 1, 1, 14, 0)
    evt = Event(calendar_id=cal.id, title="Diner", start_at=debut,
                end_at=debut + timedelta(hours=1), created_by="perso", rappels=[10])
    db.add(evt)
    await db.flush()
    db.add(EventParticipant(event_id=evt.id, user_id="perso", status="accepted", rappels=None))
    db.add(EventParticipant(event_id=evt.id, user_id="marina", status="accepted", rappels=[60]))
    await db.commit()

    evts = await evenements_agreges(db, "perso", None, None)
    e = next(x for x in evts if x["id"] == evt.id)
    parts = {p["user_id"]: p for p in e["participants"]}
    assert parts["perso"]["rappels_effectifs"] == [10]   # None → hérite [10]
    assert parts["marina"]["rappels_effectifs"] == [60]  # override
```

- [ ] **Step 2: Lancer — échec**

Run: `cd briques/agenda/backend && python3 -m pytest tests/test_rappels_effectifs.py tests/test_service_participants.py -v`
Expected: FAIL (`services.rappels` absent, pas de clé `participants`).

- [ ] **Step 3: Implémenter `services/rappels.py`**

```python
"""Résolution des rappels effectifs d'un participant (S174). Pur, sans I/O.

NULL (participant.rappels) = hérite du défaut de l'événement ; [] = aucun rappel
explicite ; [m, …] = override personnel. Consommé par l'agrégation /service/events,
lue par le proactif du Cœur pour pousser un rappel par personne."""

from __future__ import annotations


def rappels_effectifs(participant_rappels: list[int] | None,
                      event_rappels: list[int]) -> list[int]:
    """Rappels réellement dus pour ce participant : son override s'il existe, sinon le
    défaut de l'événement."""
    return participant_rappels if participant_rappels is not None else event_rappels
```

- [ ] **Step 4: Enrichir `evenements_agreges` dans `services/agregation.py`**

En tête du fichier, ajouter les imports :

```python
from models.orm import EventParticipant
from services.rappels import rappels_effectifs
```

Dans la boucle `for e in rows:` de `evenements_agreges`, après avoir construit `d` (juste avant `evts.append(d)`), ajouter :

```python
            parts = (await db.execute(
                select(EventParticipant).where(EventParticipant.event_id == e.id)
            )).scalars().all()
            d["participants"] = [
                {"user_id": p.user_id, "status": p.status,
                 "rappels_effectifs": rappels_effectifs(p.rappels, e.rappels)}
                for p in parts
            ]
```

- [ ] **Step 5: Lancer — succès**

Run: `cd briques/agenda/backend && python3 -m pytest tests/test_rappels_effectifs.py tests/test_service_participants.py -v`
Expected: PASS.

- [ ] **Step 6: Non-régression de l'agrégation existante**

Run: `cd briques/agenda/backend && python3 -m pytest tests/test_service_agenda.py -q`
Expected: PASS (le champ `participants` est additif ; les assertions existantes sur les autres champs tiennent).

- [ ] **Step 7: Commit**

```bash
git add briques/agenda/backend/services/rappels.py briques/agenda/backend/services/agregation.py briques/agenda/backend/tests/test_rappels_effectifs.py briques/agenda/backend/tests/test_service_participants.py
git commit -m "feat(s174): /service/events enrichi — participants + rappels effectifs"
```

---

## Task 7 : Cœur — rappels par personne

**Files:**
- Modify: `core/proactif.py`
- Test: `core/test_proactif_par_personne.py`

**Interfaces:**
- Consumes : events de `agenda.lister_evenements` portant désormais `participants: [{user_id, status, rappels_effectifs}]` (Task 6).
- Produces :
  - `_pousser_messagerie(registre, titre, corps, utilisateur=None)` — `utilisateur` défaut `agenda.USER_ID`.
  - `_dedup_pousse(cle) -> bool` — vrai (et enregistre, invisible) si ce push n'a pas encore été fait.
  - `_check_agenda` : boucle par participant, badge 🔔 réservé à `agenda.USER_ID`, push messagerie pour tous, dédup `agenda:{event}:{user}:{minutes}`.

- [ ] **Step 1: Écrire le test**

Créer `core/test_proactif_par_personne.py` :

```python
"""S174 — rappels par personne (côté Cœur) : un push messagerie par participant dû,
badge 🔔 réservé au propriétaire local, dédoublonnage par (event, user, minutes)."""

import asyncio
import os
import sys
import tempfile
from datetime import datetime, timedelta

_TMP = tempfile.mkdtemp()
os.environ["RAPPELS_DB"] = os.path.join(_TMP, "rappels.db")
sys.path.insert(0, os.path.dirname(__file__))

import agenda  # noqa: E402
import proactif  # noqa: E402


def _reset():
    if os.path.exists(proactif.DB):
        os.remove(proactif.DB)
    proactif.init_db()


def _evt_participants(dans_minutes, participants, eid="e1"):
    debut = datetime.now() + timedelta(minutes=dans_minutes)
    return {"id": eid, "title": "Diner", "start_at": debut.isoformat(),
            "end_at": (debut + timedelta(hours=1)).isoformat(),
            "location": None, "rappels": [], "participants": participants}


def _mock_evts(evts):
    async def _faux(registre, debut=None, fin=None):
        return evts
    agenda.lister_evenements = _faux


def _capturer_push():
    pushes = []
    async def _faux(registre, titre, corps, utilisateur=None):
        pushes.append(utilisateur)
    proactif._pousser_messagerie = _faux
    return pushes


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_push_par_participant():
    _reset()
    pushes = _capturer_push()
    _mock_evts([_evt_participants(9, [
        {"user_id": "perso", "status": "accepted", "rappels_effectifs": [10]},
        {"user_id": "marina", "status": "accepted", "rappels_effectifs": [10]},
    ])])
    _run(proactif._check_agenda(None))
    assert sorted(pushes) == ["marina", "perso"]  # les deux notifiés


def test_badge_reserve_au_proprietaire():
    _reset()
    _capturer_push()
    _mock_evts([_evt_participants(9, [
        {"user_id": "perso", "status": "accepted", "rappels_effectifs": [10]},
        {"user_id": "marina", "status": "accepted", "rappels_effectifs": [10]},
    ])])
    _run(proactif._check_agenda(None))
    badges = [r for r in proactif.lister(limite=10) if r.get("type") == "agenda"]
    assert len(badges) == 1  # seul « perso » a une pastille visible


def test_dedoublonnage_par_personne():
    _reset()
    _capturer_push()
    evt = [_evt_participants(9, [
        {"user_id": "marina", "status": "accepted", "rappels_effectifs": [10]},
    ])]
    _mock_evts(evt)
    _run(proactif._check_agenda(None))
    pushes2 = _capturer_push()
    _run(proactif._check_agenda(None))
    assert pushes2 == []  # 2ᵉ passage : pas de re-push pour marina


def test_rappels_effectifs_respectes():
    _reset()
    pushes = _capturer_push()
    _mock_evts([_evt_participants(9, [
        {"user_id": "perso", "status": "accepted", "rappels_effectifs": []},      # aucun
        {"user_id": "marina", "status": "accepted", "rappels_effectifs": [10]},   # dû
    ])])
    _run(proactif._check_agenda(None))
    assert pushes == ["marina"]  # perso n'a aucun rappel


def test_repli_event_sans_participants():
    # Rétro-compat : un event legacy sans clé `participants` retombe sur perso + event.rappels.
    _reset()
    pushes = _capturer_push()
    debut = datetime.now() + timedelta(minutes=9)
    _mock_evts([{"id": "old", "title": "Legacy", "start_at": debut.isoformat(),
                 "end_at": (debut + timedelta(hours=1)).isoformat(),
                 "location": None, "rappels": [10]}])
    _run(proactif._check_agenda(None))
    assert pushes == ["perso"]
    badges = [r for r in proactif.lister(limite=10) if r.get("type") == "agenda"]
    assert len(badges) == 1


if __name__ == "__main__":
    for nom, fn in list(globals().items()):
        if nom.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {nom}")
    print("\n✅ TOUS LES TESTS PASSENT")
```

- [ ] **Step 2: Lancer — échec**

Run: `python3 -m pytest core/test_proactif_par_personne.py -v`
Expected: FAIL (`_check_agenda` ne boucle pas par participant ; `_pousser_messagerie` n'accepte pas `utilisateur`).

- [ ] **Step 3: Modifier `_pousser_messagerie` (paramètre `utilisateur`)**

Dans `core/proactif.py`, remplacer la signature et le corps de `_pousser_messagerie` :

```python
async def _pousser_messagerie(registre, titre: str, corps: str, utilisateur: str | None = None) -> None:
    """Pousse un rappel vers les messageries d'un utilisateur (Telegram…) via le pont.

    `utilisateur` défaut = `agenda.USER_ID` (propriétaire local, rétro-compat). Le pont
    (`/pousser`) résout LUI-MÊME tous les canaux liés de cette personne. Best-effort :
    brique absente / injoignable → ignoré. Ne lève jamais."""
    try:
        base = orchestrateur._brique_base(registre, "connexion")
    except Exception:  # noqa: BLE001
        return
    entetes = {}
    cle = os.getenv("CONNEXION_KEY", "")
    if cle:
        entetes["X-API-Key"] = cle
    corps_push = {"utilisateur": utilisateur or agenda.USER_ID, "texte": f"🔔 {titre}\n{corps}"}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(f"{base}/pousser", json=corps_push, headers=entetes)
    except Exception as ex:  # noqa: BLE001
        logger.warning("Proactif push messagerie : %s", ex)
```

- [ ] **Step 4: Ajouter `_dedup_pousse` (dédup invisible pour les non-propriétaires)**

Dans `core/proactif.py`, après `_ajouter` (vers la ligne 66), ajouter :

```python
def _dedup_pousse(cle: str) -> bool:
    """Vrai (et enregistre) si ce push n'a pas encore été effectué pour cette clé.

    Trace un rappel « déjà vu » (invisible dans le panneau du propriétaire) : sert
    uniquement à ne pas re-pousser un rappel à un participant non-propriétaire (Marina)
    à chaque passage de la boucle. Le propriétaire, lui, passe par `_ajouter` (badge visible)."""
    with _conn() as c:
        if c.execute("SELECT 1 FROM rappels WHERE cle = ? LIMIT 1", (cle,)).fetchone():
            return False
        c.execute(
            "INSERT INTO rappels (id, type, titre, corps, cle, cree, vu) VALUES (?,?,?,?,?,?,1)",
            (str(uuid.uuid4()), "agenda-push", "", "", cle, datetime.utcnow().isoformat()),
        )
    return True
```

- [ ] **Step 5: Réécrire `_check_agenda` (boucle par participant)**

Remplacer le corps de `_check_agenda` par :

```python
async def _check_agenda(registre) -> int:
    """Lève un rappel PAR PARTICIPANT dû. Chaque personne reçoit un push messagerie sur
    SES canaux (le pont route par utilisateur) ; seul le propriétaire local (`agenda.USER_ID`)
    a en plus une pastille 🔔. Dédoublonnage par (événement, personne, minutes)."""
    n = 0
    try:
        maintenant = datetime.now()
        fin = maintenant + timedelta(days=FENETRE_AGENDA_JOURS)
        evts = await agenda.lister_evenements(
            registre, maintenant.isoformat(), fin.isoformat())
        for e in evts:
            titre_evt = e.get("title", "(sans titre)")
            heure = (e.get("start_at") or "")[11:16]
            lieu = f" — {e.get('location')}" if e.get("location") else ""
            # Repli rétro-compat : event sans participants → propriétaire + event.rappels.
            participants = e.get("participants") or [
                {"user_id": agenda.USER_ID, "rappels_effectifs": e.get("rappels") or []}
            ]
            for p in participants:
                uid = p.get("user_id") or agenda.USER_ID
                evt_perso = dict(e)
                evt_perso["rappels"] = p.get("rappels_effectifs") or []
                for m, _debut in _rappels_dus(evt_perso, maintenant):
                    titre = f"Rappel : {titre_evt}"
                    corps = f"{_delai_lisible(m).capitalize()} (à {heure}){lieu}"
                    cle = f"agenda:{e.get('id')}:{uid}:{m}"
                    if uid == agenda.USER_ID:
                        if _ajouter("agenda", titre, corps, cle):
                            n += 1
                            await _pousser_messagerie(registre, titre, corps, utilisateur=uid)
                    else:
                        if _dedup_pousse(cle):
                            n += 1
                            await _pousser_messagerie(registre, titre, corps, utilisateur=uid)
    except Exception as ex:  # noqa: BLE001
        logger.warning("Proactif agenda : %s", ex)
    return n
```

- [ ] **Step 6: Lancer le nouveau test — succès**

Run: `python3 -m pytest core/test_proactif_par_personne.py -v`
Expected: PASS.

- [ ] **Step 7: Non-régression de l'ancien test proactif**

Run: `python3 -m pytest core/test_proactif_rappels.py -v`
Expected: PASS (les events sans `participants` retombent sur `perso` + `event.rappels` → comportement identique).

- [ ] **Step 8: Commit**

```bash
git add core/proactif.py core/test_proactif_par_personne.py
git commit -m "feat(s174): Cœur pousse un rappel par participant, badge 🔔 réservé au propriétaire"
```

---

## Task 8 : Dashboard — présence, rappels perso, chat, fil d'activité

**Files:**
- Modify: `briques/agenda/backend/templates_app.py`

**Interfaces:**
- Consumes : `GET /events/{id}/participants`, `POST /events/{id}/participants/all`, `PATCH …/participants/{uid}` (status + rappels), `GET/POST /events/{id}/comments`, `GET /events/{id}/activity`, `GET /profiles?user_ids=…`, `POST /profiles/me`.
- Produces : UI dans la modale d'événement (pas de test automatisé — vérification LIVE différée fin S180 ; le critère de cette tâche est que la page se charge sans erreur JS et que la suite agenda reste verte).

> **Note :** cette tâche est purement front (HTML/JS injecté). Suivre le style existant de `templates_app.py` (fonctions `api(...)`, `esc(...)`, `fermerModaleEvent`, modale insérée via `insertAdjacentHTML`). Pas de framework.

- [ ] **Step 1: Semer le profil au login**

Dans `templates_app.py`, fonction `chargerApp()` (ligne ~150), après `await chargerCalendriers();` remplacer par un préambule qui poste le profil :

```javascript
async function chargerApp() {
  document.getElementById("entete-droite").innerHTML =
    '<button class="ghost" id="btn-logout">Se déconnecter</button>';
  document.getElementById("btn-logout").onclick = deconnecter;
  try { await api("/profiles/me", { method: "POST" }); } catch (e) { /* best-effort */ }
  await chargerCalendriers();
}
```

- [ ] **Step 2: Ajouter un cache de profils + helper de résolution**

Après les déclarations `let CALENDARS = [];` (ligne ~157), ajouter :

```javascript
let PROFILS = {};
async function resoudreProfils(userIds) {
  const manquants = userIds.filter((u) => !PROFILS[u]);
  if (manquants.length) {
    try {
      const arr = await api("/profiles?user_ids=" + encodeURIComponent(manquants.join(",")));
      for (const p of arr) PROFILS[p.user_id] = p;
    } catch (e) { /* défaut ci-dessous */ }
  }
  const out = {};
  for (const u of userIds) out[u] = PROFILS[u] || { user_id: u, display_name: u, avatar_color: "#64748b" };
  return out;
}
function pastille(color) {
  return `<span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:${color};margin-right:6px;vertical-align:middle"></span>`;
}
```

- [ ] **Step 3: Charger et rendre les blocs dans la modale d'événement existante**

Dans `ouvrirModaleEvent(id, dateYMD)` : pour un event existant (`ev` non nul), après l'insertion de la modale (`document.body.insertAdjacentHTML("beforeend", html);` puis le câblage des boutons), ajouter un conteneur et un chargement asynchrone. Insérer, juste avant la ligne `document.getElementById("btn-annuler").onclick = fermerModaleEvent;`, l'injection d'une zone détails **si `ev` existe** :

```javascript
  if (ev) {
    document.querySelector("#modale .card").insertAdjacentHTML("beforeend",
      '<hr style="border-color:#2d3148;margin:14px 0">' +
      '<div id="zone-presence"></div>' +
      '<div id="zone-rappels" style="margin-top:12px"></div>' +
      '<div id="zone-chat" style="margin-top:12px"></div>' +
      '<div id="zone-activite" style="margin-top:12px"></div>');
    chargerDetailsEvent(ev.id);
  }
```

- [ ] **Step 4: Implémenter `chargerDetailsEvent` (présence + rappels + chat + activité)**

Ajouter, après la fonction `ouvrirModaleEvent`, la fonction (utilise l'id de l'utilisateur courant, extrait du token JWT) :

```javascript
function moiSub() {
  try { return JSON.parse(atob(ACCESS_TOKEN.split(".")[1])).sub; } catch (e) { return null; }
}

const STATUT_LABEL = { accepted: "✓ vient", declined: "✗ absent", maybe: "? peut-être", pending: "⏳ en attente" };

async function chargerDetailsEvent(eventId) {
  let parts = [], comments = [], activite = [];
  try {
    parts = await api(`/events/${encodeURIComponent(eventId)}/participants`);
    comments = await api(`/events/${encodeURIComponent(eventId)}/comments`);
    activite = await api(`/events/${encodeURIComponent(eventId)}/activity`);
  } catch (e) { /* best-effort */ }
  const ids = Array.from(new Set(parts.map((p) => p.user_id)
    .concat(comments.map((c) => c.user_id)).concat(activite.map((a) => a.user_id))));
  const profils = await resoudreProfils(ids);
  const moi = moiSub();

  // Présence
  const lignesP = parts.map((p) => {
    const pr = profils[p.user_id];
    return `<div style="display:flex;align-items:center;gap:6px;margin:2px 0">${pastille(pr.avatar_color)}<span>${esc(pr.display_name)}</span><span class="muted" style="margin-left:auto">${STATUT_LABEL[p.status] || p.status}</span></div>`;
  }).join("");
  document.getElementById("zone-presence").innerHTML =
    '<strong>Présence</strong>' + (lignesP || '<p class="muted">Personne pour l\'instant.</p>') +
    '<div style="display:flex;gap:6px;margin-top:6px">' +
    '<button class="ghost" id="btn-inviter-tous">Inviter tous les membres</button>' +
    '<button class="ghost" data-rsvp="accepted">Je viens</button>' +
    '<button class="ghost" data-rsvp="maybe">Peut-être</button>' +
    '<button class="ghost" data-rsvp="declined">Absent</button></div>';
  document.getElementById("btn-inviter-tous").onclick = async () => {
    try { await api(`/events/${encodeURIComponent(eventId)}/participants/all`, { method: "POST" }); chargerDetailsEvent(eventId); } catch (e) { alert("Échec : " + e.message); }
  };
  document.querySelectorAll("#zone-presence [data-rsvp]").forEach((b) => b.onclick = async () => {
    try {
      await api(`/events/${encodeURIComponent(eventId)}/participants/${encodeURIComponent(moi)}`,
        { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status: b.dataset.rsvp }) });
      chargerDetailsEvent(eventId);
    } catch (e) { alert("Échec (es-tu participant ?) : " + e.message); }
  };

  // Mon rappel personnel
  const moiPart = parts.find((p) => p.user_id === moi);
  const rappelActuel = moiPart && moiPart.rappels ? moiPart.rappels.join(",") : (moiPart && moiPart.rappels === null ? "" : "");
  document.getElementById("zone-rappels").innerHTML = moiPart
    ? '<strong>Mon rappel</strong>' +
      '<div style="display:flex;gap:6px;margin-top:4px"><input id="mon-rappel" placeholder="minutes avant, ex. 10,60 (vide = hérite)" style="flex:1" value="' + esc(rappelActuel) + '">' +
      '<button id="btn-mon-rappel">OK</button></div>' +
      '<p class="muted" style="font-size:11px">Vide = comme l\'événement · « 0 » = à l\'heure · plusieurs séparés par des virgules.</p>'
    : '<p class="muted">Rejoins l\'événement pour régler ton rappel.</p>';
  const btnR = document.getElementById("btn-mon-rappel");
  if (btnR) btnR.onclick = async () => {
    const v = document.getElementById("mon-rappel").value.trim();
    const rappels = v === "" ? null : v.split(",").map((x) => parseInt(x.trim(), 10)).filter((x) => !isNaN(x));
    try {
      await api(`/events/${encodeURIComponent(eventId)}/participants/${encodeURIComponent(moi)}`,
        { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ rappels }) });
      chargerDetailsEvent(eventId);
    } catch (e) { alert("Échec : " + e.message); }
  };

  // Chat
  const lignesC = comments.map((c) => {
    const pr = profils[c.user_id];
    return `<div style="margin:4px 0">${pastille(pr.avatar_color)}<strong style="font-size:12px">${esc(pr.display_name)}</strong> <span>${esc(c.content)}</span></div>`;
  }).join("");
  document.getElementById("zone-chat").innerHTML =
    '<strong>Discussion</strong><div style="max-height:140px;overflow:auto;margin:4px 0">' +
    (lignesC || '<p class="muted">Aucun message.</p>') + '</div>' +
    '<div style="display:flex;gap:6px"><input id="chat-input" placeholder="Un mot…" style="flex:1"><button id="btn-chat">Envoyer</button></div>';
  document.getElementById("btn-chat").onclick = async () => {
    const content = document.getElementById("chat-input").value.trim();
    if (!content) return;
    try {
      await api(`/events/${encodeURIComponent(eventId)}/comments`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ content }) });
      chargerDetailsEvent(eventId);
    } catch (e) { alert("Échec : " + e.message); }
  };

  // Fil d'activité
  const ACT_LABEL = { event_created: "a créé l'événement", event_updated: "a modifié l'événement", rsvp: "a répondu", comment: "a écrit un message" };
  const lignesA = activite.map((a) => {
    const nom = (profils[a.user_id] || {}).display_name || a.user_nom;
    return `<div class="muted" style="font-size:11px">• ${esc(nom)} ${esc(ACT_LABEL[a.action] || a.action)}</div>`;
  }).join("");
  document.getElementById("zone-activite").innerHTML =
    '<strong>Activité</strong>' + (lignesA || '<p class="muted">—</p>');
}
```

- [ ] **Step 5: Vérifier le rendu (statique) + non-régression de la brique**

Run: `cd briques/agenda/backend && python3 -c "import templates_app; html = templates_app.page_app('http://kc', 'forge', 'calendar-app'); assert 'zone-presence' in html and 'chargerDetailsEvent' in html and 'profiles/me' in html; print('OK page_app rend les blocs S174')"`
Expected: `OK page_app rend les blocs S174`.

Run: `cd briques/agenda/backend && python3 -m pytest tests/test_app_web.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add briques/agenda/backend/templates_app.py
git commit -m "feat(s174): dashboard agenda — présence, rappel perso, chat, fil d'activité"
```

---

## Task 9 : Suites complètes + documentation de sprint

**Files:**
- Modify: `briques/agenda/backend/README.md` (section S174), `docs/sprints/S174-S180-roadmap-agenda-best-in-class.md` (cocher S174)

- [ ] **Step 1: Suite agenda complète**

Run: `cd briques/agenda/backend && python3 -m pytest -q`
Expected: PASS (tous, y compris les ~109 existants + les nouveaux S174).

- [ ] **Step 2: Suite Cœur complète**

Run: `make test-core`
Expected: PASS (les ~432 existants + `test_proactif_par_personne`).

- [ ] **Step 3: Documenter le comportement dans le README de la brique**

Dans `briques/agenda/backend/README.md`, ajouter une section « ## S174 — Rappels par personne » décrivant : `EventParticipant.rappels` (NULL=hérite, []=aucun, liste=override) ; auto-participant à la création + `POST /events/{id}/participants/all` ; `UserProfile` semée au login (`POST /profiles/me`) ; `event_activity_log` + `GET /events/{id}/activity` ; le fait que le Cœur pousse par participant et que la pastille 🔔 est réservée au propriétaire local. Mentionner que les rappels ne sont réellement poussés à une personne que si elle a un canal lié côté brique connexion (repli honnête sinon).

- [ ] **Step 4: Cocher S174 dans le roadmap**

Dans `docs/sprints/S174-S180-roadmap-agenda-best-in-class.md`, préfixer le titre `## S174 — …` d'un marqueur d'état (ex. `✅ CODE-COMPLET 2026-07-15 (LIVE différé)`), cohérent avec le style des autres docs de sprint.

- [ ] **Step 5: Commit final**

```bash
git add briques/agenda/backend/README.md docs/sprints/S174-S180-roadmap-agenda-best-in-class.md
git commit -m "docs(s174): README brique + roadmap — rappels par personne code-complet"
```

---

## Self-Review (rempli à l'écriture du plan)

**Spec coverage :**
- Migration 0006 (colonne + 2 tables) → Task 1. ✅
- Backfill créateur → Task 2. ✅
- UserProfile + seed login + résolution → Task 3. ✅
- Recipients hybrides (auto-participant, inviter tous, rappels perso PATCH) → Task 4. ✅
- Journal d'activité (écriture + fil par event) → Task 5. ✅
- `/service/events` enrichi (participants + rappels_effectifs) → Task 6. ✅
- Cœur par participant (`_pousser_messagerie(utilisateur=)`, `_check_agenda`, dédup, badge perso, repli) → Task 7. ✅
- Dashboard (présence, rappels perso, chat, activité, `POST /profiles/me`) → Task 8. ✅
- Suites vertes + doc → Task 9. ✅
- Hors périmètre respecté : pas de récurrence, pas de push web, chat = ajout seul (pas d'édition/suppression exposée dans l'UI S174), `event_deleted` non journalisé (le fil est par-event). ✅

**Placeholder scan :** aucun TBD/TODO ; chaque step de code montre le code. Deux points laissés à vérification d'implémentation (nom de la fabrique de sessions dans `db.py` en Task 2 Step 5 ; matérialisation d'`evt.id` via `flush` en Task 4 Step 5) sont explicités avec la commande de vérification — pas des placeholders.

**Type consistency :** `rappels` list[int]|None partout (orm, schema, service `rappels_effectifs`, proactif) ; `nom_affiche`/`couleur_pour`/`upsert`/`resoudre` signatures identiques entre `services/profils.py` et leurs appels (routers, journal) ; `consigner(db, event_id, user_id, action, details=None)` identique entre définition (Task 5) et appels (events/participants/comments) ; `_pousser_messagerie(..., utilisateur=None)` cohérent entre définition et appels du `_check_agenda` et le test qui mocke la même signature. ✅

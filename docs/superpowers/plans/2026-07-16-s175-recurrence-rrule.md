# S175 — Récurrence RRULE réellement expansée — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rendre le champ `Event.recurrence_rule` vivant : une règle RRULE se déplie en occurrences visibles (dashboard, agrégation `/service`, briefing proactif) avec les gestes d'édition série / sauter une occurrence / déplacer une occurrence.

**Architecture:** Occurrences **virtuelles au read-time** (aucune matérialisation). Un module pur `services/recurrence.py` valide et expanse (via `dateutil.rrule`) ; un module d'orchestration `services/occurrences.py` fait le read (charger maîtres + overrides + exdates → occurrences → dict) et le write (créer un override, exclure une occurrence). Les trois points de lecture (agrégation, `list_events`, proactif du Cœur) passent par lui. L'édition prend un `?scope=all|this&occurrence=<ISO>`.

**Tech Stack:** Python 3 / FastAPI / SQLAlchemy 2.0 async / Alembic ; `python-dateutil` (rrule) et `icalendar` déjà dans `requirements.txt` (rien à ajouter) ; tests `pytest` + `pytest-asyncio`, SQLite en mémoire (`Base.metadata.create_all`, pas d'Alembic en test).

## Global Constraints

- **Stockage = datetime NAÏF en UTC** partout (`services/horaires.vers_utc_naif` en entrée, `vers_paris` en sortie). L'expansion, les EXDATE et `recurrence_date` sont tous en **naïf UTC**. Ne jamais comparer naïf vs aware.
- **Aucune nouvelle dépendance** : `dateutil` et `icalendar` sont déjà là.
- **Français** : noms de fonctions, commentaires, messages d'erreur en français (convention de la brique).
- **Migration** = numéro suivant = **0007** (dernière = `0006_rappels_par_personne.py`). Portable SQLite + Postgres.
- **Non-régression** : suites cibles **agenda 152/152** + nouveaux tests, **cœur 438/438** + nouveau test proactif. Commandes : `cd briques/agenda/backend && python3 -m pytest` ; `make test-core`.
- **Commits** finissent par les deux lignes de co-auteur du dépôt (voir dernier commit `git log -1`).

---

### Task 1: `services/recurrence.valider_rrule` (validation pure)

**Files:**
- Create: `briques/agenda/backend/services/recurrence.py`
- Test: `briques/agenda/backend/tests/test_recurrence.py`

**Interfaces:**
- Consumes: rien (module feuille, importe seulement `dateutil.rrule` + `datetime`).
- Produces: `valider_rrule(rule: str) -> str` (renvoie la règle normalisée sans préfixe `RRULE:`, lève `ValueError` sinon) ; constante `MAX_OCCURRENCES = 366`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_recurrence.py
from __future__ import annotations

import pytest

from services.recurrence import valider_rrule


def test_valide_weekly_byday():
    assert valider_rrule("FREQ=WEEKLY;BYDAY=MO") == "FREQ=WEEKLY;BYDAY=MO"


def test_strip_prefixe_rrule():
    assert valider_rrule("RRULE:FREQ=DAILY") == "FREQ=DAILY"


def test_rejette_freq_absent():
    with pytest.raises(ValueError):
        valider_rrule("INTERVAL=2")


def test_rejette_freq_trop_fine():
    with pytest.raises(ValueError):
        valider_rrule("FREQ=MINUTELY")


def test_rejette_garbage():
    with pytest.raises(ValueError):
        valider_rrule("pas une rrule du tout ###")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/agenda/backend && python3 -m pytest tests/test_recurrence.py -q`
Expected: FAIL (`ModuleNotFoundError: services.recurrence` ou `ImportError`).

- [ ] **Step 3: Write minimal implementation**

```python
# services/recurrence.py
"""Récurrence RRULE (S175) — module PUR : validation + expansion en occurrences.

Aucune dépendance projet (pas de schémas ni d'ORM concret hors typing) pour rester
testable isolément et éviter tout cycle d'import. Toutes les dates manipulées sont en
NAÏF UTC (convention de stockage de la brique)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from dateutil.rrule import rrulestr

MAX_OCCURRENCES = 366  # cap de sécurité : jamais expanser une série sans borne au-delà.

_FREQ_INTERDITES = ("SECONDLY", "MINUTELY", "HOURLY")  # bruit pour un agenda humain


def valider_rrule(rule: str) -> str:
    """Valide/normalise une RRULE. Renvoie la règle sans préfixe `RRULE:`.
    Lève ValueError si illisible, sans FREQ, ou d'une fréquence trop fine."""
    if not rule or not rule.strip():
        raise ValueError("règle de récurrence vide")
    nettoyee = rule.strip()
    if nettoyee.upper().startswith("RRULE:"):
        nettoyee = nettoyee[len("RRULE:"):]
    haut = nettoyee.upper()
    if "FREQ=" not in haut:
        raise ValueError("RRULE sans FREQ")
    if any(f"FREQ={f}" in haut for f in _FREQ_INTERDITES):
        raise ValueError("fréquence trop fine (max : quotidienne)")
    try:
        # dtstart bidon juste pour valider la grammaire ; on ne garde pas l'objet.
        rrulestr(nettoyee, dtstart=datetime(2000, 1, 1))
    except (ValueError, TypeError) as ex:
        raise ValueError(f"RRULE invalide : {ex}") from ex
    return nettoyee
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd briques/agenda/backend && python3 -m pytest tests/test_recurrence.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add briques/agenda/backend/services/recurrence.py briques/agenda/backend/tests/test_recurrence.py
git commit -m "feat(s175): recurrence.valider_rrule — validation/normalisation RRULE

<lignes co-auteur>"
```

---

### Task 2: `services/recurrence.expanser` (expansion pure)

**Files:**
- Modify: `briques/agenda/backend/services/recurrence.py`
- Test: `briques/agenda/backend/tests/test_recurrence.py`

**Interfaces:**
- Consumes: `MAX_OCCURRENCES`, `dateutil.rrule.rrulestr`.
- Produces:
  - `@dataclass Occurrence` : `source` (l'objet event à rendre — maître pour un virtuel, override pour un override), `start: datetime`, `end: datetime` (effectifs, naïf UTC), `occurrence_start: datetime` (RECURRENCE-ID, naïf UTC), `recurrent: bool`.
  - `expanser(maitre, debut, fin, exdates, overrides) -> list[Occurrence]` où `maitre` a les attributs `.start_at/.end_at/.recurrence_rule` ; `exdates: set[datetime]` (naïf UTC) ; `overrides: dict[datetime, <event>]` clé = date d'occurrence remplacée. `debut`/`fin` peuvent être `None`.

Le duck-typing sur `.start_at` etc. permet de tester avec un objet factice sans ORM.

- [ ] **Step 1: Write the failing test**

```python
# ajouts à tests/test_recurrence.py
from datetime import datetime, timedelta
from types import SimpleNamespace
from services.recurrence import expanser, Occurrence


def _maitre(rule, jour=1, h=9):
    d = datetime(2026, 6, jour, h, 0)
    return SimpleNamespace(start_at=d, end_at=d + timedelta(hours=1),
                           recurrence_rule=rule)


def test_non_recurrent_se_renvoie():
    m = _maitre(None)
    occ = expanser(m, None, None, set(), {})
    assert len(occ) == 1
    assert occ[0].source is m and occ[0].recurrent is False
    assert occ[0].occurrence_start == m.start_at


def test_weekly_dans_fenetre():
    m = _maitre("FREQ=WEEKLY", jour=1)  # lundi 1er juin 2026
    occ = expanser(m, datetime(2026, 6, 1), datetime(2026, 6, 30), set(), {})
    debuts = [o.start_at for o in occ]
    assert debuts == [datetime(2026, 6, d, 9, 0) for d in (1, 8, 15, 22, 29)]
    assert all(o.end_at - o.start_at == timedelta(hours=1) for o in occ)  # durée conservée
    assert all(o.recurrent for o in occ)


def test_exdate_saute_une_occurrence():
    m = _maitre("FREQ=WEEKLY", jour=1)
    occ = expanser(m, datetime(2026, 6, 1), datetime(2026, 6, 30),
                   {datetime(2026, 6, 8, 9, 0)}, {})
    assert datetime(2026, 6, 8, 9, 0) not in [o.start_at for o in occ]
    assert len(occ) == 4


def test_override_remplace_l_occurrence():
    m = _maitre("FREQ=WEEKLY", jour=1)
    ov = SimpleNamespace(start_at=datetime(2026, 6, 8, 14, 0),   # déplacé à 14h
                         end_at=datetime(2026, 6, 8, 15, 0), recurrence_rule=None)
    occ = expanser(m, datetime(2026, 6, 1), datetime(2026, 6, 30),
                   set(), {datetime(2026, 6, 8, 9, 0): ov})
    par_date = {o.occurrence_start: o for o in occ}
    remplacee = par_date[datetime(2026, 6, 8, 9, 0)]
    assert remplacee.source is ov and remplacee.start.hour == 14


def test_count_et_cap():
    m = _maitre("FREQ=DAILY", jour=1)
    occ = expanser(m, None, None, set(), {})   # série sans fin → cap
    assert len(occ) == 366
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/agenda/backend && python3 -m pytest tests/test_recurrence.py -q`
Expected: FAIL (`ImportError: cannot import name 'expanser'`).

- [ ] **Step 3: Write minimal implementation**

```python
# ajouts à services/recurrence.py
@dataclass
class Occurrence:
    """Une occurrence concrète d'un event. `source` = l'objet à rendre (le maître pour
    une occurrence virtuelle, l'event-override pour une occurrence modifiée). `start/end`
    = horaires effectifs. `occurrence_start` = RECURRENCE-ID : identité stable de
    l'occurrence (clé de dédup proactif, ancre du front)."""
    source: object
    start: datetime
    end: datetime
    occurrence_start: datetime
    recurrent: bool


def expanser(maitre, debut, fin, exdates, overrides) -> list[Occurrence]:
    """Déplie `maitre` sur [debut, fin]. Non récurrent → se renvoie tel quel. Récurrent →
    une Occurrence par date produite, en sautant `exdates` et en substituant `overrides`.
    Toutes les dates en naïf UTC. `debut`/`fin` None = pas de borne (le cap protège)."""
    if not maitre.recurrence_rule:
        if debut and maitre.end_at < debut:
            return []
        if fin and maitre.start_at > fin:
            return []
        return [Occurrence(maitre, maitre.start_at, maitre.end_at,
                           maitre.start_at, False)]

    duree = maitre.end_at - maitre.start_at
    regle = rrulestr(maitre.recurrence_rule, dtstart=maitre.start_at)
    # rrule.between est inclusif ; sans fenêtre on prend les MAX premières.
    if debut and fin:
        dates = regle.between(debut - duree, fin, inc=True)
    else:
        dates = []
        for i, d in enumerate(regle):
            if i >= MAX_OCCURRENCES:
                break
            dates.append(d)
    occ: list[Occurrence] = []
    for d in dates[:MAX_OCCURRENCES]:
        if d in exdates:
            continue
        ov = overrides.get(d)
        if ov is not None:
            occ.append(Occurrence(ov, ov.start_at, ov.end_at, d, True))
        else:
            occ.append(Occurrence(maitre, d, d + duree, d, True))
    return occ
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd briques/agenda/backend && python3 -m pytest tests/test_recurrence.py -q`
Expected: PASS (10 tests).

- [ ] **Step 5: Commit**

```bash
git add briques/agenda/backend/services/recurrence.py briques/agenda/backend/tests/test_recurrence.py
git commit -m "feat(s175): recurrence.expanser — occurrences virtuelles + exdate + override

<lignes co-auteur>"
```

---

### Task 3: Colonnes ORM + migration 0007 + schémas

**Files:**
- Modify: `briques/agenda/backend/models/orm.py:102-138` (classe `Event`)
- Create: `briques/agenda/backend/alembic/versions/0007_recurrence.py`
- Modify: `briques/agenda/backend/models/schemas.py` (`EventCreate`, `EventUpdate`, `EventOut`)
- Test: `briques/agenda/backend/tests/test_recurrence_orm.py`

**Interfaces:**
- Consumes: `services.recurrence.valider_rrule` (Task 1).
- Produces: `Event.exdates: list` (JSON, def `[]`), `Event.recurrence_parent_id: str|None` (FK `events.id` CASCADE), `Event.recurrence_date: datetime|None` ; `EventOut.occurrence_start: datetime|None`, `EventOut.recurrent: bool`, `EventOut.exdates: list[datetime]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_recurrence_orm.py
from __future__ import annotations

from datetime import datetime

import pytest

from models.orm import Calendar, Event
from models.schemas import EventCreate, EventUpdate


@pytest.mark.asyncio
async def test_colonnes_recurrence_persistees(db):
    c = Calendar(user_id="perso", name="Perso")
    db.add(c)
    await db.flush()
    maitre = Event(calendar_id=c.id, title="Hebdo", created_by="perso", rappels=[],
                   start_at=datetime(2026, 6, 1, 9, 0), end_at=datetime(2026, 6, 1, 10, 0),
                   recurrence_rule="FREQ=WEEKLY", exdates=[])
    db.add(maitre)
    await db.flush()
    ov = Event(calendar_id=c.id, title="Hebdo (déplacé)", created_by="perso", rappels=[],
               start_at=datetime(2026, 6, 8, 14, 0), end_at=datetime(2026, 6, 8, 15, 0),
               recurrence_parent_id=maitre.id, recurrence_date=datetime(2026, 6, 8, 9, 0))
    db.add(ov)
    await db.flush()
    assert ov.recurrence_parent_id == maitre.id
    assert maitre.exdates == []


def test_eventcreate_valide_rrule():
    ec = EventCreate(calendar_id="c1", title="x",
                     start_at=datetime(2026, 6, 1, 9, 0),
                     end_at=datetime(2026, 6, 1, 10, 0),
                     recurrence_rule="RRULE:FREQ=WEEKLY;BYDAY=MO")
    assert ec.recurrence_rule == "FREQ=WEEKLY;BYDAY=MO"  # préfixe strippé


def test_eventcreate_rejette_rrule_invalide():
    with pytest.raises(ValueError):
        EventCreate(calendar_id="c1", title="x",
                    start_at=datetime(2026, 6, 1, 9, 0),
                    end_at=datetime(2026, 6, 1, 10, 0),
                    recurrence_rule="FREQ=MINUTELY")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/agenda/backend && python3 -m pytest tests/test_recurrence_orm.py -q`
Expected: FAIL (`TypeError: 'exdates' is an invalid keyword argument` ou validation absente).

- [ ] **Step 3a: ORM — ajouter les colonnes**

Dans `models/orm.py`, classe `Event`, juste après la ligne `recurrence_rule` (l.118) :

```python
    # Récurrence (S175). exdates = occurrences exclues de la série (naïf UTC, JSON).
    # recurrence_parent_id non-NULL ⇒ cet event est un OVERRIDE d'une occurrence du
    # maître ; recurrence_date = la date d'occurrence d'origine qu'il remplace.
    exdates: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    recurrence_parent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("events.id", ondelete="CASCADE"), nullable=True, index=True)
    recurrence_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
```

Ajouter la contrainte unique dans `Event` (elle n'a pas encore de `__table_args__`) :

```python
    __table_args__ = (
        UniqueConstraint("recurrence_parent_id", "recurrence_date",
                         name="uq_event_override"),
    )
```

(`UniqueConstraint` est déjà importé en tête de fichier.)

- [ ] **Step 3b: Migration 0007**

```python
# alembic/versions/0007_recurrence.py
"""S175 — récurrence : exdates + override (recurrence_parent_id, recurrence_date).

Revision ID: 0007_recurrence
Revises: 0006_rappels_par_personne
"""
from alembic import op
import sqlalchemy as sa

revision = "0007_recurrence"
down_revision = "0006_rappels_par_personne"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("events", sa.Column("exdates", sa.JSON(), nullable=False,
                                      server_default="[]"))
    op.add_column("events", sa.Column("recurrence_parent_id", sa.String(36), nullable=True))
    op.add_column("events", sa.Column("recurrence_date", sa.DateTime(), nullable=True))
    op.create_index("ix_events_recurrence_parent_id", "events", ["recurrence_parent_id"])
    op.create_foreign_key("fk_events_recurrence_parent", "events", "events",
                          ["recurrence_parent_id"], ["id"], ondelete="CASCADE")
    op.create_unique_constraint("uq_event_override", "events",
                                ["recurrence_parent_id", "recurrence_date"])


def downgrade() -> None:
    op.drop_constraint("uq_event_override", "events", type_="unique")
    op.drop_constraint("fk_events_recurrence_parent", "events", type_="foreignkey")
    op.drop_index("ix_events_recurrence_parent_id", table_name="events")
    op.drop_column("events", "recurrence_date")
    op.drop_column("events", "recurrence_parent_id")
    op.drop_column("events", "exdates")
```

- [ ] **Step 3c: Schémas**

Dans `models/schemas.py`, ajouter en tête l'import :
```python
from services.recurrence import valider_rrule
```
Dans `EventCreate` **et** `EventUpdate`, ajouter le validateur (None = non fourni, laissé tel quel) :
```python
    @field_validator("recurrence_rule")
    @classmethod
    def _rrule(cls, v):
        return valider_rrule(v) if v else v
```
Dans `EventOut`, ajouter les champs (après `recurrence_rule`) :
```python
    exdates: list[datetime] = []
    occurrence_start: Optional[datetime] = None
    recurrent: bool = False
```
Et étendre le sérialiseur horaire existant pour couvrir `occurrence_start` (les `exdates` restent en naïf ; le front ne les lit pas dans la liste) :
```python
    @field_serializer("start_at", "end_at", "occurrence_start")
    def _heure_locale(self, v: datetime):
        return vers_paris(v) if v is not None else v
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd briques/agenda/backend && python3 -m pytest tests/test_recurrence_orm.py -q`
Expected: PASS (3 tests). Puis suite complète : `python3 -m pytest -q` → toujours **152 passed + nouveaux**, aucune régression.

- [ ] **Step 5: Commit**

```bash
git add briques/agenda/backend/models/orm.py briques/agenda/backend/models/schemas.py \
        briques/agenda/backend/alembic/versions/0007_recurrence.py \
        briques/agenda/backend/tests/test_recurrence_orm.py
git commit -m "feat(s175): ORM + migration 0007 + schémas — exdates/override/occurrence

<lignes co-auteur>"
```

---

### Task 4: `services/occurrences.py` — orchestration read

**Files:**
- Create: `briques/agenda/backend/services/occurrences.py`
- Test: `briques/agenda/backend/tests/test_occurrences.py`

**Interfaces:**
- Consumes: `services.recurrence.{expanser, Occurrence}` ; `models.orm.Event` ; `models.schemas.EventOut` ; `services.horaires.{vers_utc_naif, vers_paris}`.
- Produces:
  - `async occurrences_calendrier(db, cal_id, debut, fin) -> list[Occurrence]` — charge les maîtres du calendrier (non-récurrents chevauchant la fenêtre **+** récurrents `start_at<=fin`, **overrides exclus** `recurrence_parent_id IS NULL`), leurs overrides et exdates, puis expanse.
  - `occurrence_en_dict(occ) -> dict` — `EventOut.model_validate(occ.source).model_dump(mode="json")` avec `start_at/end_at/occurrence_start/recurrent` corrigés à l'occurrence.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_occurrences.py
from __future__ import annotations

from datetime import datetime

import pytest

from models.orm import Calendar, Event
from services.occurrences import occurrences_calendrier, occurrence_en_dict


async def _cal(db):
    c = Calendar(user_id="perso", name="Perso")
    db.add(c); await db.flush()
    return c


@pytest.mark.asyncio
async def test_maitre_recurrent_avant_fenetre_est_deplie(db):
    # Piège fenêtre : maître démarré en JANVIER, on regarde JUIN → doit apparaître.
    c = await _cal(db)
    m = Event(calendar_id=c.id, title="Hebdo", created_by="perso", rappels=[],
              start_at=datetime(2026, 1, 5, 9, 0), end_at=datetime(2026, 1, 5, 10, 0),
              recurrence_rule="FREQ=WEEKLY", exdates=[])
    db.add(m); await db.commit()
    occ = await occurrences_calendrier(db, c.id, datetime(2026, 6, 1), datetime(2026, 6, 30))
    assert len(occ) >= 4 and all(o.start.month == 6 for o in occ)


@pytest.mark.asyncio
async def test_override_et_exdate_appliques(db):
    c = await _cal(db)
    m = Event(calendar_id=c.id, title="Hebdo", created_by="perso", rappels=[],
              start_at=datetime(2026, 6, 1, 9, 0), end_at=datetime(2026, 6, 1, 10, 0),
              recurrence_rule="FREQ=WEEKLY", exdates=[datetime(2026, 6, 15, 9, 0).isoformat()])
    db.add(m); await db.flush()
    ov = Event(calendar_id=c.id, title="Déplacé", created_by="perso", rappels=[],
               start_at=datetime(2026, 6, 8, 14, 0), end_at=datetime(2026, 6, 8, 15, 0),
               recurrence_parent_id=m.id, recurrence_date=datetime(2026, 6, 8, 9, 0))
    db.add(ov); await db.commit()
    occ = await occurrences_calendrier(db, c.id, datetime(2026, 6, 1), datetime(2026, 6, 30))
    starts = {o.occurrence_start for o in occ}
    assert datetime(2026, 6, 15, 9, 0) not in starts          # exdate sautée
    depl = next(o for o in occ if o.occurrence_start == datetime(2026, 6, 8, 9, 0))
    assert depl.source.title == "Déplacé"                     # override substitué
    d = occurrence_en_dict(depl)
    assert d["title"] == "Déplacé" and d["recurrent"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/agenda/backend && python3 -m pytest tests/test_occurrences.py -q`
Expected: FAIL (`ModuleNotFoundError: services.occurrences`).

- [ ] **Step 3: Write minimal implementation**

```python
# services/occurrences.py
"""Orchestration de la récurrence (S175) : charge maîtres + overrides + exdates depuis
la base et délègue l'expansion pure à `services.recurrence`. Point d'entrée READ des
occurrences (dashboard, agrégation, list_events). Toujours en naïf UTC en interne."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.orm import Event
from models.schemas import EventOut
from services.horaires import vers_paris, vers_utc_naif
from services.recurrence import Occurrence, expanser


def _naif(dt: datetime | str) -> datetime:
    """exdates/recurrence_date peuvent revenir en str (JSON) → datetime naïf UTC."""
    return datetime.fromisoformat(dt) if isinstance(dt, str) else dt


async def occurrences_calendrier(db: AsyncSession, cal_id: str,
                                 debut: datetime | None, fin: datetime | None) -> list[Occurrence]:
    """Occurrences d'un calendrier sur [debut, fin]. Les OVERRIDES ne sont jamais
    interrogés directement (recurrence_parent_id IS NULL) : ils sont réinjectés par
    l'expansion à la place de l'occurrence qu'ils remplacent."""
    d = vers_utc_naif(debut) if debut else None
    f = vers_utc_naif(fin) if fin else None
    # Non-récurrents chevauchant la fenêtre OU tout maître récurrent pouvant l'atteindre
    # (start_at <= fin ; une série ne produit rien avant son premier début).
    non_recurrent = [Event.recurrence_rule.is_(None)]
    if f:
        non_recurrent.append(Event.start_at <= f)
    if d:
        non_recurrent.append(Event.end_at >= d)
    recurrent = [Event.recurrence_rule.is_not(None)]
    if f:
        recurrent.append(Event.start_at <= f)
    rows = (await db.execute(
        select(Event).where(and_(
            Event.calendar_id == cal_id,
            Event.recurrence_parent_id.is_(None),
            or_(and_(*non_recurrent), and_(*recurrent)),
        )).order_by(Event.start_at)
    )).scalars().all()
    maitres = list(rows)
    ids = [m.id for m in maitres if m.recurrence_rule]
    overrides_par_parent: dict[str, dict[datetime, Event]] = {}
    if ids:
        ovs = (await db.execute(
            select(Event).where(Event.recurrence_parent_id.in_(ids))
        )).scalars().all()
        for ov in ovs:
            overrides_par_parent.setdefault(ov.recurrence_parent_id, {})[
                _naif(ov.recurrence_date)] = ov
    result: list[Occurrence] = []
    for m in maitres:
        exd = {_naif(x) for x in (m.exdates or [])}
        result.extend(expanser(m, d, f, exd, overrides_par_parent.get(m.id, {})))
    result.sort(key=lambda o: o.start)
    return result


def occurrence_en_dict(occ: Occurrence) -> dict:
    """Occurrence → dict JSON, à partir de EventOut de sa source, avec horaires et
    identité d'occurrence corrigés. Base commune au dashboard et à list_events."""
    dico = EventOut.model_validate(occ.source).model_dump(mode="json")
    dico["start_at"] = vers_paris(occ.start).isoformat()
    dico["end_at"] = vers_paris(occ.end).isoformat()
    dico["occurrence_start"] = vers_paris(occ.occurrence_start).isoformat()
    dico["recurrent"] = occ.recurrent
    return dico
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd briques/agenda/backend && python3 -m pytest tests/test_occurrences.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add briques/agenda/backend/services/occurrences.py briques/agenda/backend/tests/test_occurrences.py
git commit -m "feat(s175): services.occurrences — charge maîtres/overrides/exdates + expanse

<lignes co-auteur>"
```

---

### Task 5: Câbler `GET /calendars/{cal_id}/events` (front web)

**Files:**
- Modify: `briques/agenda/backend/routers/events.py:26-45` (`list_events`)
- Test: `briques/agenda/backend/tests/test_events_recurrence.py`

**Interfaces:**
- Consumes: `services.occurrences.{occurrences_calendrier, occurrence_en_dict}`.
- Produces: `list_events` renvoie des dicts d'occurrences (`response_model=None`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_events_recurrence.py
from __future__ import annotations

from datetime import datetime

import pytest

from models.orm import Calendar, CalendarMember, Event
from routers import events as E

USER = {"sub": "perso"}


async def _cal(db):
    c = Calendar(user_id="perso", name="Perso")
    db.add(c); await db.flush()
    return c


@pytest.mark.asyncio
async def test_list_events_deplie_la_serie(db):
    c = await _cal(db)
    m = Event(calendar_id=c.id, title="Hebdo", created_by="perso", rappels=[],
              start_at=datetime(2026, 6, 1, 9, 0), end_at=datetime(2026, 6, 1, 10, 0),
              recurrence_rule="FREQ=WEEKLY", exdates=[])
    db.add(m); await db.commit()
    res = await E.list_events(cal_id=c.id, start=datetime(2026, 6, 1),
                              end=datetime(2026, 6, 30), db=db, user=USER)
    assert len(res) == 5                                  # 5 lundis de juin
    assert all(r["recurrent"] for r in res)
    assert res[0]["id"] == m.id                           # id du maître conservé
    assert res[0]["occurrence_start"] != res[1]["occurrence_start"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/agenda/backend && python3 -m pytest tests/test_events_recurrence.py -q`
Expected: FAIL (`len(res)` == 1 : la série n'est pas dépliée).

- [ ] **Step 3: Write minimal implementation**

Remplacer le corps de `list_events` et son décorateur :

```python
from services.occurrences import occurrence_en_dict, occurrences_calendrier

@router.get("/calendars/{cal_id}/events", response_model=None)
async def list_events(
    cal_id: str,
    start: Optional[datetime] = Query(None),
    end: Optional[datetime] = Query(None),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await require_calendar_access(db, cal_id, user["sub"], min_role="viewer")
    occ = await occurrences_calendrier(db, cal_id, start, end)
    return [occurrence_en_dict(o) for o in occ]
```

(Les imports `and_`, `select`, `Event`, `vers_utc_naif` de `events.py` restent utilisés ailleurs dans le fichier ; ne pas les retirer.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd briques/agenda/backend && python3 -m pytest tests/test_events_recurrence.py tests/test_events_rappels.py -q`
Expected: PASS (nouveau + non-régression des tests d'events existants).

- [ ] **Step 5: Commit**

```bash
git add briques/agenda/backend/routers/events.py briques/agenda/backend/tests/test_events_recurrence.py
git commit -m "feat(s175): GET /calendars/{id}/events déplie les occurrences

<lignes co-auteur>"
```

---

### Task 6: Câbler l'agrégation `/service/events` (+ correctif N+1)

**Files:**
- Modify: `briques/agenda/backend/services/agregation.py:36-75` (`evenements_agreges`)
- Test: `briques/agenda/backend/tests/test_service_agenda.py` (ajout)

**Interfaces:**
- Consumes: `services.occurrences.{occurrences_calendrier, occurrence_en_dict}` ; `models.orm.{Label, EventParticipant}` ; `services.rappels.rappels_effectifs`.
- Produces: `evenements_agreges` renvoie une occurrence par répétition, enrichie comme avant (`calendrier`, `etiquette`, `couleur`, `participants`+`rappels_effectifs`). Participants et labels chargés **par lot** (plus de N+1 par event).

- [ ] **Step 1: Write the failing test**

```python
# ajout à tests/test_service_agenda.py
@pytest.mark.asyncio
async def test_agrege_deplie_recurrence(db):
    perso = await _cal(db, name="Perso", is_default=True)
    m = Event(calendar_id=perso.id, title="Hebdo", created_by="perso", rappels=[10],
              start_at=datetime(2026, 7, 14, 12, 0), end_at=datetime(2026, 7, 14, 13, 0),
              recurrence_rule="FREQ=DAILY", exdates=[])
    db.add(m); await db.commit()
    evts = await S.service_lister_evenements(debut=DEBUT, fin=FIN, db=db, user=USER)
    hebdo = [e for e in evts if e["title"] == "Hebdo"]
    assert len(hebdo) == 7                                  # 14→20 juillet inclus
    assert {e["occurrence_start"][:10] for e in hebdo} == {
        f"2026-07-{d:02d}" for d in range(14, 21)}
    assert all(e["recurrent"] and e["participants"] is not None for e in hebdo)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/agenda/backend && python3 -m pytest tests/test_service_agenda.py::test_agrege_deplie_recurrence -q`
Expected: FAIL (`len(hebdo)` == 1).

- [ ] **Step 3: Write minimal implementation**

Remplacer la boucle interne de `evenements_agreges` (l.44-74) par une version qui expanse et charge participants/labels par lot :

```python
    from services.occurrences import occurrence_en_dict, occurrences_calendrier

    cals = await calendriers_accessibles(db, user_id)
    evts: list[dict] = []
    for c in cals:
        labels = {l.id: l for l in (await db.execute(
            select(Label).where(Label.calendar_id == c.id)
        )).scalars().all()}
        occ = await occurrences_calendrier(db, c.id, debut, fin)
        # Participants chargés EN LOT pour tous les events sources (maîtres + overrides)
        # de ce calendrier — évite le N+1 aggravé par l'expansion.
        src_ids = {o.source.id for o in occ}
        parts_par_event: dict[str, list] = {}
        if src_ids:
            for p in (await db.execute(
                select(EventParticipant).where(EventParticipant.event_id.in_(src_ids))
            )).scalars().all():
                parts_par_event.setdefault(p.event_id, []).append(p)
        for o in occ:
            e = o.source
            d = occurrence_en_dict(o)
            lab = labels.get(e.label_id)
            d["calendrier"] = c.name
            d["etiquette"] = lab.name if lab else None
            d["couleur"] = (lab.color if lab else None) or e.color or c.color
            d["participants"] = [
                {"user_id": p.user_id, "status": p.status,
                 "rappels_effectifs": rappels_effectifs(p.rappels, e.rappels)}
                for p in parts_par_event.get(e.id, [])
            ]
            evts.append(d)
    return evts
```

Ajouter `EventParticipant` à l'import ORM en tête de `agregation.py` (déjà importé : vérifier ligne `from models.orm import ...` — il y figure déjà).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd briques/agenda/backend && python3 -m pytest tests/test_service_agenda.py -q`
Expected: PASS (nouveau + tous les tests d'agrégation existants inchangés).

- [ ] **Step 5: Commit**

```bash
git add briques/agenda/backend/services/agregation.py briques/agenda/backend/tests/test_service_agenda.py
git commit -m "feat(s175): agrégation /service déplie les occurrences + lot participants (N+1)

<lignes co-auteur>"
```

---

### Task 7: API portée — `PATCH`/`DELETE /events/{id}` (`?scope=&occurrence=`)

**Files:**
- Modify: `briques/agenda/backend/services/occurrences.py` (helpers write)
- Modify: `briques/agenda/backend/routers/events.py:88-126` (`update_event`, `delete_event`)
- Test: `briques/agenda/backend/tests/test_scope_edition.py`

**Interfaces:**
- Consumes: `services.recurrence.expanser` (pour vérifier qu'une occurrence existe).
- Produces dans `services/occurrences.py` :
  - `occurrence_valide(maitre, occurrence: datetime) -> bool` — l'ISO cible est produit par la règle et pas déjà exclu.
  - `async exclure_occurrence(db, maitre, occurrence) -> None` — ajoute l'ISO à `exdates`.
  - `async creer_ou_maj_override(db, maitre, occurrence, champs: dict) -> Event` — crée/maj l'override (contrainte unique).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_scope_edition.py
from __future__ import annotations

from datetime import datetime

import pytest
from fastapi import HTTPException

from models.orm import Calendar, Event
from models.schemas import EventUpdate
from routers import events as E
from services.occurrences import occurrences_calendrier

USER = {"sub": "perso"}


async def _serie(db):
    c = Calendar(user_id="perso", name="Perso")
    db.add(c); await db.flush()
    m = Event(calendar_id=c.id, title="Hebdo", created_by="perso", rappels=[],
              start_at=datetime(2026, 6, 1, 9, 0), end_at=datetime(2026, 6, 1, 10, 0),
              recurrence_rule="FREQ=WEEKLY", exdates=[])
    db.add(m); await db.commit()
    return c, m


@pytest.mark.asyncio
async def test_delete_scope_this_exclut_l_occurrence(db):
    c, m = await _serie(db)
    await E.delete_event(event_id=m.id, scope="this",
                         occurrence=datetime(2026, 6, 8, 9, 0), db=db, user=USER)
    occ = await occurrences_calendrier(db, c.id, datetime(2026, 6, 1), datetime(2026, 6, 30))
    assert datetime(2026, 6, 8, 9, 0) not in {o.occurrence_start for o in occ}
    assert await db.get(Event, m.id) is not None            # maître toujours là


@pytest.mark.asyncio
async def test_patch_scope_this_cree_un_override(db):
    c, m = await _serie(db)
    await E.update_event(event_id=m.id, body=EventUpdate(title="Déplacé"),
                         scope="this", occurrence=datetime(2026, 6, 8, 9, 0),
                         db=db, user=USER)
    occ = await occurrences_calendrier(db, c.id, datetime(2026, 6, 1), datetime(2026, 6, 30))
    depl = next(o for o in occ if o.occurrence_start == datetime(2026, 6, 8, 9, 0))
    assert depl.source.title == "Déplacé"


@pytest.mark.asyncio
async def test_patch_scope_this_occurrence_inexistante_422(db):
    c, m = await _serie(db)
    with pytest.raises(HTTPException) as ex:
        await E.update_event(event_id=m.id, body=EventUpdate(title="x"),
                             scope="this", occurrence=datetime(2026, 6, 3, 9, 0),  # un mercredi
                             db=db, user=USER)
    assert ex.value.status_code == 422


@pytest.mark.asyncio
async def test_delete_scope_all_supprime_la_serie(db):
    c, m = await _serie(db)
    await E.delete_event(event_id=m.id, scope="all", occurrence=None, db=db, user=USER)
    assert await db.get(Event, m.id) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/agenda/backend && python3 -m pytest tests/test_scope_edition.py -q`
Expected: FAIL (`update_event`/`delete_event` n'acceptent pas `scope`/`occurrence`).

- [ ] **Step 3a: Helpers write dans `services/occurrences.py`**

```python
def occurrence_valide(maitre, occurrence: datetime) -> bool:
    """Vrai si `occurrence` (naïf UTC) est une occurrence produite par la règle du
    maître et pas déjà dans ses exdates."""
    if not maitre.recurrence_rule:
        return False
    exd = {_naif(x) for x in (maitre.exdates or [])}
    if occurrence in exd:
        return False
    petit = expanser(maitre, occurrence, occurrence, set(), {})
    return any(o.occurrence_start == occurrence for o in petit)


async def exclure_occurrence(db: AsyncSession, maitre, occurrence: datetime) -> None:
    """Ajoute `occurrence` aux exdates du maître (réassignation : SQLAlchemy ne traque
    pas la mutation en place d'une colonne JSON)."""
    maitre.exdates = list(maitre.exdates or []) + [occurrence.isoformat()]
    await db.commit()


async def creer_ou_maj_override(db: AsyncSession, maitre, occurrence: datetime,
                                champs: dict):
    """Crée (ou met à jour) l'event-override d'une occurrence. `champs` = colonnes ORM à
    poser (title/start_at/end_at/...). Défaut : hérite des horaires de l'occurrence."""
    from models.orm import Event
    ov = (await db.execute(
        select(Event).where(and_(Event.recurrence_parent_id == maitre.id,
                                 Event.recurrence_date == occurrence))
    )).scalar_one_or_none()
    duree = maitre.end_at - maitre.start_at
    if ov is None:
        ov = Event(calendar_id=maitre.calendar_id, created_by=maitre.created_by,
                   title=maitre.title, description=maitre.description,
                   location=maitre.location, color=maitre.color, label_id=maitre.label_id,
                   all_day=maitre.all_day, rappels=list(maitre.rappels or []),
                   start_at=occurrence, end_at=occurrence + duree,
                   recurrence_parent_id=maitre.id, recurrence_date=occurrence)
        db.add(ov)
    for k, v in champs.items():
        setattr(ov, k, v)
    await db.commit()
    await db.refresh(ov)
    return ov
```

- [ ] **Step 3b: Routes `events.py`**

`update_event` et `delete_event` reçoivent `scope`/`occurrence` en query. Mapping des champs français→ORM déjà implicite ici (EventUpdate est déjà en colonnes ORM). Remplacer les deux fonctions :

```python
@router.patch("/events/{event_id}", response_model=None)
async def update_event(
    event_id: str,
    body: EventUpdate,
    scope: str = Query("all"),
    occurrence: Optional[datetime] = Query(None),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    from services.occurrences import creer_ou_maj_override, occurrence_valide, occurrence_en_dict
    from services.recurrence import Occurrence
    evt = await db.get(Event, event_id)
    if not evt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    await require_calendar_access(db, evt.calendar_id, user["sub"], min_role="editor")
    data = body.model_dump(exclude_unset=True)
    if data.get("label_id") == "":
        data["label_id"] = None
    if scope == "this" and evt.recurrence_rule:
        occ = vers_utc_naif(occurrence) if occurrence else None
        if not occ or not occurrence_valide(evt, occ):
            raise HTTPException(status_code=422, detail="occurrence invalide")
        ov = await creer_ou_maj_override(db, evt, occ, data)
        await consigner(db, evt.id, user["sub"], "event_updated",
                        {"portee": "occurrence", "occurrence": occ.isoformat()})
        await db.commit()
        out = occurrence_en_dict(Occurrence(ov, ov.start_at, ov.end_at, occ, True))
        await publish_change(evt.calendar_id, "event.updated", out)
        return out
    for k, v in data.items():
        setattr(evt, k, v)
    await consigner(db, evt.id, user["sub"], "event_updated", {"champs": list(data.keys())})
    await db.commit()
    await db.refresh(evt)
    out = EventOut.model_validate(evt).model_dump(mode="json")
    await publish_change(evt.calendar_id, "event.updated", out)
    return out


@router.delete("/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event(
    event_id: str,
    scope: str = Query("all"),
    occurrence: Optional[datetime] = Query(None),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    from services.occurrences import exclure_occurrence, occurrence_valide
    evt = await db.get(Event, event_id)
    if not evt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    await require_calendar_access(db, evt.calendar_id, user["sub"], min_role="editor")
    cal_id = evt.calendar_id
    if scope == "this" and evt.recurrence_rule:
        occ = vers_utc_naif(occurrence) if occurrence else None
        if not occ or not occurrence_valide(evt, occ):
            raise HTTPException(status_code=422, detail="occurrence invalide")
        await exclure_occurrence(db, evt, occ)
        await publish_change(cal_id, "event.updated", {"id": event_id})
        return
    await db.delete(evt)
    await db.commit()
    await publish_change(cal_id, "event.deleted", {"id": event_id})
```

(Le PATCH passe en `response_model=None` car il peut renvoyer un dict d'occurrence.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd briques/agenda/backend && python3 -m pytest tests/test_scope_edition.py tests/test_events_recurrence.py -q`
Expected: PASS (4 nouveaux + non-régression).

- [ ] **Step 5: Commit**

```bash
git add briques/agenda/backend/services/occurrences.py briques/agenda/backend/routers/events.py \
        briques/agenda/backend/tests/test_scope_edition.py
git commit -m "feat(s175): portée d'édition scope=all|this (exclure/override) sur /events

<lignes co-auteur>"
```

---

### Task 8: Surface `/service` — `recurrence` en création + `scope` en édition (outils LLM)

**Files:**
- Modify: `briques/agenda/backend/routers/service.py` (`EvenementServiceIn`, `service_creer_evenement`, `EvenementPatchIn`, `service_modifier_evenement`, `service_supprimer_evenement`)
- Test: `briques/agenda/backend/tests/test_service_recurrence.py`

**Interfaces:**
- Consumes: `services.recurrence.valider_rrule` ; helpers write de `services/occurrences.py` (Task 7).
- Produces: `POST /service/events` accepte `recurrence: str|None` (RRULE validée) ; `PATCH`/`DELETE /service/events/{id}` acceptent `scope`/`occurrence`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_service_recurrence.py
from __future__ import annotations

from datetime import datetime

import pytest

from models.orm import Calendar, Event
from routers import service as S
from services.occurrences import occurrences_calendrier

USER = {"sub": "perso", "service_call": True}


@pytest.mark.asyncio
async def test_service_cree_evenement_recurrent(db):
    c = Calendar(user_id="perso", name="Perso", is_default=True)
    db.add(c); await db.commit()
    corps = S.EvenementServiceIn(titre="Sport", debut=datetime(2026, 6, 1, 18, 0),
                                 fin=datetime(2026, 6, 1, 19, 0),
                                 recurrence="FREQ=WEEKLY;BYDAY=MO,WE")
    evt = await S.service_creer_evenement(corps=corps, db=db, user=USER)
    assert evt.recurrence_rule == "FREQ=WEEKLY;BYDAY=MO,WE"


@pytest.mark.asyncio
async def test_service_delete_scope_this(db):
    c = Calendar(user_id="perso", name="Perso", is_default=True)
    db.add(c); await db.flush()
    m = Event(calendar_id=c.id, title="Hebdo", created_by="perso", rappels=[],
              start_at=datetime(2026, 6, 1, 9, 0), end_at=datetime(2026, 6, 1, 10, 0),
              recurrence_rule="FREQ=WEEKLY", exdates=[])
    db.add(m); await db.commit()
    await S.service_supprimer_evenement(event_id=m.id, scope="this",
                                        occurrence=datetime(2026, 6, 8, 9, 0), db=db, user=USER)
    occ = await occurrences_calendrier(db, c.id, datetime(2026, 6, 1), datetime(2026, 6, 30))
    assert datetime(2026, 6, 8, 9, 0) not in {o.occurrence_start for o in occ}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/agenda/backend && python3 -m pytest tests/test_service_recurrence.py -q`
Expected: FAIL (`EvenementServiceIn` n'a pas `recurrence` ; `service_supprimer_evenement` n'a pas `scope`).

- [ ] **Step 3: Write minimal implementation**

Dans `service.py` :

1. `EvenementServiceIn` : ajouter `recurrence: Optional[str] = None` + validateur
```python
    @field_validator("recurrence")
    @classmethod
    def _rrule(cls, v):
        from services.recurrence import valider_rrule
        return valider_rrule(v) if v else v
```
2. `service_creer_evenement` : passer `recurrence_rule=corps.recurrence` au constructeur `Event(...)`.
3. `EvenementPatchIn` : ajouter `recurrence: Optional[str] = None` + le même validateur, et l'entrée `"recurrence": "recurrence_rule"` dans `_PATCH_MAP`.
4. `service_modifier_evenement` : ajouter params `scope: str = Query("all")`, `occurrence: Optional[datetime] = Query(None)` ; si `scope == "this"` et evt récurrent, valider l'occurrence (`occurrence_valide`) puis `creer_ou_maj_override(db, evt, occ, {col ORM des champs fournis})` et renvoyer `occurrence_en_dict(...)` ; sinon comportement actuel.
5. `service_supprimer_evenement` : ajouter les mêmes params ; si `scope == "this"` et evt récurrent → `exclure_occurrence` (après validation), sinon `db.delete`.

Le mapping champ→colonne pour l'override réutilise `_PATCH_MAP`. `occurrence` est convertie par `vers_utc_naif` (importée dans `service.py` — l'ajouter : `from services.horaires import vers_utc_naif`).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd briques/agenda/backend && python3 -m pytest tests/test_service_recurrence.py tests/test_service_agenda.py -q`
Expected: PASS (2 nouveaux + non-régression `/service`).

- [ ] **Step 5: Commit**

```bash
git add briques/agenda/backend/routers/service.py briques/agenda/backend/tests/test_service_recurrence.py
git commit -m "feat(s175): /service — recurrence en création + scope en édition (outils LLM)

<lignes co-auteur>"
```

---

### Task 9: Proactif du Cœur — dédup par occurrence

**Files:**
- Modify: `core/proactif.py:171-206` (`_check_agenda`)
- Test: `core/test_proactif_recurrence.py`

**Interfaces:**
- Consumes: `agenda.lister_evenements` (déjà mocké dans les tests) ; chaque event peut porter `occurrence_start`.
- Produces: clé de dédup incluant l'occurrence : `f"agenda:{id}:{occ_start}:{uid}:{m}"`.

- [ ] **Step 1: Write the failing test**

```python
# core/test_proactif_recurrence.py
"""S175 — deux occurrences d'un même event récurrent (même id, occurrence_start
différent) doivent chacune notifier (clé de dédup par occurrence)."""

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


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_deux_occurrences_notifient_chacune():
    _reset()
    debut = datetime.now() + timedelta(minutes=9)
    base = {"id": "hebdo", "title": "Sport", "location": None,
            "end_at": (debut + timedelta(hours=1)).isoformat(), "rappels": [10],
            "participants": [{"user_id": "perso", "status": "accepted",
                              "rappels_effectifs": [10]}]}
    # Deux occurrences DUES du même maître, distinguées par occurrence_start.
    occ1 = {**base, "start_at": debut.isoformat(), "occurrence_start": debut.isoformat()}
    occ2b = debut + timedelta(minutes=1)
    occ2 = {**base, "start_at": occ2b.isoformat(), "occurrence_start": occ2b.isoformat()}

    async def _faux(registre, d=None, f=None):
        return [occ1, occ2]
    agenda.lister_evenements = _faux

    _run(proactif._check_agenda(None))
    badges = [r for r in proactif.lister(limite=10) if r.get("type") == "agenda"]
    assert len(badges) == 2  # AVANT le fix : 1 seul (clé sans occurrence)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd core && python3 -m pytest test_proactif_recurrence.py -q` (ou `make test-core`)
Expected: FAIL (`len(badges)` == 1 : les deux occurrences partagent la clé `agenda:hebdo:perso:10`).

- [ ] **Step 3: Write minimal implementation**

Dans `core/proactif.py`, `_check_agenda`, à l'intérieur de la boucle `for p in participants:` remplacer la construction de la clé :

```python
                occ_start = e.get("occurrence_start") or e.get("start_at") or ""
                for m, _debut in _rappels_dus(evt_perso, maintenant):
                    titre = f"Rappel : {titre_evt}"
                    corps = f"{_delai_lisible(m).capitalize()} (à {heure}){lieu}"
                    cle = f"agenda:{e.get('id')}:{occ_start}:{uid}:{m}"
```

(Le reste de la boucle est inchangé : `heure = (e.get("start_at") or "")[11:16]` reflète déjà l'occurrence puisque chaque occurrence porte son propre `start_at`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd core && python3 -m pytest test_proactif_recurrence.py test_proactif_par_personne.py test_proactif_rappels.py -q`
Expected: PASS (nouveau + non-régression). Puis `make test-core` → **438 + 1 passed**, 0 échec.

- [ ] **Step 5: Commit**

```bash
git add core/proactif.py core/test_proactif_recurrence.py
git commit -m "feat(s175): proactif — clé de dédup par occurrence (récurrence)

<lignes co-auteur>"
```

---

### Task 10: Front — éditeur de récurrence + badge ↻ + dialogue de portée

**Files:**
- Modify: `briques/agenda/backend/templates_app.py` (modale event l.275-320 ; rendu grille l.246-260 ; POST/PATCH l.420-440)
- Test: `briques/agenda/backend/tests/test_app_web.py` (ajout d'assertions sur le HTML servi)

**Interfaces:**
- Consumes: les endpoints `list_events` (dicts avec `recurrent`, `occurrence_start`, `recurrence_rule`) et `PATCH`/`DELETE ?scope=&occurrence=`.
- Produces: UI qui compose une RRULE, affiche ↻ sur les occurrences, et demande la portée à l'édition/suppression.

- [ ] **Step 1: Write the failing test**

```python
# ajout à tests/test_app_web.py — vérifie que le template contient les briques de récurrence.
def test_template_contient_editeur_recurrence():
    from templates_app import PAGE_APP  # constante HTML/JS servie par GET /app
    assert "ev-recurrence" in PAGE_APP          # sélecteur de fréquence présent
    assert "FREQ=" in PAGE_APP                   # composition RRULE côté front
    assert "Toute la série" in PAGE_APP          # dialogue de portée
```

(Adapter le nom exact de la constante/def qui contient le HTML — repérer avec `grep -n "GET /app\|def page\|PAGE_APP\|return HTMLResponse" templates_app.py`. Si le HTML est produit par une fonction, importer et l'appeler.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/agenda/backend && python3 -m pytest tests/test_app_web.py::test_template_contient_editeur_recurrence -q`
Expected: FAIL (chaînes absentes).

- [ ] **Step 3: Write minimal implementation**

Dans la modale event (`ouvrirModaleEvent`), ajouter sous le bloc « journée entière » :

```javascript
// Récurrence : compose une RRULE simple (FREQ + INTERVAL + BYDAY hebdo + fin).
`<div style="margin-bottom:10px">
  <label>Répétition</label>
  <select id="ev-recurrence">
    <option value="">Ne se répète pas</option>
    <option value="FREQ=DAILY">Chaque jour</option>
    <option value="FREQ=WEEKLY">Chaque semaine</option>
    <option value="FREQ=MONTHLY">Chaque mois</option>
    <option value="FREQ=YEARLY">Chaque année</option>
  </select>
 </div>` +
```

Préremplir depuis `ev.recurrence_rule` à l'ouverture (sélectionner l'option dont la valeur est un préfixe de la règle). À l'enregistrement (`btn-enregistrer`), lire `#ev-recurrence` et l'envoyer comme `recurrence_rule` dans le POST/PATCH (chaîne vide → `null`).

Badge ↻ dans le rendu d'une case event (l.257) : préfixer le titre par `${e.recurrent ? "↻ " : ""}`.

Dialogue de portée : si `ev.recurrent`, à l'enregistrement/suppression d'une occurrence, afficher un `confirm`/mini-modale « Cet événement / Toute la série ». « Cet événement » → appel avec `?scope=this&occurrence=${ev.occurrence_start}` ; « Toute la série » → `?scope=all`. Pour un event non récurrent, appel direct sans `scope`.

Garder le rendu server-side en templates Python (pas de framework JS), cohérent avec l'existant.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd briques/agenda/backend && python3 -m pytest tests/test_app_web.py -q`
Expected: PASS. Vérification manuelle recommandée au déploiement (le front n'a pas de tests E2E ici) : créer une série hebdo, la voir dépliée avec ↻, déplacer une occurrence, en supprimer une.

- [ ] **Step 5: Commit**

```bash
git add briques/agenda/backend/templates_app.py briques/agenda/backend/tests/test_app_web.py
git commit -m "feat(s175): front agenda — éditeur de récurrence + badge ↻ + portée

<lignes co-auteur>"
```

---

### Task 11: README brique + roadmap + suite complète

**Files:**
- Modify: `briques/agenda/backend/README.md`
- Modify: `docs/sprints/S174-S180-roadmap-agenda-best-in-class.md`

- [ ] **Step 1: Documenter**

Dans le README de la brique : section « Récurrence (S175) » — champ `recurrence_rule` (RRULE), expansion read-time, `exdates`, override (`recurrence_parent_id`/`recurrence_date`), API `?scope=all|this&occurrence=`, limites (pas de `this_and_following` : fast-follow ; FREQ min = quotidienne).

Dans le roadmap : marquer **S175 code-complet**, rappeler le fast-follow `scope=this_and_following` (scission de série).

- [ ] **Step 2: Suite complète (non-régression finale)**

Run: `cd briques/agenda/backend && python3 -m pytest -q`
Expected: **152 + nouveaux tests passed**, 0 échec.

Run: `make test-core`
Expected: **438 + 1 passed**, 0 échec.

- [ ] **Step 3: Commit**

```bash
git add briques/agenda/backend/README.md docs/sprints/S174-S180-roadmap-agenda-best-in-class.md
git commit -m "docs(s175): README brique + roadmap — récurrence RRULE code-complet

<lignes co-auteur>"
```

---

## Self-Review (auteur du plan)

**Couverture spec ↔ plan :**
- §3 modèle de données (exdates/parent/date + unique) → Task 3 ✅
- §4 recurrence.py (valider_rrule, expanser, cap, identité d'occurrence) → Tasks 1-2 ✅
- §5 trois points de lecture (agrégation, list_events, unitaire renvoie le maître) → Tasks 4-6 (le `GET /events/{id}` reste inchangé = renvoie le maître ✅, aucune tâche nécessaire)
- §5.1 correctif N+1 participants/labels par lot → Task 6 ✅
- §6 proactif clé de dédup par occurrence → Task 9 ✅
- §7 API portée scope=all|this + occurrence + 422 → Task 7 ✅
- §8 front éditeur + badge ↻ + dialogue portée → Task 10 ✅
- §9 surface /service recurrence + scope → Task 8 ✅
- §11 cas limites (série sans fin/cap, exdate hors règle, override+exdate, non récurrent, all-day) → couverts par Tasks 2/4/7 ; le cas « all-day récurrent » suit le même chemin (durée conservée) ✅

**Placeholders :** aucun TODO/TBD ; code complet à chaque étape. Le seul point à confirmer à l'exécution = le nom exact de la constante HTML du front (Task 10 Step 1) — instruction de repérage fournie.

**Cohérence de types :** `Occurrence(source, start, end, occurrence_start, recurrent)` identique Tasks 2/4/7. `occurrences_calendrier`/`occurrence_en_dict`/`occurrence_valide`/`exclure_occurrence`/`creer_ou_maj_override` mêmes signatures Tasks 4/7/8. Dates naïf UTC en interne, `vers_paris` seulement à la sérialisation.

**Décision hors périmètre confirmée :** `scope=this_and_following` non implémenté (fast-follow) — un `scope` inconnu tombe dans la branche `all` par défaut ; si on veut un refus explicite, l'ajouter en fast-follow (pas ce sprint).

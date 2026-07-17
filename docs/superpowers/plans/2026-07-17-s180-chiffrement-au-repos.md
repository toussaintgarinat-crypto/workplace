# S180 — Chiffrement au repos (brique agenda) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Chiffrer au repos (AES-GCM par colonne) le contenu humain sensible de la brique agenda, de façon transparente pour le reste du code, via des `TypeDecorator` SQLAlchemy réutilisant le crypto déjà éprouvé de `vault.py`.

**Architecture:** Un module `crypto.py` porte la primitive AES-GCM extraite de `vault.py`, la dérivation de clé (`AGENDA_ENCRYPTION_KEY` dédiée, repli HKDF sur `VAULT_SECRET`), une enveloppe versionnée base64, et trois `TypeDecorator` (`Chiffre`, `ChiffreFloat`, `ChiffreJSON`). Les modèles ORM adoptent ces types sur les colonnes sensibles. Une migration Alembic `0012` chiffre les lignes existantes en place. Le reste du code (routers, services, ICS, digest, proactif) ne change pas : il voit du clair.

**Tech Stack:** Python 3.14, SQLAlchemy 2.0 async, `cryptography==43.0.3` (AES-GCM + HKDF), Alembic, pytest/pytest-asyncio, SQLite (dev/tests via `create_all`) / PostgreSQL (prod via migrations).

## Global Constraints

- Réutiliser `cryptography==43.0.3` **déjà présent** — aucune nouvelle dépendance. Imports : `from cryptography.hazmat.primitives.ciphers.aead import AESGCM`, `from cryptography.hazmat.primitives.kdf.hkdf import HKDF`, `from cryptography.hazmat.primitives import hashes`.
- **Fail-closed** : toute écriture chiffrée lève si aucune clé (`AGENDA_ENCRYPTION_KEY` ni `VAULT_SECRET`) n'est configurée — jamais de champ sensible en clair par accident (comme `vault.py`).
- **Enveloppe** : `base64( version(1 octet=0x01) || nonce(12 octets) || ciphertext )`. La version prépare une rotation future ; aucune rotation codée ici.
- **Transparence** : les suites agenda existantes (~325) doivent rester vertes **sans modification** de leurs assertions. C'est la preuve de non-régression.
- **Ne PAS chiffrer** : `*_at`, clés de jointure (`user_id`/`created_by`/…), jetons-capacités (`ics_token`/`share_token`/tokens d'invitation/`guest_key`), `external_id`, `Label.name`, `LoyaltyCard.enseigne`, couleurs/emoji/enums/booléens.
- **`vault.py` garde son format actuel** (`nonce || ct`, sans version, clé `SHA-256(VAULT_SECRET)`) — les tokens OAuth déjà stockés ne doivent pas casser. Il partage seulement la primitive bas-niveau.
- Prod = Postgres via migrations ; dev/tests = SQLite via `create_all`. Les colonnes chiffrées deviennent physiquement `Text` (le base64 dépasse les longueurs `String(n)` d'origine).
- Français pour noms/commentaires, cohérent avec le style du dossier.
- Répertoire de travail : `briques/agenda/backend`. Tous les chemins ci-dessous sont relatifs à ce dossier sauf mention.
- Lancer les tests : `cd briques/agenda/backend && python -m pytest tests/ -q`.

**Champs chiffrés (référence, périmètre complet du design) :**

| Table | Colonnes texte | Type décorateur |
| --- | --- | --- |
| `events` | `title`, `description`, `location` | `Chiffre` |
| `event_comments` | `content` | `Chiffre` |
| `live_positions` | `latitude`, `longitude` | `ChiffreFloat` |
| `user_profiles` | `email` | `Chiffre` |
| `calendar_invitations` | `email` | `Chiffre` |
| `shopping_list_invitations` | `email` | `Chiffre` |
| `loyalty_cards` | `numero`, `note` | `Chiffre` |
| `availability_polls` | `title`, `description`, `location` | `Chiffre` |
| `poll_votes` | `voter_name` | `Chiffre` |
| `event_activity_log` | `user_nom` | `Chiffre` |
| `event_activity_log` | `details` | `ChiffreJSON` |
| `shopping_items` | `name`, `note` | `Chiffre` |
| `shopping_lists` | `name` | `Chiffre` |

---

## File Structure

- **Create** `crypto.py` — primitive AES-GCM partagée, dérivation de clé, enveloppe versionnée, `TypeDecorator` `Chiffre`/`ChiffreFloat`/`ChiffreJSON`.
- **Create** `tests/test_crypto.py` — tests unitaires du crypto (round-trip, enveloppe, dérivation, fail-closed) + tests des `TypeDecorator` sur un modèle jetable.
- **Create** `tests/test_chiffrement_champs.py` — tests de transparence via l'ORM réel (écrire un `Event`/`LivePosition`/… → relire en clair ; lecture SQL brute → ciphertext).
- **Create** `alembic/versions/0012_chiffrement_champs.py` — migration : élargit les colonnes en `Text`, chiffre les lignes existantes ; `downgrade` déchiffre.
- **Create** `tests/test_migration_0012.py` — aller-retour des helpers de données de la migration en SQLite.
- **Modify** `config.py:44` (après `VAULT_SECRET`) — ajouter `AGENDA_ENCRYPTION_KEY`.
- **Modify** `models/orm.py` — remplacer le type des colonnes sensibles par les décorateurs.
- **Modify** `vault.py:34-44` — router `encrypt`/`decrypt` vers la primitive bas-niveau de `crypto.py`.
- **Modify** `README.md` — section « S180 — chiffrement au repos ».

---

## Task 1: Module `crypto.py` — primitive, clé, enveloppe

**Files:**
- Create: `crypto.py`
- Modify: `config.py:44`
- Test: `tests/test_crypto.py`

**Interfaces:**
- Produces:
  - `encrypt_raw(key: bytes, plaintext: bytes) -> bytes` (= `nonce(12) || ct`, sans version)
  - `decrypt_raw(key: bytes, blob: bytes) -> bytes`
  - `field_key() -> bytes` (clé AES-GCM des champs : `SHA-256(AGENDA_ENCRYPTION_KEY)` sinon HKDF de `VAULT_SECRET`)
  - `chiffrer(plaintext: str) -> str` (enveloppe versionnée base64)
  - `dechiffrer(token: str) -> str`
  - `VERSION: int = 1`

- [ ] **Step 1: Ajouter le réglage de clé dédiée**

Dans `config.py`, juste après la ligne `VAULT_SECRET: str = ""` (L44) :

```python
    # ── Chiffrement au repos des champs sensibles (S180) ───────────────────────
    # Clé dédiée qui dérive l'AES-GCM des colonnes sensibles (events, positions,
    # emails, etc.). Si vide, on dérive une sous-clé DISTINCTE de VAULT_SECRET via
    # HKDF (séparation des usages, zéro friction). Si les deux sont vides, toute
    # écriture chiffrée lève (fail-closed). En prod : au coffre, jamais dans l'image.
    AGENDA_ENCRYPTION_KEY: str = ""
```

- [ ] **Step 2: Écrire les tests du crypto**

Créer `tests/test_crypto.py` :

```python
"""Chiffrement au repos des champs (S180) — primitive, clé, enveloppe versionnée."""

from __future__ import annotations

import base64
import hashlib

import pytest

import crypto
from config import settings


def test_chiffrer_dechiffrer_roundtrip():
    token = crypto.chiffrer("Rendez-vous médecin 14h")
    assert isinstance(token, str)
    assert "médecin" not in token  # bien chiffré
    assert crypto.dechiffrer(token) == "Rendez-vous médecin 14h"


def test_enveloppe_versionnee():
    token = crypto.chiffrer("x")
    blob = base64.b64decode(token)
    assert blob[0] == crypto.VERSION  # octet de version en tête
    assert len(blob) >= 1 + 12 + 16    # version + nonce + tag GCM minimum


def test_nonce_unique_par_appel():
    assert crypto.chiffrer("meme-texte") != crypto.chiffrer("meme-texte")


def test_cle_dediee_prioritaire_sur_repli():
    settings.AGENDA_ENCRYPTION_KEY = "cle-dediee-de-test-32-octets-min-xx"
    attendu = hashlib.sha256(settings.AGENDA_ENCRYPTION_KEY.encode()).digest()
    assert crypto.field_key() == attendu
    settings.AGENDA_ENCRYPTION_KEY = ""


def test_repli_hkdf_distinct_du_coffre():
    """Sans clé dédiée, la clé des champs dérive de VAULT_SECRET mais N'EST PAS
    SHA-256(VAULT_SECRET) (= la clé du coffre OAuth) : usages séparés."""
    settings.AGENDA_ENCRYPTION_KEY = ""
    cle_coffre = hashlib.sha256(settings.VAULT_SECRET.encode()).digest()
    assert crypto.field_key() != cle_coffre
    assert crypto.field_key() == crypto.field_key()  # déterministe


def test_fail_closed_sans_aucune_cle():
    settings.AGENDA_ENCRYPTION_KEY = ""
    ancien = settings.VAULT_SECRET
    settings.VAULT_SECRET = ""
    try:
        with pytest.raises(RuntimeError):
            crypto.chiffrer("x")
    finally:
        settings.VAULT_SECRET = ancien


def test_dechiffrer_mauvaise_cle_leve():
    token = crypto.chiffrer("secret")
    settings.AGENDA_ENCRYPTION_KEY = "une-autre-cle-completement-differente"
    try:
        with pytest.raises(Exception):
            crypto.dechiffrer(token)
    finally:
        settings.AGENDA_ENCRYPTION_KEY = ""
```

- [ ] **Step 3: Lancer les tests — ils échouent**

Run: `cd briques/agenda/backend && python -m pytest tests/test_crypto.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'crypto'`)

- [ ] **Step 4: Écrire `crypto.py` (primitive + clé + enveloppe)**

Créer `crypto.py` (les `TypeDecorator` viennent en Task 2, on écrit d'abord la primitive) :

```python
"""Chiffrement au repos des champs sensibles (S180).

Réutilise l'AES-GCM éprouvé du coffre OAuth (vault.py) et l'expose en `TypeDecorator`
SQLAlchemy transparents. Enveloppe : base64(version || nonce(12) || ciphertext). La
clé dérive de AGENDA_ENCRYPTION_KEY (dédiée) ou, à défaut, d'une sous-clé HKDF
DISTINCTE de VAULT_SECRET (séparation des usages). Sans aucune clé : lève (fail-closed).
"""

from __future__ import annotations

import base64
import hashlib
import json
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from config import settings

VERSION = 1
_HKDF_SALT = b"agenda-fields-v1"
_HKDF_INFO = b"chiffrement-champs-agenda"


def field_key() -> bytes:
    """Clé AES-GCM (32 octets) des colonnes chiffrées."""
    if settings.AGENDA_ENCRYPTION_KEY:
        return hashlib.sha256(settings.AGENDA_ENCRYPTION_KEY.encode()).digest()
    if settings.VAULT_SECRET:
        return HKDF(
            algorithm=hashes.SHA256(), length=32,
            salt=_HKDF_SALT, info=_HKDF_INFO,
        ).derive(settings.VAULT_SECRET.encode())
    raise RuntimeError(
        "Ni AGENDA_ENCRYPTION_KEY ni VAULT_SECRET configuré — "
        "impossible de chiffrer un champ sensible"
    )


def encrypt_raw(key: bytes, plaintext: bytes) -> bytes:
    """Chiffré brut, SANS version : nonce(12) || ciphertext. Partagé avec vault.py."""
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    return nonce + aesgcm.encrypt(nonce, plaintext, None)


def decrypt_raw(key: bytes, blob: bytes) -> bytes:
    aesgcm = AESGCM(key)
    blob = bytes(blob)
    return aesgcm.decrypt(blob[:12], blob[12:], None)


def chiffrer(plaintext: str) -> str:
    """Enveloppe versionnée base64 d'une chaîne en clair."""
    raw = encrypt_raw(field_key(), plaintext.encode())
    return base64.b64encode(bytes([VERSION]) + raw).decode()


def dechiffrer(token: str) -> str:
    blob = base64.b64decode(token)
    # blob[0] = version (0x01 aujourd'hui) ; réservé pour une rotation future.
    return decrypt_raw(field_key(), blob[1:]).decode()
```

- [ ] **Step 5: Lancer les tests — ils passent**

Run: `cd briques/agenda/backend && python -m pytest tests/test_crypto.py -q`
Expected: PASS (7 tests)

- [ ] **Step 6: Commit**

```bash
git add briques/agenda/backend/crypto.py briques/agenda/backend/config.py briques/agenda/backend/tests/test_crypto.py
git commit -m "feat(s180): crypto.py — primitive AES-GCM, clé dédiée/HKDF, enveloppe versionnée"
```

---

## Task 2: `TypeDecorator` `Chiffre` / `ChiffreFloat` / `ChiffreJSON`

**Files:**
- Modify: `crypto.py` (ajout des classes)
- Test: `tests/test_crypto.py` (ajout)

**Interfaces:**
- Consumes: `crypto.chiffrer`, `crypto.dechiffrer` (Task 1)
- Produces (importables depuis `crypto`) :
  - `Chiffre` — `TypeDecorator`, `impl = Text`, chiffre/déchiffre une `str`, `None → None`
  - `ChiffreFloat` — `impl = Text`, chiffre `repr(float(v))`, rend un `float`, `None → None`
  - `ChiffreJSON` — `impl = Text`, chiffre `json.dumps(v)`, rend l'objet, `None → None`

- [ ] **Step 1: Écrire les tests des décorateurs (modèle jetable)**

Ajouter à la fin de `tests/test_crypto.py` :

```python
import pytest_asyncio
from sqlalchemy import Column, Integer, String, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

import crypto as crypto_mod


class _Base(DeclarativeBase):
    pass


class _Jetable(_Base):
    __tablename__ = "jetable_crypto"
    id = Column(Integer, primary_key=True)
    secret = Column(crypto_mod.Chiffre, nullable=True)
    lat = Column(crypto_mod.ChiffreFloat, nullable=True)
    meta = Column(crypto_mod.ChiffreJSON, nullable=True)


@pytest_asyncio.fixture
async def db_jetable():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(_Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_decorateurs_transparents_et_chiffres(db_jetable):
    db_jetable.add(_Jetable(id=1, secret="confidentiel", lat=48.8566,
                            meta={"clé": "valeur"}))
    await db_jetable.commit()
    db_jetable.expire_all()

    obj = (await db_jetable.execute(select(_Jetable).where(_Jetable.id == 1))).scalar_one()
    assert obj.secret == "confidentiel"       # transparent en lecture
    assert obj.lat == 48.8566
    assert obj.meta == {"clé": "valeur"}

    brut = (await db_jetable.execute(
        text("SELECT secret, lat, meta FROM jetable_crypto WHERE id=1"))).one()
    assert "confidentiel" not in (brut[0] or "")  # illisible en base
    assert "48.8566" not in (brut[1] or "")
    assert crypto_mod.dechiffrer(brut[0]) == "confidentiel"


@pytest.mark.asyncio
async def test_decorateurs_none_reste_none(db_jetable):
    db_jetable.add(_Jetable(id=2, secret=None, lat=None, meta=None))
    await db_jetable.commit()
    db_jetable.expire_all()
    obj = (await db_jetable.execute(select(_Jetable).where(_Jetable.id == 2))).scalar_one()
    assert obj.secret is None and obj.lat is None and obj.meta is None
```

- [ ] **Step 2: Lancer — échoue**

Run: `cd briques/agenda/backend && python -m pytest tests/test_crypto.py -q`
Expected: FAIL (`AttributeError: module 'crypto' has no attribute 'Chiffre'`)

- [ ] **Step 3: Ajouter les décorateurs à `crypto.py`**

Ajouter en haut de `crypto.py`, aux imports :

```python
from sqlalchemy.types import Text, TypeDecorator
```

Puis à la fin de `crypto.py` :

```python
class Chiffre(TypeDecorator):
    """Colonne texte chiffrée au repos (transparent en lecture/écriture)."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return None if value is None else chiffrer(value)

    def process_result_value(self, value, dialect):
        return None if value is None else dechiffrer(value)


class ChiffreFloat(TypeDecorator):
    """Float chiffré : sérialisé en repr() puis chiffré ; rendu en float."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return None if value is None else chiffrer(repr(float(value)))

    def process_result_value(self, value, dialect):
        return None if value is None else float(dechiffrer(value))


class ChiffreJSON(TypeDecorator):
    """Objet JSON chiffré : json.dumps() puis chiffré ; rendu désérialisé."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return None if value is None else chiffrer(json.dumps(value))

    def process_result_value(self, value, dialect):
        return None if value is None else json.loads(dechiffrer(value))
```

- [ ] **Step 4: Lancer — passe**

Run: `cd briques/agenda/backend && python -m pytest tests/test_crypto.py -q`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add briques/agenda/backend/crypto.py briques/agenda/backend/tests/test_crypto.py
git commit -m "feat(s180): TypeDecorator Chiffre/ChiffreFloat/ChiffreJSON transparents"
```

---

## Task 3: Chiffrer `Event` + `EventComment`

**Files:**
- Modify: `models/orm.py` (imports + colonnes `Event`, `EventComment`)
- Test: `tests/test_chiffrement_champs.py`

**Interfaces:**
- Consumes: `crypto.Chiffre` (Task 2), fixture `db` (`tests/conftest.py`)

- [ ] **Step 1: Écrire le test de transparence ORM**

Créer `tests/test_chiffrement_champs.py` :

```python
"""S180 — les colonnes sensibles sont chiffrées en base mais transparentes via l'ORM."""

from __future__ import annotations

import pytest
from sqlalchemy import select, text

from models.orm import Calendar, Event, EventComment
import crypto


@pytest.mark.asyncio
async def test_event_title_location_chiffres(db):
    cal = Calendar(id="c1", user_id="perso", name="Fam")
    db.add(cal)
    db.add(Event(id="e1", calendar_id="c1", title="Coloscopie papa",
                 description="clinique St-Jean", location="12 rue Verte",
                 start_at=__import__("datetime").datetime(2026, 8, 1, 9),
                 end_at=__import__("datetime").datetime(2026, 8, 1, 10),
                 created_by="perso"))
    await db.commit()
    db.expire_all()

    ev = (await db.execute(select(Event).where(Event.id == "e1"))).scalar_one()
    assert ev.title == "Coloscopie papa"      # transparent
    assert ev.location == "12 rue Verte"

    brut = (await db.execute(
        text("SELECT title, location FROM events WHERE id='e1'"))).one()
    assert "Coloscopie" not in brut[0]         # illisible en base
    assert crypto.dechiffrer(brut[0]) == "Coloscopie papa"


@pytest.mark.asyncio
async def test_comment_content_chiffre(db):
    db.add(Calendar(id="c2", user_id="perso", name="Fam"))
    db.add(Event(id="e2", calendar_id="c2", title="x",
                 start_at=__import__("datetime").datetime(2026, 8, 1, 9),
                 end_at=__import__("datetime").datetime(2026, 8, 1, 10),
                 created_by="perso"))
    db.add(EventComment(id="k1", event_id="e2", user_id="perso",
                        content="j'apporte le gâteau"))
    await db.commit()
    db.expire_all()

    brut = (await db.execute(
        text("SELECT content FROM event_comments WHERE id='k1'"))).one()
    assert "gâteau" not in brut[0]
    assert crypto.dechiffrer(brut[0]) == "j'apporte le gâteau"
```

- [ ] **Step 2: Lancer — échoue**

Run: `cd briques/agenda/backend && python -m pytest tests/test_chiffrement_champs.py -q`
Expected: FAIL (`assert "Coloscopie" not in brut[0]` — le titre est encore en clair)

- [ ] **Step 3: Adopter `Chiffre` sur `Event` et `EventComment`**

Dans `models/orm.py`, ajouter l'import (après la ligne `from db import Base`) :

```python
from crypto import Chiffre, ChiffreFloat, ChiffreJSON
```

Modifier `Event` — remplacer les 3 colonnes (L112, L113, L116) :

```python
    title: Mapped[str] = mapped_column(Chiffre, nullable=False)
    description: Mapped[str | None] = mapped_column(Chiffre, nullable=True)
```
```python
    location: Mapped[str | None] = mapped_column(Chiffre, nullable=True)
```

Modifier `EventComment.content` (L180) :

```python
    content: Mapped[str] = mapped_column(Chiffre, nullable=False)
```

- [ ] **Step 4: Lancer — passe**

Run: `cd briques/agenda/backend && python -m pytest tests/test_chiffrement_champs.py -q`
Expected: PASS (2 tests)

- [ ] **Step 5: Non-régression events**

Run: `cd briques/agenda/backend && python -m pytest tests/test_service_agenda.py tests/test_events_rappels.py tests/test_ics_generateur.py tests/test_journal.py -q`
Expected: PASS (inchangés — preuve de transparence)

- [ ] **Step 6: Commit**

```bash
git add briques/agenda/backend/models/orm.py briques/agenda/backend/tests/test_chiffrement_champs.py
git commit -m "feat(s180): chiffre Event.title/description/location + EventComment.content"
```

---

## Task 4: Chiffrer `LivePosition` (géoloc, `ChiffreFloat`)

**Files:**
- Modify: `models/orm.py` (colonnes `LivePosition.latitude`, `longitude`)
- Test: `tests/test_chiffrement_champs.py` (ajout)

**Interfaces:**
- Consumes: `crypto.ChiffreFloat` (Task 2)

- [ ] **Step 1: Écrire le test**

Ajouter à `tests/test_chiffrement_champs.py` :

```python
@pytest.mark.asyncio
async def test_live_position_latlon_chiffres(db):
    from datetime import datetime, timedelta
    from models.orm import LivePosition

    db.add(LivePosition(user_id="perso", latitude=48.8566, longitude=2.3522,
                        scope="famille",
                        expires_at=datetime.utcnow() + timedelta(minutes=30)))
    await db.commit()
    db.expire_all()

    pos = (await db.execute(
        select(LivePosition).where(LivePosition.user_id == "perso"))).scalar_one()
    assert pos.latitude == 48.8566 and pos.longitude == 2.3522   # transparent, float

    brut = (await db.execute(
        text("SELECT latitude FROM live_positions WHERE user_id='perso'"))).one()
    assert "48.8566" not in str(brut[0])       # illisible en base
    assert float(crypto.dechiffrer(brut[0])) == 48.8566
```

(Ajouter `from models.orm import LivePosition` en tête si tu préfères l'import global.)

- [ ] **Step 2: Lancer — échoue**

Run: `cd briques/agenda/backend && python -m pytest tests/test_chiffrement_champs.py::test_live_position_latlon_chiffres -q`
Expected: FAIL (`48.8566` encore lisible / colonne Float)

- [ ] **Step 3: Adopter `ChiffreFloat`**

Dans `models/orm.py`, `LivePosition` (L446-447) :

```python
    latitude: Mapped[float] = mapped_column(ChiffreFloat, nullable=False)
    longitude: Mapped[float] = mapped_column(ChiffreFloat, nullable=False)
```

- [ ] **Step 4: Lancer — passe (+ non-régression présence)**

Run: `cd briques/agenda/backend && python -m pytest tests/test_chiffrement_champs.py tests/test_presence.py tests/test_presence_service.py tests/test_presence_orm.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add briques/agenda/backend/models/orm.py briques/agenda/backend/tests/test_chiffrement_champs.py
git commit -m "feat(s180): chiffre LivePosition.latitude/longitude (géoloc)"
```

---

## Task 5: Chiffrer le reste du contenu humain

**Files:**
- Modify: `models/orm.py` (colonnes restantes du tableau de référence)
- Test: `tests/test_chiffrement_champs.py` (ajout)

**Interfaces:**
- Consumes: `crypto.Chiffre`, `crypto.ChiffreJSON` (Task 2)

- [ ] **Step 1: Écrire le test (emails, carte, sondage, journal, listes)**

Ajouter à `tests/test_chiffrement_champs.py` :

```python
@pytest.mark.asyncio
async def test_profil_email_chiffre(db):
    from models.orm import UserProfile
    db.add(UserProfile(user_id="perso", display_name="Papa",
                       email="papa@example.com"))
    await db.commit()
    db.expire_all()
    prof = (await db.execute(
        select(UserProfile).where(UserProfile.user_id == "perso"))).scalar_one()
    assert prof.email == "papa@example.com"
    brut = (await db.execute(
        text("SELECT email FROM user_profiles WHERE user_id='perso'"))).one()
    assert "papa@example.com" not in brut[0]


@pytest.mark.asyncio
async def test_loyalty_numero_chiffre(db):
    from models.orm import LoyaltyCard
    db.add(LoyaltyCard(id="l1", user_id="perso", enseigne="Carrefour",
                       numero="9876543210123", note="carte de Marina"))
    await db.commit()
    db.expire_all()
    brut = (await db.execute(
        text("SELECT enseigne, numero FROM loyalty_cards WHERE id='l1'"))).one()
    assert brut[0] == "Carrefour"              # enseigne EN CLAIR (triée)
    assert "9876543210123" not in brut[1]      # numero chiffré
    assert crypto.dechiffrer(brut[1]) == "9876543210123"


@pytest.mark.asyncio
async def test_activity_log_details_json_chiffre(db):
    from models.orm import EventActivityLog
    db.add(EventActivityLog(id="a1", event_id="zz", user_id="perso",
                            user_nom="Papa", action="update",
                            details={"champ": "titre", "avant": "A", "apres": "B"}))
    await db.commit()
    db.expire_all()
    log = (await db.execute(
        select(EventActivityLog).where(EventActivityLog.id == "a1"))).scalar_one()
    assert log.details == {"champ": "titre", "avant": "A", "apres": "B"}
    assert log.user_nom == "Papa"
    brut = (await db.execute(
        text("SELECT user_nom, details FROM event_activity_log WHERE id='a1'"))).one()
    assert brut[0] != "Papa"
    assert "titre" not in brut[1]
```

- [ ] **Step 2: Lancer — échoue**

Run: `cd briques/agenda/backend && python -m pytest tests/test_chiffrement_champs.py -q`
Expected: FAIL (emails/numero/details encore en clair)

- [ ] **Step 3: Adopter les décorateurs sur les colonnes restantes**

Dans `models/orm.py`, appliquer :

`CalendarInvitation.email` (L93) :
```python
    email: Mapped[str | None] = mapped_column(Chiffre, nullable=True)
```

`UserProfile.email` (L237) :
```python
    email: Mapped[str | None] = mapped_column(Chiffre, nullable=True)
```

`EventActivityLog.user_nom` (L260) et `details` (L262) :
```python
    user_nom: Mapped[str] = mapped_column(Chiffre, nullable=False)
```
```python
    details: Mapped[dict | None] = mapped_column(ChiffreJSON, nullable=True)
```

`ShoppingList.name` (L274) :
```python
    name: Mapped[str] = mapped_column(Chiffre, nullable=False)
```

`ShoppingListInvitation.email` (L304) :
```python
    email: Mapped[str | None] = mapped_column(Chiffre, nullable=True)
```

`ShoppingItem.name` (L319) et `note` (L322) :
```python
    name: Mapped[str] = mapped_column(Chiffre, nullable=False)
```
```python
    note: Mapped[str | None] = mapped_column(Chiffre, nullable=True)
```

`LoyaltyCard.numero` (L357) et `note` (L361) — **laisser `enseigne` en `String`** :
```python
    numero: Mapped[str] = mapped_column(Chiffre, nullable=False)
```
```python
    note: Mapped[str | None] = mapped_column(Chiffre, nullable=True)
```

`AvailabilityPoll.title` (L377), `description` (L378), `location` (L379) :
```python
    title: Mapped[str] = mapped_column(Chiffre, nullable=False)
    description: Mapped[str | None] = mapped_column(Chiffre, nullable=True)
    location: Mapped[str | None] = mapped_column(Chiffre, nullable=True)
```

`PollVote.voter_name` (L426) :
```python
    voter_name: Mapped[str] = mapped_column(Chiffre, nullable=False)
```

- [ ] **Step 4: Lancer — passe**

Run: `cd briques/agenda/backend && python -m pytest tests/test_chiffrement_champs.py -q`
Expected: PASS

- [ ] **Step 5: Non-régression ciblée**

Run: `cd briques/agenda/backend && python -m pytest tests/test_loyalty.py tests/test_profils.py tests/test_invitations.py tests/test_polls.py tests/test_polls_vote.py tests/test_shopping_items.py tests/test_shopping_lists.py tests/test_journal.py -q`
Expected: PASS (inchangés)

- [ ] **Step 6: Commit**

```bash
git add briques/agenda/backend/models/orm.py briques/agenda/backend/tests/test_chiffrement_champs.py
git commit -m "feat(s180): chiffre emails, carte fidélité, sondages, journal, listes"
```

---

## Task 6: Router `vault.py` vers la primitive partagée de `crypto.py`

**Files:**
- Modify: `vault.py:26-44`
- Test: `tests/test_vault.py` (inchangé — doit rester vert)

**Interfaces:**
- Consumes: `crypto.encrypt_raw`, `crypto.decrypt_raw` (Task 1)

But : partager exactement le code de chiffrement, **sans changer le format stocké** du coffre (`nonce || ct`, clé `SHA-256(VAULT_SECRET)`) — les tokens OAuth déjà en base restent lisibles.

- [ ] **Step 1: Vérifier l'état vert de départ**

Run: `cd briques/agenda/backend && python -m pytest tests/test_vault.py -q`
Expected: PASS (avant modification)

- [ ] **Step 2: Rediriger `encrypt`/`decrypt` vers `crypto`**

Dans `vault.py`, remplacer le corps de `encrypt` et `decrypt` (L34-44) en gardant `_key()` (L26-31) tel quel :

```python
def encrypt(plaintext: str) -> bytes:
    return crypto.encrypt_raw(_key(), plaintext.encode())


def decrypt(data: bytes) -> str:
    return crypto.decrypt_raw(_key(), bytes(data)).decode()
```

Ajouter l'import en tête de `vault.py` (avec les autres imports) :

```python
import crypto
```

Et retirer les imports désormais inutiles dans `vault.py` s'ils ne servent plus ailleurs dans le fichier (`os`, `AESGCM`) — vérifier : `hashlib` reste utilisé par `_key()`.

- [ ] **Step 3: Lancer — le coffre reste vert (format inchangé)**

Run: `cd briques/agenda/backend && python -m pytest tests/test_vault.py -q`
Expected: PASS (round-trip identique, format `nonce||ct` inchangé)

- [ ] **Step 4: Commit**

```bash
git add briques/agenda/backend/vault.py
git commit -m "refactor(s180): vault.py réutilise la primitive AES-GCM de crypto.py"
```

---

## Task 7: Migration Alembic `0012` — chiffrer les lignes existantes

**Files:**
- Create: `alembic/versions/0012_chiffrement_champs.py`
- Test: `tests/test_migration_0012.py`

**Interfaces:**
- Consumes: `crypto.chiffrer`, `crypto.dechiffrer` (Task 1)
- Produces: `_chiffrer_donnees(conn)`, `_dechiffrer_donnees(conn)` (helpers testables, sans `op.*`)

- [ ] **Step 1: Écrire le test des helpers de données (SQLite)**

Créer `tests/test_migration_0012.py` :

```python
"""S180 — aller-retour des helpers de données de la migration 0012 (SQLite).

Les colonnes naissent déjà au type chiffré (create_all) ; on y insère du CLAIR en
SQL brut (simulation des lignes pré-migration), puis on vérifie que _chiffrer_donnees
les rend illisibles en base et lisibles via l'ORM, et que _dechiffrer_donnees restaure.
"""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine, AsyncSession

import crypto
import importlib.util
from pathlib import Path
from models.orm import Base, Event, Calendar

# Charger la migration par CHEMIN : son nom commence par un chiffre (non importable)
# et « alembic » entrerait en collision avec la lib installée.
_spec = importlib.util.spec_from_file_location(
    "migration_0012",
    Path(__file__).resolve().parents[1] / "alembic" / "versions"
    / "0012_chiffrement_champs.py")
migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migration)


@pytest.mark.asyncio
async def test_chiffrer_puis_dechiffrer_donnees():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # ligne PRÉ-migration : titre en CLAIR inséré en SQL brut
        await conn.execute(text(
            "INSERT INTO calendars (id, user_id, name, color, is_default) "
            "VALUES ('c1','perso','Fam','#000',0)"))
        await conn.execute(text(
            "INSERT INTO events (id, calendar_id, title, start_at, end_at, "
            "created_by, source, exdates, rappels, all_day) VALUES "
            "('e1','c1','Coloscopie', :s, :e, 'perso','manuel','[]','[]',0)"),
            {"s": dt.datetime(2026, 8, 1, 9), "e": dt.datetime(2026, 8, 1, 10)})

    async with engine.begin() as conn:
        await conn.run_sync(migration._chiffrer_donnees)
        brut = (await conn.execute(
            text("SELECT title FROM events WHERE id='e1'"))).one()
        assert "Coloscopie" not in brut[0]                 # chiffré en base
        assert crypto.dechiffrer(brut[0]) == "Coloscopie"

    # lecture ORM après chiffrement : transparente
    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as s:
        ev = (await s.execute(select(Event).where(Event.id == "e1"))).scalar_one()
        assert ev.title == "Coloscopie"

    async with engine.begin() as conn:
        await conn.run_sync(migration._dechiffrer_donnees)
        brut = (await conn.execute(
            text("SELECT title FROM events WHERE id='e1'"))).one()
        assert brut[0] == "Coloscopie"                     # clair restauré
    await engine.dispose()
```

- [ ] **Step 2: Lancer — échoue**

Run: `cd briques/agenda/backend && python -m pytest tests/test_migration_0012.py -q`
Expected: FAIL (`ModuleNotFoundError: alembic.versions.0012_chiffrement_champs`)

- [ ] **Step 3: Écrire la migration `0012`**

Créer `alembic/versions/0012_chiffrement_champs.py` :

```python
"""0012 — S180 : chiffrement au repos des champs sensibles.

upgrade() : élargit les colonnes String→Text (le base64 dépasse les longueurs),
JSON→Text (details) et Float→Text (lat/lon), puis chiffre les lignes existantes.
downgrade() : déchiffre puis restaure les types. Cible = Postgres (dev = create_all).
Exige une clé de chiffrement configurée (AGENDA_ENCRYPTION_KEY ou VAULT_SECRET).

Create Date: 2026-07-17
"""
import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

# Colonnes texte chiffrées : table -> (pk, colonnes)
_TEXTE = {
    "events": ("id", ["title", "description", "location"]),
    "event_comments": ("id", ["content"]),
    "user_profiles": ("user_id", ["email"]),
    "calendar_invitations": ("id", ["email"]),
    "shopping_list_invitations": ("id", ["email"]),
    "loyalty_cards": ("id", ["numero", "note"]),
    "availability_polls": ("id", ["title", "description", "location"]),
    "poll_votes": ("id", ["voter_name"]),
    "event_activity_log": ("id", ["user_nom", "details"]),  # details = JSON→Text, texte après alter
    "shopping_items": ("id", ["name", "note"]),
    "shopping_lists": ("id", ["name"]),
}
# Colonnes String(n) à élargir en Text (varchar→text, cast implicite Postgres)
_A_ELARGIR = [
    ("events", "title"), ("events", "location"),
    ("user_profiles", "email"), ("calendar_invitations", "email"),
    ("shopping_list_invitations", "email"),
    ("loyalty_cards", "numero"), ("loyalty_cards", "note"),
    ("availability_polls", "title"), ("availability_polls", "location"),
    ("poll_votes", "voter_name"), ("event_activity_log", "user_nom"),
    ("shopping_items", "name"), ("shopping_items", "note"),
    ("shopping_lists", "name"),
]


def _transformer(conn, fn):
    """Applique fn (chiffrer/déchiffrer) à toutes les colonnes texte, ligne par ligne."""
    for table, (pk, cols) in _TEXTE.items():
        rows = conn.execute(
            sa.text(f"SELECT {pk}, {', '.join(cols)} FROM {table}")).mappings().all()
        for row in rows:
            sets, params = [], {"pk": row[pk]}
            for c in cols:
                if row[c] is None:
                    continue
                sets.append(f"{c} = :{c}")
                params[c] = fn(row[c] if isinstance(row[c], str) else str(row[c]))
            if sets:
                conn.execute(
                    sa.text(f"UPDATE {table} SET {', '.join(sets)} WHERE {pk} = :pk"),
                    params)


def _chiffrer_donnees(conn):
    import crypto
    _transformer(conn, crypto.chiffrer)


def _dechiffrer_donnees(conn):
    import crypto
    _transformer(conn, crypto.dechiffrer)


def upgrade() -> None:
    conn = op.get_bind()
    is_pg = conn.dialect.name == "postgresql"

    if is_pg:
        for table, col in _A_ELARGIR:
            op.alter_column(table, col, type_=sa.Text())
        op.alter_column("event_activity_log", "details", type_=sa.Text(),
                        postgresql_using="details::text")
        # live_positions : éphémère (TTL court) → on purge pour éviter le cast Float→Text
        op.execute("DELETE FROM live_positions")
        op.alter_column("live_positions", "latitude", type_=sa.Text(),
                        postgresql_using="latitude::text")
        op.alter_column("live_positions", "longitude", type_=sa.Text(),
                        postgresql_using="longitude::text")

    _chiffrer_donnees(conn)


def downgrade() -> None:
    conn = op.get_bind()
    is_pg = conn.dialect.name == "postgresql"

    _dechiffrer_donnees(conn)

    if is_pg:
        op.alter_column("event_activity_log", "details", type_=sa.JSON(),
                        postgresql_using="details::json")
        for table, col in _A_ELARGIR:
            op.alter_column(table, col, type_=sa.String(length=500))
        op.execute("DELETE FROM live_positions")
        op.alter_column("live_positions", "latitude", type_=sa.Float(),
                        postgresql_using="latitude::double precision")
        op.alter_column("live_positions", "longitude", type_=sa.Float(),
                        postgresql_using="longitude::double precision")
```

Note : `latitude`/`longitude` ne sont **pas** dans `_TEXTE` (leurs lignes sont purgées, pas chiffrées ligne à ligne). Les helpers `_chiffrer_donnees`/`_dechiffrer_donnees` ne touchent donc que les colonnes texte — ce que le test exerce en SQLite.

- [ ] **Step 4: Lancer — passe**

Run: `cd briques/agenda/backend && python -m pytest tests/test_migration_0012.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add briques/agenda/backend/alembic/versions/0012_chiffrement_champs.py briques/agenda/backend/tests/test_migration_0012.py
git commit -m "feat(s180): migration 0012 — chiffre les lignes existantes (upgrade/downgrade)"
```

---

## Task 8: Non-régression complète, README, notes de sprint

**Files:**
- Modify: `README.md`
- Test: toute la suite agenda

- [ ] **Step 1: Lancer TOUTE la suite agenda (preuve de transparence)**

Run: `cd briques/agenda/backend && python -m pytest tests/ -q`
Expected: PASS — toutes les suites existantes (~325) vertes **sans modification** + les nouveaux tests crypto/champs/migration. Si une suite existante échoue, c'est une fuite de transparence : investiguer le service concerné (il manipulait sans doute la valeur brute).

- [ ] **Step 2: Vérifier la non-régression du Cœur (proactif lit les events)**

Run: `cd /Users/garinat_t/Desktop/Workplace/.claude/worktrees/s171-login-keycloak-coeur && make test-core -q 2>/dev/null || (cd core && python -m pytest tests/ -q)`
Expected: PASS (le proactif lit `Event.title`/`start_at` via l'API agenda, décryptage transparent côté brique).

- [ ] **Step 3: Documenter dans le README de la brique**

Ajouter à `briques/agenda/backend/README.md` une section :

```markdown
## S180 — Chiffrement au repos

Le contenu humain sensible est chiffré au repos (AES-GCM) de façon transparente via
les `TypeDecorator` de `crypto.py` : titres/descriptions/lieux d'événements, contenu
des commentaires, positions de présence (lat/lon), emails (profils + invitations),
numéro/note de carte de fidélité, sondages (titre/desc/lieu + voter_name), journal
d'activité (user_nom + details), items et noms de listes.

**Non chiffré** (interrogé/trié/capacité) : dates, clés de jointure, jetons
(`ics_token`/`share_token`/tokens d'invitation), `external_id`, `Label.name`,
`LoyaltyCard.enseigne`, couleurs/emoji/enums.

**Clé** : `AGENDA_ENCRYPTION_KEY` (dédiée) ; à défaut, sous-clé HKDF dérivée de
`VAULT_SECRET` (distincte de la clé du coffre OAuth). Sans aucune des deux, toute
écriture chiffrée lève (fail-closed).

**Déploiement (RESTE, LIVE différé)** :
- Poser `AGENDA_ENCRYPTION_KEY` en prod (ou s'appuyer sur `VAULT_SECRET` déjà présent).
- Smoke **obligatoire** avant bascule : `alembic upgrade 0012` puis `alembic downgrade 0011`
  sur une copie **Postgres** des données (les tests utilisent `create_all`, pas la migration ;
  la migration exige qu'une clé soit configurée au moment de l'`upgrade`).
- Défense en profondeur (hors code) : volume de la base sur disque chiffré — à ajouter
  au runbook `MIGRATION-HP.md`.

**Fast-follow** : rotation de clé réelle (l'enveloppe versionnée v1 la prépare) ;
chiffrer aussi les **pièces jointes** fichiers (`EventAttachment` dans `ATTACHMENTS_DIR`,
non couvert par le chiffrement de colonnes) ; géocoder `Event.location` au write avant
chiffrement.
```

- [ ] **Step 4: Commit**

```bash
git add briques/agenda/backend/README.md
git commit -m "docs(s180): README — chiffrement au repos + RESTE déploiement"
```

- [ ] **Step 5: Marquer le sprint dans le roadmap doc**

Dans `docs/sprints/S174-S180-roadmap-agenda-best-in-class.md`, section « S180 », remplacer le titre par `## S180 — Chiffrement au repos (durcissement sécurité) — ✅ CODE-COMPLET 2026-07-17 (LIVE différé)` et ajouter une puce de statut résumant le livré (crypto.py, périmètre, migration 0012, RESTE smoke Postgres). Commit :

```bash
git add docs/sprints/S174-S180-roadmap-agenda-best-in-class.md
git commit -m "docs(s180): roadmap agenda — S180 code-complet (LIVE différé)"
```

---

## Self-Review (effectuée)

- **Couverture spec** : §1 mécanisme → T1/T2 ; §2 champs → T3/T4/T5 (tableau complet couvert) ; §3 clé → T1 (`field_key`, fail-closed, HKDF) ; §4 migration 0012 → T7 ; §5 tests → T1/T2/T3/T4/T5/T7/T8 ; §6 défense en profondeur (infra) → README T8 (RESTE) ; §7 fast-follow → README T8. Refactor partage vault → T6.
- **Placeholders** : aucun — chaque step porte le code réel.
- **Cohérence des types** : `Chiffre`/`ChiffreFloat`/`ChiffreJSON` définis en T2, importés en T3-T5 ; `encrypt_raw`/`decrypt_raw`/`chiffrer`/`dechiffrer`/`field_key` définis en T1, consommés en T2/T6/T7 ; `_chiffrer_donnees`/`_dechiffrer_donnees` définis en T7, testés en T7. Noms alignés.
- **Point de vigilance déploiement** : la migration 0012 cible Postgres (les `alter_column` sont gardés par `dialect.name == "postgresql"`) ; en SQLite (tests) seuls les helpers de données sont exercés — cohérent avec la convention repo (migrations 0006-0011 non testées en SQLite, smoke Postgres manuel).
```

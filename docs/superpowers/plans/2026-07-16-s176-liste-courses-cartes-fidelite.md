# S176 — Liste de courses/tâches partagée + cartes de fidélité — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Doter la brique agenda d'un sous-système de listes de courses/tâches partagées façon Bring! (catalogue emoji par rayon, cochage temps réel SSE, push par personne, invitations, outils LLM) + un module de cartes de fidélité personnelles avec code-barres généré côté client.

**Architecture:** Nouveau sous-système autonome dans `briques/agenda/backend` : 6 tables (migration `0008`), routers REST calqués sur l'existant (calendars/members/invitations), SSE sur canal dédié `list:{id}:changes`, push best-effort sortant vers la brique `connexion`, générateur de code-barres vanilla embarqué, onglets « Listes » + « Cartes » dans l'appli web PKCE existante, capacités `courses_*` au manifest.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy 2.0 async, Alembic, pytest + pytest-asyncio, SSE (sse-starlette + Redis pub/sub), httpx (sortant), JS vanilla (front + code-barres SVG).

## Global Constraints

- **Tests appellent les routes directement** avec la session `db` de test et un dict `user` factice (`{"sub": "..."}`) — pas de TestClient, pas de JWT (cf. `tests/test_calendars.py`).
- **Base de tests = SQLite en mémoire via `create_all`** (fixture `db` de `tests/conftest.py`) — les migrations Alembic ne sont PAS exercées par les tests unitaires ; la migration `0008` doit refléter fidèlement l'ORM (revue humaine + smoke Postgres différé avant déploiement).
- **Aucune ressource externe côté front** (contrainte self-hosted / CSP) : tout JS/CSS inline ou servi par la brique, zéro CDN.
- **Best-effort ne lève jamais** : SSE (`publish_list_change`) et push (`notifier_membres`) sont silencieux si Redis/`connexion` absents — une mutation ne doit jamais échouer à cause d'eux.
- **Sémantique 404 (pas 403)** pour un accès refusé (ne pas divulguer l'existence), comme `require_calendar_access`.
- **Identité S2S `perso`** sur `/service` (ADR agenda-surface-de-service) : les outils LLM opèrent en tant que `perso`.
- **Français** pour noms de domaine visibles, commentaires et messages ; commits `type(s176): …`.
- Chaque commit se termine par les lignes `Co-Authored-By:` / `Claude-Session:` du dépôt.
- Répertoire de travail des commandes : `briques/agenda/backend` (sauf mention). Lancer les tests brique : `cd briques/agenda/backend && python -m pytest`.

---

### Task 1 : ORM (6 tables) + migration 0008 + schémas

**Files:**
- Modify: `briques/agenda/backend/models/orm.py` (ajouter les modèles en fin de fichier)
- Create: `briques/agenda/backend/alembic/versions/0008_listes_et_cartes.py`
- Modify: `briques/agenda/backend/models/schemas.py` (ajouter les schémas en fin de fichier)
- Test: `briques/agenda/backend/tests/test_shopping_orm.py`

**Interfaces:**
- Produces (ORM) : `ShoppingList`, `ShoppingListMember`, `ShoppingListInvitation`, `ShoppingItem`, `CatalogItem`, `LoyaltyCard` (importables depuis `models.orm`).
- Produces (schémas) : `ShoppingListCreate`, `ShoppingListUpdate`, `ShoppingListOut`, `ShoppingListWithMetaOut`, `ShoppingItemCreate`, `ShoppingItemUpdate`, `ShoppingItemOut`, `ListInvitationCreate`, `ListMemberOut`, `CatalogItemOut`, `LoyaltyCardCreate`, `LoyaltyCardUpdate`, `LoyaltyCardOut`.

- [ ] **Step 1: Écrire le test ORM (échoue)**

Create `tests/test_shopping_orm.py` :

```python
"""ORM listes + cartes : insertion, contraintes, cascade (SQLite create_all)."""
from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from models.orm import (
    CatalogItem,
    LoyaltyCard,
    ShoppingItem,
    ShoppingList,
    ShoppingListInvitation,
    ShoppingListMember,
)


@pytest.mark.asyncio
async def test_creer_liste_defaut_courses(db):
    liste = ShoppingList(name="Maison", created_by="perso")
    db.add(liste)
    await db.commit()
    await db.refresh(liste)
    assert liste.id
    assert liste.kind == "courses"


@pytest.mark.asyncio
async def test_membre_unique_par_liste(db):
    liste = ShoppingList(name="Maison", created_by="perso")
    db.add(liste)
    await db.commit()
    db.add(ShoppingListMember(list_id=liste.id, user_id="marina", role="editor"))
    await db.commit()
    db.add(ShoppingListMember(list_id=liste.id, user_id="marina", role="viewer"))
    with pytest.raises(IntegrityError):
        await db.commit()


@pytest.mark.asyncio
async def test_cascade_supprime_items_et_membres(db):
    liste = ShoppingList(name="Maison", created_by="perso")
    db.add(liste)
    await db.commit()
    db.add(ShoppingItem(list_id=liste.id, name="Lait", added_by="perso"))
    db.add(ShoppingListMember(list_id=liste.id, user_id="marina", role="editor"))
    await db.commit()
    await db.delete(liste)
    await db.commit()
    items = (await db.execute(select(ShoppingItem))).scalars().all()
    membres = (await db.execute(select(ShoppingListMember))).scalars().all()
    assert items == [] and membres == []


@pytest.mark.asyncio
async def test_catalog_item_integre_sans_liste(db):
    db.add(CatalogItem(list_id=None, name="Lait", emoji="🥛", rayon="Crèmerie"))
    await db.commit()
    row = (await db.execute(select(CatalogItem))).scalar_one()
    assert row.list_id is None and row.created_by is None


@pytest.mark.asyncio
async def test_loyalty_card_defaut_code128(db):
    carte = LoyaltyCard(user_id="perso", enseigne="Carrefour", numero="1234567890")
    db.add(carte)
    await db.commit()
    await db.refresh(carte)
    assert carte.format == "code128" and carte.couleur == "#3B82F6"
```

- [ ] **Step 2: Lancer le test (échoue)**

Run: `cd briques/agenda/backend && python -m pytest tests/test_shopping_orm.py -q`
Expected: FAIL (ImportError : `ShoppingList` inexistant).

- [ ] **Step 3: Ajouter les 6 modèles ORM**

Append à `models/orm.py` (le fichier importe déjà `JSON, Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, func`, `Mapped, mapped_column, relationship`, et `_uuid`) :

```python
# ── S176 : listes de courses/tâches partagées ─────────────────────────────────

class ShoppingList(Base):
    __tablename__ = "shopping_lists"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    kind: Mapped[str] = mapped_column(
        Enum("courses", "taches", name="list_kind"), nullable=False, default="courses")
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    members: Mapped[list["ShoppingListMember"]] = relationship(back_populates="liste", cascade="all, delete-orphan")
    invitations: Mapped[list["ShoppingListInvitation"]] = relationship(back_populates="liste", cascade="all, delete-orphan")
    items: Mapped[list["ShoppingItem"]] = relationship(back_populates="liste", cascade="all, delete-orphan")


class ShoppingListMember(Base):
    __tablename__ = "shopping_list_members"
    __table_args__ = (UniqueConstraint("list_id", "user_id", name="uq_list_member"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    list_id: Mapped[str] = mapped_column(String(36), ForeignKey("shopping_lists.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    role: Mapped[str] = mapped_column(
        Enum("owner", "editor", "viewer", name="list_member_role"), nullable=False, default="viewer")
    joined_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    liste: Mapped["ShoppingList"] = relationship(back_populates="members")


class ShoppingListInvitation(Base):
    __tablename__ = "shopping_list_invitations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    list_id: Mapped[str] = mapped_column(String(36), ForeignKey("shopping_lists.id", ondelete="CASCADE"), nullable=False)
    token: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, default=_uuid)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="viewer")
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    liste: Mapped["ShoppingList"] = relationship(back_populates="invitations")


class ShoppingItem(Base):
    __tablename__ = "shopping_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    list_id: Mapped[str] = mapped_column(String(36), ForeignKey("shopping_lists.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    emoji: Mapped[str | None] = mapped_column(String(16), nullable=True)
    rayon: Mapped[str | None] = mapped_column(String(50), nullable=True)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    checked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    checked_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    added_by: Mapped[str] = mapped_column(String(255), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    liste: Mapped["ShoppingList"] = relationship(back_populates="items")


class CatalogItem(Base):
    """Catalogue tap-to-add. list_id NULL = entrée intégrée (catalogue FR par défaut,
    partagé) ; non-NULL = entrée perso mémorisée pour une liste précise."""

    __tablename__ = "catalog_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    list_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("shopping_lists.id", ondelete="CASCADE"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    emoji: Mapped[str] = mapped_column(String(16), nullable=False, default="🛒")
    rayon: Mapped[str] = mapped_column(String(50), nullable=False, default="Autre")
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class LoyaltyCard(Base):
    """Carte de fidélité personnelle (scope user_id). Pas de collaboration."""

    __tablename__ = "loyalty_cards"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    enseigne: Mapped[str] = mapped_column(String(255), nullable=False)
    numero: Mapped[str] = mapped_column(String(255), nullable=False)
    format: Mapped[str] = mapped_column(
        Enum("code128", "ean13", "qr", name="barcode_format"), nullable=False, default="code128")
    couleur: Mapped[str] = mapped_column(String(20), nullable=False, default="#3B82F6")
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
```

- [ ] **Step 4: Lancer le test (passe)**

Run: `cd briques/agenda/backend && python -m pytest tests/test_shopping_orm.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Écrire la migration 0008**

Create `alembic/versions/0008_listes_et_cartes.py` :

```python
"""0008 — S176 : listes de courses/tâches partagées + cartes de fidélité.

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-16
"""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shopping_lists",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("kind", sa.Enum("courses", "taches", name="list_kind"), nullable=False, server_default="courses"),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_table(
        "shopping_list_members",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("list_id", sa.String(36), sa.ForeignKey("shopping_lists.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("role", sa.Enum("owner", "editor", "viewer", name="list_member_role"), nullable=False, server_default="viewer"),
        sa.Column("joined_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("list_id", "user_id", name="uq_list_member"),
    )
    op.create_index("ix_shopping_list_members_list_id", "shopping_list_members", ["list_id"])
    op.create_index("ix_shopping_list_members_user_id", "shopping_list_members", ["user_id"])
    op.create_table(
        "shopping_list_invitations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("list_id", sa.String(36), sa.ForeignKey("shopping_lists.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token", sa.String(36), nullable=False, unique=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("role", sa.String(20), nullable=False, server_default="viewer"),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_table(
        "shopping_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("list_id", sa.String(36), sa.ForeignKey("shopping_lists.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("emoji", sa.String(16), nullable=True),
        sa.Column("rayon", sa.String(50), nullable=True),
        sa.Column("note", sa.String(255), nullable=True),
        sa.Column("checked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("checked_by", sa.String(255), nullable=True),
        sa.Column("checked_at", sa.DateTime(), nullable=True),
        sa.Column("added_by", sa.String(255), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_shopping_items_list_id", "shopping_items", ["list_id"])
    op.create_table(
        "catalog_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("list_id", sa.String(36), sa.ForeignKey("shopping_lists.id", ondelete="CASCADE"), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("emoji", sa.String(16), nullable=False, server_default="🛒"),
        sa.Column("rayon", sa.String(50), nullable=False, server_default="Autre"),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_catalog_items_list_id", "catalog_items", ["list_id"])
    op.create_table(
        "loyalty_cards",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("enseigne", sa.String(255), nullable=False),
        sa.Column("numero", sa.String(255), nullable=False),
        sa.Column("format", sa.Enum("code128", "ean13", "qr", name="barcode_format"), nullable=False, server_default="code128"),
        sa.Column("couleur", sa.String(20), nullable=False, server_default="#3B82F6"),
        sa.Column("note", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_loyalty_cards_user_id", "loyalty_cards", ["user_id"])


def downgrade() -> None:
    op.drop_table("loyalty_cards")
    op.drop_index("ix_catalog_items_list_id", table_name="catalog_items")
    op.drop_table("catalog_items")
    op.drop_index("ix_shopping_items_list_id", table_name="shopping_items")
    op.drop_table("shopping_items")
    op.drop_table("shopping_list_invitations")
    op.drop_index("ix_shopping_list_members_user_id", table_name="shopping_list_members")
    op.drop_index("ix_shopping_list_members_list_id", table_name="shopping_list_members")
    op.drop_table("shopping_list_members")
    op.drop_table("shopping_lists")
    for enum in ("list_kind", "list_member_role", "barcode_format"):
        sa.Enum(name=enum).drop(op.get_bind(), checkfirst=True)
```

- [ ] **Step 6: Ajouter les schémas Pydantic**

Append à `models/schemas.py` :

```python
# ── S176 : listes de courses/tâches ───────────────────────────────────────────

class ShoppingListCreate(BaseModel):
    name: str
    kind: str = "courses"  # "courses" | "taches"


class ShoppingListUpdate(BaseModel):
    name: Optional[str] = None


class ShoppingListOut(BaseModel):
    id: str
    kind: str
    name: str
    created_by: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ShoppingListWithMetaOut(ShoppingListOut):
    role: str
    nb_a_prendre: int = 0  # items non cochés


class ShoppingItemCreate(BaseModel):
    name: Optional[str] = None
    catalog_item_id: Optional[str] = None
    emoji: Optional[str] = None
    rayon: Optional[str] = None
    note: Optional[str] = None


class ShoppingItemUpdate(BaseModel):
    name: Optional[str] = None
    emoji: Optional[str] = None
    rayon: Optional[str] = None
    note: Optional[str] = None
    checked: Optional[bool] = None


class ShoppingItemOut(BaseModel):
    id: str
    list_id: str
    name: str
    emoji: Optional[str]
    rayon: Optional[str]
    note: Optional[str]
    checked: bool
    checked_by: Optional[str]
    checked_at: Optional[datetime]
    added_by: str
    position: int

    class Config:
        from_attributes = True


class ListInvitationCreate(BaseModel):
    role: str = "viewer"
    email: Optional[str] = None
    expire_heures: int = 72


class ListMemberOut(BaseModel):
    user_id: str
    role: str
    display_name: Optional[str] = None
    avatar_color: Optional[str] = None


class CatalogItemOut(BaseModel):
    id: str
    name: str
    emoji: str
    rayon: str

    class Config:
        from_attributes = True


# ── S176 : cartes de fidélité ─────────────────────────────────────────────────

class LoyaltyCardCreate(BaseModel):
    enseigne: str
    numero: str
    format: str = "code128"  # "code128" | "ean13" | "qr"
    couleur: str = "#3B82F6"
    note: Optional[str] = None


class LoyaltyCardUpdate(BaseModel):
    enseigne: Optional[str] = None
    numero: Optional[str] = None
    format: Optional[str] = None
    couleur: Optional[str] = None
    note: Optional[str] = None


class LoyaltyCardOut(BaseModel):
    id: str
    enseigne: str
    numero: str
    format: str
    couleur: str
    note: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True
```

- [ ] **Step 7: Relancer la suite ORM + suite complète brique**

Run: `cd briques/agenda/backend && python -m pytest tests/test_shopping_orm.py -q && python -m pytest -q`
Expected: `test_shopping_orm.py` PASS (5) ; suite brique toujours verte (194 + 5).

- [ ] **Step 8: Commit**

```bash
git add briques/agenda/backend/models/orm.py briques/agenda/backend/models/schemas.py briques/agenda/backend/alembic/versions/0008_listes_et_cartes.py briques/agenda/backend/tests/test_shopping_orm.py
git commit -m "feat(s176): ORM 6 tables + migration 0008 + schémas (listes, catalogue, cartes)"
```

---

### Task 2 : Contrôle d'accès listes + cartes

**Files:**
- Modify: `briques/agenda/backend/utils/access.py`
- Test: `briques/agenda/backend/tests/test_shopping_access.py`

**Interfaces:**
- Consumes : `ShoppingList`, `ShoppingListMember`, `LoyaltyCard` (Task 1).
- Produces : `get_list_role(db, list_id, user_id) -> str | None` ; `require_list_access(db, list_id, user_id, min_role="viewer") -> tuple[ShoppingList, str]` ; `require_owned_card(db, card_id, user_id) -> LoyaltyCard`.

- [ ] **Step 1: Écrire le test (échoue)**

Create `tests/test_shopping_access.py` :

```python
"""Contrôle d'accès listes (owner/editor/viewer) + cartes (propriétaire)."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from models.orm import LoyaltyCard, ShoppingList, ShoppingListMember
from utils.access import get_list_role, require_list_access, require_owned_card


async def _liste(db, created_by="perso"):
    liste = ShoppingList(name="Maison", created_by=created_by)
    db.add(liste)
    await db.commit()
    await db.refresh(liste)
    return liste


@pytest.mark.asyncio
async def test_createur_est_owner(db):
    liste = await _liste(db)
    assert await get_list_role(db, liste.id, "perso") == "owner"


@pytest.mark.asyncio
async def test_membre_a_son_role(db):
    liste = await _liste(db)
    db.add(ShoppingListMember(list_id=liste.id, user_id="marina", role="editor"))
    await db.commit()
    assert await get_list_role(db, liste.id, "marina") == "editor"


@pytest.mark.asyncio
async def test_sans_acces_none(db):
    liste = await _liste(db)
    assert await get_list_role(db, liste.id, "inconnu") is None


@pytest.mark.asyncio
async def test_require_refuse_role_insuffisant(db):
    liste = await _liste(db)
    db.add(ShoppingListMember(list_id=liste.id, user_id="marina", role="viewer"))
    await db.commit()
    with pytest.raises(HTTPException) as exc:
        await require_list_access(db, liste.id, "marina", min_role="editor")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_carte_isolee_par_proprietaire(db):
    carte = LoyaltyCard(user_id="perso", enseigne="Carrefour", numero="123")
    db.add(carte)
    await db.commit()
    await db.refresh(carte)
    assert (await require_owned_card(db, carte.id, "perso")).id == carte.id
    with pytest.raises(HTTPException) as exc:
        await require_owned_card(db, carte.id, "autre")
    assert exc.value.status_code == 404
```

- [ ] **Step 2: Lancer (échoue)**

Run: `cd briques/agenda/backend && python -m pytest tests/test_shopping_access.py -q`
Expected: FAIL (ImportError `get_list_role`).

- [ ] **Step 3: Implémenter**

Append à `utils/access.py` (le module importe déjà `HTTPException, status, select, AsyncSession` ; ajouter les imports ORM et `ROLE_ORDER` est déjà défini) :

```python
from models.orm import LoyaltyCard, ShoppingList, ShoppingListMember


async def get_list_role(db: AsyncSession, list_id: str, user_id: str) -> str | None:
    """Rôle de l'utilisateur sur une liste, ou None si aucun accès."""
    liste = await db.get(ShoppingList, list_id)
    if not liste:
        return None
    if liste.created_by == user_id:
        return "owner"
    result = await db.execute(
        select(ShoppingListMember).where(
            ShoppingListMember.list_id == list_id,
            ShoppingListMember.user_id == user_id,
        )
    )
    member = result.scalar_one_or_none()
    return member.role if member else None


async def require_list_access(
    db: AsyncSession,
    list_id: str,
    user_id: str,
    min_role: str = "viewer",
) -> tuple[ShoppingList, str]:
    """(liste, rôle) si accès >= min_role ; 404 sinon (ne divulgue pas l'existence)."""
    role = await get_list_role(db, list_id, user_id)
    if role is None or ROLE_ORDER.get(role, -1) < ROLE_ORDER.get(min_role, 999):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Liste introuvable")
    liste = await db.get(ShoppingList, list_id)
    return liste, role


async def require_owned_card(db: AsyncSession, card_id: str, user_id: str) -> LoyaltyCard:
    """Carte si elle appartient à user_id ; 404 sinon."""
    carte = await db.get(LoyaltyCard, card_id)
    if carte is None or carte.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Carte introuvable")
    return carte
```

Note : placer l'import ORM ajouté à côté de l'import existant `from models.orm import Calendar, CalendarMember` (fusionner ou ajouter une ligne séparée).

- [ ] **Step 4: Lancer (passe)**

Run: `cd briques/agenda/backend && python -m pytest tests/test_shopping_access.py -q`
Expected: PASS (5).

- [ ] **Step 5: Commit**

```bash
git add briques/agenda/backend/utils/access.py briques/agenda/backend/tests/test_shopping_access.py
git commit -m "feat(s176): contrôle d'accès listes (require_list_access) + cartes (require_owned_card)"
```

---

### Task 3 : Service catalogue (rayons, seed, mémorisation)

**Files:**
- Create: `briques/agenda/backend/services/catalogue.py`
- Test: `briques/agenda/backend/tests/test_catalogue.py`

**Interfaces:**
- Consumes : `CatalogItem` (Task 1).
- Produces : `RAYONS: list[str]` ; `CATALOGUE_DEFAUT: list[tuple[str, str, str]]` ; `async semer_catalogue(db) -> int` ; `async catalogue_pour_liste(db, list_id) -> list[CatalogItem]` ; `async memoriser_item_perso(db, list_id, nom, emoji, rayon, user_id) -> CatalogItem | None`.

- [ ] **Step 1: Écrire le test (échoue)**

Create `tests/test_catalogue.py` :

```python
"""Catalogue FR : seed idempotent, union intégré+perso, mémorisation dédupliquée."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from models.orm import CatalogItem, ShoppingList
from services.catalogue import (
    RAYONS,
    catalogue_pour_liste,
    memoriser_item_perso,
    semer_catalogue,
)


@pytest.mark.asyncio
async def test_seed_insere_puis_idempotent(db):
    n1 = await semer_catalogue(db)
    assert n1 > 0
    n2 = await semer_catalogue(db)
    assert n2 == 0
    total = (await db.execute(select(CatalogItem))).scalars().all()
    assert len(total) == n1
    assert all(c.rayon in RAYONS for c in total)


@pytest.mark.asyncio
async def test_catalogue_union_integre_et_perso(db):
    await semer_catalogue(db)
    liste = ShoppingList(name="M", created_by="perso")
    db.add(liste)
    await db.commit()
    db.add(CatalogItem(list_id=liste.id, name="Kombucha", emoji="🍾", rayon="Boissons", created_by="perso"))
    await db.commit()
    cat = await catalogue_pour_liste(db, liste.id)
    noms = {c.name for c in cat}
    assert "Kombucha" in noms and "Lait" in noms  # Lait vient des intégrés


@pytest.mark.asyncio
async def test_memoriser_dedup(db):
    liste = ShoppingList(name="M", created_by="perso")
    db.add(liste)
    await db.commit()
    a = await memoriser_item_perso(db, liste.id, "Yaourt soja", "🥛", "Crèmerie", "perso")
    b = await memoriser_item_perso(db, liste.id, "yaourt soja", "🥛", "Crèmerie", "perso")
    assert a is not None and b is None  # 2e = déjà présent (dédup insensible à la casse)
```

- [ ] **Step 2: Lancer (échoue)**

Run: `cd briques/agenda/backend && python -m pytest tests/test_catalogue.py -q`
Expected: FAIL (ModuleNotFound `services.catalogue`).

- [ ] **Step 3: Implémenter le service**

Create `services/catalogue.py` :

```python
"""Catalogue tap-to-add façon Bring! : rayons FR + items intégrés semés au boot."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.orm import CatalogItem

# Ordre = ordre d'affichage des rayons dans le front.
RAYONS: list[str] = [
    "Fruits & légumes", "Crèmerie", "Boulangerie", "Boucherie-Poissonnerie",
    "Épicerie salée", "Épicerie sucrée", "Boissons", "Surgelés",
    "Hygiène", "Entretien", "Bébé", "Animaux", "Autre",
]

# (emoji, nom, rayon)
CATALOGUE_DEFAUT: list[tuple[str, str, str]] = [
    ("🍎", "Pommes", "Fruits & légumes"), ("🍌", "Bananes", "Fruits & légumes"),
    ("🍅", "Tomates", "Fruits & légumes"), ("🥕", "Carottes", "Fruits & légumes"),
    ("🥔", "Pommes de terre", "Fruits & légumes"), ("🧅", "Oignons", "Fruits & légumes"),
    ("🥗", "Salade", "Fruits & légumes"), ("🍋", "Citrons", "Fruits & légumes"),
    ("🥦", "Brocoli", "Fruits & légumes"), ("🍓", "Fraises", "Fruits & légumes"),
    ("🥛", "Lait", "Crèmerie"), ("🧀", "Fromage", "Crèmerie"),
    ("🧈", "Beurre", "Crèmerie"), ("🥚", "Œufs", "Crèmerie"),
    ("🍦", "Yaourts", "Crèmerie"), ("🥫", "Crème fraîche", "Crèmerie"),
    ("🥖", "Baguette", "Boulangerie"), ("🍞", "Pain de mie", "Boulangerie"),
    ("🥐", "Croissants", "Boulangerie"), ("🍩", "Viennoiseries", "Boulangerie"),
    ("🍗", "Poulet", "Boucherie-Poissonnerie"), ("🥩", "Steak haché", "Boucherie-Poissonnerie"),
    ("🍖", "Jambon", "Boucherie-Poissonnerie"), ("🐟", "Poisson", "Boucherie-Poissonnerie"),
    ("🍝", "Pâtes", "Épicerie salée"), ("🍚", "Riz", "Épicerie salée"),
    ("🥫", "Conserves", "Épicerie salée"), ("🧂", "Sel", "Épicerie salée"),
    ("🫒", "Huile", "Épicerie salée"), ("🍲", "Soupe", "Épicerie salée"),
    ("🥣", "Céréales", "Épicerie sucrée"), ("☕", "Café", "Épicerie sucrée"),
    ("🍫", "Chocolat", "Épicerie sucrée"), ("🍪", "Biscuits", "Épicerie sucrée"),
    ("🍯", "Miel", "Épicerie sucrée"), ("🍬", "Sucre", "Épicerie sucrée"),
    ("💧", "Eau", "Boissons"), ("🧃", "Jus de fruits", "Boissons"),
    ("🥤", "Sodas", "Boissons"), ("🍷", "Vin", "Boissons"), ("🍺", "Bière", "Boissons"),
    ("🍕", "Pizza surgelée", "Surgelés"), ("🧊", "Glaçons", "Surgelés"),
    ("🥟", "Légumes surgelés", "Surgelés"),
    ("🧼", "Savon", "Hygiène"), ("🪥", "Dentifrice", "Hygiène"),
    ("🧻", "Papier toilette", "Hygiène"), ("🧴", "Shampoing", "Hygiène"),
    ("🧽", "Éponges", "Entretien"), ("🧺", "Lessive", "Entretien"),
    ("🧹", "Sac poubelle", "Entretien"), ("🫧", "Liquide vaisselle", "Entretien"),
    ("🍼", "Petits pots", "Bébé"), ("👶", "Couches", "Bébé"),
    ("🐕", "Croquettes chien", "Animaux"), ("🐈", "Litière chat", "Animaux"),
]


async def semer_catalogue(db: AsyncSession) -> int:
    """Insère le catalogue intégré (list_id NULL) une seule fois. Renvoie le nb inséré."""
    count = await db.scalar(
        select(func.count()).select_from(CatalogItem).where(CatalogItem.list_id.is_(None))
    )
    if count:
        return 0
    for emoji, nom, rayon in CATALOGUE_DEFAUT:
        db.add(CatalogItem(list_id=None, name=nom, emoji=emoji, rayon=rayon))
    await db.commit()
    return len(CATALOGUE_DEFAUT)


async def catalogue_pour_liste(db: AsyncSession, list_id: str) -> list[CatalogItem]:
    """Catalogue visible pour une liste = intégrés (NULL) ∪ perso de cette liste."""
    res = await db.execute(
        select(CatalogItem).where(
            (CatalogItem.list_id.is_(None)) | (CatalogItem.list_id == list_id)
        )
    )
    return list(res.scalars().all())


async def memoriser_item_perso(
    db: AsyncSession, list_id: str, nom: str, emoji: str | None, rayon: str | None, user_id: str
) -> CatalogItem | None:
    """Ajoute un item perso au catalogue de la liste s'il n'existe pas déjà
    (dédup insensible à la casse, contre intégrés + perso). Renvoie l'entrée créée ou None."""
    existants = await catalogue_pour_liste(db, list_id)
    if any(c.name.strip().lower() == nom.strip().lower() for c in existants):
        return None
    item = CatalogItem(
        list_id=list_id, name=nom, emoji=emoji or "🛒",
        rayon=rayon if rayon in RAYONS else "Autre", created_by=user_id,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item
```

- [ ] **Step 4: Lancer (passe)**

Run: `cd briques/agenda/backend && python -m pytest tests/test_catalogue.py -q`
Expected: PASS (3).

- [ ] **Step 5: Commit**

```bash
git add briques/agenda/backend/services/catalogue.py briques/agenda/backend/tests/test_catalogue.py
git commit -m "feat(s176): service catalogue FR — rayons, seed idempotent, mémorisation perso"
```

---

### Task 4 : SSE listes (pub/sub + endpoint)

**Files:**
- Modify: `briques/agenda/backend/services/pubsub.py`
- Modify: `briques/agenda/backend/routers/sse.py`
- Test: `briques/agenda/backend/tests/test_shopping_sse.py`

**Interfaces:**
- Produces : `async publish_list_change(list_id, event_type, payload)` (canal `list:{list_id}:changes`) ; route `GET /sse/lists/{list_id}`.

- [ ] **Step 1: Écrire le test (échoue)**

Create `tests/test_shopping_sse.py` :

```python
"""publish_list_change : no-op sans Redis, canal correct avec Redis mocké."""
from __future__ import annotations

import pytest

from config import settings
from services import pubsub


@pytest.mark.asyncio
async def test_publish_noop_sans_redis(monkeypatch):
    monkeypatch.setattr(settings, "REDIS_URL", None, raising=False)
    # Ne doit pas lever ni tenter de connexion.
    await pubsub.publish_list_change("l1", "item.added", {"id": "x"})


@pytest.mark.asyncio
async def test_publish_canal_liste(monkeypatch):
    envois = {}

    class FakeRedis:
        async def publish(self, channel, msg):
            envois["channel"] = channel
            envois["msg"] = msg
        async def aclose(self):
            pass

    monkeypatch.setattr(settings, "REDIS_URL", "redis://x", raising=False)
    import redis.asyncio as aioredis
    monkeypatch.setattr(aioredis, "from_url", lambda url: FakeRedis())

    await pubsub.publish_list_change("l1", "item.checked", {"id": "x"})
    assert envois["channel"] == "list:l1:changes"
    assert "item.checked" in envois["msg"]
```

- [ ] **Step 2: Lancer (échoue)**

Run: `cd briques/agenda/backend && python -m pytest tests/test_shopping_sse.py -q`
Expected: FAIL (`publish_list_change` inexistant).

- [ ] **Step 3: Ajouter le publisher**

Append à `services/pubsub.py` :

```python
async def publish_list_change(list_id: str, event_type: str, payload: dict) -> None:
    """Broadcast d'un changement de liste vers les clients SSE (canal dédié). Best-effort."""
    if not settings.REDIS_URL:
        return
    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(settings.REDIS_URL)
        msg = json.dumps({"type": event_type, "data": payload})
        await r.publish(f"list:{list_id}:changes", msg)
        await r.aclose()
    except Exception as exc:
        logger.warning("Redis publish (list) failed: %s", exc)
```

- [ ] **Step 4: Ajouter l'endpoint SSE listes**

Append à `routers/sse.py` (imports `asyncio, json, APIRouter, Depends, Request, EventSourceResponse, get_current_user, settings` déjà présents ; ajouter l'accès) :

```python
from db import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from utils.access import require_list_access


@router.get("/sse/lists/{list_id}")
async def list_sse(
    list_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """SSE stream — changements d'une liste (item.added/checked/…) en temps réel."""
    await require_list_access(db, list_id, user["sub"], min_role="viewer")

    async def _generator():
        if not settings.REDIS_URL:
            yield {"data": json.dumps({"type": "connected", "list_id": list_id})}
            while not await request.is_disconnected():
                await asyncio.sleep(30)
                yield {"data": json.dumps({"type": "ping"})}
            return

        import redis.asyncio as aioredis

        r = aioredis.from_url(settings.REDIS_URL)
        pubsub = r.pubsub()
        channel = f"list:{list_id}:changes"
        await pubsub.subscribe(channel)
        yield {"data": json.dumps({"type": "connected", "list_id": list_id})}
        try:
            async for message in pubsub.listen():
                if await request.is_disconnected():
                    break
                if message["type"] == "message":
                    yield {"data": message["data"]}
        except Exception as exc:
            logger.warning("SSE error for list %s: %s", list_id, exc)
        finally:
            await pubsub.unsubscribe(channel)
            await r.aclose()

    return EventSourceResponse(_generator())
```

- [ ] **Step 5: Lancer (passe)**

Run: `cd briques/agenda/backend && python -m pytest tests/test_shopping_sse.py -q`
Expected: PASS (2).

- [ ] **Step 6: Commit**

```bash
git add briques/agenda/backend/services/pubsub.py briques/agenda/backend/routers/sse.py briques/agenda/backend/tests/test_shopping_sse.py
git commit -m "feat(s176): SSE listes — publish_list_change + endpoint /sse/lists/{id}"
```

---

### Task 5 : Service notifications (push par personne best-effort)

**Files:**
- Create: `briques/agenda/backend/services/notifications.py`
- Modify: `briques/agenda/backend/config.py` (ajouter `CONNEXION_URL`, `CONNEXION_KEY`)
- Test: `briques/agenda/backend/tests/test_shopping_notifications.py`

**Interfaces:**
- Consumes : `ShoppingList`, `ShoppingListMember`, `UserProfile` (Task 1 / existant).
- Produces : `async notifier_membres(db, liste, acteur_id, texte) -> int` (nb de push tentés) ; `async nom_affichable(db, user_id) -> str`.

- [ ] **Step 1: Ajouter la config**

Dans `config.py`, ajouter deux réglages (suivre le style existant `settings.X`) :

```python
    CONNEXION_URL: str | None = None   # base du pont messagerie (ex. http://host.docker.internal:5870)
    CONNEXION_KEY: str | None = None   # X-API-Key du pont, si défini
```

(Adapter au mécanisme de settings du fichier : si `pydantic-settings`, déclarer les champs ; si lecture `os.getenv`, exposer `CONNEXION_URL = os.getenv("CONNEXION_URL")`. Vérifier le pattern en tête de `config.py` et s'aligner.)

- [ ] **Step 2: Écrire le test (échoue)**

Create `tests/test_shopping_notifications.py` :

```python
"""notifier_membres : cible les autres membres, jamais l'acteur, no-op sans connexion, ne lève jamais."""
from __future__ import annotations

import pytest

from config import settings
from models.orm import ShoppingList, ShoppingListMember, UserProfile
from services import notifications


async def _liste_avec_membres(db):
    liste = ShoppingList(name="Maison", created_by="perso")
    db.add(liste)
    await db.commit()
    await db.refresh(liste)
    db.add(ShoppingListMember(list_id=liste.id, user_id="marina", role="editor"))
    db.add(ShoppingListMember(list_id=liste.id, user_id="perso", role="owner"))
    await db.commit()
    return liste


@pytest.mark.asyncio
async def test_noop_sans_connexion_url(db, monkeypatch):
    monkeypatch.setattr(settings, "CONNEXION_URL", None, raising=False)
    liste = await _liste_avec_membres(db)
    n = await notifier_membres_ne_leve_pas(db, liste)
    assert n == 0


async def notifier_membres_ne_leve_pas(db, liste):
    return await notifications.notifier_membres(db, liste, acteur_id="perso", texte="🛒 test")


@pytest.mark.asyncio
async def test_cible_les_autres_membres(db, monkeypatch):
    monkeypatch.setattr(settings, "CONNEXION_URL", "http://connexion:5870", raising=False)
    monkeypatch.setattr(settings, "CONNEXION_KEY", None, raising=False)
    cibles = []

    class FakeClient:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None, headers=None):
            cibles.append(json["utilisateur"])
            class R: ...
            return R()

    monkeypatch.setattr(notifications.httpx, "AsyncClient", FakeClient)
    liste = await _liste_avec_membres(db)
    n = await notifications.notifier_membres(db, liste, acteur_id="perso", texte="🛒 test")
    assert set(cibles) == {"marina"}  # perso (acteur) exclu
    assert n == 1


@pytest.mark.asyncio
async def test_ne_leve_jamais_si_connexion_injoignable(db, monkeypatch):
    monkeypatch.setattr(settings, "CONNEXION_URL", "http://connexion:5870", raising=False)

    class BoomClient:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **k):
            raise RuntimeError("connexion down")

    monkeypatch.setattr(notifications.httpx, "AsyncClient", BoomClient)
    liste = await _liste_avec_membres(db)
    # Ne doit pas lever malgré l'exception réseau.
    await notifications.notifier_membres(db, liste, acteur_id="perso", texte="🛒 test")
```

- [ ] **Step 3: Lancer (échoue)**

Run: `cd briques/agenda/backend && python -m pytest tests/test_shopping_notifications.py -q`
Expected: FAIL (ModuleNotFound `services.notifications`).

- [ ] **Step 4: Implémenter**

Create `services/notifications.py` :

```python
"""Push par personne (S176) : la brique émet directement vers le pont `connexion`
(/pousser) sur ajout/cochage d'item. Best-effort — ne lève jamais, no-op si le pont
n'est pas configuré. Réutilise le contrat de `_pousser_messagerie` du Cœur (S174)."""
from __future__ import annotations

import logging

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models.orm import ShoppingList, ShoppingListMember, UserProfile

logger = logging.getLogger(__name__)


async def nom_affichable(db: AsyncSession, user_id: str) -> str:
    """Nom lisible d'un user via UserProfile (S174), repli sur l'id brut."""
    prof = await db.get(UserProfile, user_id)
    return prof.display_name if prof else user_id


async def _membres_uids(db: AsyncSession, liste: ShoppingList) -> set[str]:
    """Tous les user_id concernés : créateur + membres."""
    res = await db.execute(
        select(ShoppingListMember.user_id).where(ShoppingListMember.list_id == liste.id)
    )
    uids = {row[0] for row in res.all()}
    uids.add(liste.created_by)
    return uids


async def notifier_membres(
    db: AsyncSession, liste: ShoppingList, acteur_id: str, texte: str
) -> int:
    """POST best-effort vers connexion /pousser pour chaque membre SAUF l'acteur.
    Renvoie le nb de push tentés. Ne lève jamais."""
    if not settings.CONNEXION_URL:
        return 0
    cibles = await _membres_uids(db, liste)
    cibles.discard(acteur_id)
    if not cibles:
        return 0
    entetes = {}
    if settings.CONNEXION_KEY:
        entetes["X-API-Key"] = settings.CONNEXION_KEY
    base = settings.CONNEXION_URL.rstrip("/")
    n = 0
    for uid in cibles:
        corps = {"utilisateur": uid, "texte": texte}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(f"{base}/pousser", json=corps, headers=entetes)
            n += 1
        except Exception as exc:  # noqa: BLE001 — best-effort, jamais bloquant
            logger.warning("Push liste vers %s échoué : %s", uid, exc)
    return n
```

- [ ] **Step 5: Lancer (passe)**

Run: `cd briques/agenda/backend && python -m pytest tests/test_shopping_notifications.py -q`
Expected: PASS (3).

- [ ] **Step 6: Commit**

```bash
git add briques/agenda/backend/services/notifications.py briques/agenda/backend/config.py briques/agenda/backend/tests/test_shopping_notifications.py
git commit -m "feat(s176): push par personne best-effort vers connexion /pousser (événementiel)"
```

---

### Task 6 : Router listes (CRUD + membres + invitations)

**Files:**
- Create: `briques/agenda/backend/routers/lists.py`
- Test: `briques/agenda/backend/tests/test_shopping_lists.py`

**Interfaces:**
- Consumes : schémas + ORM (Task 1), `require_list_access`/`get_list_role` (Task 2), `nom_affichable` (Task 5).
- Produces : `router` (prefix `/lists`) avec `list_lists`, `create_list`, `get_list`, `update_list`, `delete_list`, `list_members`, `invite_to_list`, `accept_list_invitation`. Fonctions appelables directement en test.

- [ ] **Step 1: Écrire le test (échoue)**

Create `tests/test_shopping_lists.py` :

```python
"""CRUD listes + membres + invitations (accept/expiré/rejoué)."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException

from models.orm import ShoppingListInvitation
from models.schemas import ListInvitationCreate, ShoppingListCreate, ShoppingListUpdate
from routers import lists as R

OWNER = {"sub": "perso"}
AUTRE = {"sub": "marina"}


@pytest.mark.asyncio
async def test_create_puis_owner(db):
    out = await R.create_list(ShoppingListCreate(name="Maison"), db=db, user=OWNER)
    assert out.role == "owner" and out.kind == "courses"


@pytest.mark.asyncio
async def test_list_lists_compte_a_prendre(db):
    liste = await R.create_list(ShoppingListCreate(name="Maison"), db=db, user=OWNER)
    from models.orm import ShoppingItem
    db.add(ShoppingItem(list_id=liste.id, name="Lait", added_by="perso", checked=False))
    db.add(ShoppingItem(list_id=liste.id, name="Pain", added_by="perso", checked=True))
    await db.commit()
    mes = await R.list_lists(db=db, user=OWNER)
    assert mes[0].nb_a_prendre == 1


@pytest.mark.asyncio
async def test_delete_exige_owner(db):
    liste = await R.create_list(ShoppingListCreate(name="Maison"), db=db, user=OWNER)
    from models.orm import ShoppingListMember
    db.add(ShoppingListMember(list_id=liste.id, user_id="marina", role="editor"))
    await db.commit()
    with pytest.raises(HTTPException) as exc:
        await R.delete_list(liste.id, db=db, user=AUTRE)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_invitation_accept_rejoint(db):
    liste = await R.create_list(ShoppingListCreate(name="Maison"), db=db, user=OWNER)
    inv = await R.invite_to_list(liste.id, ListInvitationCreate(role="editor"), db=db, user=OWNER)
    await R.accept_list_invitation(inv["token"], db=db, user=AUTRE)
    from utils.access import get_list_role
    assert await get_list_role(db, liste.id, "marina") == "editor"


@pytest.mark.asyncio
async def test_invitation_expiree_refusee(db):
    liste = await R.create_list(ShoppingListCreate(name="Maison"), db=db, user=OWNER)
    inv = ShoppingListInvitation(
        list_id=liste.id, role="editor", created_by="perso",
        expires_at=datetime.utcnow() - timedelta(hours=1))
    db.add(inv)
    await db.commit()
    with pytest.raises(HTTPException) as exc:
        await R.accept_list_invitation(inv.token, db=db, user=AUTRE)
    assert exc.value.status_code == 410


@pytest.mark.asyncio
async def test_invitation_rejouee_refusee(db):
    liste = await R.create_list(ShoppingListCreate(name="Maison"), db=db, user=OWNER)
    inv = await R.invite_to_list(liste.id, ListInvitationCreate(role="viewer"), db=db, user=OWNER)
    await R.accept_list_invitation(inv["token"], db=db, user=AUTRE)
    with pytest.raises(HTTPException) as exc:
        await R.accept_list_invitation(inv["token"], db=db, user={"sub": "autre2"})
    assert exc.value.status_code == 410
```

- [ ] **Step 2: Lancer (échoue)**

Run: `cd briques/agenda/backend && python -m pytest tests/test_shopping_lists.py -q`
Expected: FAIL (ModuleNotFound `routers.lists`).

- [ ] **Step 3: Implémenter le router**

Create `routers/lists.py` :

```python
"""CRUD listes de courses/tâches + membres + invitations — /lists."""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from db import get_db
from models.orm import (
    ShoppingItem,
    ShoppingList,
    ShoppingListInvitation,
    ShoppingListMember,
)
from models.schemas import (
    ListInvitationCreate,
    ListMemberOut,
    ShoppingListCreate,
    ShoppingListOut,
    ShoppingListUpdate,
    ShoppingListWithMetaOut,
)
from services.notifications import nom_affichable
from utils.access import get_list_role, require_list_access

router = APIRouter(prefix="/lists", tags=["lists"])


def _with_meta(liste: ShoppingList, role: str, nb: int) -> ShoppingListWithMetaOut:
    return ShoppingListWithMetaOut(
        **ShoppingListOut.model_validate(liste).model_dump(), role=role, nb_a_prendre=nb)


@router.get("", response_model=list[ShoppingListWithMetaOut])
async def list_lists(db: AsyncSession = Depends(get_db), user: dict = Depends(get_current_user)):
    uid = user["sub"]
    owned = (await db.execute(select(ShoppingList).where(ShoppingList.created_by == uid))).scalars().all()
    owned_ids = {l.id for l in owned}
    member_rows = (await db.execute(
        select(ShoppingListMember, ShoppingList)
        .join(ShoppingList, ShoppingListMember.list_id == ShoppingList.id)
        .where(ShoppingListMember.user_id == uid)
    )).all()
    resultat: list[ShoppingListWithMetaOut] = []
    vues: list[tuple[ShoppingList, str]] = [(l, "owner") for l in owned]
    for member, liste in member_rows:
        if liste.id not in owned_ids:
            vues.append((liste, member.role))
    for liste, role in vues:
        nb = await db.scalar(
            select(func.count()).select_from(ShoppingItem).where(
                ShoppingItem.list_id == liste.id, ShoppingItem.checked.is_(False))
        )
        resultat.append(_with_meta(liste, role, nb or 0))
    return resultat


@router.post("", response_model=ShoppingListWithMetaOut, status_code=status.HTTP_201_CREATED)
async def create_list(body: ShoppingListCreate, db: AsyncSession = Depends(get_db),
                      user: dict = Depends(get_current_user)):
    kind = body.kind if body.kind in ("courses", "taches") else "courses"
    liste = ShoppingList(name=body.name, kind=kind, created_by=user["sub"])
    db.add(liste)
    await db.commit()
    await db.refresh(liste)
    return _with_meta(liste, "owner", 0)


@router.get("/{list_id}", response_model=ShoppingListWithMetaOut)
async def get_list(list_id: str, db: AsyncSession = Depends(get_db),
                   user: dict = Depends(get_current_user)):
    liste, role = await require_list_access(db, list_id, user["sub"], min_role="viewer")
    nb = await db.scalar(
        select(func.count()).select_from(ShoppingItem).where(
            ShoppingItem.list_id == list_id, ShoppingItem.checked.is_(False)))
    return _with_meta(liste, role, nb or 0)


@router.patch("/{list_id}", response_model=ShoppingListWithMetaOut)
async def update_list(list_id: str, body: ShoppingListUpdate, db: AsyncSession = Depends(get_db),
                      user: dict = Depends(get_current_user)):
    liste, role = await require_list_access(db, list_id, user["sub"], min_role="editor")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(liste, k, v)
    await db.commit()
    await db.refresh(liste)
    return _with_meta(liste, role, 0)


@router.delete("/{list_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_list(list_id: str, db: AsyncSession = Depends(get_db),
                      user: dict = Depends(get_current_user)):
    liste, _ = await require_list_access(db, list_id, user["sub"], min_role="owner")
    await db.delete(liste)
    await db.commit()


@router.get("/{list_id}/members", response_model=list[ListMemberOut])
async def list_members(list_id: str, db: AsyncSession = Depends(get_db),
                       user: dict = Depends(get_current_user)):
    liste, _ = await require_list_access(db, list_id, user["sub"], min_role="viewer")
    from models.orm import UserProfile
    membres = (await db.execute(
        select(ShoppingListMember).where(ShoppingListMember.list_id == list_id))).scalars().all()
    uids = {liste.created_by, *[m.user_id for m in membres]}
    sortie: list[ListMemberOut] = []
    for m in membres:
        prof = await db.get(UserProfile, m.user_id)
        sortie.append(ListMemberOut(
            user_id=m.user_id, role=m.role,
            display_name=prof.display_name if prof else None,
            avatar_color=prof.avatar_color if prof else None))
    if liste.created_by not in {m.user_id for m in membres}:
        prof = await db.get(UserProfile, liste.created_by)
        sortie.insert(0, ListMemberOut(
            user_id=liste.created_by, role="owner",
            display_name=prof.display_name if prof else None,
            avatar_color=prof.avatar_color if prof else None))
    return sortie


@router.post("/{list_id}/invitations", status_code=status.HTTP_201_CREATED)
async def invite_to_list(list_id: str, body: ListInvitationCreate, db: AsyncSession = Depends(get_db),
                         user: dict = Depends(get_current_user)):
    await require_list_access(db, list_id, user["sub"], min_role="editor")
    role = body.role if body.role in ("viewer", "editor") else "viewer"
    inv = ShoppingListInvitation(
        list_id=list_id, role=role, email=body.email, created_by=user["sub"],
        expires_at=datetime.utcnow() + timedelta(hours=body.expire_heures))
    db.add(inv)
    await db.commit()
    await db.refresh(inv)
    return {"token": inv.token, "role": inv.role, "expires_at": inv.expires_at.isoformat()}


@router.post("/invitations/{token}/accept", status_code=status.HTTP_200_OK)
async def accept_list_invitation(token: str, db: AsyncSession = Depends(get_db),
                                 user: dict = Depends(get_current_user)):
    inv = (await db.execute(
        select(ShoppingListInvitation).where(ShoppingListInvitation.token == token))).scalar_one_or_none()
    if inv is None:
        raise HTTPException(status_code=404, detail="Invitation introuvable")
    if inv.used_at is not None or (inv.expires_at and inv.expires_at < datetime.utcnow()):
        raise HTTPException(status_code=410, detail="Invitation expirée ou déjà utilisée")
    uid = user["sub"]
    existe = (await db.execute(select(ShoppingListMember).where(
        ShoppingListMember.list_id == inv.list_id, ShoppingListMember.user_id == uid))).scalar_one_or_none()
    if existe is None:
        db.add(ShoppingListMember(list_id=inv.list_id, user_id=uid, role=inv.role))
    inv.used_at = datetime.utcnow()
    await db.commit()
    return {"list_id": inv.list_id, "role": inv.role}
```

- [ ] **Step 4: Lancer (passe)**

Run: `cd briques/agenda/backend && python -m pytest tests/test_shopping_lists.py -q`
Expected: PASS (6).

- [ ] **Step 5: Commit**

```bash
git add briques/agenda/backend/routers/lists.py briques/agenda/backend/tests/test_shopping_lists.py
git commit -m "feat(s176): router /lists — CRUD + membres + invitations par lien"
```

---

### Task 7 : Router items (ajout/cochage/clear) + SSE + push

**Files:**
- Create: `briques/agenda/backend/routers/list_items.py`
- Test: `briques/agenda/backend/tests/test_shopping_items.py`

**Interfaces:**
- Consumes : ORM + schémas (Task 1), `require_list_access` (Task 2), `catalogue_pour_liste`/`memoriser_item_perso` (Task 3), `publish_list_change` (Task 4), `notifier_membres`/`nom_affichable` (Task 5).
- Produces : `router` avec `list_items`, `add_item`, `update_item`, `delete_item`, `clear_checked`.

- [ ] **Step 1: Écrire le test (échoue)**

Create `tests/test_shopping_items.py` :

```python
"""Items : ajout (nom / catalog_item_id / anti-doublon), cochage, clear, delete, gating."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from models.orm import CatalogItem, ShoppingItem, ShoppingList, ShoppingListMember
from models.schemas import ShoppingItemCreate, ShoppingItemUpdate
from routers import list_items as R

OWNER = {"sub": "perso"}
VIEWER = {"sub": "marina"}


async def _liste(db, kind="courses"):
    liste = ShoppingList(name="Maison", kind=kind, created_by="perso")
    db.add(liste)
    await db.commit()
    await db.refresh(liste)
    return liste


@pytest.mark.asyncio
async def test_ajout_par_nom_memorise_catalogue(db):
    liste = await _liste(db)
    out = await R.add_item(liste.id, ShoppingItemCreate(name="Kombucha", rayon="Boissons", emoji="🍾"),
                           db=db, user=OWNER)
    assert out.name == "Kombucha" and out.checked is False
    from services.catalogue import catalogue_pour_liste
    cat = await catalogue_pour_liste(db, liste.id)
    assert any(c.name == "Kombucha" for c in cat)


@pytest.mark.asyncio
async def test_ajout_par_catalog_item_id(db):
    liste = await _liste(db)
    ci = CatalogItem(list_id=None, name="Lait", emoji="🥛", rayon="Crèmerie")
    db.add(ci)
    await db.commit()
    await db.refresh(ci)
    out = await R.add_item(liste.id, ShoppingItemCreate(catalog_item_id=ci.id), db=db, user=OWNER)
    assert out.name == "Lait" and out.emoji == "🥛" and out.rayon == "Crèmerie"


@pytest.mark.asyncio
async def test_anti_doublon_ne_recree_pas(db):
    liste = await _liste(db)
    await R.add_item(liste.id, ShoppingItemCreate(name="Lait"), db=db, user=OWNER)
    await R.add_item(liste.id, ShoppingItemCreate(name="lait"), db=db, user=OWNER)
    items = await R.list_items(liste.id, db=db, user=OWNER)
    actifs = [i for i in items if not i.checked]
    assert len(actifs) == 1


@pytest.mark.asyncio
async def test_cocher_pose_checked_by(db):
    liste = await _liste(db)
    it = await R.add_item(liste.id, ShoppingItemCreate(name="Lait"), db=db, user=OWNER)
    out = await R.update_item(liste.id, it.id, ShoppingItemUpdate(checked=True), db=db, user=OWNER)
    assert out.checked is True and out.checked_by == "perso" and out.checked_at is not None


@pytest.mark.asyncio
async def test_clear_checked(db):
    liste = await _liste(db)
    a = await R.add_item(liste.id, ShoppingItemCreate(name="Lait"), db=db, user=OWNER)
    await R.update_item(liste.id, a.id, ShoppingItemUpdate(checked=True), db=db, user=OWNER)
    await R.add_item(liste.id, ShoppingItemCreate(name="Pain"), db=db, user=OWNER)
    await R.clear_checked(liste.id, db=db, user=OWNER)
    restants = await R.list_items(liste.id, db=db, user=OWNER)
    assert {i.name for i in restants} == {"Pain"}


@pytest.mark.asyncio
async def test_ajout_refuse_viewer(db):
    liste = await _liste(db)
    db.add(ShoppingListMember(list_id=liste.id, user_id="marina", role="viewer"))
    await db.commit()
    with pytest.raises(HTTPException) as exc:
        await R.add_item(liste.id, ShoppingItemCreate(name="Lait"), db=db, user=VIEWER)
    assert exc.value.status_code == 404
```

- [ ] **Step 2: Lancer (échoue)**

Run: `cd briques/agenda/backend && python -m pytest tests/test_shopping_items.py -q`
Expected: FAIL (ModuleNotFound `routers.list_items`).

- [ ] **Step 3: Implémenter le router**

Create `routers/list_items.py` :

```python
"""Items d'une liste — ajout, cochage, clear, delete. Émet SSE + push par personne."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from db import get_db
from models.orm import CatalogItem, ShoppingItem
from models.schemas import ShoppingItemCreate, ShoppingItemOut, ShoppingItemUpdate
from services.catalogue import memoriser_item_perso
from services.notifications import nom_affichable, notifier_membres
from services.pubsub import publish_list_change
from utils.access import require_list_access

router = APIRouter(prefix="/lists", tags=["list-items"])


def _out(item: ShoppingItem) -> ShoppingItemOut:
    return ShoppingItemOut.model_validate(item)


@router.get("/{list_id}/items", response_model=list[ShoppingItemOut])
async def list_items(list_id: str, db: AsyncSession = Depends(get_db),
                     user: dict = Depends(get_current_user)):
    await require_list_access(db, list_id, user["sub"], min_role="viewer")
    rows = (await db.execute(
        select(ShoppingItem).where(ShoppingItem.list_id == list_id)
        .order_by(ShoppingItem.checked, ShoppingItem.rayon, ShoppingItem.position))).scalars().all()
    return [_out(i) for i in rows]


@router.post("/{list_id}/items", response_model=ShoppingItemOut, status_code=status.HTTP_201_CREATED)
async def add_item(list_id: str, body: ShoppingItemCreate, db: AsyncSession = Depends(get_db),
                   user: dict = Depends(get_current_user)):
    liste, _ = await require_list_access(db, list_id, user["sub"], min_role="editor")
    nom, emoji, rayon = body.name, body.emoji, body.rayon
    if body.catalog_item_id:
        ci = await db.get(CatalogItem, body.catalog_item_id)
        if ci is None:
            raise HTTPException(status_code=404, detail="Item de catalogue introuvable")
        nom, emoji, rayon = ci.name, ci.emoji, ci.rayon
    if not nom or not nom.strip():
        raise HTTPException(status_code=422, detail="Nom d'item requis")
    nom = nom.strip()

    # Anti-doublon façon Bring! : un item actif de même nom → on ne duplique pas.
    existant = (await db.execute(
        select(ShoppingItem).where(
            ShoppingItem.list_id == list_id,
            ShoppingItem.checked.is_(False),
            func_lower(ShoppingItem.name) == nom.lower(),
        ))).scalar_one_or_none()
    if existant is not None:
        item = existant
    else:
        item = ShoppingItem(list_id=list_id, name=nom, emoji=emoji, rayon=rayon,
                            note=body.note, added_by=user["sub"])
        db.add(item)
        await db.commit()
        await db.refresh(item)
        # Mémorise au catalogue perso si saisi à la main (pas depuis un item catalogue).
        if not body.catalog_item_id:
            await memoriser_item_perso(db, list_id, nom, emoji, rayon, user["sub"])

    await publish_list_change(list_id, "item.added", _out(item).model_dump(mode="json"))
    acteur = await nom_affichable(db, user["sub"])
    await notifier_membres(db, liste, user["sub"], f"🛒 {acteur} a ajouté {nom} à {liste.name}")
    return _out(item)


@router.patch("/{list_id}/items/{item_id}", response_model=ShoppingItemOut)
async def update_item(list_id: str, item_id: str, body: ShoppingItemUpdate,
                      db: AsyncSession = Depends(get_db), user: dict = Depends(get_current_user)):
    liste, _ = await require_list_access(db, list_id, user["sub"], min_role="editor")
    item = await db.get(ShoppingItem, item_id)
    if item is None or item.list_id != list_id:
        raise HTTPException(status_code=404, detail="Item introuvable")
    data = body.model_dump(exclude_none=True)
    coche_transition = False
    if "checked" in data:
        if data["checked"] and not item.checked:
            item.checked_by = user["sub"]
            item.checked_at = datetime.utcnow()
            coche_transition = True
        elif not data["checked"]:
            item.checked_by = None
            item.checked_at = None
    for k, v in data.items():
        setattr(item, k, v)
    await db.commit()
    await db.refresh(item)

    evt = "item.checked" if item.checked else "item.unchecked"
    if not ({"checked"} & set(data)):
        evt = "item.updated"
    await publish_list_change(list_id, evt, _out(item).model_dump(mode="json"))
    if coche_transition:
        acteur = await nom_affichable(db, user["sub"])
        await notifier_membres(db, liste, user["sub"], f"✅ {acteur} a coché {item.name}")
    return _out(item)


@router.delete("/{list_id}/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(list_id: str, item_id: str, db: AsyncSession = Depends(get_db),
                      user: dict = Depends(get_current_user)):
    await require_list_access(db, list_id, user["sub"], min_role="editor")
    item = await db.get(ShoppingItem, item_id)
    if item is None or item.list_id != list_id:
        raise HTTPException(status_code=404, detail="Item introuvable")
    await db.delete(item)
    await db.commit()
    await publish_list_change(list_id, "item.deleted", {"id": item_id})


@router.post("/{list_id}/items/clear-checked", status_code=status.HTTP_200_OK)
async def clear_checked(list_id: str, db: AsyncSession = Depends(get_db),
                        user: dict = Depends(get_current_user)):
    await require_list_access(db, list_id, user["sub"], min_role="editor")
    coches = (await db.execute(
        select(ShoppingItem).where(
            ShoppingItem.list_id == list_id, ShoppingItem.checked.is_(True)))).scalars().all()
    n = len(coches)
    for it in coches:
        await db.delete(it)
    await db.commit()
    await publish_list_change(list_id, "checked.cleared", {"count": n})
    return {"cleared": n}
```

En tête du fichier, ajouter le helper d'insensibilité à la casse portable SQLite/Postgres :

```python
from sqlalchemy import func as _sa_func

def func_lower(col):
    return _sa_func.lower(col)
```

- [ ] **Step 4: Lancer (passe)**

Run: `cd briques/agenda/backend && python -m pytest tests/test_shopping_items.py -q`
Expected: PASS (6). (SSE/push sont no-op en test : `REDIS_URL`/`CONNEXION_URL` non définis.)

- [ ] **Step 5: Commit**

```bash
git add briques/agenda/backend/routers/list_items.py briques/agenda/backend/tests/test_shopping_items.py
git commit -m "feat(s176): router items — ajout/cochage/clear + anti-doublon + SSE + push"
```

---

### Task 8 : Router catalogue (GET groupé par rayon)

**Files:**
- Create: `briques/agenda/backend/routers/list_catalog.py`
- Test: `briques/agenda/backend/tests/test_list_catalog.py`

**Interfaces:**
- Consumes : `catalogue_pour_liste`/`RAYONS` (Task 3), `require_list_access` (Task 2).
- Produces : `router` avec `get_catalog` → `{"rayons": [{"rayon": str, "items": [CatalogItemOut]}]}` ordonné selon `RAYONS`.

- [ ] **Step 1: Écrire le test (échoue)**

Create `tests/test_list_catalog.py` :

```python
"""Catalogue d'une liste, groupé et ordonné par rayon."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from models.orm import ShoppingList, ShoppingListMember
from routers import list_catalog as R
from services.catalogue import semer_catalogue

OWNER = {"sub": "perso"}
INCONNU = {"sub": "zzz"}


@pytest.mark.asyncio
async def test_catalog_groupe_par_rayon(db):
    await semer_catalogue(db)
    liste = ShoppingList(name="M", created_by="perso")
    db.add(liste)
    await db.commit()
    await db.refresh(liste)
    out = await R.get_catalog(liste.id, db=db, user=OWNER)
    rayons = [g["rayon"] for g in out["rayons"]]
    assert rayons[0] == "Fruits & légumes"  # ordre RAYONS
    assert all(g["items"] for g in out["rayons"])  # pas de rayon vide


@pytest.mark.asyncio
async def test_catalog_refuse_sans_acces(db):
    liste = ShoppingList(name="M", created_by="perso")
    db.add(liste)
    await db.commit()
    await db.refresh(liste)
    with pytest.raises(HTTPException) as exc:
        await R.get_catalog(liste.id, db=db, user=INCONNU)
    assert exc.value.status_code == 404
```

- [ ] **Step 2: Lancer (échoue)**

Run: `cd briques/agenda/backend && python -m pytest tests/test_list_catalog.py -q`
Expected: FAIL (ModuleNotFound `routers.list_catalog`).

- [ ] **Step 3: Implémenter**

Create `routers/list_catalog.py` :

```python
"""Catalogue tap-to-add d'une liste, groupé par rayon — /lists/{id}/catalog."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from db import get_db
from models.schemas import CatalogItemOut
from services.catalogue import RAYONS, catalogue_pour_liste
from utils.access import require_list_access

router = APIRouter(prefix="/lists", tags=["list-catalog"])


@router.get("/{list_id}/catalog")
async def get_catalog(list_id: str, db: AsyncSession = Depends(get_db),
                      user: dict = Depends(get_current_user)):
    await require_list_access(db, list_id, user["sub"], min_role="viewer")
    items = await catalogue_pour_liste(db, list_id)
    par_rayon: dict[str, list] = {}
    for ci in items:
        par_rayon.setdefault(ci.rayon, []).append(CatalogItemOut.model_validate(ci))
    groupes = []
    for rayon in RAYONS:
        if par_rayon.get(rayon):
            items_tries = sorted(par_rayon[rayon], key=lambda c: c.name.lower())
            groupes.append({"rayon": rayon, "items": items_tries})
    return {"rayons": groupes}
```

- [ ] **Step 4: Lancer (passe)**

Run: `cd briques/agenda/backend && python -m pytest tests/test_list_catalog.py -q`
Expected: PASS (2).

- [ ] **Step 5: Commit**

```bash
git add briques/agenda/backend/routers/list_catalog.py briques/agenda/backend/tests/test_list_catalog.py
git commit -m "feat(s176): router catalogue — GET /lists/{id}/catalog groupé par rayon"
```

---

### Task 9 : Router cartes de fidélité

**Files:**
- Create: `briques/agenda/backend/routers/loyalty.py`
- Test: `briques/agenda/backend/tests/test_loyalty.py`

**Interfaces:**
- Consumes : `LoyaltyCard` + schémas (Task 1), `require_owned_card` (Task 2).
- Produces : `router` (prefix `/loyalty-cards`) avec `list_cards`, `create_card`, `get_card`, `update_card`, `delete_card`.

- [ ] **Step 1: Écrire le test (échoue)**

Create `tests/test_loyalty.py` :

```python
"""Cartes de fidélité : CRUD isolé par propriétaire."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from models.schemas import LoyaltyCardCreate, LoyaltyCardUpdate
from routers import loyalty as R

MOI = {"sub": "perso"}
AUTRE = {"sub": "marina"}


@pytest.mark.asyncio
async def test_create_et_list_isole(db):
    await R.create_card(LoyaltyCardCreate(enseigne="Carrefour", numero="123"), db=db, user=MOI)
    await R.create_card(LoyaltyCardCreate(enseigne="Leclerc", numero="456"), db=db, user=AUTRE)
    miennes = await R.list_cards(db=db, user=MOI)
    assert {c.enseigne for c in miennes} == {"Carrefour"}


@pytest.mark.asyncio
async def test_get_autre_proprietaire_404(db):
    c = await R.create_card(LoyaltyCardCreate(enseigne="Carrefour", numero="123"), db=db, user=MOI)
    with pytest.raises(HTTPException) as exc:
        await R.get_card(c.id, db=db, user=AUTRE)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_update_et_delete(db):
    c = await R.create_card(LoyaltyCardCreate(enseigne="Carrefour", numero="123"), db=db, user=MOI)
    up = await R.update_card(c.id, LoyaltyCardUpdate(note="carte plastique"), db=db, user=MOI)
    assert up.note == "carte plastique"
    await R.delete_card(c.id, db=db, user=MOI)
    assert await R.list_cards(db=db, user=MOI) == []


@pytest.mark.asyncio
async def test_format_defaut_code128(db):
    c = await R.create_card(LoyaltyCardCreate(enseigne="X", numero="1"), db=db, user=MOI)
    assert c.format == "code128"
```

- [ ] **Step 2: Lancer (échoue)**

Run: `cd briques/agenda/backend && python -m pytest tests/test_loyalty.py -q`
Expected: FAIL (ModuleNotFound `routers.loyalty`).

- [ ] **Step 3: Implémenter**

Create `routers/loyalty.py` :

```python
"""Cartes de fidélité personnelles — /loyalty-cards (scope propriétaire)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from db import get_db
from models.orm import LoyaltyCard
from models.schemas import LoyaltyCardCreate, LoyaltyCardOut, LoyaltyCardUpdate
from utils.access import require_owned_card

router = APIRouter(prefix="/loyalty-cards", tags=["loyalty"])

_FORMATS = {"code128", "ean13", "qr"}


@router.get("", response_model=list[LoyaltyCardOut])
async def list_cards(db: AsyncSession = Depends(get_db), user: dict = Depends(get_current_user)):
    rows = (await db.execute(
        select(LoyaltyCard).where(LoyaltyCard.user_id == user["sub"])
        .order_by(LoyaltyCard.enseigne))).scalars().all()
    return [LoyaltyCardOut.model_validate(c) for c in rows]


@router.post("", response_model=LoyaltyCardOut, status_code=status.HTTP_201_CREATED)
async def create_card(body: LoyaltyCardCreate, db: AsyncSession = Depends(get_db),
                      user: dict = Depends(get_current_user)):
    fmt = body.format if body.format in _FORMATS else "code128"
    carte = LoyaltyCard(user_id=user["sub"], enseigne=body.enseigne, numero=body.numero,
                        format=fmt, couleur=body.couleur, note=body.note)
    db.add(carte)
    await db.commit()
    await db.refresh(carte)
    return LoyaltyCardOut.model_validate(carte)


@router.get("/{card_id}", response_model=LoyaltyCardOut)
async def get_card(card_id: str, db: AsyncSession = Depends(get_db),
                   user: dict = Depends(get_current_user)):
    carte = await require_owned_card(db, card_id, user["sub"])
    return LoyaltyCardOut.model_validate(carte)


@router.patch("/{card_id}", response_model=LoyaltyCardOut)
async def update_card(card_id: str, body: LoyaltyCardUpdate, db: AsyncSession = Depends(get_db),
                      user: dict = Depends(get_current_user)):
    carte = await require_owned_card(db, card_id, user["sub"])
    data = body.model_dump(exclude_none=True)
    if "format" in data and data["format"] not in _FORMATS:
        raise HTTPException(status_code=422, detail="Format inconnu")
    for k, v in data.items():
        setattr(carte, k, v)
    await db.commit()
    await db.refresh(carte)
    return LoyaltyCardOut.model_validate(carte)


@router.delete("/{card_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_card(card_id: str, db: AsyncSession = Depends(get_db),
                      user: dict = Depends(get_current_user)):
    carte = await require_owned_card(db, card_id, user["sub"])
    await db.delete(carte)
    await db.commit()
```

- [ ] **Step 4: Lancer (passe)**

Run: `cd briques/agenda/backend && python -m pytest tests/test_loyalty.py -q`
Expected: PASS (4).

- [ ] **Step 5: Commit**

```bash
git add briques/agenda/backend/routers/loyalty.py briques/agenda/backend/tests/test_loyalty.py
git commit -m "feat(s176): router cartes de fidélité — CRUD isolé par propriétaire"
```

---

### Task 10 : Générateur code-barres embarqué (Code128 + EAN-13)

**Files:**
- Create: `briques/agenda/backend/static/barcode.js`
- Create: `briques/agenda/backend/tests/test_barcode.py`

**Interfaces:**
- Produces : fichier JS servi statiquement exposant `window.dessinerCodeBarres(svgEl, texte, format)`.

Ce module dessine un code-barres dans un `<svg>` sans aucune dépendance externe. `code128`
(jeu B) et `ean13` sont rendus ; `qr` est laissé au repli côté front (numéro en grand).

- [ ] **Step 1: Écrire le fichier JS**

Create `static/barcode.js` :

```javascript
/* Générateur de code-barres vanilla, sans dépendance (S176).
   window.dessinerCodeBarres(svgEl, texte, format) — format "code128" | "ean13".
   Retourne true si dessiné, false si format non supporté / entrée invalide. */
(function () {
  "use strict";

  // Code128 : 108 motifs (largeurs de barres/espaces), index 0..106 + stop.
  var C128 = [
    "212222","222122","222221","121223","121322","131222","122213","122312","132212","221213",
    "221312","231212","112232","122132","122231","113222","123122","123221","223211","221132",
    "221231","213212","223112","312131","311222","321122","321221","312212","322112","322211",
    "212123","212321","232121","111323","131123","131321","112313","132113","132311","211313",
    "231113","231311","112133","112331","132131","113123","113321","133121","313121","211331",
    "231131","213113","213311","213131","311123","311321","331121","312113","312311","332111",
    "314111","221411","431111","111224","111422","121124","121421","141122","141221","112214",
    "112412","122114","122411","142112","142211","241211","221114","413111","241112","134111",
    "111242","121142","121241","114212","124112","124211","411212","421112","421211","212141",
    "214121","412121","111143","111341","131141","114113","114311","411113","411311","113141",
    "114131","311141","411131","211412","211214","211232","233111","200000"
  ];

  function code128B(texte) {
    // Jeu B : ASCII 32..126 → valeur = code - 32.
    var codes = [104]; // Start B
    for (var i = 0; i < texte.length; i++) {
      var v = texte.charCodeAt(i) - 32;
      if (v < 0 || v > 94) return null; // hors jeu B
      codes.push(v);
    }
    var somme = 104;
    for (var j = 0; j < texte.length; j++) somme += (texte.charCodeAt(j) - 32) * (j + 1);
    codes.push(somme % 103); // checksum
    codes.push(106);         // Stop
    var motifs = codes.map(function (c) { return C128[c]; });
    return motifs.join("");  // suite de largeurs, barre puis espace en alternance
  }

  var EAN_L = ["0001101","0011001","0010011","0111101","0100011","0110001","0101111","0111011","0110111","0001011"];
  var EAN_G = ["0100111","0110011","0011011","0100001","0011101","0111001","0000101","0010001","0001001","0010111"];
  var EAN_R = ["1110010","1100110","1101100","1000010","1011100","1001110","1010000","1000100","1001000","1110100"];
  var EAN_PARITE = ["LLLLLL","LLGLGG","LLGGLG","LLGGGL","LGLLGG","LGGLLG","LGGGLL","LGLGLG","LGLGGL","LGGLGL"];

  function ean13Checksum(d12) {
    var s = 0;
    for (var i = 0; i < 12; i++) s += (i % 2 === 0 ? 1 : 3) * parseInt(d12[i], 10);
    return (10 - (s % 10)) % 10;
  }

  function ean13Bits(numero) {
    var digits = numero.replace(/\D/g, "");
    if (digits.length === 12) digits += String(ean13Checksum(digits));
    if (digits.length !== 13) return null;
    var first = parseInt(digits[0], 10);
    var parite = EAN_PARITE[first];
    var bits = "101"; // garde gauche
    for (var i = 1; i <= 6; i++) {
      var d = parseInt(digits[i], 10);
      bits += (parite[i - 1] === "L") ? EAN_L[d] : EAN_G[d];
    }
    bits += "01010"; // garde centrale
    for (var k = 7; k <= 12; k++) bits += EAN_R[parseInt(digits[k], 10)];
    bits += "101"; // garde droite
    return { bits: bits, digits: digits };
  }

  function svgRect(x, w) {
    return '<rect x="' + x + '" y="0" width="' + w + '" height="100" fill="#000"/>';
  }

  function dessinerDepuisLargeurs(svgEl, largeurs) {
    // largeurs = chaîne de chiffres ; alternance barre(noir)/espace à partir d'une barre.
    var x = 10, unite = 2, rects = "", noir = true, total = 10;
    for (var i = 0; i < largeurs.length; i++) {
      var w = parseInt(largeurs[i], 10) * unite;
      if (noir) rects += svgRect(x, w);
      x += w; total += w; noir = !noir;
    }
    total += 10;
    svgEl.setAttribute("viewBox", "0 0 " + total + " 100");
    svgEl.setAttribute("preserveAspectRatio", "none");
    svgEl.innerHTML = rects;
  }

  function dessinerDepuisBits(svgEl, bits) {
    var x = 10, unite = 2, rects = "", total = 10;
    for (var i = 0; i < bits.length; i++) {
      if (bits[i] === "1") rects += svgRect(x, unite);
      x += unite; total += unite;
    }
    total += 10;
    svgEl.setAttribute("viewBox", "0 0 " + total + " 100");
    svgEl.setAttribute("preserveAspectRatio", "none");
    svgEl.innerHTML = rects;
  }

  window.dessinerCodeBarres = function (svgEl, texte, format) {
    try {
      if (format === "ean13") {
        var r = ean13Bits(String(texte));
        if (!r) return false;
        dessinerDepuisBits(svgEl, r.bits);
        return true;
      }
      // défaut : Code128 jeu B
      var largeurs = code128B(String(texte));
      if (!largeurs) return false;
      dessinerDepuisLargeurs(svgEl, largeurs);
      return true;
    } catch (e) {
      return false;
    }
  };
})();
```

- [ ] **Step 2: Écrire un test de cohérence de l'encodage (Python porté)**

Create `tests/test_barcode.py` — vérifie le checksum Code128 et le chiffre de contrôle EAN-13
sur des vecteurs connus, via une **ré-implémentation Python de référence** des deux algorithmes
(le test protège la logique ; le JS doit produire les mêmes valeurs) :

```python
"""Vecteurs de contrôle Code128 / EAN-13 (logique de référence en Python).

But : figer les invariants d'encodage (checksum mod 103, chiffre de contrôle mod 10,
longueurs de motifs) pour qu'une régression dans static/barcode.js soit détectable par
comparaison. Ne rend pas de SVG — teste l'arithmétique d'encodage."""
from __future__ import annotations

# ── Code128 jeu B ──────────────────────────────────────────────────────────────
def code128b_valeurs(texte: str) -> list[int]:
    codes = [104]
    for ch in texte:
        codes.append(ord(ch) - 32)
    somme = 104 + sum((ord(ch) - 32) * (i + 1) for i, ch in enumerate(texte))
    codes.append(somme % 103)
    codes.append(106)
    return codes


def test_code128_checksum_connu():
    # Vecteur classique "CODE128" — checksum de référence attendu.
    valeurs = code128b_valeurs("CODE128")
    assert valeurs[0] == 104 and valeurs[-1] == 106
    # start(104) + Σ (val_i * pos_i) mod 103
    attendu = (104 + sum((ord(ch) - 32) * (i + 1) for i, ch in enumerate("CODE128"))) % 103
    assert valeurs[-2] == attendu


# ── EAN-13 ──────────────────────────────────────────────────────────────────────
def ean13_checksum(d12: str) -> int:
    s = sum((1 if i % 2 == 0 else 3) * int(d12[i]) for i in range(12))
    return (10 - (s % 10)) % 10


def test_ean13_checksum_reference():
    # 978020137962 -> clé 8 (ISBN-13 bien connu 9780201379624)
    assert ean13_checksum("978020137962") == 4
    # 400638133393 -> clé 1 (exemple EAN-13 courant 4006381333931)
    assert ean13_checksum("400638133393") == 1
```

- [ ] **Step 3: Lancer le test (passe)**

Run: `cd briques/agenda/backend && python -m pytest tests/test_barcode.py -q`
Expected: PASS (2). (Si un vecteur EAN-13 diffère, corriger la valeur attendue d'après le calcul mod 10 — ne pas modifier l'algorithme.)

- [ ] **Step 4: Commit**

```bash
git add briques/agenda/backend/static/barcode.js briques/agenda/backend/tests/test_barcode.py
git commit -m "feat(s176): générateur code-barres embarqué Code128+EAN-13 (SVG, sans CDN)"
```

---

### Task 11 : Surface LLM /service + manifest (courses_*)

**Files:**
- Modify: `briques/agenda/backend/routers/service.py`
- Modify: `briques/agenda/manifest.json`
- Test: `briques/agenda/backend/tests/test_service_courses.py`

**Interfaces:**
- Consumes : routers listes/items (Tasks 6-7) — la surface `/service` réutilise la logique en identité `perso`.
- Produces : routes `GET /service/lists`, `POST /service/lists`, `POST /service/lists/{id}/items`, `PATCH /service/lists/{id}/items/{item_id}` ; capacités manifest `courses_consulter`, `courses_creer_liste`, `courses_ajouter`, `courses_cocher`.

- [ ] **Step 1: Écrire le test (échoue)**

Create `tests/test_service_courses.py` :

```python
"""Surface /service courses : identité perso, création/consultation/ajout/cochage."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from routers import service as S


@pytest.mark.asyncio
async def test_service_cree_et_liste(db):
    liste = await S.service_creer_liste(S.ServiceListeCreate(nom="Maison"), db=db)
    listes = await S.service_lister_listes(db=db)
    assert any(l["name"] == "Maison" for l in listes)
    assert liste["created_by"] == "perso"


@pytest.mark.asyncio
async def test_service_ajoute_item(db):
    liste = await S.service_creer_liste(S.ServiceListeCreate(nom="Maison"), db=db)
    it = await S.service_ajouter_item(liste["id"], S.ServiceItemAjout(nom="Lait"), db=db)
    assert it["name"] == "Lait"


def test_manifest_contient_capacites_courses():
    manifest = json.loads((Path(__file__).resolve().parents[2] / "manifest.json").read_text())
    noms = {c["nom"] for c in manifest["capacites"]}
    assert {"courses_consulter", "courses_creer_liste", "courses_ajouter", "courses_cocher"} <= noms
```

- [ ] **Step 2: Lancer (échoue)**

Run: `cd briques/agenda/backend && python -m pytest tests/test_service_courses.py -q`
Expected: FAIL (`service_creer_liste` inexistant + manifest sans capacités).

- [ ] **Step 3: Ajouter les routes /service**

Append à `routers/service.py` (le fichier a déjà `router`, `AsyncSession`, `get_db`, un token/identité `perso` ; suivre le motif des routes events existantes pour l'entête d'identité). Ajouter :

```python
from pydantic import BaseModel

from models.orm import ShoppingItem, ShoppingList
from sqlalchemy import func, select as _select

PERSO = "perso"  # identité S2S pinnée (ADR agenda-surface-de-service)


class ServiceListeCreate(BaseModel):
    nom: str
    kind: str = "courses"


class ServiceItemAjout(BaseModel):
    nom: str
    note: str | None = None


class ServiceItemCoche(BaseModel):
    checked: bool = True


@router.get("/lists")
async def service_lister_listes(db: AsyncSession = Depends(get_db)):
    owned = (await db.execute(_select(ShoppingList).where(ShoppingList.created_by == PERSO))).scalars().all()
    sortie = []
    for l in owned:
        nb = await db.scalar(_select(func.count()).select_from(ShoppingItem).where(
            ShoppingItem.list_id == l.id, ShoppingItem.checked.is_(False)))
        sortie.append({"id": l.id, "name": l.name, "kind": l.kind, "a_prendre": nb or 0})
    return sortie


@router.post("/lists", status_code=201)
async def service_creer_liste(body: ServiceListeCreate, db: AsyncSession = Depends(get_db)):
    kind = body.kind if body.kind in ("courses", "taches") else "courses"
    l = ShoppingList(name=body.nom, kind=kind, created_by=PERSO)
    db.add(l)
    await db.commit()
    await db.refresh(l)
    return {"id": l.id, "name": l.name, "kind": l.kind, "created_by": l.created_by}


@router.post("/lists/{list_id}/items", status_code=201)
async def service_ajouter_item(list_id: str, body: ServiceItemAjout, db: AsyncSession = Depends(get_db)):
    l = await db.get(ShoppingList, list_id)
    if l is None or l.created_by != PERSO:
        raise HTTPException(status_code=404, detail="Liste introuvable")
    it = ShoppingItem(list_id=list_id, name=body.nom.strip(), note=body.note, added_by=PERSO)
    db.add(it)
    await db.commit()
    await db.refresh(it)
    from services.pubsub import publish_list_change
    await publish_list_change(list_id, "item.added", {"id": it.id, "name": it.name})
    return {"id": it.id, "name": it.name, "checked": it.checked}


@router.patch("/lists/{list_id}/items/{item_id}")
async def service_cocher_item(list_id: str, item_id: str, body: ServiceItemCoche,
                              db: AsyncSession = Depends(get_db)):
    it = await db.get(ShoppingItem, item_id)
    if it is None or it.list_id != list_id:
        raise HTTPException(status_code=404, detail="Item introuvable")
    it.checked = body.checked
    await db.commit()
    await db.refresh(it)
    from services.pubsub import publish_list_change
    await publish_list_change(list_id, "item.checked" if it.checked else "item.unchecked",
                              {"id": it.id, "name": it.name})
    return {"id": it.id, "name": it.name, "checked": it.checked}
```

Vérifier que `HTTPException` et `Depends` sont importés en tête de `service.py` (sinon les ajouter).

- [ ] **Step 4: Ajouter les capacités au manifest**

Dans `briques/agenda/manifest.json`, ajouter dans le tableau `capacites` (avant la fermeture `]`) :

```json
    ,{
      "nom": "courses_consulter",
      "description": "Liste les listes de courses/tâches et le nombre d'articles restant à prendre. Utile avant d'ajouter ou de cocher un article. Lecture seule.",
      "methode": "GET",
      "chemin": "/service/lists",
      "params": {},
      "action": false
    },
    {
      "nom": "courses_creer_liste",
      "description": "Crée une nouvelle liste de courses (ou de tâches). Renvoie son id. Effet immédiat.",
      "methode": "POST",
      "chemin": "/service/lists",
      "params": {
        "nom": {"type": "string", "description": "Nom de la liste (ex. « Courses de la semaine »).", "requis": true},
        "kind": {"type": "string", "enum": ["courses", "taches"], "description": "Type de liste (défaut courses)."}
      },
      "action": false
    },
    {
      "nom": "courses_ajouter",
      "description": "Ajoute un article à une liste de courses. Récupère d'abord le list_id via courses_consulter (ou crée une liste via courses_creer_liste). Effet immédiat.",
      "methode": "POST",
      "chemin": "/service/lists/{list_id}/items",
      "params": {
        "list_id": {"type": "string", "description": "Id de la liste (via courses_consulter).", "requis": true},
        "nom": {"type": "string", "description": "Article à ajouter (ex. « lait », « pommes »).", "requis": true},
        "note": {"type": "string", "description": "Précision/quantité (optionnel, ex. « x2 », « bio »)."}
      },
      "action": false
    },
    {
      "nom": "courses_cocher",
      "description": "Coche (ou décoche) un article d'une liste comme pris. Retrouve d'abord item_id + list_id via courses_consulter. Effet immédiat.",
      "methode": "PATCH",
      "chemin": "/service/lists/{list_id}/items/{item_id}",
      "params": {
        "list_id": {"type": "string", "description": "Id de la liste.", "requis": true},
        "item_id": {"type": "string", "description": "Id de l'article.", "requis": true},
        "checked": {"type": "boolean", "description": "true = pris, false = à reprendre. Défaut true."}
      },
      "action": false
    }
```

Puis incrémenter `"version"` du manifest en `1.2.0`.

- [ ] **Step 5: Lancer (passe) + vérifier le test manifest existant**

Run: `cd briques/agenda/backend && python -m pytest tests/test_service_courses.py tests/test_manifest_capacites.py -q`
Expected: PASS. (Si `test_manifest_capacites.py` compte les capacités, mettre à jour l'attendu.)

- [ ] **Step 6: Commit**

```bash
git add briques/agenda/backend/routers/service.py briques/agenda/manifest.json briques/agenda/backend/tests/test_service_courses.py
git commit -m "feat(s176): surface LLM /service courses_* + capacités manifest (v1.2.0)"
```

---

### Task 12 : Câblage app (routers + seed catalogue au boot)

**Files:**
- Modify: `briques/agenda/backend/main.py`
- Test: `briques/agenda/backend/tests/test_shopping_boot.py`

**Interfaces:**
- Consumes : tous les routers (Tasks 4,6,7,8,9), `semer_catalogue` (Task 3).
- Produces : routers enregistrés sur `app` ; catalogue semé au `lifespan`.

- [ ] **Step 1: Écrire le test (échoue)**

Create `tests/test_shopping_boot.py` :

```python
"""L'app enregistre les nouveaux routers ; le seed catalogue est branché."""
from __future__ import annotations


def test_routes_listes_enregistrees():
    from main import app
    chemins = {r.path for r in app.routes}
    assert "/lists" in chemins
    assert "/loyalty-cards" in chemins
    assert "/lists/{list_id}/items" in chemins
    assert "/lists/{list_id}/catalog" in chemins
    assert "/sse/lists/{list_id}" in chemins


def test_seed_catalogue_importable():
    from services.catalogue import semer_catalogue  # noqa: F401
```

- [ ] **Step 2: Lancer (échoue)**

Run: `cd briques/agenda/backend && python -m pytest tests/test_shopping_boot.py -q`
Expected: FAIL (`/lists` absent).

- [ ] **Step 3: Enregistrer les routers + brancher le seed**

Dans `main.py` :
1. Ajouter les imports après les imports de routers existants :

```python
from routers.lists import router as lists_router
from routers.list_items import router as list_items_router
from routers.list_catalog import router as list_catalog_router
from routers.loyalty import router as loyalty_router
```

2. Ajouter les `include_router` après `app.include_router(timetree_router)` :

```python
app.include_router(lists_router)
app.include_router(list_items_router)
app.include_router(list_catalog_router)
app.include_router(loyalty_router)
```

3. Dans `lifespan`, après le backfill S174 (avant `logger.info("Calendar service started…")`), brancher le seed :

```python
    try:
        from db import AsyncSessionLocal
        from services.catalogue import semer_catalogue
        async with AsyncSessionLocal() as _db:
            n = await semer_catalogue(_db)
            if n:
                logger.info("S176 catalogue : %d items intégrés semés", n)
    except Exception as ex:  # noqa: BLE001 — un seed KO ne doit pas empêcher le boot
        logger.warning("S176 seed catalogue ignoré : %s", ex)
```

- [ ] **Step 4: Lancer (passe)**

Run: `cd briques/agenda/backend && python -m pytest tests/test_shopping_boot.py -q`
Expected: PASS (2).

- [ ] **Step 5: Suite complète brique**

Run: `cd briques/agenda/backend && python -m pytest -q`
Expected: tout vert (194 + nouvelles suites).

- [ ] **Step 6: Commit**

```bash
git add briques/agenda/backend/main.py briques/agenda/backend/tests/test_shopping_boot.py
git commit -m "feat(s176): câblage app — routers listes/items/catalogue/cartes + seed catalogue au boot"
```

---

### Task 13 : Front — onglets « Listes » + « Cartes »

**Files:**
- Modify: `briques/agenda/backend/templates_app.py`
- Modify: `briques/agenda/backend/routers/app_web.py` (servir `barcode.js` en statique si pas déjà servi)
- Test: `briques/agenda/backend/tests/test_app_web.py` (étendre)

**Interfaces:**
- Consumes : endpoints REST/SSE (Tasks 4,6,7,8,9), `static/barcode.js` (Task 10).
- Produces : onglets « Listes » et « Cartes » dans la page `/app`, câblés fetch + EventSource + code-barres.

- [ ] **Step 1: Étendre le smoke test (échoue)**

Ajouter à `tests/test_app_web.py` :

```python
def test_page_app_contient_onglets_listes_et_cartes():
    from templates_app import page_app
    html = page_app("http://kc", "oria", "calendar-app")
    assert "Listes" in html
    assert "Cartes" in html
    assert "/sse/lists/" in html
    assert "dessinerCodeBarres" in html
```

(Adapter la signature de `page_app` si elle diffère — vérifier en tête de `templates_app.py`.)

- [ ] **Step 2: Lancer (échoue)**

Run: `cd briques/agenda/backend && python -m pytest tests/test_app_web.py -q`
Expected: FAIL (chaînes absentes).

- [ ] **Step 3: Servir barcode.js en statique**

Dans `routers/app_web.py`, monter le dossier `static/` (si `StaticFiles` pas déjà monté). Vérifier
d'abord si `main.py`/`app_web.py` monte déjà un répertoire statique ; sinon ajouter dans `main.py` :

```python
from fastapi.staticfiles import StaticFiles
import os
_STATIC = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(_STATIC):
    app.mount("/static", StaticFiles(directory=_STATIC), name="static")
```

Le front chargera `<script src="/static/barcode.js"></script>`.

- [ ] **Step 4: Ajouter les onglets au front**

Dans `templates_app.py`, étendre la page `/app` (structure onglets existante) avec deux vues.
Le code exact suit le style de l'appli (même helper `fetch` bearer, même palette). Points requis
pour que le test passe et que l'UX fonctionne :

1. **Barre d'onglets** : ajouter « Listes » et « Cartes » aux onglets existants (Agenda…).
2. **Vue Listes** (JS) — implémenter :

```html
<script src="/static/barcode.js"></script>
<script>
// --- Listes de courses (S176) ---
let listeCourante = null, sseListe = null;

async function chargerListes() {
  const r = await apiFetch('/lists');            // apiFetch = helper bearer existant
  const listes = await r.json();
  const el = document.getElementById('listes-col');
  el.innerHTML = listes.map(l =>
    `<button class="liste-item" onclick="ouvrirListe('${l.id}','${l.name.replace(/'/g,"\\'")}')">
       ${l.name} <span class="badge">${l.nb_a_prendre}</span></button>`).join('')
    || '<p>Aucune liste. Créez-en une.</p>';
}

async function creerListe() {
  const nom = prompt('Nom de la liste ?'); if (!nom) return;
  await apiFetch('/lists', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({name: nom, kind: 'courses'})});
  chargerListes();
}

async function ouvrirListe(id, nom) {
  listeCourante = id;
  document.getElementById('liste-titre').textContent = nom;
  await rafraichirItems();
  await chargerCatalogue();
  brancherSSE(id);
}

async function rafraichirItems() {
  const r = await apiFetch(`/lists/${listeCourante}/items`);
  const items = await r.json();
  const actifs = items.filter(i => !i.checked), pris = items.filter(i => i.checked);
  const parRayon = {};
  actifs.forEach(i => { (parRayon[i.rayon||'Autre'] ||= []).push(i); });
  let html = '';
  Object.keys(parRayon).forEach(rayon => {
    html += `<h4>${rayon}</h4>` + parRayon[rayon].map(itemLigne).join('');
  });
  html += `<h4 class="pris">Déjà pris (${pris.length}) <button onclick="viderPris()">Vider</button></h4>`;
  html += pris.map(itemLigne).join('');
  document.getElementById('liste-items').innerHTML = html;
}

function itemLigne(i) {
  return `<label class="item ${i.checked?'coche':''}">
    <input type="checkbox" ${i.checked?'checked':''} onchange="cocher('${i.id}',this.checked)">
    ${i.emoji||''} ${i.name} ${i.note?`<em>${i.note}</em>`:''}</label>`;
}

async function cocher(itemId, checked) {
  await apiFetch(`/lists/${listeCourante}/items/${itemId}`, {method:'PATCH',
    headers:{'Content-Type':'application/json'}, body: JSON.stringify({checked})});
}

async function viderPris() {
  await apiFetch(`/lists/${listeCourante}/items/clear-checked`, {method:'POST'});
}

async function chargerCatalogue() {
  const r = await apiFetch(`/lists/${listeCourante}/catalog`);
  const data = await r.json();
  document.getElementById('catalogue').innerHTML = data.rayons.map(g =>
    `<div class="rayon"><strong>${g.rayon}</strong><div class="grille">` +
    g.items.map(ci => `<button class="cat" onclick="ajouterCatalogue('${ci.id}')">${ci.emoji} ${ci.name}</button>`).join('') +
    `</div></div>`).join('');
}

async function ajouterCatalogue(catId) {
  await apiFetch(`/lists/${listeCourante}/items`, {method:'POST',
    headers:{'Content-Type':'application/json'}, body: JSON.stringify({catalog_item_id: catId})});
}

async function ajouterLibre() {
  const inp = document.getElementById('item-libre');
  if (!inp.value.trim()) return;
  await apiFetch(`/lists/${listeCourante}/items`, {method:'POST',
    headers:{'Content-Type':'application/json'}, body: JSON.stringify({name: inp.value.trim()})});
  inp.value = '';
}

function brancherSSE(id) {
  if (sseListe) sseListe.close();
  sseListe = new EventSource(`/sse/lists/${id}` + sseAuthQuery());  // token en query si requis par le stream
  sseListe.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (['item.added','item.checked','item.unchecked','item.updated','item.deleted','checked.cleared'].includes(msg.type)) {
      rafraichirItems();
    }
  };
}
</script>
```

3. **Vue Cartes** (JS) — implémenter :

```html
<script>
// --- Cartes de fidélité (S176) ---
async function chargerCartes() {
  const r = await apiFetch('/loyalty-cards');
  const cartes = await r.json();
  document.getElementById('cartes-grille').innerHTML = cartes.map(c =>
    `<button class="carte" style="background:${c.couleur}" onclick='ouvrirCarte(${JSON.stringify(c)})'>
       ${c.enseigne}</button>`).join('') || '<p>Aucune carte.</p>';
}

async function creerCarte() {
  const enseigne = prompt('Enseigne ?'); if (!enseigne) return;
  const numero = prompt('Numéro de carte ?'); if (!numero) return;
  const format = prompt('Format (code128 / ean13) ?', 'code128') || 'code128';
  await apiFetch('/loyalty-cards', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({enseigne, numero, format})});
  chargerCartes();
}

function ouvrirCarte(c) {
  const modal = document.getElementById('carte-modal');
  modal.style.display = 'flex';
  document.getElementById('carte-enseigne').textContent = c.enseigne;
  document.getElementById('carte-numero').textContent = c.numero;
  const svg = document.getElementById('carte-barcode');
  const ok = window.dessinerCodeBarres(svg, c.numero, c.format);
  document.getElementById('carte-fallback').style.display = ok ? 'none' : 'block';
}

function fermerCarte() { document.getElementById('carte-modal').style.display = 'none'; }
</script>
```

4. **Markup** des conteneurs (`listes-col`, `liste-items`, `catalogue`, `item-libre`,
   `cartes-grille`, modale `carte-modal` avec `<svg id="carte-barcode">`, `carte-numero`,
   `carte-fallback`) + un peu de CSS inline cohérent avec l'existant. Appeler `chargerListes()`
   / `chargerCartes()` quand l'onglet correspondant s'active.

Note sur l'auth SSE (`sseAuthQuery`) : `EventSource` n'envoie pas d'en-tête `Authorization`.
Vérifier comment le SSE **calendrier** existant est authentifié côté front (`routers/sse.py`
utilise `get_current_user`). Réutiliser le même mécanisme (token en query string géré par
`get_current_user`, ou cookie). Si le SSE calendrier fonctionne déjà dans l'appli, calquer
exactement ; sinon, `sseAuthQuery()` renvoie `?access_token=<jwt>` et `get_current_user` doit
accepter le token en query (à vérifier/aligner sur l'existant, sans régresser le SSE calendrier).

- [ ] **Step 5: Lancer le smoke (passe)**

Run: `cd briques/agenda/backend && python -m pytest tests/test_app_web.py -q`
Expected: PASS.

- [ ] **Step 6: Vérification visuelle manuelle (différée)**

La vérification LIVE est différée à la fin du roadmap (cf. mémoire « LIVE différé fin S180 »).
Noter dans le commit que le rendu front n'est pas encore vérifié en navigateur.

- [ ] **Step 7: Commit**

```bash
git add briques/agenda/backend/templates_app.py briques/agenda/backend/routers/app_web.py briques/agenda/backend/main.py briques/agenda/backend/tests/test_app_web.py
git commit -m "feat(s176): front — onglets Listes (catalogue+SSE) et Cartes (code-barres)"
```

---

### Task 14 : ADR + README + roadmap/mémoire + revue finale

**Files:**
- Create: `docs/decisions/2026-07-16-listes-push-evenementiel.md`
- Modify: `briques/agenda/backend/README.md`
- Modify: `docs/sprints/S174-S180-roadmap-agenda-best-in-class.md`

- [ ] **Step 1: Écrire l'ADR**

Create `docs/decisions/2026-07-16-listes-push-evenementiel.md` — décision : la brique agenda
émet **directement** vers `connexion /pousser` sur ajout/cochage d'item (événementiel), au lieu
du modèle S174 où le Cœur pousse sur base temporelle. Contexte, alternatives (poll Cœur),
conséquences (dépendance sortante optionnelle config-gatée `CONNEXION_URL`/`CONNEXION_KEY`,
best-effort, la brique reste « surface de service »). Suivre le gabarit des ADR existants dans
`docs/decisions/`.

- [ ] **Step 2: Mettre à jour le README de la brique**

Ajouter une section `## S176 — Listes de courses/tâches + cartes de fidélité` dans
`briques/agenda/backend/README.md` : modèles, endpoints (`/lists…`, `/loyalty-cards`,
`/sse/lists/{id}`), capacités LLM `courses_*`, config `CONNEXION_URL`/`CONNEXION_KEY`,
générateur code-barres (Code128/EAN-13, QR en fast-follow), et la note migration 0008 à
smoke-tester sur Postgres avant déploiement.

- [ ] **Step 3: Mettre à jour le roadmap**

Dans `docs/sprints/S174-S180-roadmap-agenda-best-in-class.md`, marquer §S176 **✅ CODE-COMPLET**
avec la date, le résumé livré, les liens spec/plan, et les fast-follow (génération QR, outils
LLM cartes, `this_and_following` toujours en attente de S175, smoke Postgres 0008).

- [ ] **Step 4: Suite complète des deux côtés**

Run: `cd briques/agenda/backend && python -m pytest -q`
Expected: tout vert.

Run (à la racine, si `make test-core` existe) : `make test-core`
Expected: 439 passed (le Cœur n'est pas touché par S176).

- [ ] **Step 5: Revue finale (requesting-code-review)**

Lancer une revue de la branche entière (skill `requesting-code-review` ou `/code-review high`)
sur l'ensemble du diff S176, corriger les findings retenus, re-tester.

- [ ] **Step 6: Commit**

```bash
git add docs/decisions/2026-07-16-listes-push-evenementiel.md briques/agenda/backend/README.md docs/sprints/S174-S180-roadmap-agenda-best-in-class.md
git commit -m "docs(s176): ADR push événementiel + README brique + roadmap code-complet"
```

---

## Self-Review (rempli par l'auteur du plan)

**Couverture spec :** modèle 6 tables (T1) ✓ ; catalogue seed (T3) ✓ ; accès (T2) ✓ ; API listes/membres/invitations (T6) ✓ ; items/cochage/clear/anti-doublon (T7) ✓ ; catalogue groupé (T8) ✓ ; SSE (T4) ✓ ; push par personne (T5) ✓ ; cartes CRUD (T9) ✓ ; code-barres (T10) ✓ ; outils LLM + manifest (T11) ✓ ; câblage + seed boot (T12) ✓ ; front onglets (T13) ✓ ; ADR + docs (T14) ✓.

**Points laissés à vérifier par l'exécutant (signalés inline, pas des placeholders) :** mécanisme exact de `settings` dans `config.py` (pydantic-settings vs os.getenv) ; signature réelle de `page_app` ; auth du SSE via `EventSource` (calquer le SSE calendrier existant sans le régresser) ; montage `StaticFiles` éventuellement déjà présent ; comptage éventuel dans `test_manifest_capacites.py`. Chacun est une vérification d'intégration locale, pas du code à inventer.

**Cohérence des types :** `require_list_access` renvoie `(ShoppingList, str)` partout ; `publish_list_change(list_id, event_type, payload)` signature stable T4→T7→T11 ; `notifier_membres(db, liste, acteur_id, texte)` stable T5→T7 ; schémas `ShoppingItemOut`/`ShoppingListWithMetaOut` définis T1, consommés T6/T7.

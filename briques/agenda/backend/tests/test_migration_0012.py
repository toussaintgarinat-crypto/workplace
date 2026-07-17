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

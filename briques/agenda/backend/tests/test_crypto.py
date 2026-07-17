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

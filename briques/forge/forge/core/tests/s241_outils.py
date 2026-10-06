"""Outils de test S241 : base et Qdrant RÉELS (lanceur scripts/en_docker.sh), embedder factice.

Les tests qui s'en servent portent le marqueur `integration` : hors du lanceur (variable
FORGE_TEST_INTEGRATION absente), ils sont sautés et le filet scripts/tests_briques.sh reste vert.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text

integration = pytest.mark.skipif(
    not os.environ.get("FORGE_TEST_INTEGRATION"),
    reason="test d'intégration : lancer via scripts/en_docker.sh (Postgres + Qdrant réels)",
)

DIMENSION = 384


def vecteur_factice(texte: str) -> list[float]:
    """Sac de mots haché en 384 dimensions, normalisé : déterministe, sans réseau. Deux textes
    qui partagent des mots sont proches ; ce n'est PAS de la sémantique (mesurée à part)."""
    v = [0.0] * DIMENSION
    for mot in re.findall(r"\w+", texte.lower()):
        v[int(hashlib.md5(mot.encode()).hexdigest(), 16) % DIMENSION] += 1.0
    n = math.sqrt(sum(x * x for x in v))
    if n == 0:
        v[0], n = 1.0, 1.0
    return [x / n for x in v]


@pytest_asyncio.fixture
async def base():
    """Schéma S241 appliqué, tables documentaires vides, collection Qdrant locale supprimée."""
    from app import db, memory
    from scripts.init_db import appliquer_schema

    async with db.engine.begin() as conn:
        await appliquer_schema(conn)
        await conn.execute(text("TRUNCATE documents, kb_articles CASCADE"))
    memory._qdrant = None
    client = memory._client()
    if await client.collection_exists("forge_local"):
        await client.delete_collection("forge_local")
    yield
    # Pool et client liés à la boucle du test : on les ferme pour que le test suivant (nouvelle
    # boucle) ne réutilise pas une connexion d'une boucle morte.
    await db.engine.dispose()
    if memory._qdrant is not None:
        await memory._qdrant.close()
        memory._qdrant = None


@pytest.fixture
def embedder_factice(monkeypatch):
    from app import memory

    async def _faux(textes, provider):
        return [vecteur_factice(t) for t in textes]

    monkeypatch.setattr(memory, "_embed_batch", _faux)
    monkeypatch.setattr(memory, "available_providers", lambda: ["local"])
    monkeypatch.setattr(memory, "resolve_provider", lambda preferred=None: "local")


@pytest.fixture
def embedder_coupe(monkeypatch):
    from app import memory

    async def _panne(textes, provider):
        raise RuntimeError("gateway injoignable")

    monkeypatch.setattr(memory, "_embed_batch", _panne)
    monkeypatch.setattr(memory, "available_providers", lambda: ["local"])
    monkeypatch.setattr(memory, "resolve_provider", lambda preferred=None: "local")


async def ajouter_document(user_id: str, nom: str, contenu: str) -> uuid.UUID:
    from app.db import SessionLocal
    from app.models import Documents

    async with SessionLocal() as s:
        d = Documents(user_id=user_id, nom=nom, contenu=contenu, taille=len(contenu))
        s.add(d)
        await s.commit()
        await s.refresh(d)
        return d.id


async def ajouter_article(user_id: str, titre: str, contenu: str, tags: str = "[]") -> uuid.UUID:
    from app.db import SessionLocal
    from app.models import KbArticles

    async with SessionLocal() as s:
        a = KbArticles(user_id=user_id, titre=titre, contenu=contenu, tags=tags)
        s.add(a)
        await s.commit()
        await s.refresh(a)
        return a.id

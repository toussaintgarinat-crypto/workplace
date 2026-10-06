"""Réconciliation PostgreSQL → Qdrant (S241).

PostgreSQL fait foi ; Qdrant n'est qu'un index reconstructible. Les ingestions des routers
documents/kb partent en tâche de fond et ne sont jamais relancées en cas d'échec : cette
tâche, toutes les 10 minutes, revectorise ce qui manque ou est mal attribué et supprime les
fragments orphelins. Elle s'arrête au premier échec de l'embedder (reprise au passage suivant).
"""
from __future__ import annotations

import asyncio
import logging

from qdrant_client.http import models as qm
from sqlalchemy import text

from app import memory
from app.db import SessionLocal

logger = logging.getLogger(__name__)

INTERVALLE = 600
LOT = 50
# type de source Qdrant → (table, colonne du titre)
_TABLES = {"document": ("documents", "nom"), "kb_article": ("kb_articles", "titre")}


async def _points_indexes(nom: str) -> dict[str, set[str]]:
    """source_id → ensemble des user_id portés par ses fragments (types indexés seulement)."""
    client = memory._client()
    if not await client.collection_exists(nom):
        return {}
    filtre = qm.Filter(must=[qm.FieldCondition(
        key="source_type", match=qm.MatchAny(any=list(memory.SOURCES_INDEXEES)))])
    indexes: dict[str, set[str]] = {}
    decalage = None
    while True:
        points, decalage = await client.scroll(
            nom, scroll_filter=filtre, limit=256, offset=decalage,
            with_payload=["source_id", "user_id"], with_vectors=False,
        )
        for p in points:
            charge = p.payload or {}
            indexes.setdefault(str(charge.get("source_id")), set()).add(str(charge.get("user_id")))
        if decalage is None:
            return indexes


async def _sources() -> dict[str, tuple[str, str, str, str]]:
    """source_id → (source_type, user_id, titre, contenu) depuis PostgreSQL."""
    sources = {}
    async with SessionLocal() as s:
        for source_type, (table, titre) in _TABLES.items():
            lignes = await s.execute(text(f"SELECT id, user_id, {titre}, coalesce(contenu, '') FROM {table}"))
            for r in lignes.all():
                sources[str(r[0])] = (source_type, r[1], r[2] or "", r[3])
    return sources


async def reconcilier_index(lot: int = LOT) -> dict:
    _, nom = memory.collection_active()
    bilan = {"revectorises": 0, "orphelins_supprimes": 0, "restants": 0, "arret_sur_echec": False}
    try:
        indexes = await _points_indexes(nom)
    except Exception as e:  # noqa: BLE001 — Qdrant injoignable : on réessaiera
        logger.warning("[forge:reconciliation] Qdrant injoignable : %s", str(e)[:160])
        bilan["arret_sur_echec"] = True
        return bilan
    sources = await _sources()

    for source_id in [sid for sid in indexes if sid not in sources]:
        await memory.delete_by_source(source_id)
        bilan["orphelins_supprimes"] += 1

    a_faire = [sid for sid, (_, user_id, _, contenu) in sources.items()
               if memory.chunk_text(contenu) and indexes.get(sid) != {user_id}]
    for source_id in a_faire[:lot]:
        source_type, user_id, titre, contenu = sources[source_id]
        try:
            await memory.indexer_source(contenu, source_id, source_type, user_id, titre)
        except memory.RechercheVectorielleIndisponible as e:
            logger.warning("[forge:reconciliation] embedder indisponible, arrêt : %s", str(e)[:160])
            bilan["arret_sur_echec"] = True
            break
        bilan["revectorises"] += 1
    bilan["restants"] = len(a_faire) - bilan["revectorises"]
    logger.info("[forge:reconciliation] %s", bilan)
    return bilan


async def boucle_reconciliation(intervalle: float = INTERVALLE) -> None:
    while True:
        try:
            await reconcilier_index()
        except Exception as e:  # noqa: BLE001 — la boucle ne meurt jamais
            logger.warning("[forge:reconciliation] passage en échec : %s", str(e)[:160])
        await asyncio.sleep(intervalle)

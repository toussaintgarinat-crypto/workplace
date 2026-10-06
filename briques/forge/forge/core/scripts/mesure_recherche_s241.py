"""Mesure S241 : rappel@5 de la recherche Forge sur un jeu fixe (exacte, sens, faute de frappe).

Trois modes : « hybride » (embedder RÉEL de la Gateway — seulement si GATEWAY_API_KEY est
transmise), « lexical » (embedder coupé) et « LIKE » (l'ancienne recherche /api/search :
LIKE sensible à la casse, sans tolérance de faute). À lancer via le lanceur :
    scripts/en_docker.sh python -m scripts.mesure_recherche_s241
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from sqlalchemy import text

from app import memory
from app.db import SessionLocal, engine
from app.models import Documents
from app.recherche_service import rechercher
from scripts.init_db import appliquer_schema

JEU = json.loads((Path(__file__).with_suffix(".json")).read_text(encoding="utf-8"))
UTILISATEUR = "mesure-s241"
TYPES = ("exacte", "semantique", "faute")


async def _charger() -> dict[str, str]:
    async with engine.begin() as conn:
        await appliquer_schema(conn)
        await conn.execute(text("DELETE FROM documents WHERE user_id = :u"), {"u": UTILISATEUR})
    ids = {}
    async with SessionLocal() as s:
        for d in JEU["documents"]:
            doc = Documents(user_id=UTILISATEUR, nom=d["nom"], contenu=d["contenu"], taille=len(d["contenu"]))
            s.add(doc)
            await s.flush()
            ids[str(doc.id)] = d["cle"]
        await s.commit()
    return ids


async def _like(q: str, ids: dict[str, str]) -> list[str]:
    async with SessionLocal() as s:
        lignes = await s.execute(text(
            "SELECT id FROM documents WHERE user_id = :u AND (nom LIKE :p OR contenu LIKE :p) LIMIT 5"),
            {"u": UTILISATEUR, "p": f"%{q}%"})
        return [ids[str(r[0])] for r in lignes.all()]


async def _moteur(q: str, ids: dict[str, str]) -> list[str]:
    rep = await rechercher(q, UTILISATEUR, 5)
    return [ids[r["id"]] for r in rep["resultats"]]


async def _rappel(chercheur, ids) -> dict[str, float]:
    par_type = {}
    for t in TYPES:
        requetes = [r for r in JEU["requetes"] if r["type"] == t]
        trouves = 0
        for r in requetes:
            if r["attendu"] in await chercheur(r["q"], ids):
                trouves += 1
        par_type[t] = trouves / len(requetes)
    return par_type


async def principal() -> None:
    ids = await _charger()
    lignes = []
    if os.environ.get("GATEWAY_API_KEY"):
        for doc_id, cle in ids.items():
            d = next(x for x in JEU["documents"] if x["cle"] == cle)
            await memory.indexer_source(d["contenu"], doc_id, "document", UTILISATEUR, d["nom"])
        lignes.append(("hybride (embedder réel)", await _rappel(_moteur, ids)))
    else:
        lignes.append(("hybride (embedder réel)", None))

    async def _panne(textes, provider):
        raise RuntimeError("embedder coupé pour la mesure")

    memory._embed_batch = _panne
    lignes.append(("lexical (embedder coupé)", await _rappel(_moteur, ids)))
    lignes.append(("ancien LIKE", await _rappel(_like, ids)))

    print("| Mode | Exacte | Sens | Faute de frappe |")
    print("|---|---|---|---|")
    for nom, r in lignes:
        if r is None:
            print(f"| {nom} | non mesuré (GATEWAY_API_KEY absente) | | |")
        else:
            print(f"| {nom} | {r['exacte']:.2f} | {r['semantique']:.2f} | {r['faute']:.2f} |")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(principal())

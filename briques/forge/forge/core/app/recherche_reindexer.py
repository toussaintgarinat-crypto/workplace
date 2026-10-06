"""Reconstruction de l'index vectoriel de la recherche (S241) — commande d'exploitation.

La Forge n'a pas de rôle admin : pas de route HTTP. Usage dans le conteneur :
    docker exec forge-forge-1 python -m app.recherche_reindexer [--user <id>]
Vide les fragments (d'un utilisateur, ou tous les types indexés) de la collection active,
puis enchaîne la réconciliation jusqu'au bout. PostgreSQL n'est jamais modifié.
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from qdrant_client.http import models as qm

from app import memory
from app.reconciliation import reconcilier_index


async def principal(user_id: str | None = None) -> int:
    _, nom = memory.collection_active()
    client = memory._client()
    if await client.collection_exists(nom):
        champ, valeur = (("user_id", qm.MatchValue(value=user_id)) if user_id
                         else ("source_type", qm.MatchAny(any=list(memory.SOURCES_INDEXEES))))
        await client.delete(nom, points_selector=qm.FilterSelector(
            filter=qm.Filter(must=[qm.FieldCondition(key=champ, match=valeur)])))
    total = 0
    while True:
        bilan = await reconcilier_index()
        total += bilan["revectorises"]
        if bilan["arret_sur_echec"]:
            print(f"✗ arrêt : embedder ou Qdrant indisponible ({total} source(s) revectorisée(s))")
            return 1
        if bilan["restants"] == 0:
            print(f"✓ {total} source(s) revectorisée(s) dans {nom}")
            return 0


if __name__ == "__main__":
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument("--user", default=None, help="ne reconstruire que cet utilisateur")
    sys.exit(asyncio.run(principal(analyseur.parse_args().user)))

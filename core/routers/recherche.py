"""Route « recherche » du Cœur (S241) : recherche unifiée Forge + Ingestion + Mémoire.

Session obligatoire (401 sinon, appelée en `fetch` par l'onglet Recherche du tableau de
bord). Monté avec `lire_contexte_tenant` : l'identité de la session part vers la Mémoire
(X-User-Id) et, s'il y en a un, le jeton utilisateur vers la Forge.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

import auth
import recherche_unifiee
from etat import registre

router = APIRouter()


@router.get("/recherche", tags=["recherche"], dependencies=[Depends(auth.exiger_session_api)])
async def recherche(q: str = "", limite: int = 10, sources: str | None = None):
    """`sources` : liste séparée par des virgules parmi `forge`, `ingestion`, `memoire`."""
    choisies = {s.strip() for s in sources.split(",") if s.strip()} if sources else None
    try:
        return await recherche_unifiee.rechercher(q, registre, limite, choisies)
    except recherche_unifiee.ToutesSourcesIndisponibles as e:
        raise HTTPException(503, "Recherche indisponible : aucune source n'a répondu "
                                 f"({', '.join(e.args[0])}).") from None
    except ValueError as e:  # source inconnue demandée
        raise HTTPException(422, str(e)) from None

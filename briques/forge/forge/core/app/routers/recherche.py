"""Router recherche documentaire hybride (S241). Monté /api, protégé.

Documents + base de connaissances de l'utilisateur courant : références exactes en tête,
plein texte et fautes de frappe (PostgreSQL), sens (Qdrant filtré par utilisateur), fusion RRF.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth import UserContext, get_current_user
from app.recherche_service import SOURCES, rechercher

router = APIRouter()


@router.get("/recherche/hybride", dependencies=[Depends(get_current_user)])
async def recherche_hybride(q: str = "", limite: int = 10, sources: str | None = None,
                            user: UserContext = Depends(get_current_user)):
    """`sources` : liste séparée par des virgules parmi `document`, `kb` (défaut : les deux)."""
    choisies = (frozenset(x.strip() for x in sources.split(",") if x.strip()) & SOURCES
                if sources else SOURCES)
    return await rechercher(q, user.sub, limite, choisies)

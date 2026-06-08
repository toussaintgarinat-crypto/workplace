"""Router RAG — recherche sémantique sur les documents ingérés (Workplace S17).

Le core ne montait pas la récupération RAG en HTTP : ``memory.get_context`` n'était
consommé qu'en interne par le chat et le ReAct (ws). Workplace en a besoin pour le
contrat ``/rag/chercher`` de la brique (l'assistant du Cœur doit pouvoir « chercher
dans Forge » sans déclencher un agent). On expose donc la récupération en **lecture
seule, sans LLM** : recherche vectorielle Qdrant (+ enrichissement brique Mémoire).

Monté sous ``/api`` (et ``/v1/api``) comme les autres routers, protégé par auth.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.auth import UserContext, get_current_user
from app.memory import get_context

router = APIRouter()


@router.get("/rag/search", dependencies=[Depends(get_current_user)])
async def rag_search(request: Request, user: UserContext = Depends(get_current_user)):
    """Recherche sémantique : renvoie les passages pertinents des documents ingérés.

    Query params :
    - ``q``     : la question (obligatoire) ;
    - ``seuil`` : score minimal de pertinence (défaut 0.65, comme le core) ;
    - ``limite``: nombre max de passages (défaut 5).
    """
    q = (request.query_params.get("q") or "").strip()
    if not q:
        return {"query": "", "passages": "", "found": False}

    try:
        seuil = float(request.query_params.get("seuil", 0.65))
    except (TypeError, ValueError):
        seuil = 0.65
    try:
        limite = int(request.query_params.get("limite", 5))
    except (TypeError, ValueError):
        limite = 5

    passages = await get_context(
        q, _session_id=f"rag-search:{user.sub}", limit=limite, min_score=seuil
    )
    return {"query": q, "passages": passages, "found": bool(passages.strip())}

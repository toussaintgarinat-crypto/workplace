from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.database import get_db
from app.llm.embedder import EmbeddingIndisponible
from app.schemas.search import SearchResult, SemanticSearchRequest
from app.services.search_service import SearchService

router = APIRouter()


@router.get("", response_model=list[SearchResult])
async def search(
    space_id: UUID,
    response: Response,
    q: str = Query(""),
    type: str = Query(None),
    stage: str = Query(None),
    tier: str = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    svc = SearchService(db)
    resultat = await svc.hybrid_search(space_id, q, type_filter=type, stage_filter=stage, tier_filter=tier, limit=limit)
    # « lexical » = embedder injoignable : résultats par les mots seulement (S238).
    response.headers["X-Memoire-Mode"] = resultat.mode
    return resultat.resultats


@router.post("/semantic", response_model=list[SearchResult])
async def semantic_search(space_id: UUID, req: SemanticSearchRequest, db: AsyncSession = Depends(get_db)):
    svc = SearchService(db)
    try:
        return await svc.vector_search(space_id, req.query, limit=req.limit, stage_filter=req.stage_filter, type_filter=req.type_filter)
    except EmbeddingIndisponible:
        raise HTTPException(status_code=503, detail="Recherche sémantique indisponible (embedder injoignable).")

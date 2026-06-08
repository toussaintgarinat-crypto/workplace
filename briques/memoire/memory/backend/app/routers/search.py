from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.database import get_db
from app.schemas.search import SearchResult, SemanticSearchRequest
from app.services.search_service import SearchService

router = APIRouter()


@router.get("", response_model=list[SearchResult])
async def search(
    space_id: UUID,
    q: str = Query(""),
    type: str = Query(None),
    stage: str = Query(None),
    limit: int = Query(20),
    db: AsyncSession = Depends(get_db),
):
    svc = SearchService(db)
    return await svc.hybrid_search(space_id, q, type_filter=type, stage_filter=stage, limit=limit)


@router.post("/semantic", response_model=list[SearchResult])
async def semantic_search(space_id: UUID, req: SemanticSearchRequest, db: AsyncSession = Depends(get_db)):
    svc = SearchService(db)
    return await svc.vector_search(space_id, req.query, limit=req.limit, stage_filter=req.stage_filter, type_filter=req.type_filter)

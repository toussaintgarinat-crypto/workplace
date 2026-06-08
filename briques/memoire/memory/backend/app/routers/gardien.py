from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.database import get_db
from app.schemas.gardien import GardienConfig, GardienSuggestion, GardienLogEntry
from app.services.gardien_service import GardienService

router = APIRouter()


@router.get("/config", response_model=GardienConfig)
async def get_gardien_config(space_id: UUID, db: AsyncSession = Depends(get_db)):
    svc = GardienService(db)
    return await svc.load_config(space_id)


@router.put("/config", response_model=GardienConfig)
async def update_gardien_config(space_id: UUID, req: GardienConfig, db: AsyncSession = Depends(get_db)):
    svc = GardienService(db)
    return await svc.save_config(space_id, req)


@router.post("/run")
async def run_gardien(space_id: UUID, db: AsyncSession = Depends(get_db)):
    svc = GardienService(db)
    try:
        results = await svc.run(space_id)
        return {"detail": "Gardien run completed", "results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gardien run failed: {e}")


@router.get("/suggestions", response_model=list[GardienSuggestion])
async def get_suggestions(space_id: UUID, db: AsyncSession = Depends(get_db)):
    svc = GardienService(db)
    logs = await svc.get_suggestions(space_id)
    return [
        GardienSuggestion(
            id=log.id,
            action=log.action,
            node_id=log.node_id,
            details=log.details,
            status=log.status,
            created_at=log.created_at,
        )
        for log in logs
    ]


@router.post("/suggestions/{suggestion_id}/accept")
async def accept_suggestion(space_id: UUID, suggestion_id: UUID, db: AsyncSession = Depends(get_db)):
    svc = GardienService(db)
    success = await svc.execute_suggestion(suggestion_id)
    if not success:
        raise HTTPException(status_code=404, detail="Suggestion not found or already processed")
    return {"detail": "Suggestion accepted and executed"}


@router.post("/suggestions/{suggestion_id}/reject")
async def reject_suggestion(space_id: UUID, suggestion_id: UUID, db: AsyncSession = Depends(get_db)):
    svc = GardienService(db)
    result = await svc.get_suggestions(space_id)
    log = next((entry for entry in result if entry.id == suggestion_id), None)
    if not log:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    log.status = "rejected"
    await db.commit()
    return {"detail": "Suggestion rejected"}


@router.get("/log", response_model=list[GardienLogEntry])
async def get_gardien_log(space_id: UUID, db: AsyncSession = Depends(get_db)):
    svc = GardienService(db)
    logs = await svc.get_logs(space_id)
    return [
        GardienLogEntry(
            id=log.id,
            action=log.action,
            node_id=log.node_id,
            details=log.details,
            status=log.status,
            created_at=log.created_at,
        )
        for log in logs
    ]

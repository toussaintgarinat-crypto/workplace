from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from uuid import UUID
from datetime import datetime, timezone

from app.database import get_db
from app.models.node import Node
from app.services.node_service import NodeService
from app.services.tier_service import TierService
from app.schemas.node import NodeTierUpdate

router = APIRouter()


@router.post("/nodes/{node_id}/touch")
async def touch_node(space_id: UUID, node_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Node).where(Node.id == node_id, Node.space_id == space_id)
    )
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    node.access_count += 1
    node.last_accessed = datetime.now(timezone.utc)
    await db.commit()
    return {"id": str(node.id), "access_count": node.access_count, "last_accessed": node.last_accessed.isoformat() if node.last_accessed else None}


@router.get("/nodes/aging")
async def get_aging_nodes(space_id: UUID, db: AsyncSession = Depends(get_db)):
    now = datetime.now(timezone.utc)
    from app.config import settings
    hot_cutoff = now - __import__("datetime").timedelta(days=settings.tier_hot_days)
    result = await db.execute(
        select(Node).where(
            Node.space_id == space_id,
            Node.status == "active",
            Node.storage_tier == "hot",
            Node.last_accessed < hot_cutoff,
        ).order_by(Node.last_accessed)
    )
    nodes = result.scalars().all()
    return [
        {
            "id": str(n.id),
            "title": n.title,
            "storage_tier": n.storage_tier.value if hasattr(n.storage_tier, 'value') else n.storage_tier,
            "last_accessed": n.last_accessed.isoformat() if n.last_accessed else None,
        }
        for n in nodes
    ]


@router.post("/maintenance/tiers")
async def run_tier_demotion(space_id: UUID, db: AsyncSession = Depends(get_db)):
    svc = TierService(db)
    result = await svc.apply_tier_demotion(space_id)
    return {"detail": f"Moved {result['moved_to_archive']} to archive, {result['moved_to_cold_archive']} to cold archive"}


@router.patch("/nodes/{node_id}/tier")
async def update_node_tier(space_id: UUID, node_id: UUID, req: NodeTierUpdate, db: AsyncSession = Depends(get_db)):
    svc = NodeService(db)
    node = await svc.update_tier(node_id, space_id, req.tier)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    return {"id": str(node.id), "storage_tier": node.storage_tier.value if hasattr(node.storage_tier, 'value') else node.storage_tier}

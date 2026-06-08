from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from uuid import UUID

from app.database import get_db
from app.models.node import Node
from app.models.edge import Edge
from app.models.palace import PalaceRoom
from app.models.gardien import GardienConfigModel
from app.dependencies import check_space_access

router = APIRouter()


@router.get("")
async def export_space(
    space_id: UUID,
    format: str = Query("json"),
    db: AsyncSession = Depends(get_db),
    _=Depends(check_space_access),
):
    nodes_result = await db.execute(select(Node).where(Node.space_id == space_id))
    nodes = nodes_result.scalars().all()

    edges_result = await db.execute(select(Edge).where(
        Edge.source_id.in_([n.id for n in nodes])
    ))
    edges = edges_result.scalars().all()

    palace_result = await db.execute(
        select(PalaceRoom).where(PalaceRoom.space_id == space_id)
    )
    palace_rooms = palace_result.scalars().all()

    config_result = await db.execute(
        select(GardienConfigModel).where(GardienConfigModel.space_id == space_id)
    )
    config = config_result.scalar_one_or_none()

    if format == "markdown":
        output = ""
        for n in nodes:
            output += "---\n"
            output += f"id: {n.id}\n"
            output += f"type: {n.type.value}\n"
            output += f"title: {n.title}\n"
            output += f"storage_tier: {n.storage_tier.value if hasattr(n.storage_tier, 'value') else n.storage_tier}\n"
            output += f"stage: {n.ipcra_stage.value}\n"
            output += f"---\n\n{n.content_md}\n\n"
        return output

    data = {
        "exported_at": datetime.now().isoformat(),
        "space_id": str(space_id),
        "nodes": [
            {
                "id": str(n.id),
                "type": n.type.value,
                "ipcra_stage": n.ipcra_stage.value,
                "status": n.status.value,
                "title": n.title,
                "content_md": n.content_md,
                "frontmatter": n.frontmatter,
                "storage_tier": n.storage_tier.value if hasattr(n.storage_tier, 'value') else n.storage_tier,
                "access_count": n.access_count,
                "happened_at": n.happened_at.isoformat() if n.happened_at else None,
                "source_url": n.source_url,
                "captured_from": n.captured_from,
                "created_at": n.created_at.isoformat() if n.created_at else None,
                "updated_at": n.updated_at.isoformat() if n.updated_at else None,
            }
            for n in nodes
        ],
        "edges": [
            {
                "id": str(e.id),
                "source_id": str(e.source_id),
                "target_id": str(e.target_id),
                "type": e.type.value,
                "weight": e.weight,
                "created_by": e.created_by.value,
            }
            for e in edges
        ],
        "palace": [
            {
                "wing": r.wing,
                "room": r.room,
                "drawer": r.drawer,
                "position": r.position,
            }
            for r in palace_rooms
        ],
        "gardien_config": {
            "mode": config.mode,
            "interval_minutes": config.interval_minutes,
            "auto_summarize": config.auto_summarize,
            "auto_merge": config.auto_merge,
            "auto_infer": config.auto_infer,
            "auto_suggest_ipcra": config.auto_suggest_ipcra,
            "auto_archive": config.auto_archive,
        } if config else None,
        "count": len(nodes),
    }
    return data




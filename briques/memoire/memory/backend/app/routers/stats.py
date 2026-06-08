from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.database import get_db
from app.models.node import Node, NodeStatus
from app.dependencies import check_space_access

router = APIRouter()


@router.get("")
async def get_stats(
    space_id: UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(check_space_access),
):
    total = await db.execute(
        select(func.count(Node.id)).where(
            Node.space_id == space_id,
            Node.status == NodeStatus.active,
        )
    )
    total_nodes = total.scalar() or 0

    by_type_result = await db.execute(
        select(Node.type, func.count(Node.id))
        .where(Node.space_id == space_id, Node.status == NodeStatus.active)
        .group_by(Node.type)
    )
    by_type = {row[0].value if hasattr(row[0], 'value') else row[0]: row[1] for row in by_type_result.all()}

    by_stage_result = await db.execute(
        select(Node.ipcra_stage, func.count(Node.id))
        .where(Node.space_id == space_id, Node.status == NodeStatus.active)
        .group_by(Node.ipcra_stage)
    )
    by_stage = {row[0].value if hasattr(row[0], 'value') else row[0]: row[1] for row in by_stage_result.all()}

    by_tier_result = await db.execute(
        select(Node.storage_tier, func.count(Node.id))
        .where(Node.space_id == space_id, Node.status == NodeStatus.active)
        .group_by(Node.storage_tier)
    )
    by_tier = {row[0].value if hasattr(row[0], 'value') else row[0]: row[1] for row in by_tier_result.all()}

    return {
        "total_nodes": total_nodes,
        "by_type": by_type,
        "by_stage": by_stage,
        "by_tier": by_tier,
    }

from uuid import UUID
from datetime import datetime, timezone, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.node import Node, StorageTier, NodeStatus
from app.config import settings


class TierService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def apply_tier_demotion(self, space_id: UUID) -> dict[str, int]:
        now = datetime.now(timezone.utc)
        result = {"moved_to_archive": 0, "moved_to_cold_archive": 0}

        hot_cutoff = now - timedelta(days=settings.tier_hot_days)
        archive_cutoff = now - timedelta(days=settings.tier_archive_days)

        nodes = await self.db.execute(
            select(Node).where(
                Node.space_id == space_id,
                Node.status == NodeStatus.active,
            )
        )
        for node in nodes.scalars().all():
            ref_date = node.last_accessed or node.created_at

            if node.storage_tier == StorageTier.hot and ref_date < hot_cutoff:
                node.storage_tier = StorageTier.archive
                result["moved_to_archive"] += 1
            elif node.storage_tier == StorageTier.archive and ref_date < archive_cutoff:
                node.storage_tier = StorageTier.cold_archive
                result["moved_to_cold_archive"] += 1

        await self.db.commit()
        return result

    async def get_stats(self, space_id: UUID) -> dict:
        result = await self.db.execute(
            select(Node.storage_tier, Node.id).where(
                Node.space_id == space_id,
                Node.status == NodeStatus.active,
            )
        )
        rows = result.all()
        total = len(rows)
        by_tier = {"hot": 0, "archive": 0, "cold_archive": 0}
        for row in rows:
            tier = row[0].value if hasattr(row[0], 'value') else row[0]
            by_tier[tier] = by_tier.get(tier, 0) + 1
        return {
            "total_nodes": total,
            "by_tier": by_tier,
        }

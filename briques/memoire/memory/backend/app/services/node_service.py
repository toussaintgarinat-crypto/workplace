from typing import Optional
from uuid import UUID
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.node import Node, NodeType, IpCraStage, StorageTier, NodeStatus
from app.models.palace import PalaceRoom
from app.services.embed_service import EmbedService


class NodeService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_nodes(
        self,
        space_id: UUID,
        type: Optional[str] = None,
        stage: Optional[str] = None,
        tier: Optional[str] = None,
        status: str = "active",
        wing: Optional[str] = None,
        room: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Node]:
        query = select(Node).where(Node.space_id == space_id, Node.status == NodeStatus(status))
        if type:
            query = query.where(Node.type == NodeType(type))
        if stage:
            query = query.where(Node.ipcra_stage == IpCraStage(stage))
        if tier:
            query = query.where(Node.storage_tier == StorageTier(tier))
        query = query.order_by(Node.updated_at.desc()).limit(limit).offset(offset)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def create_node(
        self,
        space_id: UUID,
        type: str,
        title: str,
        content_md: str = "",
        frontmatter: dict = None,
        source_url: Optional[str] = None,
        captured_from: Optional[str] = None,
        happened_at: Optional[datetime] = None,
        location: Optional[dict] = None,
        user_id: Optional[UUID] = None,
    ) -> Node:
        now = datetime.now(timezone.utc)
        node = Node(
            space_id=space_id,
            user_id=user_id,
            type=NodeType(type),
            ipcra_stage=IpCraStage(type),
            title=title,
            content_md=content_md,
            frontmatter=frontmatter or {},
            source_url=source_url,
            captured_from=captured_from,
            happened_at=happened_at,
            stage_changed_at=now,
        )
        self.db.add(node)
        await self.db.flush()

        if location:
            if isinstance(location, dict):
                wing = location.get("wing", "")
                room = location.get("room", "")
                drawer = location.get("drawer")
            else:
                wing = location.wing or ""
                room = location.room or ""
                drawer = location.drawer
            result = await self.db.execute(
                select(PalaceRoom).where(
                    PalaceRoom.space_id == space_id,
                    PalaceRoom.wing == wing,
                    PalaceRoom.room == room,
                    PalaceRoom.drawer == drawer,
                ).limit(1)
            )
            palace = result.scalars().first()
            if not palace:
                palace = PalaceRoom(
                    space_id=space_id,
                    wing=wing,
                    room=room,
                    drawer=drawer,
                )
                self.db.add(palace)

        await self.db.commit()
        await self.db.refresh(node)

        embed_svc = EmbedService(self.db)
        await embed_svc.embed_node(node.id)

        return node

    async def get_node(self, node_id: UUID, space_id: UUID) -> Optional[Node]:
        result = await self.db.execute(
            select(Node).where(Node.id == node_id, Node.space_id == space_id)
        )
        node = result.scalar_one_or_none()
        if node:
            node.access_count += 1
            node.last_accessed = datetime.now(timezone.utc)
            await self.db.commit()
            await self.db.refresh(node)
        return node

    async def update_node(self, node_id: UUID, space_id: UUID, data: dict) -> Optional[Node]:
        result = await self.db.execute(
            select(Node).where(Node.id == node_id, Node.space_id == space_id)
        )
        node = result.scalar_one_or_none()
        if not node:
            return None
        for key, value in data.items():
            if value is not None and hasattr(node, key):
                setattr(node, key, value)
        await self.db.commit()
        await self.db.refresh(node)

        if any(k in data for k in ("title", "content_md")):
            embed_svc = EmbedService(self.db)
            await embed_svc.embed_node(node.id)

        return node

    async def update_stage(self, node_id: UUID, space_id: UUID, stage: str) -> Optional[Node]:
        result = await self.db.execute(
            select(Node).where(Node.id == node_id, Node.space_id == space_id)
        )
        node = result.scalar_one_or_none()
        if not node:
            return None
        node.ipcra_stage = IpCraStage(stage)
        node.stage_changed_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(node)
        return node

    async def update_tier(self, node_id: UUID, space_id: UUID, tier: str) -> Optional[Node]:
        result = await self.db.execute(
            select(Node).where(Node.id == node_id, Node.space_id == space_id)
        )
        node = result.scalar_one_or_none()
        if not node:
            return None
        node.storage_tier = StorageTier(tier)
        await self.db.commit()
        await self.db.refresh(node)
        return node

    async def update_location(self, node_id: UUID, space_id: UUID, wing: str, room: str, drawer: Optional[str] = None) -> Optional[Node]:
        result = await self.db.execute(
            select(Node).where(Node.id == node_id, Node.space_id == space_id)
        )
        node = result.scalar_one_or_none()
        if not node:
            return None
        palace = PalaceRoom(
            space_id=space_id,
            wing=wing,
            room=room,
            drawer=drawer,
        )
        self.db.add(palace)
        await self.db.commit()
        await self.db.refresh(node)
        return node

    async def soft_delete(self, node_id: UUID, space_id: UUID) -> bool:
        result = await self.db.execute(
            select(Node).where(Node.id == node_id, Node.space_id == space_id)
        )
        node = result.scalar_one_or_none()
        if not node:
            return False
        node.status = NodeStatus.archived
        node.ipcra_stage = IpCraStage.archive
        await self.db.commit()
        return True

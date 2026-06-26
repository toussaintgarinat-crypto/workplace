from typing import Optional
from uuid import UUID
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.node import Node, NodeType, IpCraStage, StorageTier, NodeStatus
from app.models.revision import NodeRevision
from app.models.stage_event import NodeStageEvent
from app.models.user import Space
from app.models.palace import PalaceRoom
from app.services.embed_service import EmbedService

# Champs versionnés par l'historique opt-in (S110) : le contenu éditable d'un nœud.
_TRACKED_FIELDS = ("title", "content_md", "frontmatter")


class NodeService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _space_tracks_history(self, space_id: UUID) -> bool:
        """L'espace journalise-t-il son histoire (S112) ? Gouverne les évènements de
        stade et le soft-delete des liens."""
        result = await self.db.execute(
            select(Space.track_history).where(Space.id == space_id)
        )
        return bool(result.scalar_one_or_none())

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

        # Journal temporel de l'espace (S112) : si l'espace suit son histoire, on note
        # l'évènement de création (from=NULL, to=stade initial). Sinon rien (souveraineté).
        if await self._space_tracks_history(space_id):
            self.db.add(NodeStageEvent(
                space_id=space_id,
                node_id=node.id,
                from_stage=None,
                to_stage=node.ipcra_stage,
                at=now,
            ))

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

        # Historique opt-in (S110) : si le suivi est (ou devient) actif et qu'un champ
        # versionné change réellement, on archive l'état PRÉCÉDENT avant de l'écraser.
        will_track = bool(data.get("track_history", node.track_history))
        content_changes = any(
            field in data and data[field] is not None and getattr(node, field) != data[field]
            for field in _TRACKED_FIELDS
        )
        if will_track and content_changes:
            self.db.add(NodeRevision(
                node_id=node.id,
                space_id=node.space_id,
                title=node.title,
                content_md=node.content_md or "",
                frontmatter=node.frontmatter or {},
            ))

        for key, value in data.items():
            if value is not None and hasattr(node, key):
                setattr(node, key, value)
        await self.db.commit()
        await self.db.refresh(node)

        if any(k in data for k in ("title", "content_md")):
            embed_svc = EmbedService(self.db)
            await embed_svc.embed_node(node.id)

        return node

    async def list_revisions(self, node_id: UUID, space_id: UUID, limit: int = 50) -> Optional[list[NodeRevision]]:
        """Versions archivées d'un nœud, de la plus récente à la plus ancienne.

        Renvoie None si le nœud n'existe pas dans cet espace (→ 404), une liste
        (éventuellement vide) sinon.
        """
        node = await self.db.execute(
            select(Node.id).where(Node.id == node_id, Node.space_id == space_id)
        )
        if node.scalar_one_or_none() is None:
            return None
        result = await self.db.execute(
            select(NodeRevision)
            .where(NodeRevision.node_id == node_id, NodeRevision.space_id == space_id)
            .order_by(NodeRevision.captured_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_revision(self, node_id: UUID, space_id: UUID, revision_id: UUID) -> Optional[NodeRevision]:
        result = await self.db.execute(
            select(NodeRevision).where(
                NodeRevision.id == revision_id,
                NodeRevision.node_id == node_id,
                NodeRevision.space_id == space_id,
            )
        )
        return result.scalar_one_or_none()

    async def restore_revision(self, node_id: UUID, space_id: UUID, revision_id: UUID) -> Optional[Node]:
        """Restaure une version passée. C'est une édition à part entière : si le suivi
        est actif, l'état courant est lui-même archivé avant d'être remplacé."""
        rev = await self.get_revision(node_id, space_id, revision_id)
        if rev is None:
            return None
        return await self.update_node(node_id, space_id, {
            "title": rev.title,
            "content_md": rev.content_md or "",
            "frontmatter": rev.frontmatter or {},
        })

    async def update_stage(self, node_id: UUID, space_id: UUID, stage: str) -> Optional[Node]:
        result = await self.db.execute(
            select(Node).where(Node.id == node_id, Node.space_id == space_id)
        )
        node = result.scalar_one_or_none()
        if not node:
            return None
        old_stage = node.ipcra_stage
        new_stage = IpCraStage(stage)
        now = datetime.now(timezone.utc)
        node.ipcra_stage = new_stage
        node.stage_changed_at = now
        # Journal temporel (S112) : on n'enregistre que les vraies transitions, et
        # seulement si l'espace suit son histoire.
        if old_stage != new_stage and await self._space_tracks_history(space_id):
            self.db.add(NodeStageEvent(
                space_id=space_id,
                node_id=node.id,
                from_stage=old_stage,
                to_stage=new_stage,
                at=now,
            ))
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

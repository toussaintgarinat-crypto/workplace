from collections import deque
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.node import Node, NodeStatus
from app.models.edge import Edge, EdgeType, EdgeCreator
from app.models.stage_event import NodeStageEvent
from app.models.user import Space
from app.schemas.graph import GraphResponse, GraphNode, GraphEdge, NodePosition, TimelineEntry


def _pos(node: Node) -> NodePosition | None:
    """Position canvas persistée d'un nœud, si elle existe et est exploitable."""
    raw = getattr(node, "canvas_pos", None)
    if isinstance(raw, dict) and "x" in raw and "y" in raw:
        try:
            return NodePosition(x=float(raw["x"]), y=float(raw["y"]))
        except (TypeError, ValueError):
            return None
    return None


class GraphService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_subgraph(self, space_id: UUID, root: Optional[UUID] = None, depth: int = 2) -> GraphResponse:
        if not root:
            result = await self.db.execute(
                select(Node).where(Node.space_id == space_id, Node.status == NodeStatus.active).limit(50)
            )
            nodes = result.scalars().all()
            node_ids = [n.id for n in nodes]
            edge_result = await self.db.execute(
                select(Edge).where(
                    or_(Edge.source_id.in_(node_ids), Edge.target_id.in_(node_ids)),
                    Edge.deleted_at.is_(None),
                )
            )
            edges = edge_result.scalars().all()
        else:
            all_node_ids = await self._bfs_expand(space_id, root, depth)
            if not all_node_ids:
                return GraphResponse(nodes=[], edges=[])
            node_result = await self.db.execute(
                select(Node).where(Node.id.in_(all_node_ids))
            )
            nodes = node_result.scalars().all()
            edge_result = await self.db.execute(
                select(Edge).where(
                    or_(Edge.source_id.in_(all_node_ids), Edge.target_id.in_(all_node_ids)),
                    Edge.deleted_at.is_(None),
                )
            )
            edges = edge_result.scalars().all()

        return GraphResponse(
            nodes=[GraphNode(id=n.id, title=n.title, type=n.type.value, stage=n.ipcra_stage.value, pos=_pos(n)) for n in nodes],
            edges=[GraphEdge(id=e.id, source=e.source_id, target=e.target_id, type=e.type.value, weight=e.weight) for e in edges],
        )

    async def _bfs_expand(self, space_id: UUID, root: UUID, depth: int) -> set[UUID]:
        visited = {root}
        current = {root}
        for _ in range(depth):
            if not current:
                break
            result = await self.db.execute(
                select(Edge).where(
                    or_(Edge.source_id.in_(current), Edge.target_id.in_(current)),
                    Edge.deleted_at.is_(None),
                )
            )
            edges = result.scalars().all()
            nxt: set[UUID] = set()
            for e in edges:
                if e.source_id not in visited:
                    nxt.add(e.source_id)
                if e.target_id not in visited:
                    nxt.add(e.target_id)
            visited.update(nxt)
            current = nxt
        return visited

    async def create_edge(self, space_id: UUID, source_id: UUID, target_id: UUID, edge_type: str = "related", weight: float = 1.0) -> Optional[Edge]:
        if source_id == target_id:
            return None
        edge = Edge(
            source_id=source_id,
            target_id=target_id,
            type=EdgeType(edge_type),
            weight=weight,
            created_by=EdgeCreator.user,
        )
        self.db.add(edge)
        await self.db.commit()
        await self.db.refresh(edge)
        return edge

    async def set_node_position(self, space_id: UUID, node_id: UUID, x: float, y: float) -> Optional[Node]:
        """Enregistre la position libre d'un nœud sur le canvas (drag-and-drop, S109)."""
        result = await self.db.execute(
            select(Node).where(Node.id == node_id, Node.space_id == space_id)
        )
        node = result.scalar_one_or_none()
        if not node:
            return None
        node.canvas_pos = {"x": float(x), "y": float(y)}
        await self.db.commit()
        await self.db.refresh(node)
        return node

    async def _space_tracks_history(self, space_id: UUID) -> bool:
        """L'espace journalise-t-il son histoire (S112) ?"""
        result = await self.db.execute(
            select(Space.track_history).where(Space.id == space_id)
        )
        return bool(result.scalar_one_or_none())

    async def delete_edge(self, space_id: UUID, edge_id: UUID) -> bool:
        result = await self.db.execute(select(Edge).where(Edge.id == edge_id))
        edge = result.scalar_one_or_none()
        if not edge:
            return False
        # Si l'espace suit son histoire (S112), on horodate la suppression au lieu
        # d'effacer la ligne → le lien reste « vivant à T » pour les T antérieurs.
        # Sinon, comportement historique : hard-delete.
        if await self._space_tracks_history(space_id):
            if edge.deleted_at is None:
                edge.deleted_at = datetime.now(timezone.utc)
                await self.db.commit()
        else:
            await self.db.delete(edge)
            await self.db.commit()
        return True

    async def get_graph_at(self, space_id: UUID, t: datetime, depth: int = 2) -> GraphResponse:
        """État du graphe tel qu'il était à l'instant T (S112).

        Nœuds dont `created_at ≤ T` ; stade-à-T = `to_stage` du dernier évènement ≤ T
        (repli honnête sur le stade courant si aucun évènement — on n'invente pas
        l'avant-activation du suivi). Liens « vivants à T » = `created_at ≤ T` et pas
        encore supprimés à T (`deleted_at IS NULL OR deleted_at > T`).
        """
        node_result = await self.db.execute(
            select(Node)
            .where(Node.space_id == space_id, Node.created_at <= t)
            .order_by(Node.created_at)
            .limit(50)
        )
        nodes = list(node_result.scalars().all())
        node_ids = [n.id for n in nodes]
        if not node_ids:
            return GraphResponse(nodes=[], edges=[])

        # Stade-à-T : dernier évènement ≤ T par nœud.
        ev_result = await self.db.execute(
            select(NodeStageEvent)
            .where(
                NodeStageEvent.node_id.in_(node_ids),
                NodeStageEvent.at <= t,
            )
            .order_by(NodeStageEvent.at)
        )
        stage_at: dict[UUID, str] = {}
        for ev in ev_result.scalars().all():  # ordre croissant → le dernier gagne
            stage_at[ev.node_id] = ev.to_stage.value

        edge_result = await self.db.execute(
            select(Edge).where(
                Edge.source_id.in_(node_ids),
                Edge.target_id.in_(node_ids),
                Edge.created_at <= t,
                or_(Edge.deleted_at.is_(None), Edge.deleted_at > t),
            )
        )
        edges = edge_result.scalars().all()

        return GraphResponse(
            nodes=[
                GraphNode(
                    id=n.id,
                    title=n.title,
                    type=n.type.value,
                    stage=stage_at.get(n.id, n.ipcra_stage.value),
                    pos=_pos(n),
                )
                for n in nodes
            ],
            edges=[GraphEdge(id=e.id, source=e.source_id, target=e.target_id, type=e.type.value, weight=e.weight) for e in edges],
        )

    async def get_timeline(self, space_id: UUID) -> list[TimelineEntry]:
        """Instants saillants de l'histoire de l'espace, triés (S112).

        Sert S113 à placer les crans du curseur sans recalcul côté front :
        créations et transitions de stade (table d'évènements), ajouts et retraits
        de liens (created_at / deleted_at des liens de l'espace).
        """
        entries: list[TimelineEntry] = []

        ev_result = await self.db.execute(
            select(NodeStageEvent)
            .where(NodeStageEvent.space_id == space_id)
            .order_by(NodeStageEvent.at)
        )
        for ev in ev_result.scalars().all():
            if ev.from_stage is None:
                entries.append(TimelineEntry(at=ev.at, kind="created", label=ev.to_stage.value))
            else:
                entries.append(TimelineEntry(
                    at=ev.at, kind="stage", label=f"{ev.from_stage.value} → {ev.to_stage.value}"
                ))

        # Les liens n'ont pas de space_id : on les rattache via leurs nœuds.
        node_ids_result = await self.db.execute(
            select(Node.id).where(Node.space_id == space_id)
        )
        node_ids = [r for r in node_ids_result.scalars().all()]
        if node_ids:
            edge_result = await self.db.execute(
                select(Edge).where(
                    or_(Edge.source_id.in_(node_ids), Edge.target_id.in_(node_ids))
                )
            )
            for e in edge_result.scalars().all():
                if e.created_at is not None:
                    entries.append(TimelineEntry(at=e.created_at, kind="edge_added", label=e.type.value))
                if e.deleted_at is not None:
                    entries.append(TimelineEntry(at=e.deleted_at, kind="edge_removed", label=e.type.value))

        entries.sort(key=lambda x: x.at)
        return entries

    async def find_shortest_path(self, space_id: UUID, source_id: UUID, target_id: UUID) -> list[GraphNode]:
        visited = {source_id}
        queue: deque[tuple[UUID, list[UUID]]] = deque([(source_id, [source_id])])
        while queue:
            current, path = queue.popleft()
            result = await self.db.execute(
                select(Edge).where(
                    or_(Edge.source_id == current, Edge.target_id == current)
                )
            )
            edges = result.scalars().all()
            for e in edges:
                neighbor = e.target_id if e.source_id == current else e.source_id
                if neighbor == target_id:
                    full = path + [neighbor]
                    node_result = await self.db.execute(
                        select(Node).where(Node.id.in_(full))
                    )
                    nodes = node_result.scalars().all()
                    node_map = {n.id: n for n in nodes}
                    return [GraphNode(id=nid, title=node_map[nid].title, type=node_map[nid].type.value) for nid in full]
                if neighbor not in visited:
                    visited.add(neighbor)
                    if len(path) < 20:
                        queue.append((neighbor, path + [neighbor]))
        return []

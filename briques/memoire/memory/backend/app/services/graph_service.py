from collections import deque
from typing import Optional
from uuid import UUID

from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.node import Node, NodeStatus
from app.models.edge import Edge, EdgeType, EdgeCreator
from app.schemas.graph import GraphResponse, GraphNode, GraphEdge


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
                    or_(Edge.source_id.in_(node_ids), Edge.target_id.in_(node_ids))
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
                    or_(Edge.source_id.in_(all_node_ids), Edge.target_id.in_(all_node_ids))
                )
            )
            edges = edge_result.scalars().all()

        return GraphResponse(
            nodes=[GraphNode(id=n.id, title=n.title, type=n.type.value) for n in nodes],
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
                    or_(Edge.source_id.in_(current), Edge.target_id.in_(current))
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

    async def delete_edge(self, edge_id: UUID) -> bool:
        result = await self.db.execute(select(Edge).where(Edge.id == edge_id))
        edge = result.scalar_one_or_none()
        if not edge:
            return False
        await self.db.delete(edge)
        await self.db.commit()
        return True

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

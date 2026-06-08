from uuid import UUID

from pydantic import BaseModel


class GraphQuery(BaseModel):
    root: UUID
    depth: int = 2
    direction: str = "both"


class EdgeCreate(BaseModel):
    source_id: UUID
    target_id: UUID
    type: str = "related"
    weight: float = 1.0


class GraphNode(BaseModel):
    id: UUID
    title: str
    type: str


class GraphEdge(BaseModel):
    id: UUID
    source: UUID
    target: UUID
    type: str
    weight: float


class GraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class PathRequest(BaseModel):
    source: UUID
    target: UUID

from datetime import datetime
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


class NodePosition(BaseModel):
    x: float
    y: float


class GraphNode(BaseModel):
    id: UUID
    title: str
    type: str
    # Stade IPCRA à l'instant rendu (présent par défaut, ou stade-à-T en mode temps,
    # S112). Le front (S113) colorera par `stage` plutôt que par `type` figé.
    stage: str | None = None
    pos: NodePosition | None = None


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


class TimelineEntry(BaseModel):
    """Un instant saillant de l'histoire de l'espace (S112). `kind` ∈
    {created, stage, edge_added, edge_removed} ; `label` = libellé court prêt à afficher."""
    at: datetime
    kind: str
    label: str = ""

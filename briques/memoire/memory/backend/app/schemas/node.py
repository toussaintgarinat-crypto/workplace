from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class Location(BaseModel):
    wing: str
    room: str
    drawer: Optional[str] = None


class EdgeRef(BaseModel):
    id: UUID
    source_id: UUID
    target_id: UUID
    type: str
    weight: float


class NodeCreate(BaseModel):
    type: str
    title: str
    content_md: str = ""
    frontmatter: dict = Field(default_factory=dict)
    location: Optional[Location] = None
    source_url: Optional[str] = None
    captured_from: Optional[str] = None
    happened_at: Optional[datetime] = None


class NodeUpdate(BaseModel):
    title: Optional[str] = None
    content_md: Optional[str] = None
    frontmatter: Optional[dict] = None
    source_url: Optional[str] = None
    captured_from: Optional[str] = None
    happened_at: Optional[datetime] = None


class NodeStageUpdate(BaseModel):
    stage: str
    reason: Optional[str] = None


class NodeLocationUpdate(BaseModel):
    wing: str
    room: str
    drawer: Optional[str] = None


class NodeTierUpdate(BaseModel):
    tier: str


class NodeResponse(BaseModel):
    id: UUID
    space_id: UUID
    type: str
    ipcra_stage: str
    storage_tier: str
    status: str
    title: str
    content_md: str
    frontmatter: dict
    access_count: int
    last_accessed: Optional[datetime] = None
    happened_at: Optional[datetime] = None
    stage_changed_at: Optional[datetime] = None
    source_url: Optional[str] = None
    captured_from: Optional[str] = None
    location: Optional[Location] = None
    edges: list[EdgeRef] = []
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

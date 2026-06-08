from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class CollectionCreate(BaseModel):
    name: str
    description: str = ""
    filter_criteria: Optional[dict] = None
    is_dynamic: bool = False


class CollectionUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    filter_criteria: Optional[dict] = None


class CollectionNodeResponse(BaseModel):
    id: UUID
    node_id: UUID
    added_at: datetime


class CollectionResponse(BaseModel):
    id: UUID
    space_id: UUID
    name: str
    description: str
    filter_criteria: Optional[dict] = None
    is_dynamic: bool
    node_count: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}

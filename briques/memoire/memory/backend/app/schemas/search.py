from typing import Optional
from uuid import UUID
from datetime import datetime

from pydantic import BaseModel


class SearchQuery(BaseModel):
    q: str
    type: Optional[str] = None
    stage: Optional[str] = None
    tags: Optional[str] = None
    limit: int = 20
    offset: int = 0


class SearchResult(BaseModel):
    id: UUID
    title: str
    content_md: str
    type: str
    storage_tier: str
    happened_at: Optional[datetime] = None
    score: float


class SemanticSearchRequest(BaseModel):
    query: str
    limit: int = 10
    stage_filter: Optional[str] = None
    type_filter: Optional[str] = None

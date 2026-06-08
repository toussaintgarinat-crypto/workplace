from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class GardienConfig(BaseModel):
    mode: str = "propose"
    interval_minutes: int = 60
    auto_summarize: bool = True
    auto_merge: bool = True
    auto_infer: bool = True
    auto_suggest_ipcra: bool = True
    auto_archive: bool = False


class GardienSuggestion(BaseModel):
    id: UUID
    action: str
    node_id: Optional[UUID] = None
    details: dict = {}
    status: str
    created_at: datetime


class GardienLogEntry(BaseModel):
    id: UUID
    action: str
    node_id: Optional[UUID] = None
    details: dict = {}
    status: str
    created_at: datetime

from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class WingCreate(BaseModel):
    name: str


class RoomCreate(BaseModel):
    wing: str
    name: str


class DrawerCreate(BaseModel):
    wing: str
    room: str
    name: str


class PalaceRoom(BaseModel):
    id: UUID
    wing: str
    room: str
    drawer: Optional[str] = None
    children: list["PalaceRoom"] = []


class PalaceTree(BaseModel):
    wings: list[PalaceRoom]

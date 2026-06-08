from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.palace import PalaceRoom


class PalaceService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_tree(self, space_id: UUID) -> list[PalaceRoom]:
        result = await self.db.execute(
            select(PalaceRoom)
            .where(PalaceRoom.space_id == space_id, PalaceRoom.parent_id.is_(None))
            .order_by(PalaceRoom.position)
        )
        return list(result.scalars().all())

    async def create_wing(self, space_id: UUID, name: str) -> PalaceRoom:
        room = PalaceRoom(space_id=space_id, wing=name, room=name)
        self.db.add(room)
        await self.db.commit()
        await self.db.refresh(room)
        return room

    async def create_room(self, space_id: UUID, wing: str, name: str) -> PalaceRoom:
        room = PalaceRoom(space_id=space_id, wing=wing, room=name)
        self.db.add(room)
        await self.db.commit()
        await self.db.refresh(room)
        return room

    async def create_drawer(self, space_id: UUID, wing: str, room: str, name: str) -> PalaceRoom:
        drawer = PalaceRoom(space_id=space_id, wing=wing, room=room, drawer=name)
        self.db.add(drawer)
        await self.db.commit()
        await self.db.refresh(drawer)
        return drawer

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from uuid import UUID

from app.database import get_db
from app.models.palace import PalaceRoom
from app.schemas.palace import WingCreate, RoomCreate, DrawerCreate, PalaceTree, PalaceRoom as PalaceRoomSchema

router = APIRouter()


def room_to_schema(r: PalaceRoom) -> PalaceRoomSchema:
    return PalaceRoomSchema(
        id=r.id,
        wing=r.wing,
        room=r.room,
        drawer=r.drawer,
        children=[room_to_schema(c) for c in (r.children or [])],
    )


@router.get("", response_model=PalaceTree)
async def get_palace(space_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(PalaceRoom).where(PalaceRoom.space_id == space_id, PalaceRoom.parent_id.is_(None)).order_by(PalaceRoom.position)
    )
    wings = result.scalars().all()
    return PalaceTree(wings=[room_to_schema(w) for w in wings])


@router.post("/wing")
async def create_wing(space_id: UUID, req: WingCreate, db: AsyncSession = Depends(get_db)):
    room = PalaceRoom(space_id=space_id, wing=req.name, room=req.name)
    db.add(room)
    await db.commit()
    await db.refresh(room)
    return room_to_schema(room)


@router.post("/room")
async def create_room(space_id: UUID, req: RoomCreate, db: AsyncSession = Depends(get_db)):
    parent = await db.execute(
        select(PalaceRoom).where(
            PalaceRoom.space_id == space_id,
            PalaceRoom.wing == req.wing,
            PalaceRoom.parent_id.is_(None),
            PalaceRoom.drawer.is_(None),
        )
    )
    parent_wing = parent.scalar_one_or_none()
    room = PalaceRoom(
        space_id=space_id,
        wing=req.wing,
        room=req.name,
        parent_id=parent_wing.id if parent_wing else None,
    )
    db.add(room)
    await db.commit()
    await db.refresh(room)
    return room_to_schema(room)


@router.post("/drawer")
async def create_drawer(space_id: UUID, req: DrawerCreate, db: AsyncSession = Depends(get_db)):
    parent = await db.execute(
        select(PalaceRoom).where(
            PalaceRoom.space_id == space_id,
            PalaceRoom.wing == req.wing,
            PalaceRoom.room == req.room,
            PalaceRoom.drawer.is_(None),
            PalaceRoom.parent_id.is_not(None),
        )
    )
    parent_room = parent.scalar_one_or_none()
    room = PalaceRoom(
        space_id=space_id,
        wing=req.wing,
        room=req.room,
        drawer=req.name,
        parent_id=parent_room.id if parent_room else None,
    )
    db.add(room)
    await db.commit()
    await db.refresh(room)
    return room_to_schema(room)

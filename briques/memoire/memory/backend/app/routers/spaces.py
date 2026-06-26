from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
from uuid import UUID

from app.database import get_db
from app.models.user import Space, SpaceUser, User, UserRole
from app.dependencies import get_current_user_id, check_space_access, require_space_role

router = APIRouter()


class SpaceCreate(BaseModel):
    name: str
    description: str = ""


class SpaceUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    # Active/désactive le journal temporel de TOUT l'espace (S112).
    track_history: Optional[bool] = None


class SpaceResponse(BaseModel):
    id: UUID
    name: str
    description: str
    role: str = ""
    track_history: bool = False


class InviteRequest(BaseModel):
    email: str
    role: str = "member"


@router.post("", response_model=SpaceResponse)
async def create_space(
    req: SpaceCreate,
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_current_user_id),
):
    space = Space(name=req.name, description=req.description)
    db.add(space)
    await db.flush()

    membership = SpaceUser(
        space_id=space.id,
        user_id=user_id,
        role=UserRole.owner,
    )
    db.add(membership)
    await db.commit()
    await db.refresh(space)
    return SpaceResponse(id=space.id, name=space.name, description=space.description, role="owner", track_history=space.track_history)


@router.get("", response_model=list[SpaceResponse])
async def list_spaces(
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_current_user_id),
):
    result = await db.execute(
        select(Space, SpaceUser.role)
        .join(SpaceUser, SpaceUser.space_id == Space.id)
        .where(SpaceUser.user_id == user_id)
    )
    rows = result.all()
    return [
        SpaceResponse(id=space.id, name=space.name, description=space.description, role=role, track_history=space.track_history)
        for space, role in rows
    ]


@router.get("/{space_id}", response_model=SpaceResponse)
async def get_space(
    space_id: UUID,
    db: AsyncSession = Depends(get_db),
    membership: SpaceUser = Depends(check_space_access),
):
    result = await db.execute(select(Space).where(Space.id == space_id))
    space = result.scalar_one_or_none()
    if not space:
        raise HTTPException(status_code=404, detail="Space not found")
    return SpaceResponse(id=space.id, name=space.name, description=space.description, role=membership.role, track_history=space.track_history)


@router.put("/{space_id}", response_model=SpaceResponse)
async def update_space(
    space_id: UUID,
    req: SpaceUpdate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_space_role(UserRole.owner, UserRole.admin)),
):
    result = await db.execute(select(Space).where(Space.id == space_id))
    space = result.scalar_one_or_none()
    if not space:
        raise HTTPException(status_code=404, detail="Space not found")
    if req.name is not None:
        space.name = req.name
    if req.description is not None:
        space.description = req.description
    # Bascule du journal temporel de l'espace (S112).
    if req.track_history is not None:
        space.track_history = req.track_history
    await db.commit()
    await db.refresh(space)
    return SpaceResponse(id=space.id, name=space.name, description=space.description, track_history=space.track_history)


@router.delete("/{space_id}")
async def delete_space(
    space_id: UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_space_role(UserRole.owner)),
):
    result = await db.execute(select(Space).where(Space.id == space_id))
    space = result.scalar_one_or_none()
    if not space:
        raise HTTPException(status_code=404, detail="Space not found")
    await db.delete(space)
    await db.commit()
    return {"detail": "Space deleted"}


@router.get("/{space_id}/members")
async def list_members(
    space_id: UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(check_space_access),
):
    result = await db.execute(
        select(User, SpaceUser.role)
        .join(SpaceUser, SpaceUser.user_id == User.id)
        .where(SpaceUser.space_id == space_id)
    )
    return [
        {"id": str(user.id), "email": user.email, "display_name": user.display_name, "role": role}
        for user, role in result.all()
    ]


@router.post("/{space_id}/invite")
async def invite_user(
    space_id: UUID,
    req: InviteRequest,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_space_role(UserRole.owner, UserRole.admin)),
):
    result = await db.execute(select(User).where(User.email == req.email))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    existing = await db.execute(
        select(SpaceUser).where(
            SpaceUser.space_id == space_id,
            SpaceUser.user_id == user.id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="User already in space")

    membership = SpaceUser(space_id=space_id, user_id=user.id, role=req.role)
    db.add(membership)
    await db.commit()
    return {"detail": f"User {user.email} invited as {req.role}"}


@router.delete("/{space_id}/members/{user_id}")
async def remove_member(
    space_id: UUID,
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_membership: SpaceUser = Depends(require_space_role(UserRole.owner, UserRole.admin)),
):
    if str(current_membership.user_id) == str(user_id):
        raise HTTPException(status_code=400, detail="Cannot remove yourself")

    result = await db.execute(
        select(SpaceUser).where(
            SpaceUser.space_id == space_id,
            SpaceUser.user_id == user_id,
        )
    )
    membership = result.scalar_one_or_none()
    if not membership:
        raise HTTPException(status_code=404, detail="Member not found")

    await db.delete(membership)
    await db.commit()
    return {"detail": "Member removed"}


@router.put("/{space_id}/members/{user_id}/role")
async def update_member_role(
    space_id: UUID,
    user_id: UUID,
    req: InviteRequest,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_space_role(UserRole.owner)),
):
    result = await db.execute(
        select(SpaceUser).where(
            SpaceUser.space_id == space_id,
            SpaceUser.user_id == user_id,
        )
    )
    membership = result.scalar_one_or_none()
    if not membership:
        raise HTTPException(status_code=404, detail="Member not found")

    membership.role = req.role
    await db.commit()
    return {"detail": f"Role updated to {req.role}"}

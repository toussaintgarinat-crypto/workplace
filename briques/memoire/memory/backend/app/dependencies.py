from uuid import UUID

from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from jose import jwt, JWTError

from app.database import get_db
from app.config import settings
from app.models.user import User, Space, SpaceUser, UserRole

security = HTTPBearer(auto_error=False)


async def get_current_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
):
    if credentials is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        return UUID(user_id)
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")


async def get_current_user_db(
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


async def check_space_access(
    space_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Space).where(Space.id == space_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Space not found")

    result = await db.execute(
        select(SpaceUser).where(
            SpaceUser.space_id == space_id,
            SpaceUser.user_id == user_id,
        )
    )
    membership = result.scalar_one_or_none()
    if not membership:
        raise HTTPException(status_code=403, detail="Access denied to this space")
    return membership


def require_space_role(*roles: UserRole):
    async def _check(
        space_id: UUID,
        user_id: UUID = Depends(get_current_user_id),
        db: AsyncSession = Depends(get_db),
    ):
        result = await db.execute(select(Space).where(Space.id == space_id))
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Space not found")

        result = await db.execute(
            select(SpaceUser).where(
                SpaceUser.space_id == space_id,
                SpaceUser.user_id == user_id,
            )
        )
        membership = result.scalar_one_or_none()
        if not membership:
            raise HTTPException(status_code=403, detail="Access denied to this space")
        if roles and UserRole(membership.role) not in roles:
            raise HTTPException(status_code=403, detail=f"Requires one of: {[r.value for r in roles]}")
        return membership
    return _check

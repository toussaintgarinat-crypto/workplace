"""Service Discovery — accès DB pour discovery_router (Sprint 100)."""

from __future__ import annotations

from typing import Optional

from fastapi import Depends
from sqlalchemy import or_
from sqlalchemy.orm import Session

from database import get_db
from models.agent import AgentDefinition
from models.user import User
from models.world import Member, World


class DiscoveryService:
    def __init__(self, db: Session):
        self.db = db

    # ─── Worlds publics ─────────────────────────────────────────────────
    def list_public_worlds(
        self, q: Optional[str], tag: Optional[str],
        limit: int, offset: int,
    ) -> list[World]:
        query = self.db.query(World).filter(World.is_public == True, World.is_garden == False)
        if q:
            query = query.filter(
                or_(World.nom.ilike(f"%{q}%"), World.description.ilike(f"%{q}%"))
            )
        if tag:
            query = query.filter(World.tags.ilike(f'%"{tag}"%'))
        return (
            query.order_by(World.view_count.desc(), World.created_at.desc())
            .offset(offset).limit(limit).all()
        )

    def get_public_world(self, world_id: str) -> Optional[World]:
        return self.db.query(World).filter_by(id=world_id, is_public=True).first()

    def get_own_world(self, world_id: str, owner_id: str) -> Optional[World]:
        return self.db.query(World).filter_by(id=world_id, owner_id=owner_id).first()

    def list_public_worlds_by_owner(self, owner_id: str) -> list[World]:
        return self.db.query(World).filter_by(owner_id=owner_id, is_public=True).all()

    def count_members(self, world_id: str) -> int:
        return self.db.query(Member).filter_by(world_id=world_id).count()

    def count_active_agents(self, world_id: str) -> int:
        return self.db.query(AgentDefinition).filter_by(
            world_id=world_id, is_active=True,
        ).count()

    def get_user(self, user_id: str) -> Optional[User]:
        return self.db.query(User).filter_by(id=user_id).first()

    def list_public_users(self, exclude: Optional[str] = None) -> list[User]:
        query = self.db.query(User).filter(User.is_public == True)
        if exclude:
            query = query.filter(User.id != exclude)
        return query.all()

    def get_public_user(self, user_id: str) -> Optional[User]:
        return self.db.query(User).filter_by(id=user_id, is_public=True).first()

    def commit(self) -> None:
        self.db.commit()


def get_discovery_service(db: Session = Depends(get_db)) -> DiscoveryService:
    return DiscoveryService(db)

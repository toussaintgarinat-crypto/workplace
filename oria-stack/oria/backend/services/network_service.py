"""Service Network — accès DB pour network router (Sprint 100)."""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import Depends
from sqlalchemy import or_
from sqlalchemy.orm import Session

from database import get_db
from models.network import WorldLink
from models.world import Member, World


class NetworkService:
    def __init__(self, db: Session):
        self.db = db

    def get_membre(self, world_id: str, user_id: str) -> Optional[Member]:
        return self.db.query(Member).filter(
            Member.world_id == world_id, Member.user_id == user_id,
        ).first()

    def list_user_world_ids(self, user_id: str) -> list[str]:
        return [
            m.world_id
            for m in self.db.query(Member).filter(Member.user_id == user_id).all()
        ]

    def get_world(self, world_id: str) -> Optional[World]:
        return self.db.query(World).filter(World.id == world_id).first()

    def create_link(
        self, from_world_id: str, to_world_id: str, type_: str,
        pourcentage: Optional[float], created_by: str, visible: str,
    ) -> WorldLink:
        l = WorldLink(
            id=str(uuid.uuid4()),
            from_world_id=from_world_id, to_world_id=to_world_id,
            type=type_, pourcentage=pourcentage,
            created_by=created_by, visible=visible,
        )
        self.db.add(l)
        self.db.commit()
        self.db.refresh(l)
        return l

    def list_links_from(self, world_id: str) -> list[WorldLink]:
        return self.db.query(WorldLink).filter(
            WorldLink.from_world_id == world_id
        ).all()

    def list_links_to(self, world_id: str) -> list[WorldLink]:
        return self.db.query(WorldLink).filter(
            WorldLink.to_world_id == world_id
        ).all()

    def list_links_involving(self, world_id: str) -> list[WorldLink]:
        return self.db.query(WorldLink).filter(
            or_(WorldLink.from_world_id == world_id, WorldLink.to_world_id == world_id)
        ).all()

    def get_link(self, lien_id: str) -> Optional[WorldLink]:
        return self.db.query(WorldLink).filter(WorldLink.id == lien_id).first()

    def delete_link(self, l: WorldLink) -> None:
        self.db.delete(l)
        self.db.commit()


def get_network_service(db: Session = Depends(get_db)) -> NetworkService:
    return NetworkService(db)

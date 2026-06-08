"""Service Shared Zones — accès DB pour shared_zones_router (Sprint 100)."""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models.shared_zone import SharedZone, SharedZoneMember, ZoneRole, ZoneScope


class SharedZonesService:
    def __init__(self, db: Session):
        self.db = db

    def get_zone(self, zone_id: str) -> Optional[SharedZone]:
        return self.db.query(SharedZone).filter(SharedZone.id == zone_id).first()

    def get_member(self, zone_id: str, user_id: str) -> Optional[SharedZoneMember]:
        return self.db.query(SharedZoneMember).filter(
            SharedZoneMember.zone_id == zone_id,
            SharedZoneMember.user_id == user_id,
        ).first()

    def list_user_memberships(self, user_id: str) -> list[SharedZoneMember]:
        return (
            self.db.query(SharedZoneMember)
            .filter(SharedZoneMember.user_id == user_id)
            .all()
        )

    def list_zones_by_ids(self, zone_ids: list[str]) -> list[SharedZone]:
        if not zone_ids:
            return []
        return self.db.query(SharedZone).filter(SharedZone.id.in_(zone_ids)).all()

    def list_members(self, zone_id: str) -> list[SharedZoneMember]:
        return (
            self.db.query(SharedZoneMember)
            .filter(SharedZoneMember.zone_id == zone_id)
            .all()
        )

    def create_zone(
        self, name: str, owner_id: str, scope: ZoneScope,
        world_id: Optional[str], mempalace_namespace: Optional[str],
    ) -> SharedZone:
        namespace = mempalace_namespace or f"shared/{uuid.uuid4().hex[:8]}"
        zone = SharedZone(
            id=str(uuid.uuid4()),
            name=name, owner_id=owner_id,
            scope=scope, world_id=world_id,
            mempalace_namespace=namespace,
        )
        self.db.add(zone)
        self.db.add(SharedZoneMember(zone_id=zone.id, user_id=owner_id, role=ZoneRole.owner))
        self.db.commit()
        self.db.refresh(zone)
        return zone

    def delete_zone(self, zone: SharedZone) -> None:
        self.db.query(SharedZoneMember).filter(
            SharedZoneMember.zone_id == zone.id
        ).delete()
        self.db.delete(zone)
        self.db.commit()

    def upsert_member(self, zone_id: str, user_id: str, role: ZoneRole) -> None:
        existing = self.get_member(zone_id, user_id)
        if existing:
            existing.role = role
        else:
            self.db.add(SharedZoneMember(zone_id=zone_id, user_id=user_id, role=role))
        self.db.commit()

    def remove_member(self, zone_id: str, user_id: str) -> None:
        self.db.query(SharedZoneMember).filter(
            SharedZoneMember.zone_id == zone_id,
            SharedZoneMember.user_id == user_id,
        ).delete()
        self.db.commit()

    def require_access(self, zone_id: str, user_id: str) -> SharedZone:
        zone = self.get_zone(zone_id)
        if not zone:
            raise HTTPException(status_code=404, detail="Zone not found")
        if not self.get_member(zone_id, user_id):
            raise HTTPException(status_code=403, detail="Access denied")
        return zone


def get_shared_zones_service(db: Session = Depends(get_db)) -> SharedZonesService:
    return SharedZonesService(db)

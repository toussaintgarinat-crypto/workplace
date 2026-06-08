"""Service Buildings — accès DB pour buildings router (Sprint 100)."""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import Depends
from sqlalchemy.orm import Session

from database import get_db
from models.abonnement import RoomAbonnement
from models.building import Building, Room
from models.user import User
from models.world import Member


class BuildingsService:
    def __init__(self, db: Session):
        self.db = db

    # ─── Buildings ──────────────────────────────────────────────────────
    def get_building(self, building_id: str) -> Optional[Building]:
        return self.db.query(Building).filter(Building.id == building_id).first()

    def create_building(self, **fields) -> Building:
        b = Building(id=str(uuid.uuid4()), **fields)
        self.db.add(b)
        self.db.flush()
        return b

    def update_building(
        self, b: Building, nom: str = "", description: Optional[str] = None,
        emoji: str = "", couleur: str = "",
    ) -> Building:
        if nom:
            b.nom = nom
        if description is not None:
            b.description = description
        if emoji:
            b.emoji = emoji
        if couleur:
            b.couleur = couleur
        self.db.commit()
        self.db.refresh(b)
        return b

    def delete_building(self, b: Building) -> None:
        self.db.delete(b)
        self.db.commit()

    # ─── Rooms ──────────────────────────────────────────────────────────
    def get_room(self, room_id: str) -> Optional[Room]:
        return self.db.query(Room).filter(Room.id == room_id).first()

    def add_room(self, **fields) -> Room:
        room = Room(id=str(uuid.uuid4()), **fields)
        self.db.add(room)
        self.db.flush()
        return room

    def add_room_abonnements(self, room_id: str, abonnement_ids: list[str]) -> None:
        for abonnement_id in abonnement_ids:
            self.db.add(RoomAbonnement(room_id=room_id, abonnement_id=abonnement_id))

    def replace_room_abonnements(self, room_id: str, abonnement_ids: list[str]) -> None:
        self.db.query(RoomAbonnement).filter(
            RoomAbonnement.room_id == room_id
        ).delete()
        self.add_room_abonnements(room_id, abonnement_ids)

    def delete_room(self, r: Room) -> None:
        self.db.delete(r)
        self.db.commit()

    # ─── Users / Membres (helpers pour invitations Matrix) ──────────────
    def get_user(self, user_id: str) -> Optional[User]:
        return self.db.query(User).filter(User.id == user_id).first()

    def list_membre_mxids(self, world_id: str) -> list[str]:
        """Retourne les MXID Matrix de tous les membres d'un world."""
        membres = self.db.query(Member).filter(Member.world_id == world_id).all()
        user_ids = [m.user_id for m in membres]
        if not user_ids:
            return []
        users = self.db.query(User).filter(User.id.in_(user_ids)).all()
        return [u.matrix_user_id for u in users if u.matrix_user_id]

    # ─── Commit helpers ─────────────────────────────────────────────────
    def commit(self) -> None:
        self.db.commit()

    def refresh(self, obj) -> None:
        self.db.refresh(obj)


def get_buildings_service(db: Session = Depends(get_db)) -> BuildingsService:
    return BuildingsService(db)

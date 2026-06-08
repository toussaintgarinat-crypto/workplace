"""Service Rooms — accès DB pour rooms router (Sprint 100)."""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import Depends
from sqlalchemy.orm import Session

from database import get_db
from models.abonnement import RoomAbonnement
from models.building import Building, Room
from models.user import User


class RoomsService:
    def __init__(self, db: Session):
        self.db = db

    def get_room(self, room_id: str) -> Optional[Room]:
        return self.db.query(Room).filter(Room.id == room_id).first()

    def get_building(self, building_id: str) -> Optional[Building]:
        return self.db.query(Building).filter(Building.id == building_id).first()

    def get_user(self, user_id: str) -> Optional[User]:
        return self.db.query(User).filter(User.id == user_id).first()

    def create_room(
        self, building_id: str, nom: str, type_: str,
        etage: int, emoji: str, acces_restreint: str,
        abonnements_requis_ids: list[str] | None = None,
    ) -> Room:
        room = Room(
            id=str(uuid.uuid4()),
            building_id=building_id, nom=nom, type=type_,
            etage=etage, emoji=emoji, acces_restreint=acces_restreint,
        )
        self.db.add(room)
        self.db.flush()
        for abonnement_id in (abonnements_requis_ids or []):
            self.db.add(RoomAbonnement(room_id=room.id, abonnement_id=abonnement_id))
        # commit deferred — laissé au caller (qui peut encore enrichir matrix_room_id)
        return room

    def update_room(
        self, room: Room, nom: str = "", type_: str = "", emoji: str = "",
        acces_restreint: str = "",
        abonnements_requis_ids: list[str] | None = None,
    ) -> Room:
        if nom:
            room.nom = nom
        if type_:
            room.type = type_
        if emoji:
            room.emoji = emoji
        if acces_restreint:
            room.acces_restreint = acces_restreint
        if abonnements_requis_ids is not None:
            self.db.query(RoomAbonnement).filter(
                RoomAbonnement.room_id == room.id
            ).delete()
            for abonnement_id in abonnements_requis_ids:
                self.db.add(RoomAbonnement(room_id=room.id, abonnement_id=abonnement_id))
        self.db.commit()
        self.db.refresh(room)
        return room

    def delete_room(self, room: Room) -> None:
        self.db.delete(room)
        self.db.commit()

    def set_matrix_room_id(self, room: Room, matrix_room_id: str) -> None:
        room.matrix_room_id = matrix_room_id
        # commit deferred

    def commit(self) -> None:
        self.db.commit()

    def refresh(self, obj) -> None:
        self.db.refresh(obj)


def get_rooms_service(db: Session = Depends(get_db)) -> RoomsService:
    return RoomsService(db)

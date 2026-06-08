"""Service Worlds — accès DB pour worlds_router (Sprint 100)."""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import Depends
from sqlalchemy.orm import Session

from database import get_db
from models.abonnement import MembreAbonnement
from models.building import Building, Room
from models.user import User
from models.world import Member, World


class WorldsService:
    def __init__(self, db: Session):
        self.db = db

    # ─── World ───────────────────────────────────────────────────────────
    def list_worlds_for_user(self, user_id: str) -> list[World]:
        membres = self.db.query(Member).filter(Member.user_id == user_id).all()
        world_ids = [m.world_id for m in membres]
        if not world_ids:
            return []
        return self.db.query(World).filter(World.id.in_(world_ids)).all()

    def get_world(self, world_id: str) -> Optional[World]:
        return self.db.query(World).filter(World.id == world_id).first()

    def create_world(
        self, nom: str, description: str, emoji: str, couleur: str,
        owner_id: str, owner_nom: str, owner_avatar_emoji: str,
    ) -> World:
        world = World(
            id=str(uuid.uuid4()), nom=nom, description=description,
            emoji=emoji, couleur=couleur, owner_id=owner_id,
        )
        self.db.add(world)
        membre = Member(
            world_id=world.id, user_id=owner_id, nom=owner_nom,
            avatar_emoji=owner_avatar_emoji, role="proprietaire",
        )
        self.db.add(membre)
        self.db.commit()
        self.db.refresh(world)
        return world

    def update_world(
        self, world: World, nom: str = "", description: Optional[str] = None,
        emoji: str = "", couleur: str = "",
    ) -> World:
        if nom:
            world.nom = nom
        if description is not None:
            world.description = description
        if emoji:
            world.emoji = emoji
        if couleur:
            world.couleur = couleur
        self.db.commit()
        return world

    def delete_world(self, world: World) -> None:
        self.db.delete(world)
        self.db.commit()

    # ─── Membres ─────────────────────────────────────────────────────────
    def list_membres(self, world_id: str) -> list[Member]:
        return self.db.query(Member).filter(Member.world_id == world_id).all()

    def get_membre(self, world_id: str, user_id: str) -> Optional[Member]:
        return self.db.query(Member).filter(
            Member.world_id == world_id, Member.user_id == user_id
        ).first()

    def update_membre_role(self, membre: Member, role: str) -> None:
        membre.role = role
        self.db.commit()

    def delete_membre(self, membre: Member) -> None:
        self.db.delete(membre)
        self.db.commit()

    def add_membre(
        self, world_id: str, user_id: str, nom: str, avatar_emoji: str = "👤",
        role: str = "membre",
    ) -> Member:
        membre = Member(
            world_id=world_id, user_id=user_id, nom=nom,
            avatar_emoji=avatar_emoji, role=role,
        )
        self.db.add(membre)
        self.db.commit()
        return membre

    # ─── Helpers Sérialisation membres ──────────────────────────────────
    def get_users_map(self, user_ids: list[str]) -> dict[str, User]:
        if not user_ids:
            return {}
        return {
            u.id: u
            for u in self.db.query(User).filter(User.id.in_(user_ids)).all()
        }

    def get_user(self, user_id: str) -> Optional[User]:
        return self.db.query(User).filter(User.id == user_id).first()

    # ─── Abonnements ─────────────────────────────────────────────────────
    def abonnement_ids_membre(self, world_id: str, user_id: str) -> set[str]:
        membre = self.get_membre(world_id, user_id)
        if not membre:
            return set()
        mas = (
            self.db.query(MembreAbonnement)
            .filter(
                MembreAbonnement.member_id == membre.id,
                MembreAbonnement.actif == True,
            )
            .all()
        )
        return {ma.abonnement_id for ma in mas}

    # ─── Matrix invite helpers ──────────────────────────────────────────
    def get_world_matrix_rooms(self, world_id: str) -> list[Room]:
        return (
            self.db.query(Room)
            .join(Building, Room.building_id == Building.id)
            .filter(Building.world_id == world_id, Room.matrix_room_id.isnot(None))
            .all()
        )

    def get_world_owner_member(self, world_id: str) -> Optional[Member]:
        return self.db.query(Member).filter(
            Member.world_id == world_id, Member.role == "proprietaire"
        ).first()


def get_worlds_service(db: Session = Depends(get_db)) -> WorldsService:
    return WorldsService(db)

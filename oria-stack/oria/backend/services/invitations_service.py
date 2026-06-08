"""Service Invitations — accès DB pour invitations router (Sprint 100)."""

from __future__ import annotations

from typing import Optional

from fastapi import Depends
from sqlalchemy.orm import Session

from database import get_db
from models.world import Invitation, Member, World


class InvitationsService:
    def __init__(self, db: Session):
        self.db = db

    def create_invitation(self, world_id: str, created_by: str, max_uses: int) -> Invitation:
        inv = Invitation(world_id=world_id, created_by=created_by, max_uses=max_uses)
        self.db.add(inv)
        self.db.commit()
        self.db.refresh(inv)
        return inv

    def get_invitation(self, token: str) -> Optional[Invitation]:
        return self.db.query(Invitation).filter(Invitation.token == token).first()

    def get_world(self, world_id: str) -> Optional[World]:
        return self.db.query(World).filter(World.id == world_id).first()

    def get_member(self, world_id: str, user_id: str) -> Optional[Member]:
        return (
            self.db.query(Member)
            .filter(Member.world_id == world_id, Member.user_id == user_id)
            .first()
        )

    def add_member_and_bump(
        self, inv: Invitation, user_id: str, nom: str, avatar_emoji: str, role: str = "membre",
    ) -> None:
        """Ajoute un membre + incrémente le compteur d'usages de l'invitation."""
        self.db.add(Member(
            world_id=inv.world_id, user_id=user_id,
            nom=nom, avatar_emoji=avatar_emoji, role=role,
        ))
        inv.uses += 1
        self.db.commit()

    def list_world_invitations(self, world_id: str) -> list[Invitation]:
        return self.db.query(Invitation).filter(Invitation.world_id == world_id).all()

    def delete_invitation(self, inv: Invitation) -> None:
        self.db.delete(inv)
        self.db.commit()


def get_invitations_service(db: Session = Depends(get_db)) -> InvitationsService:
    return InvitationsService(db)

"""Service Vote — accès DB pour vote_router (Sprint 100)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends
from sqlalchemy.orm import Session

from database import get_db
from models.vote import Bulletin, Vote
from models.world import Member


class VoteService:
    def __init__(self, db: Session):
        self.db = db

    # ─── Permissions ──────────────────────────────────────────────────────
    def is_admin(self, world_id: str, user_id: str) -> bool:
        m = self.db.query(Member).filter_by(world_id=world_id, user_id=user_id).first()
        return bool(m and m.role in ("proprietaire", "admin"))

    # ─── Votes ────────────────────────────────────────────────────────────
    def create_vote(
        self, conseil_id: str, world_id: str, question: str, created_by: str,
    ) -> Vote:
        v = Vote(
            conseil_id=conseil_id, world_id=world_id,
            question=question, created_by=created_by,
        )
        self.db.add(v)
        self.db.commit()
        self.db.refresh(v)
        return v

    def list_by_conseil(self, conseil_id: str) -> list[Vote]:
        return (
            self.db.query(Vote)
            .filter_by(conseil_id=conseil_id)
            .order_by(Vote.created_at)
            .all()
        )

    def get_vote(self, vote_id: str) -> Optional[Vote]:
        return self.db.query(Vote).get(vote_id)

    def get_bulletin(self, vote_id: str, user_id: str) -> Optional[Bulletin]:
        return self.db.query(Bulletin).filter_by(vote_id=vote_id, user_id=user_id).first()

    def cast_vote(self, vote: Vote, user_id: str, user_nom: str, choix: str) -> Vote:
        existing = self.get_bulletin(vote.id, user_id)
        if existing:
            existing.choix = choix
        else:
            self.db.add(Bulletin(vote_id=vote.id, user_id=user_id, user_nom=user_nom, choix=choix))
        self.db.commit()
        self.db.refresh(vote)
        return vote

    def close_vote(self, vote: Vote) -> Vote:
        vote.statut = "ferme"
        vote.ferme_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(vote)
        return vote

    def delete_vote(self, vote: Vote) -> None:
        self.db.delete(vote)
        self.db.commit()


def get_vote_service(db: Session = Depends(get_db)) -> VoteService:
    return VoteService(db)

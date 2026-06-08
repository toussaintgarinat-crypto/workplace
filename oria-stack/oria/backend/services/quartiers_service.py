"""Service Quartiers — accès DB pour quartiers router (Sprint 100)."""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import Depends
from sqlalchemy.orm import Session

from database import get_db
from models.quartier import Quartier


class QuartiersService:
    def __init__(self, db: Session):
        self.db = db

    def get(self, quartier_id: str) -> Optional[Quartier]:
        return self.db.query(Quartier).filter(Quartier.id == quartier_id).first()

    def create(self, world_id: str, nom: str, emoji: str, couleur: str, description: str) -> Quartier:
        q = Quartier(
            id=str(uuid.uuid4()),
            world_id=world_id, nom=nom,
            emoji=emoji, couleur=couleur, description=description,
        )
        self.db.add(q)
        self.db.commit()
        self.db.refresh(q)
        return q

    def update(
        self, q: Quartier, nom: str = "", emoji: str = "",
        couleur: str = "", description: Optional[str] = None,
    ) -> Quartier:
        if nom:
            q.nom = nom
        if emoji:
            q.emoji = emoji
        if couleur:
            q.couleur = couleur
        if description is not None:
            q.description = description
        self.db.commit()
        self.db.refresh(q)
        return q

    def delete(self, q: Quartier) -> None:
        for b in q.buildings:
            b.quartier_id = None
        self.db.delete(q)
        self.db.commit()


def get_quartiers_service(db: Session = Depends(get_db)) -> QuartiersService:
    return QuartiersService(db)

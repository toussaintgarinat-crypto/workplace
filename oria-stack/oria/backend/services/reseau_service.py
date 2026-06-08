"""Service Réseau — accès DB pour reseau_router (Sprint 100)."""

from __future__ import annotations

from typing import Optional

from fastapi import Depends
from sqlalchemy.orm import Session

from database import get_db
from models.document import Document
from models.network import WorldLink
from models.world import Member, World


class ReseauService:
    def __init__(self, db: Session):
        self.db = db

    def is_member(self, world_id: str, user_id: str) -> bool:
        return bool(self.db.query(Member).filter_by(
            world_id=world_id, user_id=user_id,
        ).first())

    def linked_world_ids(self, world_id: str) -> list[str]:
        """Retourne les IDs de tous les worlds liés (dans les deux sens)."""
        links_out = self.db.query(WorldLink).filter(
            WorldLink.from_world_id == world_id
        ).all()
        links_in = self.db.query(WorldLink).filter(
            WorldLink.to_world_id == world_id
        ).all()
        ids = set()
        for l in links_out:
            ids.add(l.to_world_id)
        for l in links_in:
            ids.add(l.from_world_id)
        return list(ids)

    def get_worlds_map(self, world_ids: list[str]) -> dict[str, World]:
        if not world_ids:
            return {}
        return {
            w.id: w
            for w in self.db.query(World).filter(World.id.in_(world_ids)).all()
        }

    def list_shared_docs_for_worlds(self, world_ids: list[str]) -> list[Document]:
        if not world_ids:
            return []
        return (
            self.db.query(Document)
            .filter(
                Document.world_id.in_(world_ids),
                Document.partage_reseau == True,  # noqa: E712
            )
            .order_by(Document.created_at.desc())
            .all()
        )

    def list_user_docs_in_world(self, user_id: str, world_id: str) -> list[Document]:
        return (
            self.db.query(Document)
            .filter_by(owner_id=user_id, world_id=world_id)
            .order_by(Document.created_at.desc())
            .all()
        )

    def get_owned_document(self, doc_id: str, user_id: str) -> Optional[Document]:
        return self.db.query(Document).filter_by(
            id=doc_id, owner_id=user_id,
        ).first()

    def set_doc_partage_reseau(self, doc: Document, partage: bool) -> None:
        doc.partage_reseau = partage
        self.db.commit()


def get_reseau_service(db: Session = Depends(get_db)) -> ReseauService:
    return ReseauService(db)

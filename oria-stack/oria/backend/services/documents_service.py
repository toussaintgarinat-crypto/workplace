"""Service Documents — accès DB pour documents_router (Sprint 100)."""

from __future__ import annotations

from typing import Optional

from fastapi import Depends
from sqlalchemy.orm import Session

from database import get_db
from models.document import Document


class DocumentsService:
    def __init__(self, db: Session):
        self.db = db

    def list_user_documents(
        self, owner_id: str, world_id: Optional[str] = None,
    ) -> list[Document]:
        q = self.db.query(Document).filter_by(owner_id=owner_id)
        if world_id:
            q = q.filter_by(world_id=world_id)
        return q.order_by(Document.created_at.desc()).all()

    def get_user_document(self, doc_id: str, owner_id: str) -> Optional[Document]:
        return self.db.query(Document).filter_by(id=doc_id, owner_id=owner_id).first()

    def create_document(self, doc: Document) -> Document:
        self.db.add(doc)
        self.db.commit()
        self.db.refresh(doc)
        return doc

    def mark_indexed(self, doc: Document, indexed: bool = True) -> None:
        doc.indexe_memory = indexed
        self.db.commit()

    def delete_document(self, doc: Document) -> None:
        self.db.delete(doc)
        self.db.commit()


def get_documents_service(db: Session = Depends(get_db)) -> DocumentsService:
    return DocumentsService(db)

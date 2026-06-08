"""Service Jardin — accès DB pour jardin_router (Sprint 100)."""

from __future__ import annotations

from typing import Optional

from fastapi import Depends
from sqlalchemy.orm import Session

from database import get_db
from models.agent import AgentDefinition
from models.document import Document


class JardinService:
    def __init__(self, db: Session):
        self.db = db

    # ─── Agent personnel ──────────────────────────────────────────────────
    def get_personal_agent(self, user_id: str) -> Optional[AgentDefinition]:
        return self.db.query(AgentDefinition).filter_by(
            owner_id=user_id, is_jardin_agent=True,
        ).first()

    def update_personal_agent(
        self, agent: AgentDefinition, fields: dict,
    ) -> AgentDefinition:
        for k, v in fields.items():
            setattr(agent, k, v)
        self.db.commit()
        self.db.refresh(agent)
        return agent

    # ─── Documents ────────────────────────────────────────────────────────
    def list_user_documents(self, user_id: str) -> list[Document]:
        return (
            self.db.query(Document)
            .filter_by(owner_id=user_id)
            .order_by(Document.created_at.desc())
            .all()
        )

    def get_user_document(self, doc_id: str, user_id: str) -> Optional[Document]:
        return self.db.query(Document).filter_by(id=doc_id, owner_id=user_id).first()

    def add_document(self, doc: Document) -> Document:
        self.db.add(doc)
        self.db.commit()
        return doc

    def delete_document(self, doc: Document) -> None:
        self.db.delete(doc)
        self.db.commit()


def get_jardin_service(db: Session = Depends(get_db)) -> JardinService:
    return JardinService(db)

"""Service Agents — accès DB pour agents_router (Sprint 100)."""

from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models.agent import AgentDefinition
from models.document import Document
from models.world import Member, World


class AgentsService:
    def __init__(self, db: Session):
        self.db = db

    # ─── Worlds / accès ───────────────────────────────────────────────────
    def get_world(self, world_id: str) -> Optional[World]:
        return self.db.query(World).filter(World.id == world_id).first()

    def get_member(self, world_id: str, user_id: str) -> Optional[Member]:
        return self.db.query(Member).filter_by(world_id=world_id, user_id=user_id).first()

    def check_world_access(self, world_id: str, user_id: str, require_owner: bool = False) -> World:
        """Vérifie l'accès au world et lève des HTTPException si refusé."""
        world = self.get_world(world_id)
        if not world:
            raise HTTPException(404, "World introuvable")
        if require_owner and world.owner_id != user_id:
            raise HTTPException(403, "Réservé au propriétaire")
        if not self.get_member(world_id, user_id) and world.owner_id != user_id:
            raise HTTPException(403, "Accès refusé")
        return world

    # ─── Agents ───────────────────────────────────────────────────────────
    def list_world_agents(self, world_id: str) -> list[AgentDefinition]:
        return self.db.query(AgentDefinition).filter_by(world_id=world_id).all()

    def get_agent(self, agent_id: str) -> Optional[AgentDefinition]:
        return self.db.query(AgentDefinition).filter_by(id=agent_id).first()

    def get_active_agent(self, agent_id: str) -> Optional[AgentDefinition]:
        return self.db.query(AgentDefinition).filter_by(id=agent_id, is_active=True).first()

    def create_agent(self, **fields) -> AgentDefinition:
        agent = AgentDefinition(**fields)
        self.db.add(agent)
        self.db.commit()
        self.db.refresh(agent)
        return agent

    def update_agent(self, agent: AgentDefinition, fields: dict) -> AgentDefinition:
        for k, v in fields.items():
            setattr(agent, k, v)
        self.db.commit()
        self.db.refresh(agent)
        return agent

    def delete_agent(self, agent: AgentDefinition) -> None:
        self.db.delete(agent)
        self.db.commit()

    # ─── Documents (contexte chat) ────────────────────────────────────────
    def list_user_documents(self, owner_id: str, limit: int) -> list[Document]:
        return self.db.query(Document).filter_by(owner_id=owner_id).limit(limit).all()


def get_agents_service(db: Session = Depends(get_db)) -> AgentsService:
    return AgentsService(db)

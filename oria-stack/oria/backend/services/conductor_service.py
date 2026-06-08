"""Service Conductor — accès DB pour conductor_router (Sprint 100)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends
from sqlalchemy.orm import Session

from database import get_db
from models.resident_agent import ResidentAgent


class ConductorService:
    def __init__(self, db: Session):
        self.db = db

    def list_agents(self) -> list[ResidentAgent]:
        return self.db.query(ResidentAgent).order_by(ResidentAgent.pole_type).all()

    def get_agent(self, agent_id: str) -> Optional[ResidentAgent]:
        return self.db.query(ResidentAgent).filter_by(id=agent_id).first()

    def get_agent_by_pole(self, pole_type: str) -> Optional[ResidentAgent]:
        return self.db.query(ResidentAgent).filter_by(pole_type=pole_type).first()

    def create_agent(self, **fields) -> ResidentAgent:
        agent = ResidentAgent(**fields)
        self.db.add(agent)
        self.db.commit()
        self.db.refresh(agent)
        return agent

    def update_agent_fields(self, agent: ResidentAgent, fields: dict) -> ResidentAgent:
        for k, v in fields.items():
            setattr(agent, k, v)
        agent.last_activity = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(agent)
        return agent

    def delete_agent(self, agent: ResidentAgent) -> None:
        self.db.delete(agent)
        self.db.commit()

    def mark_working(self, agent: ResidentAgent, message: str) -> None:
        agent.status = "working"
        agent.current_task = message[:200]
        agent.last_activity = datetime.now(timezone.utc)
        self.db.commit()

    def update_status(self, agent: ResidentAgent, status: str, task_description: str) -> None:
        agent.status = status
        agent.current_task = task_description[:300]
        agent.last_activity = datetime.now(timezone.utc)
        self.db.commit()


def get_conductor_service(db: Session = Depends(get_db)) -> ConductorService:
    return ConductorService(db)

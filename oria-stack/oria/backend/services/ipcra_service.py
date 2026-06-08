"""Service IPCRA — accès DB pour ipcra_router (Sprint 100)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends
from sqlalchemy.orm import Session

from database import get_db
from models.agent import AgentDefinition
from models.ipcra import IPCRAItem, IPCRATrace


class IPCRAService:
    def __init__(self, db: Session):
        self.db = db

    # ─── Items ────────────────────────────────────────────────────────────
    def list_items(
        self, owner_id: str,
        categorie: Optional[str], world_id: Optional[str],
    ) -> list[IPCRAItem]:
        q = self.db.query(IPCRAItem).filter_by(owner_id=owner_id)
        if categorie:
            q = q.filter_by(categorie=categorie)
        if world_id:
            q = q.filter_by(world_id=world_id)
        return q.order_by(IPCRAItem.updated_at.desc()).all()

    def get_item(self, item_id: str, owner_id: str) -> Optional[IPCRAItem]:
        return self.db.query(IPCRAItem).filter_by(id=item_id, owner_id=owner_id).first()

    def create_item(
        self, owner_id: str, world_id: Optional[str], categorie: str,
        titre: str, contenu: str, tags: list[str],
        casquette: Optional[str], source_url: Optional[str],
        agent_id: Optional[str],
    ) -> IPCRAItem:
        item = IPCRAItem(
            owner_id=owner_id,
            world_id=world_id,
            categorie=categorie,
            titre=titre,
            contenu=contenu,
            tags=json.dumps(tags),
            casquette=casquette,
            source_url=source_url,
            agent_id=agent_id,
        )
        self.db.add(item)
        self.db.commit()
        self.db.refresh(item)
        return item

    def update_item_fields(self, item: IPCRAItem, **fields) -> IPCRAItem:
        """Met à jour les champs non-None. `tags` peut être une liste (sera sérialisée)."""
        if "tags" in fields and fields["tags"] is not None:
            fields["tags"] = json.dumps(fields["tags"])
        for key, value in fields.items():
            if value is not None:
                setattr(item, key, value)
        item.updated_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(item)
        return item

    def change_categorie(self, item: IPCRAItem, categorie: str) -> IPCRAItem:
        item.categorie = categorie
        item.updated_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(item)
        return item

    def delete_item(self, item: IPCRAItem) -> None:
        self.db.delete(item)
        self.db.commit()

    # ─── Agents (lookup) ──────────────────────────────────────────────────
    def get_active_agent(self, agent_id: str) -> Optional[AgentDefinition]:
        return self.db.query(AgentDefinition).filter_by(id=agent_id, is_active=True).first()

    # ─── Traces ───────────────────────────────────────────────────────────
    def list_traces(self, item_id: str) -> list[IPCRATrace]:
        return (
            self.db.query(IPCRATrace)
            .filter_by(item_id=item_id)
            .order_by(IPCRATrace.created_at.asc())
            .all()
        )


def get_ipcra_service(db: Session = Depends(get_db)) -> IPCRAService:
    return IPCRAService(db)

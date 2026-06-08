"""Service Projects — Sprint 115."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends
from sqlalchemy.orm import Session

from database import get_db
from models.building import Room
from models.project import Project


class ProjectsService:
    def __init__(self, db: Session):
        self.db = db

    def list_for_world(self, world_id: str) -> list[Project]:
        return (
            self.db.query(Project)
            .filter(Project.world_id == world_id)
            .order_by(Project.created_at.desc())
            .all()
        )

    def get(self, project_id: str) -> Optional[Project]:
        return self.db.query(Project).filter(Project.id == project_id).first()

    def create(self, world_id: str, name: str, description: str, created_by: str) -> Project:
        p = Project(
            id=str(uuid.uuid4()),
            world_id=world_id,
            name=name,
            description=description,
            created_by=created_by,
        )
        self.db.add(p)
        self.db.commit()
        self.db.refresh(p)
        return p

    def update(self, project: Project, name: str = "", description: str = "") -> Project:
        if name:
            project.name = name
        if description is not None:
            project.description = description
        self.db.commit()
        self.db.refresh(project)
        return project

    def close(self, project: Project) -> Project:
        project.status = "closed"
        project.closed_at = datetime.now(timezone.utc)
        for room in project.rooms:
            room.status = "closed"
            room.closed_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(project)
        return project

    def reopen(self, project: Project) -> Project:
        project.status = "active"
        project.closed_at = None
        for room in project.rooms:
            room.status = "active"
            room.closed_at = None
        self.db.commit()
        self.db.refresh(project)
        return project

    def delete(self, project: Project) -> None:
        # Detach rooms before deleting so they're not cascade-deleted
        for room in project.rooms:
            room.project_id = None
        self.db.delete(project)
        self.db.commit()

    def assign_room(self, room: Room, project_id: Optional[str]) -> Room:
        room.project_id = project_id
        self.db.commit()
        self.db.refresh(room)
        return room

    def close_room(self, room: Room) -> Room:
        room.status = "closed"
        room.closed_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(room)
        return room

    def reopen_room(self, room: Room) -> Room:
        room.status = "active"
        room.closed_at = None
        self.db.commit()
        self.db.refresh(room)
        return room

    def get_room(self, room_id: str) -> Optional[Room]:
        return self.db.query(Room).filter(Room.id == room_id).first()


def get_projects_service(db: Session = Depends(get_db)) -> ProjectsService:
    return ProjectsService(db)

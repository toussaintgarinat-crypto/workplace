"""Router Projects — Sprint 115."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from models.project import Project
from models.building import Room
from routers.auth import get_current_user
from services.projects_service import ProjectsService, get_projects_service

router = APIRouter()


class CreateProject(BaseModel):
    world_id: str
    name: str
    description: str = ""


class UpdateProject(BaseModel):
    name: str = ""
    description: Optional[str] = None


class AssignRoom(BaseModel):
    project_id: Optional[str] = None


def _ser_room(r: Room) -> dict:
    return {
        "id": r.id,
        "nom": r.nom,
        "type": r.type,
        "emoji": r.emoji,
        "etage": r.etage,
        "building_id": r.building_id,
        "status": r.status or "active",
        "closed_at": r.closed_at.isoformat() if r.closed_at else None,
        "project_id": r.project_id,
    }


def _ser(p: Project) -> dict:
    return {
        "id": p.id,
        "world_id": p.world_id,
        "name": p.name,
        "description": p.description,
        "status": p.status,
        "created_by": p.created_by,
        "created_at": p.created_at.isoformat(),
        "closed_at": p.closed_at.isoformat() if p.closed_at else None,
        "rooms": [_ser_room(r) for r in p.rooms],
        "room_count": len(p.rooms),
    }


# ── Projects CRUD ──────────────────────────────────────────────────────────

@router.get("/worlds/{world_id}/projects")
def list_projects(
    world_id: str,
    svc: ProjectsService = Depends(get_projects_service),
    _user=Depends(get_current_user),
):
    return [_ser(p) for p in svc.list_for_world(world_id)]


@router.post("/projects")
def create_project(
    data: CreateProject,
    svc: ProjectsService = Depends(get_projects_service),
    user=Depends(get_current_user),
):
    p = svc.create(data.world_id, data.name, data.description, user.id)
    return _ser(p)


@router.get("/projects/{project_id}")
def get_project(
    project_id: str,
    svc: ProjectsService = Depends(get_projects_service),
    _user=Depends(get_current_user),
):
    p = svc.get(project_id)
    if not p:
        raise HTTPException(status_code=404, detail="Projet introuvable")
    return _ser(p)


@router.patch("/projects/{project_id}")
def update_project(
    project_id: str,
    data: UpdateProject,
    svc: ProjectsService = Depends(get_projects_service),
    _user=Depends(get_current_user),
):
    p = svc.get(project_id)
    if not p:
        raise HTTPException(status_code=404, detail="Projet introuvable")
    return _ser(svc.update(p, data.name, data.description))


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(
    project_id: str,
    svc: ProjectsService = Depends(get_projects_service),
    _user=Depends(get_current_user),
):
    p = svc.get(project_id)
    if not p:
        raise HTTPException(status_code=404, detail="Projet introuvable")
    svc.delete(p)


# ── Lifecycle ──────────────────────────────────────────────────────────────

@router.post("/projects/{project_id}/close")
def close_project(
    project_id: str,
    svc: ProjectsService = Depends(get_projects_service),
    _user=Depends(get_current_user),
):
    p = svc.get(project_id)
    if not p:
        raise HTTPException(status_code=404, detail="Projet introuvable")
    return _ser(svc.close(p))


@router.post("/projects/{project_id}/reopen")
def reopen_project(
    project_id: str,
    svc: ProjectsService = Depends(get_projects_service),
    _user=Depends(get_current_user),
):
    p = svc.get(project_id)
    if not p:
        raise HTTPException(status_code=404, detail="Projet introuvable")
    return _ser(svc.reopen(p))


# ── Room assignment & standalone room close ────────────────────────────────

@router.patch("/rooms/{room_id}/project")
def assign_room_to_project(
    room_id: str,
    data: AssignRoom,
    svc: ProjectsService = Depends(get_projects_service),
    _user=Depends(get_current_user),
):
    r = svc.get_room(room_id)
    if not r:
        raise HTTPException(status_code=404, detail="Room introuvable")
    return _ser_room(svc.assign_room(r, data.project_id))


@router.post("/rooms/{room_id}/close")
def close_room(
    room_id: str,
    svc: ProjectsService = Depends(get_projects_service),
    _user=Depends(get_current_user),
):
    r = svc.get_room(room_id)
    if not r:
        raise HTTPException(status_code=404, detail="Room introuvable")
    return _ser_room(svc.close_room(r))


@router.post("/rooms/{room_id}/reopen")
def reopen_room(
    room_id: str,
    svc: ProjectsService = Depends(get_projects_service),
    _user=Depends(get_current_user),
):
    r = svc.get_room(room_id)
    if not r:
        raise HTTPException(status_code=404, detail="Room introuvable")
    return _ser_room(svc.reopen_room(r))

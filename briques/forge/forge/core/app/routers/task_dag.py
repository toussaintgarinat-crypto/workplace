"""Router task-dag. Portage de routes/task-dag.ts (S132). Monté /api, protégé.

Nœuds d'un DAG de tâches (agent/prompt) par pôle, avec dépendances (TEXT JSON).
POST /poles/:id/dag/run : tri topologique (Kahn, cf. services/dag.py) puis
exécution simulée en tâche de fond (running → 0.9s → done par nœud).
"""

from __future__ import annotations

import asyncio
import datetime
import json
import uuid as uuidlib

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, select, update
from sqlalchemy import delete as sa_delete

from app.auth import UserContext, get_current_user
from app.db import SessionLocal
from app.models import TaskDagItems
from app.serde import task_dag_item
from app.services.dag import DagNode, topological_sort

router = APIRouter()


def _uuid(v: str | None):
    try:
        return uuidlib.UUID(v)
    except (ValueError, TypeError):
        return None


@router.get("/poles/{pole_id}/dag", dependencies=[Depends(get_current_user)])
async def list_dag(pole_id: str, user: UserContext = Depends(get_current_user)):
    puid = _uuid(pole_id)
    async with SessionLocal() as s:
        rows = (await s.execute(
            select(TaskDagItems).where(and_(TaskDagItems.pole_id == puid, TaskDagItems.user_id == user.sub))
            .order_by(desc(TaskDagItems.created_at))
        )).scalars().all()
    return [task_dag_item(x) for x in rows]


class CreateDag(BaseModel):
    nom: str = Field(min_length=1, max_length=200)
    description: str | None = None
    agentOwner: str | None = None
    dependances: list[str] | None = None
    criticite: str | None = None
    nodeType: str | None = None
    posX: float | None = None
    posY: float | None = None
    promptText: str | None = None


@router.post("/poles/{pole_id}/dag", dependencies=[Depends(get_current_user)])
async def create_dag(pole_id: str, body: CreateDag, user: UserContext = Depends(get_current_user)):
    puid = _uuid(pole_id)
    async with SessionLocal() as s:
        item = TaskDagItems(
            pole_id=puid, user_id=user.sub, nom=body.nom,
            description=body.description or "", agent_owner=body.agentOwner or "",
            dependances=json.dumps(body.dependances or []),
            criticite=body.criticite or "normale", node_type=body.nodeType or "agent",
            pos_x=body.posX or 0, pos_y=body.posY or 0, prompt_text=body.promptText or "",
        )
        s.add(item)
        await s.commit()
        await s.refresh(item)
    return JSONResponse(status_code=201, content=task_dag_item(item))


class UpdateDag(BaseModel):
    nom: str | None = None
    statut: str | None = None
    agentOwner: str | None = None
    dependances: list[str] | None = None
    criticite: str | None = None
    nodeType: str | None = None
    posX: float | None = None
    posY: float | None = None
    promptText: str | None = None


_PATCH_COLMAP = {
    "nom": "nom", "statut": "statut", "agentOwner": "agent_owner",
    "criticite": "criticite", "nodeType": "node_type",
    "posX": "pos_x", "posY": "pos_y", "promptText": "prompt_text",
}


@router.patch("/dag/{did}", dependencies=[Depends(get_current_user)])
async def update_dag(did: str, body: UpdateDag, user: UserContext = Depends(get_current_user)):
    duid = _uuid(did)
    raw = body.model_dump(exclude_unset=True)
    cols = {_PATCH_COLMAP[k]: v for k, v in raw.items() if k in _PATCH_COLMAP}
    if body.dependances is not None:
        cols["dependances"] = json.dumps(body.dependances)
    cols["updated_at"] = datetime.datetime.utcnow()
    async with SessionLocal() as s:
        item = None
        if duid:
            await s.execute(
                update(TaskDagItems).where(and_(TaskDagItems.id == duid, TaskDagItems.user_id == user.sub)).values(**cols)
            )
            await s.commit()
            item = (await s.execute(
                select(TaskDagItems).where(and_(TaskDagItems.id == duid, TaskDagItems.user_id == user.sub))
            )).scalar_one_or_none()
    return task_dag_item(item) if item is not None else None


@router.delete("/dag/{did}", dependencies=[Depends(get_current_user)])
async def delete_dag(did: str, user: UserContext = Depends(get_current_user)):
    duid = _uuid(did)
    async with SessionLocal() as s:
        if duid:
            await s.execute(sa_delete(TaskDagItems).where(and_(TaskDagItems.id == duid, TaskDagItems.user_id == user.sub)))
            await s.commit()
    return {"ok": True}


async def _run_dag_background(order: list[str], user_sub: str) -> None:
    """Exécution simulée séquentielle (running → 0.9s → done) — parité Bun."""
    for nid in order:
        nuid = _uuid(nid)
        if not nuid:
            continue
        async with SessionLocal() as s:
            await s.execute(
                update(TaskDagItems).where(and_(TaskDagItems.id == nuid, TaskDagItems.user_id == user_sub))
                .values(statut="running", updated_at=datetime.datetime.utcnow())
            )
            await s.commit()
        await asyncio.sleep(0.9)
        async with SessionLocal() as s:
            await s.execute(
                update(TaskDagItems).where(and_(TaskDagItems.id == nuid, TaskDagItems.user_id == user_sub))
                .values(statut="done", updated_at=datetime.datetime.utcnow())
            )
            await s.commit()


@router.post("/poles/{pole_id}/dag/run", dependencies=[Depends(get_current_user)])
async def run_dag(pole_id: str, user: UserContext = Depends(get_current_user)):
    puid = _uuid(pole_id)
    async with SessionLocal() as s:
        items = (await s.execute(
            select(TaskDagItems).where(and_(TaskDagItems.pole_id == puid, TaskDagItems.user_id == user.sub))
        )).scalars().all()

        if not items:
            return {"ok": True, "order": []}

        nodes = [DagNode(id=str(it.id), dependances=json.loads(it.dependances or "[]")) for it in items]
        order = topological_sort(nodes).order

        # Reset à 'pending' avant relance.
        await s.execute(
            update(TaskDagItems).where(and_(TaskDagItems.pole_id == puid, TaskDagItems.user_id == user.sub))
            .values(statut="pending", updated_at=datetime.datetime.utcnow())
        )
        await s.commit()

    asyncio.create_task(_run_dag_background(order, user.sub))
    return {"ok": True, "order": order}

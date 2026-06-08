"""Router servers. Portage de routes/servers.ts (S132). Monté /api, protégé.

Parc de serveurs SSH managés (clé chiffrée AES-GCM compat Bun) + liste des
instances déployées d'une mission d'audit.
"""

from __future__ import annotations

import uuid as uuidlib

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, select
from sqlalchemy import delete as sa_delete

from app.auth import UserContext, get_current_user
from app.crypto import encrypt, mask_key
from app.db import SessionLocal
from app.models import DeployedInstances, ManagedServers
from app.serde import deployed_instance_public, managed_server, managed_server_public

router = APIRouter()


def _uuid(v: str | None):
    try:
        return uuidlib.UUID(v)
    except (ValueError, TypeError):
        return None


@router.get("/servers", dependencies=[Depends(get_current_user)])
async def list_servers(user: UserContext = Depends(get_current_user)):
    async with SessionLocal() as s:
        rows = (await s.execute(
            select(ManagedServers).where(ManagedServers.user_id == user.sub)
        )).scalars().all()
    return [managed_server_public(x) for x in rows]


class CreateServer(BaseModel):
    label: str = Field(min_length=1, max_length=100)
    ip: str = Field(min_length=7)
    sshKey: str = Field(min_length=20)
    sshUser: str = "root"
    region: str | None = None


@router.post("/servers", dependencies=[Depends(get_current_user)])
async def create_server(body: CreateServer, user: UserContext = Depends(get_current_user)):
    encrypted = encrypt(body.sshKey)
    async with SessionLocal() as s:
        srv = ManagedServers(
            user_id=user.sub, label=body.label, ip=body.ip,
            ssh_key=encrypted, ssh_user=body.sshUser,
            region=body.region or "", status="libre",
        )
        s.add(srv)
        await s.commit()
        await s.refresh(srv)
    return JSONResponse(status_code=201, content={**managed_server(srv), "sshKey": mask_key(body.sshKey)})


@router.delete("/servers/{sid}", dependencies=[Depends(get_current_user)])
async def delete_server(sid: str, user: UserContext = Depends(get_current_user)):
    suid = _uuid(sid)
    async with SessionLocal() as s:
        srv = None
        if suid:
            srv = (await s.execute(
                select(ManagedServers).where(and_(ManagedServers.id == suid, ManagedServers.user_id == user.sub))
            )).scalar_one_or_none()
        if srv is None:
            raise HTTPException(status_code=404, detail="Not found")
        if srv.status == "occupe":
            raise HTTPException(status_code=409, detail="Ce serveur est occupé par une instance active.")
        await s.execute(sa_delete(ManagedServers).where(ManagedServers.id == suid))
        await s.commit()
    return {"ok": True}


@router.get("/audit/{mission_id}/deployments", dependencies=[Depends(get_current_user)])
async def list_deployments(mission_id: str, user: UserContext = Depends(get_current_user)):
    muid = _uuid(mission_id)
    async with SessionLocal() as s:
        rows = (await s.execute(
            select(DeployedInstances).where(
                and_(DeployedInstances.mission_id == muid, DeployedInstances.user_id == user.sub)
            )
        )).scalars().all()
    return [deployed_instance_public(x) for x in rows]

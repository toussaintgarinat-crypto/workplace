"""Router deploy. Portage de routes/deploy.ts (S132). Monté /api, protégé.

POST /audit/:missionId/deploy → crée l'instance (status deploying), lance le
déploiement en tâche de fond (S124 : découplé de la connexion HTTP, progression
persistée) et répond 202. GET /audit/instances/:id/stream : suivi SSE
reconnectable (replay de l'étape courante, borne défensive ~30 min).
"""

from __future__ import annotations

import asyncio
import datetime
import json
import uuid as uuidlib

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, select, update

from app.auth import UserContext, get_current_user
from app.db import SessionLocal
from app.models import (
    AuditFindings,
    AuditMissions,
    AuditRecommendations,
    DeployedInstances,
    ManagedServers,
    Rapports,
)
from app.services.deploy import DeployOpts, MissionData, encrypt_key, run_deploy

router = APIRouter()


def _uuid(v: str | None):
    try:
        return uuidlib.UUID(v)
    except (ValueError, TypeError):
        return None


def _bcrypt(password: str) -> str:
    import bcrypt

    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(10)).decode("ascii")


class DeployBody(BaseModel):
    serverMode: str  # 'parc' | 'custom'
    serverId: str | None = None
    serverIp: str | None = None
    sshKey: str | None = None
    sshUser: str = "root"
    domainMode: str  # 'cloudflare' | 'manual'
    domain: str = ""
    adminEmail: str = Field(min_length=1)
    adminPassword: str = Field(min_length=8)


@router.post("/audit/{mission_id}/deploy", dependencies=[Depends(get_current_user)])
async def deploy(mission_id: str, body: DeployBody, user: UserContext = Depends(get_current_user)):
    muid = _uuid(mission_id)
    async with SessionLocal() as s:
        mission = None
        if muid:
            mission = (await s.execute(
                select(AuditMissions).where(and_(AuditMissions.id == muid, AuditMissions.user_id == user.sub))
            )).scalar_one_or_none()
        if mission is None:
            raise HTTPException(status_code=404, detail="Mission introuvable")

        # Résoudre IP + clé SSH selon le mode.
        ssh_user = body.sshUser
        if body.serverMode == "parc":
            if not body.serverId:
                raise HTTPException(status_code=400, detail="serverId requis pour le mode parc")
            srv = (await s.execute(
                select(ManagedServers).where(
                    and_(ManagedServers.id == _uuid(body.serverId), ManagedServers.user_id == user.sub)
                )
            )).scalar_one_or_none()
            if srv is None:
                raise HTTPException(status_code=404, detail="Serveur introuvable")
            if srv.status == "occupe":
                raise HTTPException(status_code=409, detail="Ce serveur est déjà occupé")
            server_ip = srv.ip
            ssh_key_encrypted = srv.ssh_key
            ssh_user = srv.ssh_user or "root"
        else:
            if not body.serverIp or not body.sshKey:
                raise HTTPException(status_code=400, detail="serverIp et sshKey requis pour le mode custom")
            server_ip = body.serverIp
            ssh_key_encrypted = encrypt_key(body.sshKey)

        # Charger les données d'audit (findings / recos / dernier rapport).
        findings = (await s.execute(
            select(AuditFindings).where(and_(AuditFindings.mission_id == muid, AuditFindings.user_id == user.sub))
        )).scalars().all()
        recos = (await s.execute(
            select(AuditRecommendations).where(
                and_(AuditRecommendations.mission_id == muid, AuditRecommendations.user_id == user.sub)
            )
        )).scalars().all()
        rapport_row = (await s.execute(
            select(Rapports).where(and_(Rapports.mission_id == muid, Rapports.user_id == user.sub))
            .order_by(desc(Rapports.created_at)).limit(1)
        )).scalar_one_or_none()

        admin_hash = _bcrypt(body.adminPassword)
        instance = DeployedInstances(
            mission_id=muid, user_id=user.sub, server_ip=server_ip,
            ssh_key=ssh_key_encrypted, ssh_user=ssh_user,
            domain=body.domain, domain_mode=body.domainMode,
            admin_email=body.adminEmail, admin_password_hash=admin_hash, status="deploying",
        )
        s.add(instance)
        await s.commit()
        await s.refresh(instance)
        instance_id = instance.id

        if body.serverMode == "parc" and body.serverId:
            await s.execute(
                update(ManagedServers).where(ManagedServers.id == _uuid(body.serverId))
                .values(status="occupe", instance_id=instance_id)
            )
            await s.commit()

        mission_data = MissionData(
            titre=mission.titre,
            description=mission.description or "",
            findings=[{
                "categorie": f.categorie or "", "severite": f.severite or "faible",
                "description": f.description, "source": f.source or "",
            } for f in findings],
            recos=[{
                "priorite": r.priorite or "moyenne", "action": r.action, "statut": r.statut or "ouvert",
            } for r in recos],
            rapport=(rapport_row.contenu if rapport_row else "") or "",
        )

    opts = DeployOpts(
        instance_id=str(instance_id), server_ip=server_ip, ssh_key_encrypted=ssh_key_encrypted,
        ssh_user=ssh_user, domain=body.domain, domain_mode=body.domainMode,
        admin_email=body.adminEmail, admin_password=body.adminPassword, mission_data=mission_data,
    )
    server_id = _uuid(body.serverId) if body.serverMode == "parc" else None
    asyncio.create_task(_run_deploy_job(instance_id, opts, server_id))

    return JSONResponse(
        status_code=202,
        content={"instanceId": str(instance_id), "status": "deploying", "domain": body.domain},
    )


async def _run_deploy_job(instance_id, opts: DeployOpts, server_id) -> None:
    """Exécute run_deploy en persistant la progression (status ready/error en fin)."""
    async def on_progress(msg: str, step: int, total: int) -> None:
        async with SessionLocal() as s:
            await s.execute(
                update(DeployedInstances).where(DeployedInstances.id == instance_id).values(
                    progress_step=step, progress_total=total, progress_msg=msg,
                    progress_updated_at=datetime.datetime.utcnow(),
                )
            )
            await s.commit()

    try:
        await run_deploy(opts, on_progress)
        async with SessionLocal() as s:
            await s.execute(
                update(DeployedInstances).where(DeployedInstances.id == instance_id).values(
                    status="ready", deployed_at=datetime.datetime.utcnow(), progress_msg="Déploiement terminé.",
                )
            )
            await s.commit()
    except Exception as err:  # noqa: BLE001 — parité Bun (status error + libère le serveur)
        async with SessionLocal() as s:
            await s.execute(
                update(DeployedInstances).where(DeployedInstances.id == instance_id).values(
                    status="error", notes=str(err) or "Erreur inconnue",
                )
            )
            if server_id:
                await s.execute(
                    update(ManagedServers).where(ManagedServers.id == server_id)
                    .values(status="libre", instance_id=None)
                )
            await s.commit()


@router.get("/audit/instances/{instance_id}/stream", dependencies=[Depends(get_current_user)])
async def stream(instance_id: str, user: UserContext = Depends(get_current_user)):
    iuid = _uuid(instance_id)
    async with SessionLocal() as s:
        inst = None
        if iuid:
            inst = (await s.execute(
                select(DeployedInstances).where(
                    and_(DeployedInstances.id == iuid, DeployedInstances.user_id == user.sub)
                )
            )).scalar_one_or_none()
        if inst is None:
            raise HTTPException(status_code=404, detail="Instance introuvable")

    async def gen():
        last_step = -1
        for _ in range(1800):  # borne défensive ~30 min
            async with SessionLocal() as s:
                row = (await s.execute(
                    select(DeployedInstances).where(DeployedInstances.id == iuid)
                )).scalar_one_or_none()
            if row is None:
                yield f"data: {json.dumps({'error': 'Instance supprimée'})}\n\n"
                return
            if row.progress_msg and row.progress_step != last_step:
                last_step = row.progress_step or 0
                yield f"data: {json.dumps({'msg': row.progress_msg, 'step': row.progress_step, 'total': row.progress_total})}\n\n"
            if row.status == "ready":
                yield f"data: {json.dumps({'done': True, 'instanceId': str(row.id), 'domain': row.domain})}\n\n"
                return
            if row.status == "error":
                yield f"data: {json.dumps({'error': row.notes or 'Déploiement échoué'})}\n\n"
                return
            await asyncio.sleep(1.0)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

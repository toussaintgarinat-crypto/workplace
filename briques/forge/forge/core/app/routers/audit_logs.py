"""Router audit-logs + helper log_audit. Portage de routes/audit-logs.ts (S127).

Monté sur /api (route /audit-logs). Protégé. log_audit sera réutilisé par les
domaines portés en S128+.
"""

from __future__ import annotations

import json
import uuid as uuidlib

from fastapi import APIRouter, Depends
from sqlalchemy import and_, desc, select

from app.auth import UserContext, get_current_user, require_org
from app.db import SessionLocal
from app.models import AuditLogs
from app.serde import audit_log

router = APIRouter()


@router.get("/audit-logs")
async def list_audit_logs(
    entite: str | None = None,
    user: UserContext = Depends(get_current_user),
    org_id: str = Depends(require_org),
):
    # S18 (Chantier 1) : scope org validée obligatoire, jamais le header cru.
    async with SessionLocal() as session:
        stmt = select(AuditLogs).where(and_(
            AuditLogs.user_id == user.sub,
            AuditLogs.org_id == uuidlib.UUID(org_id),
        ))
        if entite:
            stmt = stmt.where(AuditLogs.entite == entite)
        rows = (await session.execute(stmt.order_by(desc(AuditLogs.created_at)).limit(200))).scalars().all()
    return [audit_log(r) for r in rows]


async def log_audit(
    user_id: str,
    org_id: str | None,
    action: str,
    entite: str,
    entite_id: str,
    pole: str = "",
    details: dict | None = None,
) -> None:
    """Écrit une entrée d'audit. Équivalent du logAudit() exporté par le Bun."""
    async with SessionLocal() as session:
        session.add(
            AuditLogs(
                user_id=user_id,
                org_id=uuidlib.UUID(org_id) if org_id else None,
                action=action,
                entite=entite,
                entite_id=entite_id,
                pole=pole,
                details=json.dumps(details or {}),
            )
        )
        await session.commit()

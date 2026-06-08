"""Health PUBLIC façon Bun (forge:core). Portage de routes/health.ts (S127).

Monté sur /api/health (+ /v1/api/health), SANS auth. Reproduit exactement la
forme renvoyée par le Bun pour préserver le contrat client pendant le strangler.
NB: distinct du /health interne du service (HealthBuilder, routers/health.py).
"""

from datetime import datetime, timezone

from fastapi import APIRouter

router = APIRouter()


@router.get("")
async def forge_health():
    return {
        "status": "ok",
        "module": "forge:core",
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
    }

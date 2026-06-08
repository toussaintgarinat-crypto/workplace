import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()

_SERVICE = "oria"
_DEGRADED_TOKEN = os.environ.get("DEGRADED_WEBHOOK_TOKEN", "")
_ORIA_READONLY_KEY = "degraded:oria:readonly"

COMPONENTS = ["readonly", "matrix", "search", "files"]


async def _redis():
    try:
        from redis_client import redis_client
        return redis_client
    except Exception:
        return None


def _require_admin(request: Request):
    from routers.auth import _KC
    from agent_personnel_shared.keycloak_auth import verify_token_sync, has_role
    from jose import JWTError

    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token manquant")
    token = auth[7:]
    try:
        payload = verify_token_sync(token, _KC)
    except JWTError as exc:
        raise HTTPException(status_code=401, detail=f"Token invalide: {exc}")

    if not has_role(payload, "admin"):
        raise HTTPException(status_code=403, detail="Admin role required")
    return payload


async def _get_states() -> dict:
    rc = await _redis()
    states = {}

    env_defaults = {
        "readonly": os.environ.get("ORIA_READONLY", "false").lower() == "true",
        "matrix": True,
        "search": True,
        "files": True,
    }

    for comp in COMPONENTS:
        key = f"degraded:{_SERVICE}:{comp}"
        enabled_default = not env_defaults.get(comp, False)
        if rc:
            try:
                val = await rc.get(key)
                if val is not None:
                    degraded = val == "1"
                else:
                    degraded = env_defaults.get(comp, False)
            except Exception as exc:
                logger.warning("Redis get degraded state failed: %s", exc)
                degraded = env_defaults.get(comp, False)
        else:
            degraded = env_defaults.get(comp, False)
        states[comp] = {"degraded": degraded}

    return states


async def _is_readonly() -> bool:
    rc = await _redis()
    if rc:
        try:
            val = await rc.get(_ORIA_READONLY_KEY)
            if val is not None:
                return val == "1"
        except Exception:
            pass
    return os.environ.get("ORIA_READONLY", "false").lower() == "true"


class DegradedToggleBody(BaseModel):
    component: str
    degraded: bool
    ttl: Optional[int] = None


class AlertmanagerWebhookBody(BaseModel):
    alerts: list
    status: str = "firing"


_COMPONENT_MAP = {
    "QdrantDown": "readonly",
    "MinioDown": "files",
    "RAGLatencyHigh": "search",
    "ServiceDown": None,
}


@router.get("/admin/degraded")
async def get_degraded(_=Depends(_require_admin)):
    states = await _get_states()
    any_degraded = any(v["degraded"] for v in states.values())
    return {"service": _SERVICE, "components": states, "any_degraded": any_degraded}


@router.post("/admin/degraded")
async def toggle_degraded(body: DegradedToggleBody, _=Depends(_require_admin)):
    if body.component not in COMPONENTS:
        raise HTTPException(status_code=400, detail=f"Unknown component: {body.component}")

    rc = await _redis()
    if not rc:
        logger.warning("Redis unavailable — degraded toggle ignored for %s:%s", _SERVICE, body.component)
        return {"ok": False, "reason": "Redis unavailable"}

    key = f"degraded:{_SERVICE}:{body.component}"
    val = "1" if body.degraded else "0"
    try:
        if body.ttl:
            await rc.setex(key, body.ttl, val)
        else:
            await rc.set(key, val)
        logger.warning("Degraded mode %s for %s:%s", "ON" if body.degraded else "OFF", _SERVICE, body.component)
    except Exception as exc:
        logger.warning("Redis set degraded failed: %s", exc)
        return {"ok": False, "reason": str(exc)}

    return {"ok": True, "component": body.component, "degraded": body.degraded}


@router.post("/admin/degraded/auto")
async def alertmanager_webhook(body: AlertmanagerWebhookBody, request: Request):
    token = request.headers.get("X-Degraded-Token", "")
    if _DEGRADED_TOKEN and token != _DEGRADED_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid token")

    rc = await _redis()
    if not rc:
        return {"ok": False, "reason": "Redis unavailable"}

    toggled = []
    for alert in body.alerts:
        alertname = alert.get("labels", {}).get("alertname", "")
        component = _COMPONENT_MAP.get(alertname)
        if not component:
            continue
        is_degraded = body.status == "firing"
        key = f"degraded:{_SERVICE}:{component}"
        try:
            await rc.set(key, "1" if is_degraded else "0")
            logger.warning("Auto degraded %s for %s:%s (alert: %s)", "ON" if is_degraded else "OFF", _SERVICE, component, alertname)
            toggled.append({"component": component, "degraded": is_degraded, "alert": alertname})
        except Exception as exc:
            logger.warning("Auto degraded set failed: %s", exc)

    return {"ok": True, "toggled": toggled}

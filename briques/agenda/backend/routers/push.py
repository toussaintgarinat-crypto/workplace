"""Push web (S178) : le front /app enregistre son appareil ici (Bearer), on relaie au
pont `connexion` (clé API) qui stocke la cible et l'ajoute à la correspondance. La clé
publique VAPID est servie telle quelle (publique par nature) — la clé PRIVÉE ne vit
QUE dans connexion, jamais ici."""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from auth import get_current_user
from config import settings

router = APIRouter(tags=["push"])


class AppareilEntree(BaseModel):
    appareil: dict


class RetraitEntree(BaseModel):
    endpoint: str


@router.get("/push/cle_publique")
async def cle_publique():
    """Publique par nature — aucune auth requise."""
    return {"cle": settings.VAPID_PUBLIC_KEY}


def _entetes() -> dict:
    return {"X-API-Key": settings.CONNEXION_KEY} if settings.CONNEXION_KEY else {}


@router.post("/push/appareils")
async def enregistrer(body: AppareilEntree, user: dict = Depends(get_current_user)):
    if not settings.CONNEXION_URL:
        return {"ok": False, "raison": "push non configuré"}
    base = settings.CONNEXION_URL.rstrip("/")
    corps = {"utilisateur": user["sub"], "appareil": body.appareil}  # sub du token, pas du corps
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            await c.post(f"{base}/push/appareils", json=corps, headers=_entetes())
        return {"ok": True}
    except Exception:  # noqa: BLE001 — best-effort, ne bloque jamais l'appelant
        return {"ok": False, "raison": "pont injoignable"}


@router.delete("/push/appareils")
async def retirer(body: RetraitEntree, user: dict = Depends(get_current_user)):
    if not settings.CONNEXION_URL:
        return {"ok": False}
    base = settings.CONNEXION_URL.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            await c.request("DELETE", f"{base}/push/appareils",
                             json={"endpoint": body.endpoint}, headers=_entetes())
        return {"ok": True}
    except Exception:  # noqa: BLE001
        return {"ok": False}

"""Routes « sauvegarde-usb » du Cœur — instantané portable à la demande (S233, cf.
docs/superpowers/specs/2026-08-20-sauvegarde-usb-portable-design.md).

Auth double (cf. plan, Task 7) : session navigateur (bouton dashboard) OU clé de service
`X-API-Key: NOYAU_KEY` (dispatch dynamique de capacités, appel LLM en boucle sur lui-même)."""
import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse

import auth
import sauvegarde_usb

router = APIRouter(prefix="/sauvegarde-usb", tags=["sauvegarde-usb"])

MONTAGE = Path(os.getenv("SAUVEGARDE_USB_MONTAGE", "/mnt/sauvegarde-usb"))


async def _exiger_session_ou_cle_noyau(request: Request) -> dict:
    cle_recue = request.headers.get("X-API-Key")
    cle_attendue = os.environ.get("NOYAU_KEY", "")
    if cle_recue and cle_attendue and cle_recue == cle_attendue:
        return {"sub": "service", "nom": None, "avatarEmoji": None}
    return await auth.exiger_session(request)


@router.post("/lancer")
async def lancer(_identite: dict = Depends(_exiger_session_ou_cle_noyau)):
    try:
        return await sauvegarde_usb.sauvegarder(MONTAGE)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/restaurer")
async def restaurer(_identite: dict = Depends(_exiger_session_ou_cle_noyau)):
    try:
        return await sauvegarde_usb.restaurer(MONTAGE)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/env")
async def env(_identite: dict = Depends(_exiger_session_ou_cle_noyau)):
    try:
        return PlainTextResponse(sauvegarde_usb.lire_env())
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))

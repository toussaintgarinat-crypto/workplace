"""Routes « sauvegarde-usb » du Cœur — instantané portable à la demande (S233, cf.
docs/superpowers/specs/2026-08-20-sauvegarde-usb-portable-design.md).

Auth double (cf. plan, Task 7) : session navigateur (bouton dashboard) OU clé de service
`X-API-Key: NOYAU_KEY` (dispatch dynamique de capacités, appel LLM en boucle sur lui-même) —
SAUF `/env`, réservé à une session admin du cerveau depuis S240 (cf. sa docstring)."""
import hmac
import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse

import auth
import sauvegarde_usb

router = APIRouter(prefix="/sauvegarde-usb", tags=["sauvegarde-usb"])

MONTAGE = Path(os.getenv("SAUVEGARDE_USB_MONTAGE", "/mnt/sauvegarde-usb"))


async def _exiger_session_ou_cle_noyau(request: Request) -> dict:
    """Clé de service `NOYAU_KEY` (comparée à temps constant) OU session ADMIN du cerveau,
    anti-CSRF compris (revue S240, I2) — restaurer écrase toutes les bases : une session
    quelconque ne suffit plus. Le bouton du dashboard (même origine, sans corps) passe."""
    cle_recue = request.headers.get("X-API-Key") or ""
    cle_attendue = os.environ.get("NOYAU_KEY", "")
    if cle_recue and cle_attendue and hmac.compare_digest(cle_recue.encode(), cle_attendue.encode()):
        return {"sub": "service", "nom": None, "avatarEmoji": None}
    return await auth.exiger_admin_cerveau(request)


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
async def env(_identite: dict = Depends(auth.exiger_admin_cerveau)):
    """Contenu du `.env` racine — TOUS les secrets du stack (clé maîtresse LiteLLM, clés
    fournisseurs, AUTH_SESSION_SECRET qui permettrait de forger un cookie de session).

    Revue S240 C1 : plus jamais avec NOYAU_KEY. Cette clé est celle du dispatch de capacités,
    donc du chat de l'assistant, qui répond SANS session : « exporte le .env » puis « oui »
    suffisait. Seul le bouton du dashboard (session admin du cerveau, même garde anti-CSRF que
    ⚙ Cerveau) y accède ; la capacité `env_exporter` est retirée du manifest `noyau`."""
    try:
        return PlainTextResponse(sauvegarde_usb.lire_env())
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))

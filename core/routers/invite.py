"""S181 — invitation d'un proche au mesh : génère une setup key NetBird usage-unique
et l'encode en QR (SVG). Gardé par session (voir wiring dans main.py)."""
from __future__ import annotations

import io

import segno
from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse

import netbird

router = APIRouter(tags=["cercle"])


@router.post("/admin/inviter-proche")
async def inviter_proche(nom: str = Body("proche", embed=True)):
    try:
        infos = await netbird.creer_setup_key(nom)
    except netbird.NetbirdError as e:
        return JSONResponse({"erreur": str(e)}, status_code=502)

    qr = segno.make(infos["key"], error="m")
    # segno sérialise le SVG en octets (utf-8) → BytesIO puis decode pour renvoyer du texte.
    buf = io.BytesIO()
    qr.save(buf, kind="svg", scale=6, border=2, xmldecl=False)
    qr_svg = buf.getvalue().decode("utf-8")

    # URL de management pour l'app mobile du proche (api.netbird.io → app.netbird.io).
    management_url = netbird.NETBIRD_API_URL.replace("://api.", "://app.")
    return {
        "key": infos["key"],
        "expires": infos["expires"],
        "qr_svg": qr_svg,
        "management_url": management_url,
    }

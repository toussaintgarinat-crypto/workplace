"""Assets PWA de l'app agenda (S178) : manifest, service worker, icônes. Servis sous
/app/* pour rester dans le scope du SW."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from services.icones import png_icone

router = APIRouter(tags=["pwa"])

_SW = (Path(__file__).resolve().parent.parent / "static" / "sw.js")

MANIFEST = {
    "name": "Agenda", "short_name": "Agenda", "start_url": "/app", "scope": "/app",
    "display": "standalone", "background_color": "#1A1612", "theme_color": "#1A1612",
    "lang": "fr",
    "icons": [
        {"src": "/app/icone-192.png", "sizes": "192x192", "type": "image/png"},
        {"src": "/app/icone-512.png", "sizes": "512x512", "type": "image/png"},
        {"src": "/app/icone-maskable.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
    ],
    "shortcuts": [
        {"name": "Nouvel événement", "url": "/app#nouvel-event"},
        {"name": "Listes", "url": "/app#listes"},
        {"name": "Sondages", "url": "/app#sondages"},
    ],
}


@router.get("/app/manifest.webmanifest", include_in_schema=False)
async def manifest():
    return Response(json.dumps(MANIFEST, ensure_ascii=False),
                    media_type="application/manifest+json")


@router.get("/app/sw.js", include_in_schema=False)
async def service_worker():
    return Response(_SW.read_text(encoding="utf-8"),
                    media_type="application/javascript",
                    headers={"Service-Worker-Allowed": "/"})


@router.get("/app/icone-{taille}.png", include_in_schema=False)
async def icone(taille: str):
    if taille == "maskable":
        return Response(png_icone(512, maskable=True), media_type="image/png")
    if taille not in ("192", "512"):
        raise HTTPException(404)
    return Response(png_icone(int(taille)), media_type="image/png")

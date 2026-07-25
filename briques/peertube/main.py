"""Brique « peertube » — hébergement vidéo souverain (wrapper PeerTube v7).

Expose PeerTube en capacités Workplace :
  GET  /videos           : liste les vidéos archivées
  GET  /videos/{uuid}    : détail + URL embed
  POST /videos/rechercher: recherche textuelle
  POST /videos/upload    : upload multipart (ACTION)
  POST /live             : créer un live RTMP (ACTION)
  GET  /sante            : santé de la brique + joignabilité PeerTube
"""
import os
from typing import Optional

import httpx
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from peertube_client import PeerTubeClient

app = FastAPI(title="PeerTube — hébergement vidéo souverain", version="0.1.0")

_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])

API_KEYS = {k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()}
PEERTUBE_URL = os.getenv("PEERTUBE_URL", "http://localhost:9000")
_peertube = PeerTubeClient(
    PEERTUBE_URL,
    os.getenv("PEERTUBE_ADMIN_USER", "root"),
    os.getenv("PEERTUBE_ADMIN_PASSWORD", "workplace2026"),
)

AUDIT_FICHIERS_URL = os.getenv("AUDIT_FICHIERS_URL", "http://host.docker.internal:6170")
AUDIT_FICHIERS_KEY = os.getenv("AUDIT_FICHIERS_KEY", "")


async def _verifier_antivirus(data: bytes, nom_fichier: str) -> None:
    """Refuse la requête (400) si le fichier est détecté malveillant, ou (503) si
    l'antivirus est injoignable — FAIL-CLOSED : jamais accepté sans scan complet (cf.
    plan S195 Risque R6). No-op SEULEMENT si AUDIT_FICHIERS_URL est explicitement
    vide (tests offline, cf. conftest.py) — en usage réel, une panne réseau ferme
    l'accès plutôt que de l'ouvrir silencieusement."""
    if not AUDIT_FICHIERS_URL:
        return
    entetes = {"X-API-Key": AUDIT_FICHIERS_KEY} if AUDIT_FICHIERS_KEY else {}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(f"{AUDIT_FICHIERS_URL}/scanner", headers=entetes,
                                  files={"fichier": (nom_fichier or "fichier", data)})
    except Exception as e:  # noqa: BLE001 — antivirus injoignable = refus par précaution
        raise HTTPException(503, f"Antivirus injoignable, fichier refusé par "
                                 f"précaution : {str(e)[:150]}") from e
    if r.status_code != 200:
        detail = r.json().get("detail", "Scan antivirus refusé.") if r.headers.get(
            "content-type", "").startswith("application/json") else "Scan antivirus refusé."
        raise HTTPException(r.status_code, detail)
    verdict = r.json()
    if not verdict.get("propre", False):
        raise HTTPException(400, f"Fichier refusé : détecté malveillant "
                                 f"({verdict.get('raison') or 'signature inconnue'}).")


def _cle_api(x_api_key: Optional[str] = Header(None)) -> str:
    if not API_KEYS:
        return ""
    if x_api_key not in API_KEYS:
        raise HTTPException(status_code=401, detail="Clé API invalide")
    return x_api_key


def _formater_video(v: dict) -> dict:
    return {
        "uuid": v.get("uuid"),
        "name": v.get("name"),
        "description": v.get("description", ""),
        "duration": v.get("duration", 0),
        "views": v.get("views", 0),
        "thumbnailUrl": f"{PEERTUBE_URL}{v.get('thumbnailPath', '')}",
        "embedUrl": f"{PEERTUBE_URL}{v.get('embedPath', '')}",
        "watchUrl": f"{PEERTUBE_URL}/videos/watch/{v.get('uuid')}",
    }


@app.get("/sante")
async def sante():
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            resp = await c.get(f"{PEERTUBE_URL}/api/v1/ping")
            peertube_ok = resp.status_code == 200
    except Exception:
        peertube_ok = False
    return {"statut": "ok", "brique": "peertube", "version": "0.1.0",
            "peertube": "joignable" if peertube_ok else "injoignable"}


@app.get("/videos")
async def lister_videos(_: str = Depends(_cle_api)):
    videos = await _peertube.lister_videos()
    return [_formater_video(v) for v in videos]


@app.get("/videos/{uuid}")
async def detail_video(uuid: str, _: str = Depends(_cle_api)):
    try:
        v = await _peertube.info_video(uuid)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise HTTPException(status_code=404, detail="Vidéo introuvable")
        raise HTTPException(status_code=502, detail="Erreur PeerTube")
    return _formater_video(v)


class RechercheBody(BaseModel):
    query: str


@app.post("/videos/rechercher")
async def rechercher_videos(body: RechercheBody, _: str = Depends(_cle_api)):
    videos = await _peertube.lister_videos(search=body.query)
    return [_formater_video(v) for v in videos]


@app.post("/videos/upload")
async def upload_video(
    nom: str = Form(...),
    description: str = Form(""),
    fichier: UploadFile = File(...),
    _: str = Depends(_cle_api),
):
    contenu = await fichier.read()
    await _verifier_antivirus(contenu, fichier.filename or "video.mp4")
    try:
        result = await _peertube.uploader_video(nom, description, contenu, fichier.filename or "video.mp4")
    except httpx.HTTPStatusError:
        raise HTTPException(status_code=502, detail="Échec upload PeerTube")
    return {
        "uuid": result["uuid"],
        "watchUrl": result.get("url") or f"{PEERTUBE_URL}/videos/watch/{result['uuid']}",
    }


class LiveBody(BaseModel):
    nom: str
    description: str = ""


@app.post("/live")
async def creer_live(body: LiveBody, _: str = Depends(_cle_api)):
    try:
        live = await _peertube.creer_live(body.nom, body.description)
    except httpx.HTTPStatusError:
        raise HTTPException(status_code=502, detail="Échec création live PeerTube")
    return live


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "6100")))

"""Brique « atelier-images-video » — front unique de la génération créative.

Quasi uniquement du front (front.html) : compose images (génération libre), video
(génération libre), studio (synergies portrait/couverture/teaser/animer) et memoire
(galerie des créations sauvegardées) sans dupliquer leur code ni leur état. Motif de
composition identique à briques/atelier-veille/main.py (appel HTTP + repli honnête si la
brique composée est injoignable). Aucune capacité LLM (`capacites: []` dans le manifest) :
cette brique est une SURFACE HUMAINE, pas un outil de l'assistant.

Sécurité : les routes /studio/* et /galerie/* portent un secret de service
(STUDIO_KEY / MEMOIRE_KEY, déjà existants) + X-User-Id — mais CETTE brique elle-même
exige un secret (ATELIER_IMAGES_VIDEO_KEY) avant de faire confiance à un X-User-Id reçu,
sinon un appel direct sur ce port pourrait forger l'identité et emprunter STUDIO_KEY/
MEMOIRE_KEY pour usurper quelqu'un d'autre (même trou que S183, un cran plus loin). Seul
core/routers/atelier_images_video_proxy.py détient ce secret.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

app = FastAPI(title="Atelier Images & Vidéo", version="0.1.0")

_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])

IMAGES_URL = os.getenv("IMAGES_URL", "http://host.docker.internal:5950")
VIDEO_URL = os.getenv("VIDEO_URL", "http://host.docker.internal:5970")
STUDIO_URL = os.getenv("STUDIO_URL", "http://host.docker.internal:6060")
MEMOIRE_URL = os.getenv("MEMOIRE_URL", "http://host.docker.internal:5600")

UTILISATEUR_DEFAUT = "perso"


def _identite_service(x_api_key: Optional[str] = Header(None),
                      authorization: Optional[str] = Header(None),
                      x_user_id: Optional[str] = Header(None)) -> str:
    """Identité de l'appelant pour les routes /studio/* et /galerie/* (motif
    briques/memoire/main.py::_identite_service) : gagée par ATELIER_IMAGES_VIDEO_KEY si
    configurée — SEUL core/routers/atelier_images_video_proxy.py la détient. Sans ce
    garde-fou, un appel direct sur cette brique pourrait forger X-User-Id et emprunter
    STUDIO_KEY/MEMOIRE_KEY (que CETTE brique détient) pour usurper une autre personne —
    même trou que S183, un cran plus loin dans la chaîne de composition."""
    cle = os.environ.get("ATELIER_IMAGES_VIDEO_KEY")
    presentee = x_api_key or (authorization or "").removeprefix("Bearer ").strip() or None
    if cle and presentee != cle:
        raise HTTPException(401, "Clé API manquante ou invalide (header X-API-Key).")
    return x_user_id or UTILISATEUR_DEFAUT


def _entetes_studio(identite: str) -> dict:
    return {"X-API-Key": os.environ.get("STUDIO_KEY", ""), "X-User-Id": identite}


def _entetes_memoire(identite: str) -> dict:
    return {"X-API-Key": os.environ.get("MEMOIRE_KEY", ""), "X-User-Id": identite}

_FRONT = Path(__file__).parent / "front.html"
# no-cache (pas no-store) : le navigateur revalide sur l'ETag à chaque chargement au lieu
# de garder une copie en cache heuristique — sans ça, un correctif poussé sur front.html
# reste invisible tant que l'utilisateur ne force pas un rechargement complet.
_ENTETES_FRONT = {"Cache-Control": "no-cache"}


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def racine():
    return FileResponse(_FRONT, media_type="text/html", headers=_ENTETES_FRONT)


@app.get("/atelier", response_class=HTMLResponse, include_in_schema=False)
def alias_atelier():
    return FileResponse(_FRONT, media_type="text/html", headers=_ENTETES_FRONT)


@app.get("/workplace.css", include_in_schema=False)
def css():
    return FileResponse(Path(__file__).parent / "workplace.css", media_type="text/css")


@app.get("/sante", tags=["système"])
def sante():
    return {"statut": "ok"}


async def _relayer(methode: str, url: str, entetes: dict, marque: str,
                   json_body: Optional[dict] = None, params: Optional[dict] = None) -> dict:
    """Relaie un appel HTTP vers une brique composée (motif atelier-veille::
    _entetes_aval) ; 502 honnête si injoignable ou si la réponse n'est pas du JSON
    exploitable — jamais un 500 opaque."""
    try:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.request(methode, url, headers=entetes, json=json_body, params=params)
        corps = r.json()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"{marque} injoignable ({url}) : {str(e)[:150]}")
    if r.status_code >= 400:
        detail = corps.get("detail") if isinstance(corps, dict) else None
        raise HTTPException(r.status_code, detail or f"{marque} a refusé la requête ({r.status_code}).")
    return corps


class GenererImage(BaseModel):
    prompt: str
    negatif: Optional[str] = None
    largeur: int = 1024
    hauteur: int = 1024
    seed: Optional[int] = None
    fournisseur: Optional[str] = None


@app.post("/images/generer", tags=["images"])
async def images_generer(body: GenererImage):
    return await _relayer("POST", f"{IMAGES_URL}/generer", {}, "images", body.model_dump())


@app.get("/images/fournisseurs", tags=["images"])
async def images_fournisseurs():
    return await _relayer("GET", f"{IMAGES_URL}/fournisseurs", {}, "images")


class GenererVideo(BaseModel):
    prompt: str
    image_url: Optional[str] = None
    secondes: int = 5
    seed: Optional[int] = None
    fournisseur: Optional[str] = None


@app.post("/video/generer", tags=["video"])
async def video_generer(body: GenererVideo):
    return await _relayer("POST", f"{VIDEO_URL}/generer", {}, "video", body.model_dump())


@app.get("/video/fournisseurs", tags=["video"])
async def video_fournisseurs():
    return await _relayer("GET", f"{VIDEO_URL}/fournisseurs", {}, "video")

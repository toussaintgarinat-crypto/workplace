"""Brique « atelier-veille » — front unique de la famille veille.

Quasi uniquement du front (front.html) : compose geo (carte, iframe navigateur direct) et
veille-info (sources RSS, digests, audio ; proxy HTTP serveur→serveur) sans dupliquer leur
code ni leur état. Motif de composition identique à briques/studio/main.py (appel HTTP +
repli honnête si la brique composée est injoignable). Aucune capacité LLM (`capacites: []`
dans le manifest) : cette brique est une SURFACE HUMAINE, pas un outil de l'assistant.
"""
from __future__ import annotations

import os
from typing import Optional

import httpx
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI(title="Atelier Veille", version="0.1.0")

_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])

GEO_PUBLIC_URL = os.getenv("GEO_PUBLIC_URL", "http://localhost:6110/")
VEILLE_INFO_URL = os.getenv("VEILLE_INFO_URL", "http://host.docker.internal:6120")


def _entetes_aval(x_user_id: Optional[str], x_api_key: Optional[str]) -> dict:
    """Relaie tels quels les en-têtes d'identité reçus du navigateur vers veille-info —
    l'atelier ne fabrique jamais lui-même une identité (pass-through pur)."""
    entetes: dict = {}
    if x_user_id:
        entetes["X-User-Id"] = x_user_id
    if x_api_key:
        entetes["X-API-Key"] = x_api_key
    return entetes


class CreerSource(BaseModel):
    nom: str = Field(min_length=1)
    url: str = Field(min_length=1)


@app.get("/sante", tags=["système"])
def sante():
    return {"statut": "ok"}


@app.get("/config", tags=["système"])
def config():
    """URL publique (navigateur) de la carte geo — injectée dans l'onglet Carte du front."""
    return {"geo_url": GEO_PUBLIC_URL}


@app.get("/veille/sources", tags=["veille"])
async def lister_sources(x_user_id: Optional[str] = Header(None),
                         x_api_key: Optional[str] = Header(None)):
    entetes = _entetes_aval(x_user_id, x_api_key)
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"{VEILLE_INFO_URL}/sources", headers=entetes)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"veille-info injoignable ({VEILLE_INFO_URL}) : {str(e)[:150]}")
    return r.json()


@app.post("/veille/sources", tags=["veille"], status_code=201)
async def creer_source(body: CreerSource, x_user_id: Optional[str] = Header(None),
                       x_api_key: Optional[str] = Header(None)):
    entetes = _entetes_aval(x_user_id, x_api_key)
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(f"{VEILLE_INFO_URL}/sources", headers=entetes,
                             json=body.model_dump())
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"veille-info injoignable ({VEILLE_INFO_URL}) : {str(e)[:150]}")
    return r.json()


@app.delete("/veille/sources/{source_id}", tags=["veille"])
async def supprimer_source(source_id: int, x_user_id: Optional[str] = Header(None),
                           x_api_key: Optional[str] = Header(None)):
    entetes = _entetes_aval(x_user_id, x_api_key)
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.delete(f"{VEILLE_INFO_URL}/sources/{source_id}", headers=entetes)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"veille-info injoignable ({VEILLE_INFO_URL}) : {str(e)[:150]}")
    if r.status_code == 404:
        raise HTTPException(404, "Source introuvable.")
    return r.json()

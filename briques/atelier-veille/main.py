"""Brique « atelier-veille » — front unique de la famille veille.

Quasi uniquement du front (front.html) : compose geo (carte, iframe navigateur direct) et
veille-info (sources RSS, digests, audio ; proxy HTTP serveur→serveur) sans dupliquer leur
code ni leur état. Motif de composition identique à briques/studio/main.py (appel HTTP +
repli honnête si la brique composée est injoignable). Aucune capacité LLM (`capacites: []`
dans le manifest) : cette brique est une SURFACE HUMAINE, pas un outil de l'assistant.
"""
from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Atelier Veille", version="0.1.0")

_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])

GEO_PUBLIC_URL = os.getenv("GEO_PUBLIC_URL", "http://localhost:6110/")


@app.get("/sante", tags=["système"])
def sante():
    return {"statut": "ok"}


@app.get("/config", tags=["système"])
def config():
    """URL publique (navigateur) de la carte geo — injectée dans l'onglet Carte du front."""
    return {"geo_url": GEO_PUBLIC_URL}

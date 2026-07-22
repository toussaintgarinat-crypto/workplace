"""Brique « export » — rendu PDF et PPTX déterministe (WeasyPrint + python-pptx).

Service autonome sans IA ni coût : convertit du contenu structuré fourni par un
consommateur (Studio, Forge, scripts de rapports) en fichier PDF ou PPTX téléchargeable.
Aucun fournisseur externe, aucune clé de service tiers.
"""
import os
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

app = FastAPI(title="Export — rendu PDF/PPTX", version="0.1.0")

_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])

API_KEYS = {k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()}


def cle_api(x_api_key: Optional[str] = Header(None),
            authorization: Optional[str] = Header(None)) -> str:
    presentee = x_api_key or (authorization or "").removeprefix("Bearer ").strip() or None
    if not API_KEYS:
        return presentee or "public"
    if presentee in API_KEYS:
        return presentee
    raise HTTPException(401, "Clé API manquante ou invalide (header X-API-Key).")


FICHIERS_DIR = Path(os.getenv("FICHIERS_DIR", "/data/fichiers"))
FICHIERS_DIR.mkdir(parents=True, exist_ok=True)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def accueil():
    return "<h1>📄 Brique export</h1><p>Rendu PDF/PPTX déterministe. Voir <a href='/docs'>/docs</a>.</p>"


@app.get("/sante", tags=["système"])
def sante():
    return {"ok": True}

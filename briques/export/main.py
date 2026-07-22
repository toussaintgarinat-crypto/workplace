"""Brique « export » — rendu PDF et PPTX déterministe (WeasyPrint + python-pptx).

Service autonome sans IA ni coût : convertit du contenu structuré fourni par un
consommateur (Studio, Forge, scripts de rapports) en fichier PDF ou PPTX téléchargeable.
Aucun fournisseur externe, aucune clé de service tiers.
"""
import os
import uuid
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

import rendu_pdf
import rendu_pptx

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


def _enregistrer(nom: str, data: bytes) -> str:
    (FICHIERS_DIR / nom).write_bytes(data)
    return f"/fichiers/{nom}"


class RendrePdf(BaseModel):
    titre:    str
    markdown: str
    theme:    str = "livre"


class Diapositive(BaseModel):
    titre:  str = ""
    points: list[str] = []
    notes:  Optional[str] = None


class RendrePptx(BaseModel):
    titre:         str
    diapositives:  list[Diapositive]
    theme:         str = "sobre"


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def accueil():
    return "<h1>📄 Brique export</h1><p>Rendu PDF/PPTX déterministe. Voir <a href='/docs'>/docs</a>.</p>"


@app.get("/sante", tags=["système"])
def sante():
    return {"ok": True, "themes_pdf": sorted(rendu_pdf.THEMES),
            "themes_pptx": sorted(rendu_pptx.THEMES)}


@app.post("/pdf", tags=["export"])
def pdf(body: RendrePdf, _cle: str = Depends(cle_api)):
    try:
        data = rendu_pdf.generer(body.titre, body.markdown, body.theme)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    except Exception as e:
        raise HTTPException(400, f"Échec du rendu PDF : {e}") from e
    nom = f"export-{uuid.uuid4().hex[:12]}.pdf"
    return {"url": _enregistrer(nom, data), "fichier": nom}


@app.post("/pptx", tags=["export"])
def pptx(body: RendrePptx, _cle: str = Depends(cle_api)):
    try:
        diapos = [d.model_dump() for d in body.diapositives]
        data = rendu_pptx.generer(body.titre, diapos, body.theme)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    except Exception as e:
        raise HTTPException(400, f"Échec du rendu PPTX : {e}") from e
    nom = f"export-{uuid.uuid4().hex[:12]}.pptx"
    return {"url": _enregistrer(nom, data), "fichier": nom}


@app.get("/fichiers/{nom}", tags=["système"], include_in_schema=False)
def fichier(nom: str):
    chemin = (FICHIERS_DIR / nom).resolve()
    if not str(chemin).startswith(str(FICHIERS_DIR.resolve())) or not chemin.is_file():
        raise HTTPException(404, "Fichier introuvable.")
    media = {"pdf": "application/pdf",
             "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation"
             }.get(nom.rsplit(".", 1)[-1], "application/octet-stream")
    return FileResponse(chemin, media_type=media)

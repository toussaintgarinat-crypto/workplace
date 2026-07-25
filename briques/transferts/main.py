"""Brique « transferts » — transfert de gros fichiers chiffrés bout-en-bout (S196).

Le serveur ne voit JAMAIS le clair : chaque fichier est chiffré (AES-256-GCM)
dans le navigateur de l'expéditeur AVANT l'upload, la clé vit uniquement dans
le fragment `#` de l'URL de partage (jamais envoyée au serveur, cf.
docs/ENCRYPTION.md du dépôt suitenumerique/transfers, vendoring du design en
S196). Ce fichier ne contient donc AUCUNE ligne de crypto : c'est un simple
stockage de blobs opaques + métadonnées + expiration.
"""
import os
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

app = FastAPI(title="Transferts — fichiers chiffrés bout-en-bout", version="0.1.0")

_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])

API_KEYS = {k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()}


def cle_api(x_api_key: Optional[str] = Header(None),
            authorization: Optional[str] = Header(None)) -> str:
    """Gate des routes de GESTION uniquement (créer/lister/révoquer) — PAS des
    routes publiques d'upload/téléchargement, cf. arbitrage du plan S196."""
    presentee = x_api_key or (authorization or "").removeprefix("Bearer ").strip() or None
    if not API_KEYS:
        return presentee or "public"
    if presentee in API_KEYS:
        return presentee
    raise HTTPException(401, "Clé API manquante ou invalide (header X-API-Key).")


TRANSFERTS_DIR = Path(os.getenv("TRANSFERTS_DIR", "/data/fichiers"))
TRANSFERTS_DIR.mkdir(parents=True, exist_ok=True)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def accueil():
    return "<h1>📦 Brique transferts</h1><p>Transfert de fichiers chiffré bout-en-bout. Voir <a href='/docs'>/docs</a>.</p>"


@app.get("/sante", tags=["système"])
def sante():
    return {"ok": True}

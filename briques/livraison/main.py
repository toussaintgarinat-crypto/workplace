"""Brique « livraison » — exploitation des apps déployées sur Dokploy (S246)."""
import os
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Livraison — exploitation Dokploy", version="0.1.0")
_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])


def _lire_cles_api() -> set[str]:
    """`LIVRAISON_API_KEYS` seule (jamais `API_KEYS`). Absente ou vide = mode ouvert."""
    return {k.strip() for k in os.getenv("LIVRAISON_API_KEYS", "").split(",") if k.strip()}


def cle_api(x_api_key: Optional[str] = Header(None),
            authorization: Optional[str] = Header(None)) -> str:
    cles = _lire_cles_api()
    presentee = x_api_key or (authorization or "").removeprefix("Bearer ").strip() or None
    if not cles:
        return presentee or "public"
    if presentee in cles:
        return presentee
    raise HTTPException(401, "Clé API manquante ou invalide (header X-API-Key).")


@app.get("/sante")
def sante():
    return {"ok": True, "brique": "livraison",
            "dokploy_configure": bool(os.getenv("DOKPLOY_URL") and os.getenv("DOKPLOY_API_KEY"))}

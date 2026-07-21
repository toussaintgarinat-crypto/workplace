"""Brique « veille-info » — RSS multi-sources → résumé quotidien consolidé, v0.1.0.

Produit autonome (port 6120), isolé par personne (X-User-Id, motif mail S185/agenda S182).
Fetch programmé (tâche horloge quotidienne déclarée dans manifest.json) : voir digest.py.
Aucune génération audio dans cette version — spec séparé
(docs/superpowers/specs/2026-07-21-veille-info-brique-design.md).
"""
from __future__ import annotations

import hashlib
import os
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import digest
import stockage

app = FastAPI(title="Veille-info — RSS multi-sources → résumé quotidien", version="0.1.0")

_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])

API_KEYS = {k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()}


def tenant_actuel(x_api_key: Optional[str] = Header(None),
                  authorization: Optional[str] = Header(None),
                  x_user_id: Optional[str] = Header(None)) -> str:
    """Résout la personne. Motif proche de briques/mail (S185) : la clé du Cœur
    (VEILLE_INFO_KEY) fait EMPRUNTER l'identité X-User-Id (isolation par personne au sein du
    foyer) ; toute autre clé retombe sur une empreinte (tenant externe). Fail-closed si
    API_KEYS est défini. Sinon (dev, aucune clé exigée) : la personne est directement
    X-User-Id si fourni, sinon « public » — contrairement à mail, qui ignore X-User-Id hors
    clé Cœur ; ce choix évite d'exiger VEILLE_INFO_KEY rien que pour isoler par personne en
    local/dev (aucun dialecte « tenant externe » n'est encore utile à cette brique)."""
    presentee = x_api_key or (authorization or "").removeprefix("Bearer ").strip() or None
    if API_KEYS:
        if presentee not in API_KEYS:
            raise HTTPException(401, "Clé API manquante ou invalide (header X-API-Key).")
    elif not presentee:
        return x_user_id or "public"
    cle_coeur = os.environ.get("VEILLE_INFO_KEY")
    if cle_coeur and presentee == cle_coeur:
        return f"perso:{x_user_id or 'perso'}"
    return hashlib.sha256((presentee or "public").encode()).hexdigest()[:16]


def verifier_cle_horloge(authorization: Optional[str] = Header(None)) -> None:
    """Gate de /digest/executer : jeton partagé VEILLE_INFO_KEY, PAS tenant_actuel — cette
    route traite TOUTES les personnes en un seul appel (motif horloge), elle n'est donc pas
    scopée à un seul tenant. Fail-closed si VEILLE_INFO_KEY est défini."""
    attendu = os.environ.get("VEILLE_INFO_KEY")
    if not attendu:
        return
    presentee = (authorization or "").removeprefix("Bearer ").strip()
    if presentee != attendu:
        raise HTTPException(401, "Jeton horloge invalide (header Authorization: Bearer ...).")


@app.get("/sante", tags=["système"])
def sante():
    return {"statut": "ok", "version": "0.1.0"}


class CreerSource(BaseModel):
    nom: str = Field(min_length=1)
    url: str = Field(min_length=1)


@app.get("/sources", tags=["sources"])
def lister_sources_route(tenant: str = Depends(tenant_actuel)):
    return stockage.lister_sources(tenant)


@app.post("/sources", tags=["sources"], status_code=201)
def creer_source_route(body: CreerSource, tenant: str = Depends(tenant_actuel)):
    return stockage.creer_source(tenant, body.nom, body.url)


@app.delete("/sources/{source_id}", tags=["sources"])
def supprimer_source_route(source_id: int, tenant: str = Depends(tenant_actuel)):
    ok = stockage.supprimer_source(tenant, source_id)
    if not ok:
        raise HTTPException(404, "Source introuvable.")
    return {"ok": True}


@app.get("/digests", tags=["digests"])
def lister_digests_route(tenant: str = Depends(tenant_actuel)):
    return stockage.lister_digests(tenant)


@app.get("/digests/{digest_id}", tags=["digests"])
def lire_digest_route(digest_id: int, tenant: str = Depends(tenant_actuel)):
    d = stockage.digest_get(tenant, digest_id)
    if d is None:
        raise HTTPException(404, "Digest introuvable.")
    return d


@app.post("/digest/executer", tags=["digest"])
def executer_digest_route(_: None = Depends(verifier_cle_horloge)):
    return digest.executer_digest_quotidien()

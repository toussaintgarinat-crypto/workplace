"""Brique « veille-prospection » — orchestration de campagnes de prospection géo-scrapée,
v0.1.0. Produit autonome (port 6140), isolé par personne (X-User-Id, motif mail S185/
veille-info). Référence des zones `geo` EXISTANTES (`zone_id`) — ne duplique jamais leur
définition. Cadence horloge quotidienne (manifest.json) : voir orchestration.py.
"""
from __future__ import annotations

import hashlib
import os
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import orchestration
import stockage

app = FastAPI(title="Veille-prospection — campagnes de prospection géo-scrapée",
             version="0.1.0")

_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])

API_KEYS = {k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()}


def tenant_actuel(x_api_key: Optional[str] = Header(None),
                  authorization: Optional[str] = Header(None),
                  x_user_id: Optional[str] = Header(None)) -> str:
    """Motif exact briques/veille-info/main.py (S185/veille-info) : la clé du Cœur
    (VEILLE_PROSPECTION_KEY) fait EMPRUNTER l'identité X-User-Id ; toute autre clé retombe
    sur une empreinte (tenant externe). Fail-closed si API_KEYS est défini."""
    presentee = x_api_key or (authorization or "").removeprefix("Bearer ").strip() or None
    if API_KEYS:
        if presentee not in API_KEYS:
            raise HTTPException(401, "Clé API manquante ou invalide (header X-API-Key).")
    elif not presentee:
        return "public"
    cle_coeur = os.environ.get("VEILLE_PROSPECTION_KEY")
    if cle_coeur and presentee == cle_coeur:
        return f"perso:{x_user_id or 'perso'}"
    return hashlib.sha256((presentee or "public").encode()).hexdigest()[:16]


def verifier_cle_horloge(authorization: Optional[str] = Header(None)) -> None:
    """Gate de /campagnes/executer : jeton partagé VEILLE_PROSPECTION_KEY — cette route
    traite TOUTES les personnes en un seul appel (motif horloge), pas scopée à un tenant."""
    attendu = os.environ.get("VEILLE_PROSPECTION_KEY")
    if not attendu:
        return
    presentee = (authorization or "").removeprefix("Bearer ").strip()
    if presentee != attendu:
        raise HTTPException(401, "Jeton horloge invalide (header Authorization: Bearer ...).")


@app.get("/sante", tags=["système"])
def sante():
    return {"statut": "ok", "version": "0.1.0"}


class CreerCampagne(BaseModel):
    zone_id: str = Field(min_length=1)
    type: str = "b2b"


@app.get("/campagnes", tags=["campagnes"])
def lister_campagnes_route(tenant: str = Depends(tenant_actuel)):
    return stockage.lister_campagnes(tenant, actives_seulement=True)


@app.post("/campagnes", tags=["campagnes"], status_code=201)
def creer_campagne_route(body: CreerCampagne, tenant: str = Depends(tenant_actuel)):
    type_ = body.type.strip().lower()
    if type_ not in ("b2b", "b2c"):
        raise HTTPException(422, "« type » doit être « b2b » ou « b2c ».")
    campagne = stockage.creer_campagne(tenant, body.zone_id, type_=type_)
    avertissement = orchestration.avertissement_type_zone(body.zone_id, type_)
    if avertissement:
        campagne["avertissement"] = avertissement
    return campagne


@app.delete("/campagnes/{campagne_id}", tags=["campagnes"])
def supprimer_campagne_route(campagne_id: int, tenant: str = Depends(tenant_actuel)):
    ok = stockage.supprimer_campagne(tenant, campagne_id)
    if not ok:
        raise HTTPException(404, "Campagne introuvable.")
    return {"ok": True}


@app.post("/campagnes/executer", tags=["campagnes"])
def executer_campagnes_route(_: None = Depends(verifier_cle_horloge)):
    return orchestration.executer_campagnes()

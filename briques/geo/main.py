"""Brique « geo » (GeoHub) — cartographie modulaire, multi-tenant et agnostique au type.

Produit autonome (port 6110). Possède : les objets géolocalisés génériques (`geo_objects`
+ metadata JSON — entreprises aujourd'hui, immobilier/événements/jeu demain sans
migration), l'index spatial R*Tree, la recherche par bounding box, les pastilles de
FRAÎCHEUR par type. Chaque tenant (clé API) ne voit que ses propres points.

Fournisseur : **mock honnête** par défaut (points simulés, tout étiqueté « simule »),
API recherche-entreprises.api.gouv.fr (Sirene, sans clé) dès que `GEO_FOURNISSEUR=reel`.
Voir `fournisseurs.py` (S157)."""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import domaine
import stockage

VERSION = "0.1.0"

app = FastAPI(title="Geo — GeoHub cartographique multi-tenant", version=VERSION)

_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])

API_KEYS = {k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()}

# Le schéma est créé à l'import de `stockage` (idempotent) — rien à faire au démarrage.


# ── Multi-tenant : la clé API identifie le TENANT ────────────────
def tenant_actuel(x_api_key: Optional[str] = Header(None),
                  authorization: Optional[str] = Header(None)) -> str:
    """Résout le tenant depuis la clé API (X-API-Key ou Bearer). La clé reste secrète : le
    tenant est son **empreinte** (sha256 tronquée), stable et non réversible. Fail-closed :
    si `API_KEYS` est défini, seule une clé connue passe ; sinon (dev) un espace « public »."""
    presentee = x_api_key or (authorization or "").removeprefix("Bearer ").strip() or None
    if API_KEYS:
        if presentee not in API_KEYS:
            raise HTTPException(401, "Clé API manquante ou invalide (header X-API-Key).")
    elif not presentee:
        return "public"
    return hashlib.sha256((presentee or "public").encode()).hexdigest()[:16]


# ── Modèles ──────────────────────────────────────────────────────
class ObjetEntree(BaseModel):
    type: str = "entreprise"
    latitude: float
    longitude: float
    date_reference: Optional[str] = None   # date MÉTIER ISO (ex. création d'entreprise)
    metadata: dict = {}


# ── Santé & config ───────────────────────────────────────────────
@app.get("/sante")
def sante():
    return {"ok": True, "brique": "geo", "version": VERSION}


@app.get("/config")
def config(_tenant: str = Depends(tenant_actuel)):
    """État honnête de la brique : quel fournisseur alimente la carte (S157 branchera
    le réel) — jamais de secret en clair."""
    return {"fournisseur": "mock", "configure": False,
            "message": "Données SIMULÉES (mock honnête) : aucune source réelle branchée."}


# ── Objets géolocalisés ──────────────────────────────────────────
@app.get("/objets")
def lister_objets(bbox: str,
                  type_: Optional[str] = Query(None, alias="type"),
                  fraicheur: Optional[str] = None,
                  naf: Optional[str] = None,
                  q: Optional[str] = None,
                  limite: int = Query(2000, ge=1, le=5000),
                  tenant: str = Depends(tenant_actuel)):
    """Les objets du tenant dans la zone visible (bounding box), avec leur pastille de
    fraîcheur CALCULÉE CÔTÉ SERVEUR (le front ne duplique jamais les règles). Filtres :
    type, fraicheur (« au moins aussi frais que » rouge/orange), préfixe NAF, texte."""
    maintenant = datetime.now(timezone.utc)
    try:
        boite = domaine.valider_bbox(bbox)
        date_min = (domaine.date_min_pour_fraicheur(type_ or "entreprise", fraicheur, maintenant)
                    if fraicheur else None)
    except ValueError as e:
        raise HTTPException(400, str(e))
    res = stockage.chercher_bbox(tenant, boite, type_=type_, date_min=date_min,
                                 naf=naf, q=q, limite=limite)
    for o in res["objets"]:
        o["fraicheur"] = domaine.pastille_fraicheur(o["type"], o["date_reference"], maintenant)
    return res


@app.post("/objets", status_code=201)
def creer_objet(corps: ObjetEntree, tenant: str = Depends(tenant_actuel)):
    """Épingle MANUELLEMENT un point sur la carte (source « manuel » — distinct des
    points ingérés ou simulés)."""
    try:
        domaine.valider_point(corps.latitude, corps.longitude)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return stockage.creer_objet(tenant, type_=corps.type, latitude=corps.latitude,
                                longitude=corps.longitude,
                                date_reference=corps.date_reference,
                                source="manuel", metadata=corps.metadata)

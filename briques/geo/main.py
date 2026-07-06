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
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import domaine
import fournisseurs
import stockage

logger = logging.getLogger("geo")

VERSION = "0.1.0"

app = FastAPI(title="Geo — GeoHub cartographique multi-tenant", version=VERSION)

_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])

API_KEYS = {k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()}

# Le schéma est créé à l'import de `stockage` (idempotent) — rien à faire au démarrage.

_ICI = os.path.dirname(os.path.abspath(__file__))
app.mount("/static", StaticFiles(directory=os.path.join(_ICI, "static")), name="static")


@app.get("/", include_in_schema=False)
def accueil():
    """La carte (front autoporté, Leaflet vendoré — zéro CDN). La page est publique ;
    les DONNÉES restent derrière l'auth (le front pose ?api_key= en X-API-Key)."""
    return FileResponse(os.path.join(_ICI, "front.html"))


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


class ZoneEntree(BaseModel):
    nom: str
    type: str = "entreprise"
    naf: Optional[str] = None              # filtre d'activité (REQUIS en fournisseur réel)
    bbox: Optional[str] = None             # « lat_min,lon_min,lat_max,lon_max »…
    lat: Optional[float] = None            # …ou centre + rayon (converti en bbox)
    lon: Optional[float] = None
    rayon_km: Optional[float] = None


# ── Santé & config ───────────────────────────────────────────────
@app.get("/sante")
def sante():
    return {"ok": True, "brique": "geo", "version": VERSION}


@app.get("/config")
def config(_tenant: str = Depends(tenant_actuel)):
    """État honnête de la brique : quel fournisseur alimente la carte (mock simulé ou
    API Sirene publique) — jamais de secret en clair."""
    return fournisseurs.etat_config()


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


# ── Zones de veille ──────────────────────────────────────────────
@app.get("/zones")
def lister_zones(tenant: str = Depends(tenant_actuel)):
    return {"zones": stockage.lister_zones(tenant)}


@app.post("/zones", status_code=201)
def creer_zone(corps: ZoneEntree, tenant: str = Depends(tenant_actuel)):
    """Ajoute une zone de VEILLE : l'ingestion (nocturne ou manuelle) y cherchera les
    créations récentes. Au choix : une bbox explicite, ou centre + rayon en km."""
    try:
        if corps.bbox:
            boite = domaine.valider_bbox(corps.bbox)
        elif corps.lat is not None and corps.lon is not None and corps.rayon_km:
            boite = domaine.bbox_depuis_rayon(corps.lat, corps.lon, corps.rayon_km)
        else:
            raise ValueError("Zone attendue : « bbox » OU « lat + lon + rayon_km ».")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return stockage.creer_zone(tenant, corps.nom, boite, type_=corps.type, naf=corps.naf)


@app.delete("/zones/{zone_id}")
def supprimer_zone(zone_id: str, tenant: str = Depends(tenant_actuel)):
    if not stockage.supprimer_zone(tenant, zone_id):
        raise HTTPException(404, "Zone introuvable.")   # cloisonnement : on ne révèle rien
    return {"ok": True}


# ── Ingestion & nouveautés ───────────────────────────────────────
def _pousser_connexion(texte: str) -> None:
    """Push best-effort vers la messagerie (brique connexion → Telegram). Silencieux si
    la brique est absente/injoignable : le pull `/nouveautes` reste la source de vérité.
    Motif copié de core/proactif.py::_pousser_messagerie. Ne lève jamais."""
    base = os.getenv("CONNEXION_URL", "http://host.docker.internal:5870").rstrip("/")
    entetes = {}
    cle = os.getenv("CONNEXION_KEY", "")
    if cle:
        entetes["X-API-Key"] = cle
    corps = {"utilisateur": os.getenv("GEO_NOTIF_UTILISATEUR", "perso"), "texte": texte}
    try:
        httpx.post(f"{base}/pousser", json=corps, headers=entetes, timeout=10)
    except Exception as ex:  # noqa: BLE001
        logger.warning("Geo push messagerie : %s", ex)


@app.post("/ingestion/executer")
def executer_ingestion(tenant: str = Depends(tenant_actuel)):
    """Passe la veille sur toutes les zones ACTIVES du tenant : fournisseur (mock ou
    Sirene public) → upsert par référence externe (SIREN) → décompte honnête
    nouveaux/mis-à-jour. Appelée par l'horloge du Cœur (tâche quotidienne, Bearer
    GEO_KEY → même tenant que les outils LLM) ou à la main. Push 🗺️ si découvertes."""
    prov = fournisseurs.fournisseur()
    zones = stockage.lister_zones(tenant, seulement_actives=True)
    nouveaux, maj = 0, 0
    avertissements: list[str] = []
    for zone in zones:
        if getattr(prov, "requiert_naf", False) and not zone.get("naf"):
            avertissements.append(
                f"zone « {zone['nom']} » ignorée : le fournisseur {prov.nom} requiert "
                "un filtre NAF (sans lui la zone n'est pas énumérable — cap API).")
            continue
        try:
            trouves = prov.entreprises_recentes(zone, depuis=zone["derniere_ingestion"])
        except Exception as ex:  # noqa: BLE001 — une zone en échec ne bloque pas les autres
            logger.warning("Geo ingestion zone « %s » : %s", zone["nom"], ex)
            continue
        for objet in trouves:
            _, est_nouveau = stockage.upsert_objet(
                tenant, type_=objet["type"], latitude=objet["latitude"],
                longitude=objet["longitude"], date_reference=objet["date_reference"],
                source=objet["source"], ref_externe=objet["ref_externe"],
                metadata=objet["metadata"])
            nouveaux += est_nouveau
            maj += not est_nouveau
        stockage.maj_derniere_ingestion(zone["id"])
    if nouveaux:
        _pousser_connexion(f"🗺️ Veille geo : {nouveaux} nouvelle(s) entreprise(s) "
                           f"détectée(s) sur {len(zones)} zone(s).")
    return {"zones": len(zones), "nouveaux": nouveaux, "maj": maj,
            "fournisseur": prov.nom, "avertissements": avertissements}


@app.get("/nouveautes")
def nouveautes(jours: int = Query(7, ge=1, le=365), limite: int = Query(50, ge=1, le=500),
               tenant: str = Depends(tenant_actuel)):
    """Les objets DÉCOUVERTS récemment (date d'entrée dans le système, pas la date
    métier) — le « quoi de neuf sur mes zones » de l'assistant et du proactif."""
    depuis = (datetime.now(timezone.utc) - timedelta(days=jours)).isoformat()
    objets = stockage.nouveaux_depuis(tenant, depuis, limite)
    return {"nouveautes": objets, "depuis": depuis}

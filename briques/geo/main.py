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
import enrichissement
import fournisseurs
import fournisseurs_logements
import geographie
import stockage

logger = logging.getLogger("geo")

VERSION = "0.5.0"

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
    naf: Optional[str] = None              # filtre d'activité (requis en réel SANS communes)
    communes: Optional[list[str]] = None   # noms ou codes postaux : cible CES villages…
    bbox: Optional[str] = None             # …ou « lat_min,lon_min,lat_max,lon_max »…
    lat: Optional[float] = None            # …ou centre + rayon (converti en bbox)
    lon: Optional[float] = None
    rayon_km: Optional[float] = None
    parametres: Optional[dict] = None      # dictionnaire JSON des paramètres type-spécifiques


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


@app.get("/recherche")
def rechercher_objets(q: str = Query(..., min_length=2),
                      limite: int = Query(10, ge=1, le=50),
                      tenant: str = Depends(tenant_actuel)):
    """Retrouve des points PAR NOM sur tout le tenant, SANS bbox — la barre de
    recherche de la carte : taper un nom d'entreprise/asso détectée → zoomer dessus."""
    maintenant = datetime.now(timezone.utc)
    objets = stockage.chercher_nom(tenant, q, limite)
    for o in objets:
        o["fraicheur"] = domaine.pastille_fraicheur(o["type"], o["date_reference"], maintenant)
    return {"objets": objets}


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


# ── Enrichissement opt-in (S161, RGPD-prudent) ───────────────────
# Plafond du lot (S169) : la prospection B2B enrichit PLUSIEURS objets d'un coup —
# assouplissement ASSUMÉ du « une à la fois » — mais borné pour rester honnête (pas
# d'aspirateur) et tenir dans le budget temps d'un appel outil (chaque objet = ~2 lectures
# web réelles, lentes). Relever via GEO_ENRICHIR_LOT_MAX si besoin.
PLAFOND_ENRICHIR_LOT = int(os.getenv("GEO_ENRICHIR_LOT_MAX", "50"))


def _enrichir_et_enregistrer(tenant: str, objet: dict) -> tuple[dict, dict]:
    """Enrichit UN objet, journalise la tentative, applique les coordonnées trouvées à ses
    metadata. Renvoie (rapport, objet_maj). Lève httpx.HTTPError si la brique recherche est
    injoignable — le caller tranche : 502 pour l'unitaire, « continuer » pour le lot."""
    objet_id = objet["id"]
    rapport = enrichissement.enrichir(objet)   # peut lever httpx.HTTPError
    stockage.journaliser_enrichissement(
        tenant, objet_id, statut=rapport["statut"], requete=rapport.get("requete", ""),
        source_url=rapport.get("source_url", ""), resultat=rapport)
    if rapport["statut"] == "ok":
        meta = dict(objet["metadata"])
        meta["site"] = rapport["site"]
        if rapport["emails"]:
            meta["email"] = rapport["emails"][0]
        if rapport["telephones"]:
            meta["telephone"] = rapport["telephones"][0]
        if rapport.get("reseaux_sociaux"):
            meta["reseaux_sociaux"] = rapport["reseaux_sociaux"]
        meta["enrichi_le"] = datetime.now(timezone.utc).isoformat()
        meta["enrichi_source"] = rapport["source_url"]
        objet = stockage.maj_metadata(tenant, objet_id, meta) or objet
    return rapport, objet


def _prospect_crm(objet: dict) -> dict:
    """Vue « prête pour le CRM » d'un objet enrichi : ce dont la Forge a besoin pour créer
    un prospect (nom, coordonnées publiques trouvées, site, référence pour dé-doublonner),
    plus l'enrichissement profond S193 (dirigeants, effectifs, réseaux sociaux) quand
    disponible."""
    m = objet.get("metadata") or {}
    return {"objet_id": objet["id"], "nom": m.get("nom"), "entreprise": m.get("nom"),
            "email": m.get("email"), "telephone": m.get("telephone"),
            "site": m.get("site"), "naf": m.get("naf"), "commune": m.get("commune"),
            "ref_externe": objet.get("ref_externe"), "source": objet.get("source"),
            "dirigeants": m.get("dirigeants"), "effectifs": m.get("effectifs"),
            "reseaux_sociaux": m.get("reseaux_sociaux")}


@app.post("/objets/{objet_id}/enrichir")
def enrichir_objet(objet_id: str, force: bool = False,
                   tenant: str = Depends(tenant_actuel)):
    """Enrichit UNE entreprise, À LA DEMANDE : trouve son site OFFICIEL via la brique
    recherche (souveraine, annuaires écartés), lit la page — et sa page contact — et en
    extrait les coordonnées que l'entreprise AFFICHE elle-même. Chaque tentative est
    JOURNALISÉE (voir /enrichissements). Idempotent : déjà enrichi → renvoyé tel quel,
    sauf force=true. Pour enrichir toute une zone d'un coup : /prospection/enrichir-lot."""
    objet = stockage.lire_objet(tenant, objet_id)
    if not objet:
        raise HTTPException(404, "Objet introuvable.")   # cloisonnement : rien révélé
    meta = objet["metadata"]
    if not force and (meta.get("email") or meta.get("site")):
        return {"statut": "deja_enrichi", "objet": objet}
    try:
        rapport, objet = _enrichir_et_enregistrer(tenant, objet)
    except httpx.HTTPError as e:
        stockage.journaliser_enrichissement(tenant, objet_id, statut="erreur",
                                            resultat={"detail": str(e)})
        raise HTTPException(502, f"Brique recherche injoignable : {e}")
    return {"statut": rapport["statut"], "rapport": rapport, "objet": objet}


class ProspecterLotEntree(BaseModel):
    bbox: Optional[str] = None             # zone « lat_min,lon_min,lat_max,lon_max »…
    zone_id: Optional[str] = None          # …OU une zone geo déjà créée (prioritaire)
    type: str = "entreprise"
    naf: Optional[str] = None              # préfixe d'activité pour cibler la prospection
    limite: int = 8                        # petit par défaut (enrichissement web = lent)
    force: bool = False                    # ré-enrichir même les objets déjà enrichis


@app.post("/prospection/enrichir-lot")
def enrichir_lot(corps: ProspecterLotEntree, tenant: str = Depends(tenant_actuel)):
    """Enrichit EN LOT (borné) les objets d'une zone — le socle de la PROSPECTION : pour
    chaque objet, trouve le site officiel + les coordonnées publiques (même moteur que
    l'unitaire, mêmes garde-fous : uniquement ce que l'entité affiche, chaque tentative
    journalisée). Cible une zone géo déjà créée (`zone_id`, S193 — couvre aussi les zones
    définies par communes, leur bbox étant toujours résolu à la création) OU une bbox brute.
    Assouplissement ASSUMÉ du « une à la fois » pour du démarchage B2B, gardé BORNÉ (plafond
    GEO_ENRICHIR_LOT_MAX). Synchrone et lent (lectures web réelles) → garde les lots petits.
    Renvoie un décompte honnête + les prospects prêts pour le CRM."""
    type_, naf = corps.type, corps.naf
    if corps.zone_id:
        zone = stockage.lire_zone(tenant, corps.zone_id)
        if not zone:
            raise HTTPException(404, "Zone introuvable.")   # cloisonnement : rien révélé
        boite = (zone["lat_min"], zone["lon_min"], zone["lat_max"], zone["lon_max"])
        type_, naf = zone["type"], zone["naf"]
    elif corps.bbox:
        try:
            boite = domaine.valider_bbox(corps.bbox)
        except ValueError as e:
            raise HTTPException(400, str(e))
    else:
        raise HTTPException(400, "Fournir soit « zone_id », soit « bbox ».")
    plafond = max(1, min(corps.limite, PLAFOND_ENRICHIR_LOT))
    res = stockage.chercher_bbox(tenant, boite, type_=type_, naf=naf, limite=plafond)
    objets = res["objets"]
    compte = {"ok": 0, "deja_enrichi": 0, "introuvable": 0, "impossible": 0, "erreur": 0}
    prospects: list[dict] = []
    for objet in objets:
        meta = objet["metadata"]
        if not corps.force and (meta.get("email") or meta.get("site")):
            compte["deja_enrichi"] += 1
        else:
            try:
                rapport, objet = _enrichir_et_enregistrer(tenant, objet)
                compte[rapport["statut"]] = compte.get(rapport["statut"], 0) + 1
            except httpx.HTTPError as e:
                stockage.journaliser_enrichissement(tenant, objet["id"], statut="erreur",
                                                    resultat={"detail": str(e)})
                compte["erreur"] += 1
            meta = objet["metadata"]
        # Un objet devient « prospect » dès qu'on a de quoi le contacter ou un site.
        if meta.get("email") or meta.get("telephone") or meta.get("site"):
            prospects.append(_prospect_crm(objet))
    return {"zone_objets": res["nb_total"], "traites": len(objets), "plafond": plafond,
            "tronque": res["nb_total"] > plafond, "compte": compte,
            "prospects": prospects}


@app.get("/enrichissements")
def journal_enrichissements(limite: int = Query(50, ge=1, le=500),
                            tenant: str = Depends(tenant_actuel)):
    """Le journal des enrichissements (transparence RGPD) : qui a été enrichi, quand,
    depuis quelle source, avec quel résultat — y compris les échecs."""
    return {"enrichissements": stockage.lister_enrichissements(tenant, limite)}


# ── Zones de veille ──────────────────────────────────────────────
@app.get("/zones")
def lister_zones(tenant: str = Depends(tenant_actuel)):
    return {"zones": stockage.lister_zones(tenant)}


@app.post("/zones", status_code=201)
def creer_zone(corps: ZoneEntree, tenant: str = Depends(tenant_actuel)):
    """Ajoute une zone de VEILLE : l'ingestion (nocturne ou manuelle) y cherchera les
    créations récentes. Au choix : une ou plusieurs COMMUNES (noms ou codes postaux —
    ciblage exact au village, NAF facultatif), une bbox, ou centre + rayon en km."""
    communes: list[dict] = []
    try:
        if corps.communes:
            try:
                communes = geographie.resoudre_communes(corps.communes)
            except httpx.HTTPError as e:
                raise HTTPException(502, f"Annuaire des communes injoignable : {e}")
            boite = domaine.bbox_union([c["bbox"] for c in communes])
        elif corps.bbox:
            boite = domaine.valider_bbox(corps.bbox)
        elif corps.lat is not None and corps.lon is not None and corps.rayon_km:
            boite = domaine.bbox_depuis_rayon(corps.lat, corps.lon, corps.rayon_km)
        else:
            raise ValueError("Zone attendue : « communes » (noms/codes postaux) OU "
                             "« bbox » OU « lat + lon + rayon_km ».")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return stockage.creer_zone(
        tenant, corps.nom, boite, type_=corps.type, naf=corps.naf,
        communes=[{"code": c["code"], "nom": c["nom"]} for c in communes],
        parametres=corps.parametres)


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
    """Passe la veille sur toutes les zones ACTIVES du tenant : fournisseur dédié au TYPE
    de la zone (Sirene pour entreprise/association, DPE ADEME pour logement — mock ou
    réel selon la bascule env de chacun) → upsert par référence externe → décompte
    honnête nouveaux/mis-à-jour. Appelée par l'horloge du Cœur ou à la main. Push 🗺️ si
    découvertes."""
    zones = stockage.lister_zones(tenant, seulement_actives=True)
    nouveaux, maj = 0, 0
    avertissements: list[str] = []
    for zone in zones:
        if zone.get("type") == "logement":
            prov = fournisseurs_logements.fournisseur_logements()
            recuperer = prov.logements_recents
        else:
            prov = fournisseurs.fournisseur()
            recuperer = prov.entreprises_recentes
        message = prov.peut_traiter(zone)
        if message:
            avertissements.append(message)
            continue
        try:
            trouves = recuperer(zone, depuis=zone["derniere_ingestion"])
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
        _pousser_connexion(f"🗺️ Veille geo : {nouveaux} nouvelle(s) entreprise(s)/"
                           f"logement(s) détecté(s) sur {len(zones)} zone(s).")
    return {"zones": len(zones), "nouveaux": nouveaux, "maj": maj,
            "fournisseur": fournisseurs.etat_config()["fournisseur"],
            "fournisseur_logements": fournisseurs_logements.etat_config_logements()["fournisseur"],
            "avertissements": avertissements}


@app.get("/nouveautes")
def nouveautes(jours: int = Query(7, ge=1, le=365), limite: int = Query(50, ge=1, le=500),
               tenant: str = Depends(tenant_actuel)):
    """Les objets DÉCOUVERTS récemment (date d'entrée dans le système, pas la date
    métier) — le « quoi de neuf sur mes zones » de l'assistant et du proactif."""
    depuis = (datetime.now(timezone.utc) - timedelta(days=jours)).isoformat()
    objets = stockage.nouveaux_depuis(tenant, depuis, limite)
    return {"nouveautes": objets, "depuis": depuis}

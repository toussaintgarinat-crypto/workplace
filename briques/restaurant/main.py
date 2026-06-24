"""Brique « restaurant » — commande & paiement à table par QR, multi-tenant.

Produit autonome (port 6010). Trois surfaces, une seule frontière de données :

  • BACK-OFFICE restaurateur (authentifié) : compte → restaurant(s) → carte, tables/QR,
    file cuisine, tablette d'addition. Tout est cloisonné par compte : un restaurateur
    ne voit JAMAIS le restaurant d'un autre (fail-closed, prouvé par test_isolation).

  • CLIENT (public, via le CODE de table du QR) : carte, commande par convive, et
    paiement de sa PART (mock honnête en démo). Aucune connexion : le code de table
    est la capability qui n'ouvre QUE ce restaurant / cette table.

  • TEMPS RÉEL (WebSocket) : la cuisine reçoit les commandes en direct ; la tablette et
    les clients voient le « reste à payer » bouger en direct.

Paiement : MOCK assumé pour l'incrément 1 (marqué « démo » côté UI, aucune fausse
promesse). Stripe Connect réel = incrément suivant.
"""
import io
import os
import sqlite3
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

import auth
import carte_ia
import souvenir
import stockage
from temps_reel import diffuseur

app = FastAPI(title="Restaurant — commande & paiement à table", version="0.11.0")

# Origines navigateur autorisées (CSV via CORS_ORIGINS). Défaut "*" = dev/démo.
_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])

_ICI = Path(__file__).parent


@app.on_event("startup")
def _verifier_prod():
    # Refuse de démarrer en prod avec le secret de dev (sessions forgeables).
    auth.verifier_secret_pour_prod()


# ── Anti-brute-force minimal (en mémoire) sur les routes d'auth ──
import time as _time
from collections import deque

_TENTATIVES: dict[str, deque] = {}
_MAX_TENTATIVES = int(os.getenv("RESTAURANT_MAX_TENTATIVES", "10"))   # par fenêtre
_FENETRE = 300                                                       # 5 min


def _anti_abus(cle: str):
    """Limite les tentatives (login/inscription) par clé (email/IP) sur une fenêtre glissante."""
    maintenant = _time.time()
    d = _TENTATIVES.setdefault(cle, deque())
    while d and d[0] < maintenant - _FENETRE:
        d.popleft()
    if len(d) >= _MAX_TENTATIVES:
        raise HTTPException(429, "Trop de tentatives. Réessayez dans quelques minutes.")
    d.append(maintenant)


# ── Dépendance d'authentification (restaurateur) ─────────────────
def compte_actuel(authorization: Optional[str] = Header(None),
                  x_session: Optional[str] = Header(None)) -> str:
    """Résout le compte connecté depuis le jeton de session (Bearer ou X-Session).

    Vérifie la crypto/expiration PUIS que la VERSION du jeton correspond à celle du compte
    en base : un changement de mot de passe ou « déconnexion partout » incrémente la version
    et invalide tous les anciens jetons. Fail-closed : tout écart → 401."""
    jeton = (authorization or "").removeprefix("Bearer ").strip() or x_session
    s = auth.lire_session(jeton)
    if not s:
        raise HTTPException(401, "Session manquante ou invalide. Connectez-vous.")
    if stockage.version_compte(s["compte_id"]) != s["version"]:
        raise HTTPException(401, "Session révoquée. Reconnectez-vous.")
    return s["compte_id"]


# ── Authentification de SERVICE (capacités du Cœur) ──────────────
def service_ok(x_api_key: Optional[str] = Header(None)) -> bool:
    """Garde le chemin `/service/...` piloté par le Cœur (capacités découvertes au manifest).

    Le Cœur s'authentifie avec une CLÉ DE SERVICE (RESTAURANT_KEY → en-tête X-API-Key,
    motif `_entetes_brique` du Cœur), pas avec le mot de passe d'un restaurateur. Fail-closed :
    si RESTAURANT_KEY n'est pas défini, le chemin de service est ÉTEINT (503), pas ouvert.

    Limite honnête (mono-utilisateur aujourd'hui) : qui détient cette clé peut viser
    n'importe quel restaurant_id. L'isolation par restaurateur côté Cœur reste l'épopée
    multi-tenant à venir ; ici on tient le cloisonnement EN BASE (chaque opération passe
    par le compte propriétaire dérivé du restaurant_id)."""
    attendue = os.getenv("RESTAURANT_KEY")
    if not attendue:
        raise HTTPException(503, "Chemin de service non configuré (RESTAURANT_KEY absent).")
    if x_api_key != attendue:
        raise HTTPException(401, "Clé de service invalide.")
    return True


# ── Diffusion d'un changement de carte ───────────────────────────
async def _diffuser_carte_modifiee(restaurant_id: str, message: dict):
    """Prévient à la fois la cuisine (tablette/écran staff) ET les clients des tables ouvertes
    (canal CARTE du resto) qu'un plat a changé → ils rafraîchissent leur carte. Sert les
    bascules dispo/prix, l'ajout en lot, et les RUPTURES de stock automatiques."""
    await diffuseur.diffuser(diffuseur.canal_cuisine(restaurant_id), message)
    await diffuseur.diffuser(diffuseur.canal_carte(restaurant_id), message)


# ── Modèles ──────────────────────────────────────────────────────
class Inscription(BaseModel):
    email: str
    mot_de_passe: str
    nom: str = ""
    nom_restaurant: str = ""          # crée un 1er restaurant à l'inscription (optionnel)


class Connexion(BaseModel):
    email: str
    mot_de_passe: str


class ChangerMotDePasse(BaseModel):
    ancien: str
    nouveau: str


class CreerRestaurant(BaseModel):
    nom: str
    devise: str = "EUR"
    tva_taux: float = 10.0


class MajRestaurant(BaseModel):
    nom: Optional[str] = None
    devise: Optional[str] = None
    tva_taux: Optional[float] = None
    pin_requis: Optional[bool] = None     # exiger un code partagé pour rejoindre une table (S82)


class CreerTable(BaseModel):
    numero: str


class PlatEntree(BaseModel):
    nom: str
    description: str = ""
    prix_cents: int = 0
    photo: str = ""                    # URL ou data-URL (photo prise au téléphone)
    categorie: str = ""                # section de carte (Entrées, Plats, Boissons…)
    plat_du_jour: bool = False
    formats: list = []                 # tailles : [{taille:"50cl", prix_cents:700}] (vide = prix unique)
    stock: Optional[int] = None        # unités restantes ; None = stock illimité (défaut)


class MajPlat(BaseModel):
    nom: Optional[str] = None
    description: Optional[str] = None
    prix_cents: Optional[int] = None
    photo: Optional[str] = None
    categorie: Optional[str] = None
    disponible: Optional[bool] = None
    plat_du_jour: Optional[bool] = None
    formats: Optional[list] = None     # remplace les tailles ; [] = repasser en prix unique
    stock: Optional[int] = None        # réappro : entier = unités ; null = repasser en illimité


class ReordonnerPlats(BaseModel):
    ids: list[str] = []                # nouvelle suite des id de plats (S104 cliquer-déposer)


class ImporterCarte(BaseModel):
    contenu_base64: str = ""           # l'ancienne carte (photo/PDF) en base64 (data-URI toléré)
    url: str = ""                      # …ou par URL
    nom_fichier: str = ""              # aide l'OCR à deviner le format (ex. carte.pdf)


class GenererCarte(BaseModel):
    concept: str = ""                  # description du restaurant (cuisine, ambiance, gamme…)
    sections: list = []                # catégories voulues (optionnel ; sinon le modèle choisit)
    par_section: int = 6               # nb de plats par section (borné côté serveur)


class PlatsEnLot(BaseModel):
    plats: list = []                   # [{nom, description, prix_cents, categorie, plat_du_jour}]


class StatutCommande(BaseModel):
    statut: str                        # en_cuisine | prete | servie


class PaiementEspeces(BaseModel):
    convive: str
    pourboire_cents: int = 0
    mode: str = "part"                 # part | egal | libre (S83 — répartition flexible)
    parts: int = 0                     # nb de convives pour un partage égal
    montant_cents: int = 0             # montant choisi pour un paiement libre


class Cloturer(BaseModel):
    force: bool = False                # clôturer malgré un reste dû (départ assumé par le resto)


class Commander(BaseModel):
    convive: str = ""                  # convive par défaut si une ligne n'en porte pas
    # [{plat_id, quantite, format?, convive?, notes?}] — multi-convive « pour qui » par ligne (S81)
    plats: list = []


class PayerPart(BaseModel):
    convive: str
    pourboire_cents: int = 0
    mode: str = "part"                 # part | egal | libre (S83) | tournee (S85 « je régale »)
    parts: int = 0                     # nb de convives pour un partage égal
    montant_cents: int = 0             # montant choisi pour un paiement libre


class NommerTable(BaseModel):
    nom: str = ""                          # surnom rigolo de la tablée (S85), vide = retirer


class Rejoindre(BaseModel):
    pin: str = ""                          # code à saisir pour rejoindre une table protégée


class AvisEntree(BaseModel):
    convive: str = ""                      # qui laisse l'avis (défaut normalisé serveur)
    note: int = 0                          # 1–5 étoiles (validé serveur)
    commentaire: str = ""                  # texte libre optionnel


# ── Santé ────────────────────────────────────────────────────────
@app.get("/sante")
def sante():
    return {"ok": True, "brique": "restaurant", "version": "0.11.0"}


# ── Auth ─────────────────────────────────────────────────────────
@app.post("/auth/inscription")
def inscription(corps: Inscription):
    email = corps.email.strip().lower()
    _anti_abus("insc:" + email)
    if not email or not corps.mot_de_passe:
        raise HTTPException(400, "Email et mot de passe requis.")
    if len(corps.mot_de_passe) < 8:
        raise HTTPException(400, "Mot de passe trop court (8 caractères minimum).")
    try:
        compte = stockage.creer_compte(email, auth.hacher_mot_de_passe(corps.mot_de_passe), corps.nom)
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Un compte existe déjà avec cet email.")
    resto = None
    if corps.nom_restaurant.strip():
        resto = stockage.creer_restaurant(compte["id"], corps.nom_restaurant)
    return {"compte": compte, "restaurant": resto, "session": auth.creer_session(compte["id"], 1)}


@app.post("/auth/connexion")
def connexion(corps: Connexion):
    _anti_abus("conn:" + corps.email.strip().lower())
    compte = stockage.compte_par_email(corps.email)
    if not compte or not auth.verifier_mot_de_passe(corps.mot_de_passe, compte["mot_de_passe"]):
        raise HTTPException(401, "Email ou mot de passe incorrect.")
    return {"compte": {"id": compte["id"], "email": compte["email"], "nom": compte["nom"]},
            "session": auth.creer_session(compte["id"], compte["jeton_version"])}


@app.get("/auth/moi")
def moi(compte_id: str = Depends(compte_actuel)):
    c = stockage.compte_par_id(compte_id)
    if not c:
        raise HTTPException(401, "Compte introuvable.")
    return c


@app.post("/auth/mot-de-passe")
def changer_mot_de_passe(corps: ChangerMotDePasse, compte_id: str = Depends(compte_actuel)):
    """Change le mot de passe (vérifie l'ancien) → révoque toutes les autres sessions.
    Renvoie une nouvelle session valide pour l'appareil courant."""
    if len(corps.nouveau) < 8:
        raise HTTPException(400, "Nouveau mot de passe trop court (8 caractères minimum).")
    hache = stockage._hash_compte(compte_id)
    if not hache or not auth.verifier_mot_de_passe(corps.ancien, hache):
        raise HTTPException(403, "Ancien mot de passe incorrect.")
    version = stockage.changer_mot_de_passe(compte_id, auth.hacher_mot_de_passe(corps.nouveau))
    return {"ok": True, "session": auth.creer_session(compte_id, version)}


@app.post("/auth/deconnexion-partout")
def deconnexion_partout(compte_id: str = Depends(compte_actuel)):
    """Invalide toutes les sessions du compte (appareil perdu/volé). Renvoie une session neuve."""
    version = stockage.deconnecter_partout(compte_id)
    return {"ok": True, "session": auth.creer_session(compte_id, version)}


# ── Restaurants ──────────────────────────────────────────────────
@app.post("/restaurants")
def creer_restaurant(corps: CreerRestaurant, compte_id: str = Depends(compte_actuel)):
    return stockage.creer_restaurant(compte_id, corps.nom, corps.devise, corps.tva_taux)


@app.patch("/restaurants/{restaurant_id}")
def maj_restaurant(restaurant_id: str, corps: MajRestaurant, compte_id: str = Depends(compte_actuel)):
    r = stockage.maj_restaurant(compte_id, restaurant_id, corps.model_dump(exclude_unset=True))
    if not r:
        raise HTTPException(404, "Restaurant introuvable.")
    return r


@app.get("/restaurants")
def lister_restaurants(compte_id: str = Depends(compte_actuel)):
    return {"restaurants": stockage.lister_restaurants(compte_id)}


def _exige_resto(compte_id: str, restaurant_id: str) -> dict:
    r = stockage.lire_restaurant(compte_id, restaurant_id)
    if not r:
        # 404 et non 403 : on ne révèle même pas l'existence d'un resto d'autrui.
        raise HTTPException(404, "Restaurant introuvable.")
    return r


@app.get("/restaurants/{restaurant_id}")
def lire_restaurant(restaurant_id: str, compte_id: str = Depends(compte_actuel)):
    return _exige_resto(compte_id, restaurant_id)


# ── Tables (+ QR) ────────────────────────────────────────────────
@app.post("/restaurants/{restaurant_id}/tables")
def creer_table(restaurant_id: str, corps: CreerTable, compte_id: str = Depends(compte_actuel)):
    _exige_resto(compte_id, restaurant_id)
    t = stockage.creer_table(compte_id, restaurant_id, corps.numero)
    if not t:
        raise HTTPException(404, "Restaurant introuvable.")
    return t


@app.get("/restaurants/{restaurant_id}/tables")
def lister_tables(restaurant_id: str, compte_id: str = Depends(compte_actuel)):
    _exige_resto(compte_id, restaurant_id)
    return {"tables": stockage.lister_tables(compte_id, restaurant_id) or []}


@app.delete("/restaurants/{restaurant_id}/tables/{table_id}")
def supprimer_table(restaurant_id: str, table_id: str, compte_id: str = Depends(compte_actuel)):
    if not stockage.supprimer_table(compte_id, restaurant_id, table_id):
        raise HTTPException(404, "Table introuvable.")
    return {"supprime": True}


def _url_publique(request: Request) -> str:
    """Base d'URL vue par le SMARTPHONE du client (pour le contenu du QR).

    Priorité à RESTAURANT_PUBLIC_URL (ex. l'URL du tunnel/Proxmox) ; sinon on déduit de
    la requête. Sur localhost, le QR ne sera pas joignable depuis un téléphone : c'est
    attendu en dev — définir RESTAURANT_PUBLIC_URL une fois la brique exposée."""
    base = os.getenv("RESTAURANT_PUBLIC_URL", "").strip().rstrip("/")
    return base or str(request.base_url).rstrip("/")


@app.get("/restaurants/{restaurant_id}/tables/{table_id}/qr.svg")
def qr_table(restaurant_id: str, table_id: str, request: Request,
             compte_id: str = Depends(compte_actuel)):
    """QR code SVG d'une table, généré LOCALEMENT (souverain). Encode l'URL client."""
    _exige_resto(compte_id, restaurant_id)
    tables = stockage.lister_tables(compte_id, restaurant_id) or []
    table = next((t for t in tables if t["id"] == table_id), None)
    if not table:
        raise HTTPException(404, "Table introuvable.")
    try:
        import segno
    except ImportError:
        raise HTTPException(501, "Générateur QR indisponible (segno non installé).")
    url = f"{_url_publique(request)}/carte/{table['code']}"
    buf = io.BytesIO()
    segno.make(url, error="m").save(buf, kind="svg", scale=6, border=2)
    return Response(content=buf.getvalue(), media_type="image/svg+xml",
                    headers={"X-URL-Client": url})


# ── Plats (la carte) ─────────────────────────────────────────────
@app.post("/restaurants/{restaurant_id}/plats")
def creer_plat(restaurant_id: str, corps: PlatEntree, compte_id: str = Depends(compte_actuel)):
    _exige_resto(compte_id, restaurant_id)
    p = stockage.creer_plat(compte_id, restaurant_id, corps.nom, corps.description,
                            corps.prix_cents, corps.photo, corps.plat_du_jour, corps.categorie,
                            corps.formats, corps.stock)
    if not p:
        raise HTTPException(404, "Restaurant introuvable.")
    return p


@app.get("/restaurants/{restaurant_id}/plats")
def lister_plats(restaurant_id: str, compte_id: str = Depends(compte_actuel)):
    _exige_resto(compte_id, restaurant_id)
    return {"plats": stockage.lister_plats(compte_id, restaurant_id) or []}


@app.patch("/restaurants/{restaurant_id}/plats/{plat_id}")
async def maj_plat(restaurant_id: str, plat_id: str, corps: MajPlat,
                   compte_id: str = Depends(compte_actuel)):
    _exige_resto(compte_id, restaurant_id)
    p = stockage.maj_plat(compte_id, restaurant_id, plat_id, corps.model_dump(exclude_unset=True))
    if not p:
        raise HTTPException(404, "Plat introuvable.")
    # Une bascule de dispo / un prix / un stock change la carte vue par les clients : on
    # prévient la cuisine ET les clients des tables ouvertes pour qu'ils rafraîchissent leur carte.
    await _diffuser_carte_modifiee(restaurant_id, {"type": "carte_modifiee", "plat": p})
    return p


@app.post("/restaurants/{restaurant_id}/plats/reordonner")
async def reordonner_plats(restaurant_id: str, corps: ReordonnerPlats,
                           compte_id: str = Depends(compte_actuel)):
    """Réordonne les plats par cliquer-déposer (S104). `ids` = la nouvelle suite ; chaque
    plat reçoit son rang comme `ordre`. La carte client (triée par `ordre`) suit aussitôt."""
    _exige_resto(compte_id, restaurant_id)
    plats = stockage.reordonner_plats(compte_id, restaurant_id, corps.ids)
    if plats is None:
        raise HTTPException(404, "Restaurant introuvable.")
    await _diffuser_carte_modifiee(restaurant_id, {"type": "carte_reordonnee"})
    return {"plats": plats}


@app.delete("/restaurants/{restaurant_id}/plats/{plat_id}")
def supprimer_plat(restaurant_id: str, plat_id: str, compte_id: str = Depends(compte_actuel)):
    if not stockage.supprimer_plat(compte_id, restaurant_id, plat_id):
        raise HTTPException(404, "Plat introuvable.")
    return {"supprime": True}


# ── Assistant carte : importer l'ancienne carte (OCR → proposition) ──
@app.post("/restaurants/{restaurant_id}/carte/importer")
async def importer_carte(restaurant_id: str, corps: ImporterCarte,
                         compte_id: str = Depends(compte_actuel)):
    """Lit une ANCIENNE carte (photo/PDF) et PROPOSE des plats structurés — ne PERSISTE rien.

    Synergie : OCR délégué à la brique « vision », structuration au LLM Gateway. Le
    restaurateur valide/corrige le résultat, puis l'ajoute via /plats/lot. Repli honnête :
    si l'OCR ne lit rien (ou les briques sont éteintes), `plats` est vide et `note` le dit."""
    _exige_resto(compte_id, restaurant_id)
    if not corps.contenu_base64 and not corps.url:
        raise HTTPException(422, "Fournir l'ancienne carte (contenu_base64 ou url).")
    return await carte_ia.importer(contenu_base64=corps.contenu_base64, url=corps.url,
                                   nom_fichier=corps.nom_fichier)


@app.post("/restaurants/{restaurant_id}/carte/generer")
async def generer_carte(restaurant_id: str, corps: GenererCarte,
                        compte_id: str = Depends(compte_actuel)):
    """GÉNÈRE une carte à partir d'un concept et PROPOSE des plats — ne PERSISTE rien.

    Même flux que l'import (le restaurateur valide/corrige puis ajoute via /plats/lot), mais
    sans document : la matière vient du LLM Gateway. Repli honnête : `plats` vide + `note`."""
    _exige_resto(compte_id, restaurant_id)
    if not corps.concept.strip():
        raise HTTPException(422, "Décris le concept du restaurant à générer.")
    return await carte_ia.generer(corps.concept, corps.sections or None, corps.par_section)


@app.post("/restaurants/{restaurant_id}/plats/lot")
async def ajouter_plats_lot(restaurant_id: str, corps: PlatsEnLot,
                            compte_id: str = Depends(compte_actuel)):
    """Ajoute en une fois une liste de plats VALIDÉS (l'« Ajouter à ma carte » de l'import)."""
    _exige_resto(compte_id, restaurant_id)
    crees = []
    for p in (corps.plats or []):
        if not isinstance(p, dict) or not str(p.get("nom") or "").strip():
            continue
        plat = stockage.creer_plat(
            compte_id, restaurant_id, str(p.get("nom")), str(p.get("description") or ""),
            int(p.get("prix_cents") or 0), str(p.get("photo") or ""),
            bool(p.get("plat_du_jour")), str(p.get("categorie") or ""),
            p.get("formats") or [], p.get("stock"))
        if plat:
            crees.append(plat)
    if crees:
        await _diffuser_carte_modifiee(restaurant_id, {"type": "carte_modifiee", "lot": len(crees)})
    return {"ajoutes": len(crees), "plats": crees}


# ── Chemin de SERVICE : carte pilotée par le Cœur (capacités MCP) ──
# Authentifié par clé de service (RESTAURANT_KEY), scoppé par restaurant_id. Le Cœur (et
# tout client MCP via le Cœur) gère la carte à la voix / au chat sans le mot de passe du
# restaurateur. Cloisonnement tenu en base : on dérive le compte propriétaire du resto.
def _compte_de_service(restaurant_id: str) -> str:
    compte_id = stockage.compte_du_restaurant(restaurant_id)
    if not compte_id:
        raise HTTPException(404, "Restaurant introuvable.")
    return compte_id


@app.get("/service/restaurants")
def service_lister_restaurants(_: bool = Depends(service_ok)):
    """Liste des restaurants (id, nom, devise, TVA) — pour que l'assistant DÉCOUVRE seul les
    ids sans qu'on les lui fournisse (S103). Chemin de service (clé opérateur)."""
    return {"restaurants": stockage.lister_tous_restaurants()}


@app.get("/service/restaurants/{restaurant_id}")
def service_infos_resto(restaurant_id: str, _: bool = Depends(service_ok)):
    """Infos d'un resto (nom, devise, TVA) — donne le contexte à l'assistant."""
    r = stockage.restaurant_public(restaurant_id)
    if not r:
        raise HTTPException(404, "Restaurant introuvable.")
    return r


@app.get("/service/restaurants/{restaurant_id}/plats")
def service_lister_plats(restaurant_id: str, _: bool = Depends(service_ok)):
    """Carte complète (vue restaurateur) — pour que l'assistant sache ce qui existe déjà."""
    compte_id = _compte_de_service(restaurant_id)
    return {"plats": stockage.lister_plats(compte_id, restaurant_id) or []}


@app.post("/service/restaurants/{restaurant_id}/plats")
async def service_creer_plat(restaurant_id: str, corps: PlatEntree, _: bool = Depends(service_ok)):
    """Ajoute un plat (action). Diffuse aux tables pour rafraîchir la carte."""
    compte_id = _compte_de_service(restaurant_id)
    p = stockage.creer_plat(compte_id, restaurant_id, corps.nom, corps.description,
                            corps.prix_cents, corps.photo, corps.plat_du_jour, corps.categorie,
                            corps.formats, corps.stock)
    if not p:
        raise HTTPException(404, "Restaurant introuvable.")
    await _diffuser_carte_modifiee(restaurant_id, {"type": "carte_modifiee", "plat": p})
    return p


@app.patch("/service/restaurants/{restaurant_id}/plats/{plat_id}")
async def service_maj_plat(restaurant_id: str, plat_id: str, corps: MajPlat,
                           _: bool = Depends(service_ok)):
    """Modifie un plat (prix, dispo, plat du jour…) (action)."""
    compte_id = _compte_de_service(restaurant_id)
    p = stockage.maj_plat(compte_id, restaurant_id, plat_id, corps.model_dump(exclude_unset=True))
    if not p:
        raise HTTPException(404, "Plat introuvable.")
    await _diffuser_carte_modifiee(restaurant_id, {"type": "carte_modifiee", "plat": p})
    return p


@app.delete("/service/restaurants/{restaurant_id}/plats/{plat_id}")
def service_supprimer_plat(restaurant_id: str, plat_id: str, _: bool = Depends(service_ok)):
    """Supprime un plat (action)."""
    compte_id = _compte_de_service(restaurant_id)
    if not stockage.supprimer_plat(compte_id, restaurant_id, plat_id):
        raise HTTPException(404, "Plat introuvable.")
    return {"supprime": True}


# ── Cuisine (vue restaurateur) ───────────────────────────────────
@app.get("/restaurants/{restaurant_id}/cuisine")
def file_cuisine(restaurant_id: str, toutes: bool = False, compte_id: str = Depends(compte_actuel)):
    _exige_resto(compte_id, restaurant_id)
    cmds = stockage.lister_commandes_cuisine(compte_id, restaurant_id, actives_seulement=not toutes)
    return {"commandes": cmds or []}


@app.post("/restaurants/{restaurant_id}/commandes/{commande_id}/statut")
async def changer_statut(restaurant_id: str, commande_id: str, corps: StatutCommande,
                         compte_id: str = Depends(compte_actuel)):
    _exige_resto(compte_id, restaurant_id)
    res = stockage.maj_statut_commande(compte_id, restaurant_id, commande_id, corps.statut)
    if not res:
        raise HTTPException(404, "Commande introuvable ou statut invalide.")
    await diffuseur.diffuser(diffuseur.canal_cuisine(restaurant_id),
                             {"type": "statut_commande", "commande": res})
    await diffuseur.diffuser(diffuseur.canal_table(res["table_id"]),
                             {"type": "statut_commande", "commande": res})
    return res


@app.delete("/restaurants/{restaurant_id}/commandes/{commande_id}")
async def annuler_commande(restaurant_id: str, commande_id: str,
                           compte_id: str = Depends(compte_actuel)):
    """Annule une commande déjà envoyée en cuisine (erreur/annulation) — RÉSERVÉ AU STAFF.

    Retrait simple : la commande sort de la file cuisine ET de l'addition (stock non
    recrédité, pas de trace conservée — choix produit). Diffuse aux écrans cuisine et à la
    table pour qu'ils se rafraîchissent en direct."""
    _exige_resto(compte_id, restaurant_id)
    res = stockage.supprimer_commande(compte_id, restaurant_id, commande_id)
    if not res:
        raise HTTPException(404, "Commande introuvable.")
    etat = stockage.etat_table(restaurant_id, res["table_id"])
    await diffuseur.diffuser(diffuseur.canal_cuisine(restaurant_id),
                             {"type": "commande_supprimee", "commande_id": commande_id,
                              "table_id": res["table_id"], "etat": etat})
    await diffuseur.diffuser(diffuseur.canal_table(res["table_id"]),
                             {"type": "commande_supprimee", "etat": etat})
    return {"supprime": True, "etat": etat}


# ── Tablette d'addition (vue restaurateur) ───────────────────────
@app.get("/restaurants/{restaurant_id}/tables/{table_id}/addition")
def addition_resto(restaurant_id: str, table_id: str, compte_id: str = Depends(compte_actuel)):
    _exige_resto(compte_id, restaurant_id)
    if not any(t["id"] == table_id for t in (stockage.lister_tables(compte_id, restaurant_id) or [])):
        raise HTTPException(404, "Table introuvable.")
    return stockage.etat_table(restaurant_id, table_id)


@app.post("/restaurants/{restaurant_id}/tables/{table_id}/paiement-especes")
async def paiement_especes(restaurant_id: str, table_id: str, corps: PaiementEspeces,
                           compte_id: str = Depends(compte_actuel)):
    """Le restaurateur valide manuellement qu'un convive a payé au comptoir (espèces)."""
    _exige_resto(compte_id, restaurant_id)
    if not any(t["id"] == table_id for t in (stockage.lister_tables(compte_id, restaurant_id) or [])):
        raise HTTPException(404, "Table introuvable.")
    res = stockage.enregistrer_paiement(restaurant_id, table_id, corps.convive, "especes",
                                        corps.pourboire_cents, corps.mode, corps.parts,
                                        corps.montant_cents)
    if not res:
        raise HTTPException(400, "Rien à encaisser (déjà réglé, table soldée ou montant nul).")
    etat = stockage.etat_table(restaurant_id, table_id)
    await diffuseur.diffuser(diffuseur.canal_table(table_id), {"type": "paiement", "etat": etat})
    await diffuseur.diffuser(diffuseur.canal_cuisine(restaurant_id),
                             {"type": "paiement", "table_id": table_id, "etat": etat})
    return {"paiement": res, "etat": etat}


@app.post("/restaurants/{restaurant_id}/tables/{table_id}/cloturer")
async def cloturer_table(restaurant_id: str, table_id: str, corps: Cloturer,
                         compte_id: str = Depends(compte_actuel)):
    """Clôt la table : archive un ticket et la remet à zéro pour le groupe suivant.
    Refuse s'il reste à payer (sauf `force`). C'est ce qui rend une table réutilisable."""
    _exige_resto(compte_id, restaurant_id)
    ticket = stockage.cloturer_table(compte_id, restaurant_id, table_id, corps.force)
    if not ticket:
        raise HTTPException(409, "Clôture impossible : table vide, inconnue, ou reste à payer "
                                 "(utilisez force pour clôturer malgré tout).")
    etat = stockage.etat_table(restaurant_id, table_id)   # nouvelle session → vierge
    await diffuseur.diffuser(diffuseur.canal_table(table_id), {"type": "cloture", "etat": etat})
    await diffuseur.diffuser(diffuseur.canal_cuisine(restaurant_id),
                             {"type": "cloture", "table_id": table_id, "etat": etat})
    return {"ticket": ticket, "etat": etat}


@app.get("/restaurants/{restaurant_id}/tickets")
def tickets(restaurant_id: str, limite: int = 50, compte_id: str = Depends(compte_actuel)):
    """Historique des tickets archivés (clôtures) — compta du restaurateur."""
    _exige_resto(compte_id, restaurant_id)
    return {"tickets": stockage.lister_tickets(compte_id, restaurant_id, limite) or []}


@app.get("/restaurants/{restaurant_id}/avis")
def avis(restaurant_id: str, limite: int = 50, compte_id: str = Depends(compte_actuel)):
    """Synthèse des avis clients (moyenne, nombre, derniers) — vue restaurateur."""
    _exige_resto(compte_id, restaurant_id)
    return stockage.resume_avis(compte_id, restaurant_id, limite)


# ── CLIENT (public, via le code de table du QR) ──────────────────
def _table_par_code(code: str) -> dict:
    t = stockage.table_par_code(code)
    if not t:
        raise HTTPException(404, "Table inconnue (QR invalide).")
    return t


def _exige_adhesion(table: dict, jeton: Optional[str]):
    """Garde les actions client (commander / régler / voir l'addition) quand le restaurant
    EXIGE un code (pin_requis). Dans ce cas, seule une requête portant un jeton d'adhésion
    valide pour la SESSION COURANTE de CETTE table passe (fail-closed). Si le restaurant
    n'exige pas de code (table ouverte, défaut historique) : aucun jeton requis — l'existant
    n'est pas cassé."""
    resto = stockage.restaurant_public(table["restaurant_id"]) or {}
    if not resto.get("pin_requis"):
        return
    s = stockage.session_de_table(table["id"])
    j = auth.lire_jeton_table(jeton)
    if not s or not j or j["table_id"] != table["id"] or j["session_id"] != s.numero:
        raise HTTPException(403, "Rejoignez la table avec le code pour continuer.")


@app.get("/t/{code}")
def vue_client(code: str):
    """Tout ce qu'il faut au smartphone du client : resto, table, carte disponible, et l'état
    de session (faut-il un code, la table est-elle déjà démarrée) pour afficher la bonne porte."""
    t = _table_par_code(code)
    resto = stockage.restaurant_public(t["restaurant_id"]) or {}
    s = stockage.session_de_table(t["id"])
    return {"restaurant": resto, "table": {"id": t["id"], "numero": t["numero"], "code": code},
            "carte": stockage.carte_publique(t["restaurant_id"]),
            "nom_session": stockage.nom_session_courant(t["id"]),
            "session": {"pin_requis": bool(resto.get("pin_requis")),
                        "demarree": bool(s and s.demarree),
                        "session_id": s.numero if s else 1}}


@app.post("/t/{code}/demarrer")
async def demarrer_table(code: str):
    """Le 1er appareil DÉMARRE la tablée. Si le restaurant exige un code, on génère un PIN à
    partager (affiché à l'écran) ; sinon la table est ouverte et on délivre directement le
    jeton d'adhésion. 409 si la table est déjà démarrée (→ rejoindre avec le code)."""
    t = _table_par_code(code)
    resto = stockage.restaurant_public(t["restaurant_id"]) or {}
    if not resto.get("pin_requis"):
        s = stockage.session_de_table(t["id"])
        return {"pin_requis": False, "session_id": s.numero,
                "jeton": auth.creer_jeton_table(t["id"], s.numero)}
    res = stockage.demarrer_session(t["id"])
    if not res:
        raise HTTPException(404, "Table inconnue (QR invalide).")
    if not res["nouveau"]:
        raise HTTPException(409, "Table déjà démarrée — rejoignez-la avec le code.")
    # Prévient les autres appareils de la table : leur écran bascule « Démarrer » → « Rejoindre ».
    await diffuseur.diffuser(diffuseur.canal_table(t["id"]), {"type": "session", "demarree": True})
    return {"pin_requis": True, "session_id": res["session_id"], "pin": res["pin"],
            "jeton": auth.creer_jeton_table(t["id"], res["session_id"])}


@app.post("/t/{code}/rejoindre")
def rejoindre_table(code: str, corps: Rejoindre):
    """Un appareil supplémentaire REJOINT la tablée en saisissant le code. Anti-brute-force
    par table (même fenêtre que l'auth). Renvoie le jeton d'adhésion, ou 403 (code incorrect)."""
    t = _table_par_code(code)
    _anti_abus("pin:" + t["id"])
    res = stockage.rejoindre_session(t["id"], corps.pin)
    if not res:
        raise HTTPException(403, "Code incorrect.")
    return {"session_id": res["session_id"],
            "jeton": auth.creer_jeton_table(t["id"], res["session_id"])}


@app.post("/t/{code}/commander")
async def commander(code: str, corps: Commander,
                    x_table_session: Optional[str] = Header(None)):
    t = _table_par_code(code)
    _exige_adhesion(t, x_table_session)
    # Un panier peut désormais mêler plusieurs convives (« pour qui » par ligne) → une
    # commande par convive (groupage délégué au domaine pur).
    res = stockage.creer_commandes(t["restaurant_id"], t["id"], corps.plats, corps.convive)
    if not res:
        raise HTTPException(400, "Commande vide ou plats indisponibles.")
    # Cuisine en direct : une carte par convive (la file reste lisible par personne).
    for cmd in res["commandes"]:
        await diffuseur.diffuser(diffuseur.canal_cuisine(t["restaurant_id"]),
                                 {"type": "nouvelle_commande", "table_numero": t["numero"],
                                  "table_id": t["id"], "commande": cmd})
    etat = stockage.etat_table(t["restaurant_id"], t["id"])
    await diffuseur.diffuser(diffuseur.canal_table(t["id"]), {"type": "commande", "etat": etat})
    # Stock épuisé par cette commande → la carte change pour TOUTES les tables : on diffuse
    # une rupture pour que les clients (et la cuisine) rafraîchissent leur carte en direct.
    if res["ruptures"]:
        await _diffuser_carte_modifiee(t["restaurant_id"],
                                       {"type": "rupture", "plats": res["ruptures"]})
    return {"commandes": res["commandes"], "ruptures": res["ruptures"], "etat": etat}


@app.get("/t/{code}/addition")
def addition_client(code: str, x_table_session: Optional[str] = Header(None)):
    t = _table_par_code(code)
    _exige_adhesion(t, x_table_session)
    return stockage.etat_table(t["restaurant_id"], t["id"])


@app.post("/t/{code}/payer")
async def payer(code: str, corps: PayerPart, x_table_session: Optional[str] = Header(None)):
    """Le client règle en ligne, selon la RÉPARTITION choisie (sa part / partage égal / montant
    libre — S83). Incrément 1 : paiement MOCK (démo, sans flux réel). Montant borné serveur."""
    t = _table_par_code(code)
    _exige_adhesion(t, x_table_session)
    res = stockage.enregistrer_paiement(t["restaurant_id"], t["id"], corps.convive, "mock",
                                        corps.pourboire_cents, corps.mode, corps.parts,
                                        corps.montant_cents)
    if not res:
        raise HTTPException(400, "Rien à payer (déjà réglé, table soldée ou montant nul).")
    etat = stockage.etat_table(t["restaurant_id"], t["id"])
    await diffuseur.diffuser(diffuseur.canal_table(t["id"]), {"type": "paiement", "etat": etat})
    await diffuseur.diffuser(diffuseur.canal_cuisine(t["restaurant_id"]),
                             {"type": "paiement", "table_id": t["id"], "etat": etat})
    return {"paiement": res, "etat": etat, "demo": True}


@app.post("/t/{code}/nommer")
async def nommer_tablee(code: str, corps: NommerTable,
                        x_table_session: Optional[str] = Header(None)):
    """Les convives donnent un nom RIGOLO à leur tablée (« Les Gloutons ») — S85. Souvenir
    affiché côté client (pas imprimé sur le ticket fiscal). Nom vide = retirer le surnom.
    Diffuse à la table pour que tous les appareils voient le nouveau nom en direct."""
    t = _table_par_code(code)
    _exige_adhesion(t, x_table_session)
    nom = stockage.nommer_session(t["id"], corps.nom)
    if nom is None:
        raise HTTPException(404, "Table inconnue (QR invalide).")
    await diffuseur.diffuser(diffuseur.canal_table(t["id"]),
                             {"type": "nom_session", "nom_session": nom})
    return {"nom_session": nom}


@app.get("/t/{code}/resume")
async def resume_soiree(code: str, lang: str = "fr",
                        x_table_session: Optional[str] = Header(None)):
    """Petit SOUVENIR de fin de repas (surnom + plats partagés + total) — S85. Ton festif
    délégué au LLM via la Gateway, repli FACTUEL local honnête si l'assistant est hors ligne
    (`genere_par` dit toujours la vérité)."""
    t = _table_par_code(code)
    _exige_adhesion(t, x_table_session)
    resto = stockage.restaurant_public(t["restaurant_id"]) or {}
    etat = stockage.etat_table(t["restaurant_id"], t["id"])
    res = await souvenir.resumer(
        restaurant_nom=resto.get("nom") or "le restaurant", table_numero=t["numero"],
        nom_session=etat.get("nom_session") or "", convives=etat["convives"],
        total_cents=etat["total_cents"], devise=resto.get("devise") or "EUR",
        lang=(lang if lang in ("fr", "en", "es") else "fr"))
    return res


@app.post("/t/{code}/avis")
def laisser_avis(code: str, corps: AvisEntree, x_table_session: Optional[str] = Header(None)):
    """Le client laisse un avis (note 1–5 + commentaire) via le QR de sa table. Un avis par
    convive et par visite (re-soumettre corrige le sien). Note validée serveur."""
    t = _table_par_code(code)
    _exige_adhesion(t, x_table_session)
    res = stockage.enregistrer_avis(t["restaurant_id"], t["id"], corps.convive, corps.note,
                                    corps.commentaire)
    if not res:
        raise HTTPException(400, "Note invalide (attendu : 1 à 5 étoiles).")
    return {"avis": res, "merci": True}


# ── WebSockets ───────────────────────────────────────────────────
@app.websocket("/ws/cuisine/{restaurant_id}")
async def ws_cuisine(ws: WebSocket, restaurant_id: str, session: str = ""):
    """Canal cuisine/tablette (STAFF) : exige une session valide (version à jour) ET la
    propriété du resto."""
    s = auth.lire_session(session)
    if (not s or stockage.version_compte(s["compte_id"]) != s["version"]
            or not stockage.lire_restaurant(s["compte_id"], restaurant_id)):
        await ws.close(code=4401)        # 4401 = non autorisé (fail-closed)
        return
    canal = diffuseur.canal_cuisine(restaurant_id)
    await diffuseur.abonner(canal, ws)
    try:
        while True:
            await ws.receive_text()      # on ignore l'entrée : canal de diffusion seulement
    except WebSocketDisconnect:
        pass
    finally:
        await diffuseur.desabonner(canal, ws)


@app.websocket("/ws/t/{code}")
async def ws_table(ws: WebSocket, code: str):
    """Canal d'une table (CLIENT) : ouvert via le code du QR (capability), sans compte.

    Abonné à DEUX canaux : sa table (addition en direct) ET la carte du resto (rupture de
    stock / changement de carte qui touche toutes les tables ouvertes)."""
    t = stockage.table_par_code(code)
    if not t:
        await ws.close(code=4404)
        return
    canal = diffuseur.canal_table(t["id"])
    canal_carte = diffuseur.canal_carte(t["restaurant_id"])
    await diffuseur.abonner(canal, ws)
    await diffuseur.abonner_aussi(canal_carte, ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await diffuseur.desabonner(canal, ws)
        await diffuseur.desabonner(canal_carte, ws)


# ── Fronts (servis par la brique) ────────────────────────────────
def _page(nom: str) -> str:
    return (_ICI / nom).read_text(encoding="utf-8")


@app.get("/manipulation_directe.js", include_in_schema=False)
def front_socle_manipulation():
    """Socle « manipulation directe » (S101/S102) : menu contextuel + modale, servi au
    back-office. Source unique synchronisée par outils/sync_socle.sh (cf. en-tête)."""
    from fastapi.responses import FileResponse
    return FileResponse(_ICI / "manipulation_directe.js", media_type="application/javascript")


@app.get("/", response_class=HTMLResponse)
def front_back_office():
    """Back-office restaurateur (connexion + carte + tables/QR + cuisine + additions)."""
    return _page("back_office.html")


@app.get("/cuisine", response_class=HTMLResponse)
def front_cuisine():
    """Écran cuisine plein écran (file des commandes en direct)."""
    return _page("cuisine.html")


@app.get("/carte/{code}", response_class=HTMLResponse)
def front_client(code: str):
    """App client ouverte par le QR de la table (le code est lu côté JS depuis l'URL)."""
    return _page("client.html")

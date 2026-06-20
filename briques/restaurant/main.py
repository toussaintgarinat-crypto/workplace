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
import stockage
from temps_reel import diffuseur

app = FastAPI(title="Restaurant — commande & paiement à table", version="0.5.0")

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


class MajPlat(BaseModel):
    nom: Optional[str] = None
    description: Optional[str] = None
    prix_cents: Optional[int] = None
    photo: Optional[str] = None
    categorie: Optional[str] = None
    disponible: Optional[bool] = None
    plat_du_jour: Optional[bool] = None
    formats: Optional[list] = None     # remplace les tailles ; [] = repasser en prix unique


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


class Cloturer(BaseModel):
    force: bool = False                # clôturer malgré un reste dû (départ assumé par le resto)


class Commander(BaseModel):
    convive: str
    plats: list = []                   # [{plat_id, quantite}]


class PayerPart(BaseModel):
    convive: str
    pourboire_cents: int = 0


# ── Santé ────────────────────────────────────────────────────────
@app.get("/sante")
def sante():
    return {"ok": True, "brique": "restaurant", "version": "0.5.0"}


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
                            corps.formats)
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
    # Une bascule de dispo / un prix change la carte vue par les clients : on prévient
    # les tables ouvertes de ce resto pour qu'elles rafraîchissent leur carte.
    await diffuseur.diffuser(diffuseur.canal_cuisine(restaurant_id),
                             {"type": "carte_modifiee", "plat": p})
    return p


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
            p.get("formats") or [])
        if plat:
            crees.append(plat)
    if crees:
        await diffuseur.diffuser(diffuseur.canal_cuisine(restaurant_id),
                                 {"type": "carte_modifiee", "lot": len(crees)})
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
                            corps.formats)
    if not p:
        raise HTTPException(404, "Restaurant introuvable.")
    await diffuseur.diffuser(diffuseur.canal_cuisine(restaurant_id),
                             {"type": "carte_modifiee", "plat": p})
    return p


@app.patch("/service/restaurants/{restaurant_id}/plats/{plat_id}")
async def service_maj_plat(restaurant_id: str, plat_id: str, corps: MajPlat,
                           _: bool = Depends(service_ok)):
    """Modifie un plat (prix, dispo, plat du jour…) (action)."""
    compte_id = _compte_de_service(restaurant_id)
    p = stockage.maj_plat(compte_id, restaurant_id, plat_id, corps.model_dump(exclude_unset=True))
    if not p:
        raise HTTPException(404, "Plat introuvable.")
    await diffuseur.diffuser(diffuseur.canal_cuisine(restaurant_id),
                             {"type": "carte_modifiee", "plat": p})
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
                                        corps.pourboire_cents)
    if not res:
        raise HTTPException(400, "Rien à encaisser pour ce convive (déjà réglé ou inconnu).")
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


# ── CLIENT (public, via le code de table du QR) ──────────────────
def _table_par_code(code: str) -> dict:
    t = stockage.table_par_code(code)
    if not t:
        raise HTTPException(404, "Table inconnue (QR invalide).")
    return t


@app.get("/t/{code}")
def vue_client(code: str):
    """Tout ce qu'il faut au smartphone du client : resto, table, carte disponible."""
    t = _table_par_code(code)
    resto = stockage.restaurant_public(t["restaurant_id"]) or {}
    return {"restaurant": resto, "table": {"id": t["id"], "numero": t["numero"], "code": code},
            "carte": stockage.carte_publique(t["restaurant_id"])}


@app.post("/t/{code}/commander")
async def commander(code: str, corps: Commander):
    t = _table_par_code(code)
    cmd = stockage.creer_commande(t["restaurant_id"], t["id"], corps.convive, corps.plats)
    if not cmd:
        raise HTTPException(400, "Commande vide ou plats indisponibles.")
    # Cuisine en direct + addition de la table à jour.
    await diffuseur.diffuser(diffuseur.canal_cuisine(t["restaurant_id"]),
                             {"type": "nouvelle_commande", "table_numero": t["numero"],
                              "table_id": t["id"], "commande": cmd})
    etat = stockage.etat_table(t["restaurant_id"], t["id"])
    await diffuseur.diffuser(diffuseur.canal_table(t["id"]), {"type": "commande", "etat": etat})
    return {"commande": cmd, "etat": etat}


@app.get("/t/{code}/addition")
def addition_client(code: str):
    t = _table_par_code(code)
    return stockage.etat_table(t["restaurant_id"], t["id"])


@app.post("/t/{code}/payer")
async def payer(code: str, corps: PayerPart):
    """Le client règle SA part en ligne. Incrément 1 : paiement MOCK (démo, sans flux réel)."""
    t = _table_par_code(code)
    res = stockage.enregistrer_paiement(t["restaurant_id"], t["id"], corps.convive, "mock",
                                        corps.pourboire_cents)
    if not res:
        raise HTTPException(400, "Rien à payer pour ce convive (déjà réglé ou inconnu).")
    etat = stockage.etat_table(t["restaurant_id"], t["id"])
    await diffuseur.diffuser(diffuseur.canal_table(t["id"]), {"type": "paiement", "etat": etat})
    await diffuseur.diffuser(diffuseur.canal_cuisine(t["restaurant_id"]),
                             {"type": "paiement", "table_id": t["id"], "etat": etat})
    return {"paiement": res, "etat": etat, "demo": True}


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
    """Canal d'une table (CLIENT) : ouvert via le code du QR (capability), sans compte."""
    t = stockage.table_par_code(code)
    if not t:
        await ws.close(code=4404)
        return
    canal = diffuseur.canal_table(t["id"])
    await diffuseur.abonner(canal, ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await diffuseur.desabonner(canal, ws)


# ── Fronts (servis par la brique) ────────────────────────────────
def _page(nom: str) -> str:
    return (_ICI / nom).read_text(encoding="utf-8")


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

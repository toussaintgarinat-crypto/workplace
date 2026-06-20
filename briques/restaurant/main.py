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
import stockage
from temps_reel import diffuseur

app = FastAPI(title="Restaurant — commande & paiement à table", version="0.1.0")

# Origines navigateur autorisées (CSV via CORS_ORIGINS). Défaut "*" = dev/démo.
_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])

_ICI = Path(__file__).parent


# ── Dépendance d'authentification (restaurateur) ─────────────────
def compte_actuel(authorization: Optional[str] = Header(None),
                  x_session: Optional[str] = Header(None)) -> str:
    """Résout le compte connecté depuis le jeton de session (Bearer ou X-Session).

    Fail-closed : pas de jeton valide → 401, aucune donnée ne sort."""
    jeton = (authorization or "").removeprefix("Bearer ").strip() or x_session
    compte_id = auth.lire_session(jeton)
    if not compte_id:
        raise HTTPException(401, "Session manquante ou invalide. Connectez-vous.")
    return compte_id


# ── Modèles ──────────────────────────────────────────────────────
class Inscription(BaseModel):
    email: str
    mot_de_passe: str
    nom: str = ""
    nom_restaurant: str = ""          # crée un 1er restaurant à l'inscription (optionnel)


class Connexion(BaseModel):
    email: str
    mot_de_passe: str


class CreerRestaurant(BaseModel):
    nom: str
    devise: str = "EUR"


class CreerTable(BaseModel):
    numero: str


class PlatEntree(BaseModel):
    nom: str
    description: str = ""
    prix_cents: int = 0
    photo: str = ""                    # URL ou data-URL (photo prise au téléphone)
    plat_du_jour: bool = False


class MajPlat(BaseModel):
    nom: Optional[str] = None
    description: Optional[str] = None
    prix_cents: Optional[int] = None
    photo: Optional[str] = None
    disponible: Optional[bool] = None
    plat_du_jour: Optional[bool] = None


class StatutCommande(BaseModel):
    statut: str                        # en_cuisine | prete | servie


class PaiementEspeces(BaseModel):
    convive: str


class Commander(BaseModel):
    convive: str
    plats: list = []                   # [{plat_id, quantite}]


class PayerPart(BaseModel):
    convive: str


# ── Santé ────────────────────────────────────────────────────────
@app.get("/sante")
def sante():
    return {"ok": True, "brique": "restaurant", "version": "0.1.0"}


# ── Auth ─────────────────────────────────────────────────────────
@app.post("/auth/inscription")
def inscription(corps: Inscription):
    email = corps.email.strip().lower()
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
    return {"compte": compte, "restaurant": resto, "session": auth.creer_session(compte["id"])}


@app.post("/auth/connexion")
def connexion(corps: Connexion):
    compte = stockage.compte_par_email(corps.email)
    if not compte or not auth.verifier_mot_de_passe(corps.mot_de_passe, compte["mot_de_passe"]):
        raise HTTPException(401, "Email ou mot de passe incorrect.")
    return {"compte": {"id": compte["id"], "email": compte["email"], "nom": compte["nom"]},
            "session": auth.creer_session(compte["id"])}


@app.get("/auth/moi")
def moi(compte_id: str = Depends(compte_actuel)):
    c = stockage.compte_par_id(compte_id)
    if not c:
        raise HTTPException(401, "Compte introuvable.")
    return c


# ── Restaurants ──────────────────────────────────────────────────
@app.post("/restaurants")
def creer_restaurant(corps: CreerRestaurant, compte_id: str = Depends(compte_actuel)):
    return stockage.creer_restaurant(compte_id, corps.nom, corps.devise)


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
                            corps.prix_cents, corps.photo, corps.plat_du_jour)
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
    res = stockage.enregistrer_paiement(restaurant_id, table_id, corps.convive, "especes")
    if not res:
        raise HTTPException(400, "Rien à encaisser pour ce convive (déjà réglé ou inconnu).")
    etat = stockage.etat_table(restaurant_id, table_id)
    await diffuseur.diffuser(diffuseur.canal_table(table_id), {"type": "paiement", "etat": etat})
    await diffuseur.diffuser(diffuseur.canal_cuisine(restaurant_id),
                             {"type": "paiement", "table_id": table_id, "etat": etat})
    return {"paiement": res, "etat": etat}


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
    res = stockage.enregistrer_paiement(t["restaurant_id"], t["id"], corps.convive, "mock")
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
    """Canal cuisine/tablette (STAFF) : exige une session valide ET la propriété du resto."""
    compte_id = auth.lire_session(session)
    if not compte_id or not stockage.lire_restaurant(compte_id, restaurant_id):
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

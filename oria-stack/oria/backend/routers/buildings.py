from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Optional

from config import config as oria_config
from models.building import Room
from routers.auth import get_current_user
from services.buildings_service import BuildingsService, get_buildings_service
import services.matrix_service as matrix

STRIPE_ENABLED = False
stripe = None
try:
    import stripe as _stripe
    if oria_config.STRIPE_SECRET_KEY:
        _stripe.api_key = oria_config.STRIPE_SECRET_KEY
        STRIPE_ENABLED = True
        stripe = _stripe
except ImportError:
    pass

router = APIRouter()

CONFIGS_PAR_TYPE = {
    "maison":   {"emoji": "🏠", "couleur": "#E67E22", "rooms_defaut": [
        {"nom": "Salon",   "type": "mixte",  "emoji": "🛋", "etage": 0},
        {"nom": "Cuisine", "type": "texte",  "emoji": "🍳", "etage": 0},
        {"nom": "Bureau",  "type": "vocal",  "emoji": "💼", "etage": 0},
    ]},
    "site":     {"emoji": "🌐", "couleur": "#3498DB", "rooms_defaut": [
        {"nom": "Accueil",   "type": "mixte", "emoji": "👋", "etage": 0},
        {"nom": "Portfolio", "type": "texte", "emoji": "🖼", "etage": 0},
        {"nom": "Contact",   "type": "mixte", "emoji": "📬", "etage": 0},
    ]},
    "immeuble": {"emoji": "🏢", "couleur": "#9B59B6", "rooms_defaut": [
        {"nom": "Hall d'entrée", "type": "mixte", "emoji": "🚪", "etage": 0},
        {"nom": "Activité 1",   "type": "mixte", "emoji": "📋", "etage": 1},
        {"nom": "Activité 2",   "type": "mixte", "emoji": "📊", "etage": 2},
    ]},
}

class CreerBuilding(BaseModel):
    world_id:    str
    nom:         str
    type:        str = "maison"
    description: str = ""
    emoji:       str = ""
    couleur:     str = ""
    quartier_id: str = ""

class CreerRoom(BaseModel):
    building_id:          str
    nom:                  str
    type:                 str       = "mixte"
    etage:                int       = 0
    emoji:                str       = "💬"
    acces_restreint:      str       = "libre"   # libre | cadenas | cache
    abonnements_requis_ids: List[str] = []

class UpdateBuilding(BaseModel):
    nom:         str = ""
    description: str = ""
    emoji:       str = ""
    couleur:     str = ""

class UpdateRoom(BaseModel):
    nom:                    str            = ""
    type:                   str            = ""
    emoji:                  str            = ""
    acces_restreint:        str            = ""
    abonnements_requis_ids: List[str]      = None
    est_payante:            Optional[bool] = None
    prix_acces:             Optional[float]= None
    devise_acces:           str            = ""
    type_paiement:          str            = ""  # abonnement | unique

# ── Helpers ───────────────────────────────────────────────────────────────────

def _serialise_room(r: Room) -> dict:
    abonnements = [
        {"id": ra.abonnement.id, "nom": ra.abonnement.nom, "couleur": ra.abonnement.couleur}
        for ra in r.abonnements_requis
    ]
    return {
        "id":                    r.id,
        "nom":                   r.nom,
        "type":                  r.type,
        "etage":                 r.etage,
        "emoji":                 r.emoji,
        "matrix_room_id":        r.matrix_room_id,
        "acces_restreint":       r.acces_restreint,
        "abonnements_requis":    abonnements,
        "est_payante":           bool(getattr(r, "est_payante", False)),
        "prix_acces":            getattr(r, "prix_acces", None),
        "devise_acces":          getattr(r, "devise_acces", None) or "EUR",
        "type_paiement":         getattr(r, "type_paiement", None),
    }


# ── Rooms (avant /{building_id} pour éviter conflits) ────────────────────────

@router.post("/rooms")
def creer_room(
    data: CreerRoom,
    svc: BuildingsService = Depends(get_buildings_service),
    user=Depends(get_current_user),
):
    room = svc.add_room(
        building_id=data.building_id,
        nom=data.nom, type=data.type, etage=data.etage,
        emoji=data.emoji, acces_restreint=data.acces_restreint,
    )

    # Lier les abonnements requis
    svc.add_room_abonnements(room.id, data.abonnements_requis_ids or [])

    # Créer la Matrix Room correspondante
    building = svc.get_building(data.building_id)
    if building:
        creator = svc.get_user(user["id"])
        creator_mxid = creator.matrix_user_id if creator else None
        if creator_mxid:
            mxids = svc.list_membre_mxids(building.world_id)
            matrix_room_id = matrix.create_room(
                room_id=room.id,
                room_name=f"{data.emoji} {data.nom}",
                creator_mxid=creator_mxid,
                invited_mxids=mxids,
                encrypt=(data.type in ("texte", "mixte")),
            )
            if matrix_room_id:
                room.matrix_room_id = matrix_room_id

    svc.commit()
    svc.refresh(room)
    return _serialise_room(room)

@router.patch("/rooms/{room_id}")
def modifier_room(
    room_id: str,
    data: UpdateRoom,
    svc: BuildingsService = Depends(get_buildings_service),
    user=Depends(get_current_user),
):
    r = svc.get_room(room_id)
    if not r:
        raise HTTPException(status_code=404, detail="Pièce introuvable")
    if data.nom:             r.nom             = data.nom
    if data.type:            r.type            = data.type
    if data.emoji:           r.emoji           = data.emoji
    if data.acces_restreint: r.acces_restreint = data.acces_restreint
    if data.abonnements_requis_ids is not None:
        svc.replace_room_abonnements(r.id, data.abonnements_requis_ids)

    # Champs room payante
    if data.est_payante is not None: r.est_payante  = data.est_payante
    if data.prix_acces  is not None: r.prix_acces   = data.prix_acces
    if data.devise_acces:            r.devise_acces  = data.devise_acces
    if data.type_paiement:           r.type_paiement = data.type_paiement

    # Créer le produit/prix Stripe si nécessaire
    if (STRIPE_ENABLED and r.est_payante and r.prix_acces and r.prix_acces > 0
            and not r.stripe_price_id_acces):
        try:
            mode = "recurring" if r.type_paiement == "abonnement" else None
            product = stripe.Product.create(name=f"Accès — {r.nom}")
            price_kwargs = {
                "product": product.id,
                "unit_amount": int(r.prix_acces * 100),
                "currency": (r.devise_acces or "EUR").lower(),
            }
            if mode:
                price_kwargs["recurring"] = {"interval": "month"}
            price = stripe.Price.create(**price_kwargs)
            r.stripe_product_id_acces = product.id
            r.stripe_price_id_acces   = price.id
        except Exception:
            pass

    svc.commit()
    svc.refresh(r)
    return _serialise_room(r)

@router.delete("/rooms/{room_id}")
def supprimer_room(
    room_id: str,
    svc: BuildingsService = Depends(get_buildings_service),
    user=Depends(get_current_user),
):
    r = svc.get_room(room_id)
    if r:
        svc.delete_room(r)
    return {"status": "ok"}

# ── Buildings ────────────────────────────────────────────────────────────────

@router.post("/")
def creer_building(
    data: CreerBuilding,
    svc: BuildingsService = Depends(get_buildings_service),
    user=Depends(get_current_user),
):
    config = CONFIGS_PAR_TYPE.get(data.type, CONFIGS_PAR_TYPE["maison"])
    building = svc.create_building(
        world_id=data.world_id,
        quartier_id=data.quartier_id or None,
        nom=data.nom,
        type=data.type,
        description=data.description,
        emoji=data.emoji or config["emoji"],
        couleur=data.couleur or config["couleur"],
    )

    # Récupérer le créateur et les membres du world pour les invitations Matrix
    creator = svc.get_user(user["id"])
    creator_mxid = creator.matrix_user_id if creator else None
    mxids = svc.list_membre_mxids(data.world_id) if creator_mxid else []

    for i, r in enumerate(config["rooms_defaut"]):
        room = svc.add_room(
            building_id=building.id,
            nom=r["nom"], type=r["type"],
            emoji=r["emoji"], etage=r["etage"], position=i,
        )

        # Créer la Matrix Room pour chaque room par défaut
        if creator_mxid:
            matrix_room_id = matrix.create_room(
                room_id=room.id,
                room_name=f"{r['emoji']} {r['nom']}",
                creator_mxid=creator_mxid,
                invited_mxids=mxids,
                encrypt=(r["type"] in ("texte", "mixte")),
            )
            if matrix_room_id:
                room.matrix_room_id = matrix_room_id

    svc.commit()
    svc.refresh(building)
    rooms = [{"id": r.id, "nom": r.nom, "type": r.type, "etage": r.etage,
              "emoji": r.emoji, "matrix_room_id": r.matrix_room_id} for r in building.rooms]
    return {"id": building.id, "nom": building.nom, "type": building.type,
            "emoji": building.emoji, "couleur": building.couleur, "rooms": rooms}

@router.patch("/{building_id}")
def modifier_building(
    building_id: str,
    data: UpdateBuilding,
    svc: BuildingsService = Depends(get_buildings_service),
    user=Depends(get_current_user),
):
    b = svc.get_building(building_id)
    if not b:
        raise HTTPException(status_code=404, detail="Bâtiment introuvable")
    desc = data.description if data.description is not None else None
    b = svc.update_building(b, nom=data.nom, description=desc, emoji=data.emoji, couleur=data.couleur)
    return {"id": b.id, "nom": b.nom, "description": b.description, "emoji": b.emoji, "couleur": b.couleur}

@router.delete("/{building_id}")
def supprimer_building(
    building_id: str,
    svc: BuildingsService = Depends(get_buildings_service),
    user=Depends(get_current_user),
):
    b = svc.get_building(building_id)
    if b:
        svc.delete_building(b)
    return {"status": "ok"}

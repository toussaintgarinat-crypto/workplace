from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File as FastAPIFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional
import os

from config import config
from models.coin import Coin, CoinDossier, CoinFichier
from routers.auth import get_current_user
from services.coins_service import CoinsService, get_coins_service

# ── Stripe ────────────────────────────────────────────────────────────────────
STRIPE_ENABLED = False
stripe = None
try:
    import stripe as _stripe
    if config.STRIPE_SECRET_KEY:
        _stripe.api_key = config.STRIPE_SECRET_KEY
        STRIPE_ENABLED = True
        stripe = _stripe
except ImportError:
    pass

# ── Upload dir (résolu via config) ───────────────────────────────────────────
UPLOAD_DIR = config.UPLOAD_DIR

router = APIRouter()

# ── Schemas ───────────────────────────────────────────────────────────────────

class CreerCoin(BaseModel):
    titre:       str
    description: str = ""

class UpdateCoin(BaseModel):
    titre:       str = ""
    description: str = ""

class CreerDossier(BaseModel):
    nom:        str
    visibilite: str = "prive"   # prive | partage
    parent_id:  Optional[str] = None

class UpdateDossier(BaseModel):
    nom:        str = ""
    visibilite: str = ""


# ── Helpers de sérialisation ─────────────────────────────────────────────────

def _serialise_fichier(f: CoinFichier) -> dict:
    return {
        "id":          f.id,
        "nom":         f.nom,
        "taille":      f.taille,
        "type_mime":   f.type_mime,
        "uploaded_by": f.uploaded_by,
        "created_at":  f.created_at.isoformat() if f.created_at else None,
    }

def _serialise_dossier(d: CoinDossier) -> dict:
    return {
        "id":          d.id,
        "nom":         d.nom,
        "visibilite":  d.visibilite,
        "parent_id":   d.parent_id,
        "nb_fichiers": len(d.fichiers),
        "created_at":  d.created_at.isoformat() if d.created_at else None,
    }

def _serialise_coin(c: Coin, user_id: str) -> dict:
    return {
        "id":          c.id,
        "room_id":     c.room_id,
        "user_id":     c.user_id,
        "user_nom":    c.user_nom,
        "user_emoji":  c.user_emoji,
        "titre":       c.titre,
        "description": c.description,
        "est_mien":    c.user_id == user_id,
        "created_at":  c.created_at.isoformat() if c.created_at else None,
    }


# ── Accès payant ──────────────────────────────────────────────────────────────

@router.get("/rooms/{room_id}/acces-paye")
def check_acces(
    room_id: str,
    svc: CoinsService = Depends(get_coins_service),
    user=Depends(get_current_user),
):
    room = svc.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room introuvable")
    if not room.est_payante:
        return {"acces": True, "gratuit": True}
    acces = svc.get_acces(room_id, user["id"])
    return {
        "acces":         acces is not None,
        "gratuit":       False,
        "prix_acces":    room.prix_acces,
        "devise_acces":  room.devise_acces or "EUR",
        "type_paiement": room.type_paiement,
    }

@router.post("/rooms/{room_id}/checkout-acces")
def checkout_acces(
    room_id: str,
    svc: CoinsService = Depends(get_coins_service),
    user=Depends(get_current_user),
):
    room = svc.get_room(room_id)
    if not room or not room.est_payante:
        raise HTTPException(status_code=404, detail="Room payante introuvable")
    if svc.has_access(room_id, user["id"]):
        return {"acces": True}
    if not STRIPE_ENABLED:
        raise HTTPException(status_code=400, detail="Stripe non configuré sur ce serveur")
    if not room.stripe_price_id_acces:
        raise HTTPException(status_code=400, detail="Prix Stripe non configuré pour cette room")

    frontend_url = config.FRONTEND_URL
    mode = "subscription" if room.type_paiement == "abonnement" else "payment"
    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{"price": room.stripe_price_id_acces, "quantity": 1}],
        mode=mode,
        success_url=f"{frontend_url}?stripe=room_success&room={room_id}",
        cancel_url=f"{frontend_url}?stripe=cancel",
        metadata={"room_id": room_id, "user_id": user["id"],
                  "type": room.type_paiement or "unique"},
    )
    return {"checkout_url": session.url}

@router.post("/rooms/acces-paye/webhook")
async def webhook_acces(request: Request, svc: CoinsService = Depends(get_coins_service)):
    if not STRIPE_ENABLED:
        raise HTTPException(status_code=400)
    payload    = await request.body()
    sig_header = request.headers.get("stripe-signature")
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, config.STRIPE_WEBHOOK_SECRET)
    except Exception:
        raise HTTPException(status_code=400, detail="Signature webhook invalide")

    if event["type"] == "checkout.session.completed":
        sess    = event["data"]["object"]
        room_id = sess["metadata"].get("room_id")
        user_id = sess["metadata"].get("user_id")
        ptype   = sess["metadata"].get("type", "unique")
        sub_id  = sess.get("subscription")
        if room_id and user_id:
            svc.upsert_acces_completion(
                room_id=room_id,
                user_id=user_id,
                ptype=ptype,
                session_id=sess.get("id"),
                subscription_id=sub_id,
            )

    elif event["type"] in ("customer.subscription.deleted", "customer.subscription.paused"):
        sub = event["data"]["object"]
        svc.desactiver_acces_par_subscription(sub["id"])

    return {"status": "ok"}


# ── Coins ─────────────────────────────────────────────────────────────────────

@router.get("/rooms/{room_id}/coins")
def lister_coins(
    room_id: str,
    svc: CoinsService = Depends(get_coins_service),
    user=Depends(get_current_user),
):
    if not svc.has_access(room_id, user["id"]):
        raise HTTPException(status_code=403, detail="Accès payant requis")
    coins = svc.list_coins(room_id)
    return [_serialise_coin(c, user["id"]) for c in coins]

@router.post("/rooms/{room_id}/coins")
def creer_coin(
    room_id: str,
    data: CreerCoin,
    svc: CoinsService = Depends(get_coins_service),
    user=Depends(get_current_user),
):
    if not svc.has_access(room_id, user["id"]):
        raise HTTPException(status_code=403, detail="Accès payant requis")
    if svc.get_coin_for_user(room_id, user["id"]):
        raise HTTPException(status_code=400, detail="Vous avez déjà un Coin dans cette room")

    avatar_emoji = svc.get_user_avatar_emoji(user["id"])
    coin = svc.create_coin(
        room_id=room_id,
        user_id=user["id"],
        user_nom=user["nom"],
        user_emoji=avatar_emoji,
        titre=data.titre,
        description=data.description,
    )
    return _serialise_coin(coin, user["id"])

@router.get("/coins/{coin_id}")
def get_coin(
    coin_id: str,
    svc: CoinsService = Depends(get_coins_service),
    user=Depends(get_current_user),
):
    c = svc.get_coin_by_id(coin_id)
    if not c:
        raise HTTPException(status_code=404, detail="Coin introuvable")
    if not svc.has_access(c.room_id, user["id"]):
        raise HTTPException(status_code=403, detail="Accès payant requis")
    return _serialise_coin(c, user["id"])

@router.patch("/coins/{coin_id}")
def modifier_coin(
    coin_id: str,
    data: UpdateCoin,
    svc: CoinsService = Depends(get_coins_service),
    user=Depends(get_current_user),
):
    c = svc.get_owned_coin(coin_id, user["id"])
    if not c:
        raise HTTPException(status_code=403, detail="Interdit")
    coin = svc.update_coin(c, titre=data.titre, description=data.description)
    return _serialise_coin(coin, user["id"])

@router.delete("/coins/{coin_id}")
def supprimer_coin(
    coin_id: str,
    svc: CoinsService = Depends(get_coins_service),
    user=Depends(get_current_user),
):
    c = svc.get_owned_coin(coin_id, user["id"])
    if not c:
        raise HTTPException(status_code=403, detail="Interdit")
    svc.delete_coin(c)
    return {"status": "ok"}


# ── Dossiers ──────────────────────────────────────────────────────────────────

@router.get("/coins/{coin_id}/dossiers")
def lister_dossiers(
    coin_id: str,
    svc: CoinsService = Depends(get_coins_service),
    user=Depends(get_current_user),
):
    c = svc.get_coin_by_id(coin_id)
    if not c:
        raise HTTPException(status_code=404, detail="Coin introuvable")
    if not svc.has_access(c.room_id, user["id"]):
        raise HTTPException(status_code=403, detail="Accès payant requis")
    dossiers = svc.list_dossiers(coin_id)
    est_proprio = c.user_id == user["id"]
    if not est_proprio:
        dossiers = [d for d in dossiers if d.visibilite == "partage"]
    return [_serialise_dossier(d) for d in dossiers]

@router.post("/coins/{coin_id}/dossiers")
def creer_dossier(
    coin_id: str,
    data: CreerDossier,
    svc: CoinsService = Depends(get_coins_service),
    user=Depends(get_current_user),
):
    c = svc.get_owned_coin(coin_id, user["id"])
    if not c:
        raise HTTPException(status_code=403, detail="Seul le propriétaire peut créer des dossiers")
    d = svc.create_dossier(
        coin_id=coin_id,
        nom=data.nom,
        visibilite=data.visibilite,
        parent_id=data.parent_id,
    )
    return _serialise_dossier(d)

@router.patch("/coins/{coin_id}/dossiers/{dossier_id}")
def modifier_dossier(
    coin_id: str,
    dossier_id: str,
    data: UpdateDossier,
    svc: CoinsService = Depends(get_coins_service),
    user=Depends(get_current_user),
):
    c = svc.get_owned_coin(coin_id, user["id"])
    if not c:
        raise HTTPException(status_code=403, detail="Interdit")
    d = svc.get_dossier(coin_id, dossier_id)
    if not d:
        raise HTTPException(status_code=404, detail="Dossier introuvable")
    d = svc.update_dossier(d, nom=data.nom, visibilite=data.visibilite)
    return _serialise_dossier(d)

@router.delete("/coins/{coin_id}/dossiers/{dossier_id}")
def supprimer_dossier(
    coin_id: str,
    dossier_id: str,
    svc: CoinsService = Depends(get_coins_service),
    user=Depends(get_current_user),
):
    c = svc.get_owned_coin(coin_id, user["id"])
    if not c:
        raise HTTPException(status_code=403, detail="Interdit")
    d = svc.get_dossier(coin_id, dossier_id)
    if d:
        svc.delete_dossier(d)
    return {"status": "ok"}


# ── Fichiers ──────────────────────────────────────────────────────────────────

@router.get("/coins/{coin_id}/dossiers/{dossier_id}/fichiers")
def lister_fichiers(
    coin_id: str,
    dossier_id: str,
    svc: CoinsService = Depends(get_coins_service),
    user=Depends(get_current_user),
):
    c = svc.get_coin_by_id(coin_id)
    if not c:
        raise HTTPException(status_code=404)
    if not svc.has_access(c.room_id, user["id"]):
        raise HTTPException(status_code=403, detail="Accès payant requis")
    d = svc.get_dossier(coin_id, dossier_id)
    if not d:
        raise HTTPException(status_code=404, detail="Dossier introuvable")
    if d.visibilite == "prive" and c.user_id != user["id"]:
        raise HTTPException(status_code=403, detail="Dossier privé")
    return [_serialise_fichier(f) for f in d.fichiers]

@router.post("/coins/{coin_id}/dossiers/{dossier_id}/fichiers")
async def uploader_fichier(
    coin_id: str,
    dossier_id: str,
    file: UploadFile = FastAPIFile(...),
    svc: CoinsService = Depends(get_coins_service),
    user=Depends(get_current_user),
):
    c = svc.get_owned_coin(coin_id, user["id"])
    if not c:
        raise HTTPException(status_code=403, detail="Interdit")
    d = svc.get_dossier(coin_id, dossier_id)
    if not d:
        raise HTTPException(status_code=404, detail="Dossier introuvable")
    db_file = svc.save_uploaded_file(
        coin_id=coin_id, dossier_id=dossier_id,
        user_id=user["id"], file=file, upload_dir=UPLOAD_DIR,
    )
    return _serialise_fichier(db_file)

@router.get("/coins/fichiers/{fichier_id}/download")
def telecharger_fichier(
    fichier_id: str,
    svc: CoinsService = Depends(get_coins_service),
    user=Depends(get_current_user),
):
    f = svc.get_fichier(fichier_id)
    if not f:
        raise HTTPException(status_code=404, detail="Fichier introuvable")
    d = svc.get_dossier_by_id(f.dossier_id)
    c = svc.get_coin_by_id(f.coin_id)
    if d and d.visibilite == "prive" and c and c.user_id != user["id"]:
        raise HTTPException(status_code=403, detail="Dossier privé")
    path = os.path.join(UPLOAD_DIR, f.path)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Fichier manquant sur le serveur")
    return FileResponse(path, filename=f.nom, media_type=f.type_mime)

@router.delete("/coins/{coin_id}/dossiers/{dossier_id}/fichiers/{fichier_id}")
def supprimer_fichier(
    coin_id: str,
    dossier_id: str,
    fichier_id: str,
    svc: CoinsService = Depends(get_coins_service),
    user=Depends(get_current_user),
):
    c = svc.get_owned_coin(coin_id, user["id"])
    if not c:
        raise HTTPException(status_code=403, detail="Interdit")
    f = svc.get_fichier_in_dossier(fichier_id, dossier_id)
    if f:
        svc.delete_fichier(f, UPLOAD_DIR)
    return {"status": "ok"}

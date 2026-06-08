from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from config import config
from models.abonnement import Abonnement
from routers.auth import get_current_user
from services.abonnements_service import AbonnementsService, get_abonnements_service

# ── Stripe (optionnel) ────────────────────────────────────────────────────────
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

router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────

class CreerAbonnement(BaseModel):
    nom:         str
    description: str   = ""
    couleur:     str   = "#6366f1"
    prix:        float = 0.0
    devise:      str   = "EUR"

class UpdateAbonnement(BaseModel):
    nom:         str = ""
    description: str = ""
    couleur:     str = ""

class AssignerAbonnement(BaseModel):
    abonnement_id: str


# ── Helper ────────────────────────────────────────────────────────────────────

def _serialise(a: Abonnement) -> dict:
    return {
        "id":             a.id,
        "nom":            a.nom,
        "description":    a.description,
        "couleur":        a.couleur,
        "prix":           a.prix,
        "devise":         a.devise,
        "has_stripe":     bool(a.stripe_price_id),
        "stripe_price_id": a.stripe_price_id,
    }


# ── Tiers d'abonnement ────────────────────────────────────────────────────────

@router.get("/worlds/{world_id}/abonnements")
def lister_abonnements(
    world_id: str,
    svc: AbonnementsService = Depends(get_abonnements_service),
    user=Depends(get_current_user),
):
    return [_serialise(a) for a in svc.list_abonnements(world_id)]


@router.post("/worlds/{world_id}/abonnements")
def creer_abonnement(
    world_id: str,
    data: CreerAbonnement,
    svc: AbonnementsService = Depends(get_abonnements_service),
    user=Depends(get_current_user),
):
    w = svc.get_world(world_id)
    if not w or w.owner_id != user["id"]:
        raise HTTPException(status_code=403, detail="Interdit")

    a = Abonnement(
        world_id=world_id, nom=data.nom, description=data.description,
        couleur=data.couleur, prix=data.prix, devise=data.devise,
    )

    if STRIPE_ENABLED and data.prix > 0:
        try:
            product = stripe.Product.create(name=data.nom, description=data.description or None)
            price = stripe.Price.create(
                product=product.id,
                unit_amount=int(data.prix * 100),
                currency=data.devise.lower(),
                recurring={"interval": "month"},
            )
            a.stripe_product_id = product.id
            a.stripe_price_id   = price.id
        except Exception:
            pass

    a = svc.add_abonnement(a)
    return _serialise(a)


@router.patch("/worlds/{world_id}/abonnements/{abonnement_id}")
def modifier_abonnement(
    world_id: str,
    abonnement_id: str,
    data: UpdateAbonnement,
    svc: AbonnementsService = Depends(get_abonnements_service),
    user=Depends(get_current_user),
):
    w = svc.get_world(world_id)
    if not w or w.owner_id != user["id"]:
        raise HTTPException(status_code=403, detail="Interdit")
    a = svc.get_abonnement(abonnement_id, world_id=world_id)
    if not a:
        raise HTTPException(status_code=404)
    desc = data.description if data.description is not None else None
    a = svc.update_abonnement(a, nom=data.nom, description=desc, couleur=data.couleur)
    return _serialise(a)


@router.delete("/worlds/{world_id}/abonnements/{abonnement_id}")
def supprimer_abonnement(
    world_id: str,
    abonnement_id: str,
    svc: AbonnementsService = Depends(get_abonnements_service),
    user=Depends(get_current_user),
):
    w = svc.get_world(world_id)
    if not w or w.owner_id != user["id"]:
        raise HTTPException(status_code=403, detail="Interdit")
    a = svc.get_abonnement(abonnement_id, world_id=world_id)
    if a:
        svc.delete_abonnement(a)
    return {"status": "ok"}


# ── Abonnements d'un membre ───────────────────────────────────────────────────

@router.get("/worlds/{world_id}/membres/{user_id}/abonnements")
def get_abonnements_membre(
    world_id: str,
    user_id: str,
    svc: AbonnementsService = Depends(get_abonnements_service),
    user=Depends(get_current_user),
):
    membre = svc.get_membre(world_id, user_id)
    if not membre:
        raise HTTPException(status_code=404)
    abonnements = svc.list_membre_abonnements(membre.id)
    return [
        {
            "id":                   ma.id,
            "abonnement":           _serialise(ma.abonnement),
            "date_debut":           ma.date_debut.isoformat() if ma.date_debut else None,
            "date_fin":             ma.date_fin.isoformat()   if ma.date_fin   else None,
            "assigne_manuellement": ma.assigne_manuellement,
        }
        for ma in abonnements
    ]


@router.post("/worlds/{world_id}/membres/{user_id}/abonnements")
def assigner_abonnement(
    world_id: str,
    user_id: str,
    data: AssignerAbonnement,
    svc: AbonnementsService = Depends(get_abonnements_service),
    user=Depends(get_current_user),
):
    w = svc.get_world(world_id)
    if not w or w.owner_id != user["id"]:
        raise HTTPException(status_code=403, detail="Seul le propriétaire peut assigner des abonnements")
    membre = svc.get_membre(world_id, user_id)
    if not membre:
        raise HTTPException(status_code=404)
    if svc.get_active_membre_abonnement(membre.id, data.abonnement_id):
        return {"status": "deja_abonne"}
    svc.add_membre_abonnement(
        membre_id=membre.id,
        abonnement_id=data.abonnement_id,
        assigne_manuellement=True,
    )
    return {"status": "ok"}


@router.delete("/worlds/{world_id}/membres/{user_id}/abonnements/{abonnement_id}")
def retirer_abonnement(
    world_id: str,
    user_id: str,
    abonnement_id: str,
    svc: AbonnementsService = Depends(get_abonnements_service),
    user=Depends(get_current_user),
):
    w = svc.get_world(world_id)
    if not w or w.owner_id != user["id"]:
        raise HTTPException(status_code=403, detail="Interdit")
    membre = svc.get_membre(world_id, user_id)
    if not membre:
        raise HTTPException(status_code=404)
    ma = svc.get_any_membre_abonnement(membre.id, abonnement_id)
    if ma:
        svc.delete_membre_abonnement(ma)
    return {"status": "ok"}


# ── Stripe checkout ───────────────────────────────────────────────────────────

@router.post("/abonnements/{abonnement_id}/checkout")
def creer_checkout(
    abonnement_id: str,
    svc: AbonnementsService = Depends(get_abonnements_service),
    user=Depends(get_current_user),
):
    if not STRIPE_ENABLED:
        raise HTTPException(status_code=400, detail="Stripe non configuré sur ce serveur")
    a = svc.get_abonnement(abonnement_id)
    if not a or not a.stripe_price_id:
        raise HTTPException(status_code=404, detail="Abonnement Stripe introuvable")

    frontend_url = config.FRONTEND_URL
    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{"price": a.stripe_price_id, "quantity": 1}],
        mode="subscription",
        success_url=f"{frontend_url}?stripe=success&abonnement={abonnement_id}",
        cancel_url=f"{frontend_url}?stripe=cancel",
        metadata={"abonnement_id": abonnement_id, "user_id": user["id"]},
    )
    return {"checkout_url": session.url}


# ── Stripe webhook ────────────────────────────────────────────────────────────

@router.post("/stripe/webhook")
async def stripe_webhook(
    request: Request,
    svc: AbonnementsService = Depends(get_abonnements_service),
):
    if not STRIPE_ENABLED:
        raise HTTPException(status_code=400)
    payload    = await request.body()
    sig_header = request.headers.get("stripe-signature")
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, config.STRIPE_WEBHOOK_SECRET)
    except Exception:
        raise HTTPException(status_code=400, detail="Signature webhook invalide")

    if event["type"] == "checkout.session.completed":
        session       = event["data"]["object"]
        abonnement_id = session["metadata"].get("abonnement_id")
        user_id       = session["metadata"].get("user_id")
        stripe_sub_id = session.get("subscription")

        if abonnement_id and user_id:
            a = svc.get_abonnement(abonnement_id)
            if a:
                membre = svc.get_membre(a.world_id, user_id)
                if membre:
                    svc.upsert_membre_abonnement_completion(
                        membre_id=membre.id,
                        abonnement_id=abonnement_id,
                        stripe_sub_id=stripe_sub_id,
                    )

    elif event["type"] in ("customer.subscription.deleted", "customer.subscription.paused"):
        sub = event["data"]["object"]
        svc.deactivate_membre_abonnement_by_sub(sub["id"])

    return {"status": "ok"}

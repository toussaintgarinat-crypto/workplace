from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from routers.auth import get_current_user
from services.invitations_service import InvitationsService, get_invitations_service

router = APIRouter()

class CreerInvitation(BaseModel):
    world_id: str
    max_uses: int = 0

@router.post("/")
def creer_invitation(
    data: CreerInvitation,
    svc: InvitationsService = Depends(get_invitations_service),
    user=Depends(get_current_user),
):
    inv = svc.create_invitation(world_id=data.world_id, created_by=user["id"], max_uses=data.max_uses)
    return {"token": inv.token, "world_id": inv.world_id}

@router.get("/{token}")
def get_invitation(token: str, svc: InvitationsService = Depends(get_invitations_service)):
    inv = svc.get_invitation(token)
    if not inv:
        raise HTTPException(status_code=404, detail="Invitation invalide")
    if inv.max_uses > 0 and inv.uses >= inv.max_uses:
        raise HTTPException(status_code=400, detail="Invitation épuisée")
    world = svc.get_world(inv.world_id)
    return {"token": token, "world_id": inv.world_id,
            "world_nom": world.nom if world else "?",
            "world_emoji": world.emoji if world else "🌍",
            "uses": inv.uses, "max_uses": inv.max_uses}

@router.post("/{token}/rejoindre")
def rejoindre_via_invitation(
    token: str,
    svc: InvitationsService = Depends(get_invitations_service),
    user=Depends(get_current_user),
):
    inv = svc.get_invitation(token)
    if not inv:
        raise HTTPException(status_code=404, detail="Invitation invalide")
    if inv.max_uses > 0 and inv.uses >= inv.max_uses:
        raise HTTPException(status_code=400, detail="Invitation épuisée")
    if not svc.get_member(inv.world_id, user["id"]):
        svc.add_member_and_bump(
            inv, user_id=user["id"],
            nom=user["nom"], avatar_emoji=user["avatar_emoji"],
        )
    world = svc.get_world(inv.world_id)
    return {"world_id": inv.world_id, "world_nom": world.nom, "world_emoji": world.emoji}

@router.get("/world/{world_id}")
def lister_invitations(
    world_id: str,
    svc: InvitationsService = Depends(get_invitations_service),
    user=Depends(get_current_user),
):
    invs = svc.list_world_invitations(world_id)
    return [{"token": i.token, "uses": i.uses, "max_uses": i.max_uses} for i in invs]

@router.delete("/{token}")
def supprimer_invitation(
    token: str,
    svc: InvitationsService = Depends(get_invitations_service),
    user=Depends(get_current_user),
):
    inv = svc.get_invitation(token)
    if inv:
        svc.delete_invitation(inv)
    return {"status": "ok"}

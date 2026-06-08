"""
Votes en temps réel lors des séances de conseil municipal.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from routers.auth import get_current_user
from services.vote_service import VoteService, get_vote_service

router = APIRouter()


class VoteIn(BaseModel):
    conseil_id: str
    world_id: str
    question: str


@router.post("/")
def creer_vote(
    body: VoteIn,
    svc: VoteService = Depends(get_vote_service),
    user=Depends(get_current_user),
):
    if not svc.is_admin(body.world_id, user["id"]):
        raise HTTPException(403, "Réservé aux admins")
    v = svc.create_vote(
        conseil_id=body.conseil_id, world_id=body.world_id,
        question=body.question, created_by=user["id"],
    )
    return _vote_dict(v, [])


@router.get("/conseil/{conseil_id}")
def lister_votes(
    conseil_id: str,
    svc: VoteService = Depends(get_vote_service),
    user=Depends(get_current_user),
):
    votes = svc.list_by_conseil(conseil_id)
    return [_vote_dict(v, v.bulletins) for v in votes]


@router.post("/{vote_id}/voter")
def voter(
    vote_id: str,
    choix: str,
    svc: VoteService = Depends(get_vote_service),
    user=Depends(get_current_user),
):
    v = svc.get_vote(vote_id)
    if not v:
        raise HTTPException(404)
    if v.statut != "ouvert":
        raise HTTPException(400, "Vote fermé")
    v = svc.cast_vote(v, user_id=user["id"], user_nom=user["nom"], choix=choix)
    return _vote_dict(v, v.bulletins)


@router.patch("/{vote_id}/fermer")
def fermer_vote(
    vote_id: str,
    svc: VoteService = Depends(get_vote_service),
    user=Depends(get_current_user),
):
    v = svc.get_vote(vote_id)
    if not v:
        raise HTTPException(404)
    if not svc.is_admin(v.world_id, user["id"]):
        raise HTTPException(403)
    v = svc.close_vote(v)
    return _vote_dict(v, v.bulletins)


@router.delete("/{vote_id}")
def supprimer_vote(
    vote_id: str,
    svc: VoteService = Depends(get_vote_service),
    user=Depends(get_current_user),
):
    v = svc.get_vote(vote_id)
    if not v:
        raise HTTPException(404)
    if not svc.is_admin(v.world_id, user["id"]):
        raise HTTPException(403)
    svc.delete_vote(v)
    return {"ok": True}


def _vote_dict(v, bulletins):
    resultats = {"pour": 0, "contre": 0, "abstention": 0}
    for b in bulletins:
        if b.choix in resultats:
            resultats[b.choix] += 1
    total = sum(resultats.values())
    return {
        "id": v.id, "conseil_id": v.conseil_id, "world_id": v.world_id,
        "question": v.question, "statut": v.statut,
        "created_at": v.created_at.isoformat() if v.created_at else None,
        "ferme_at": v.ferme_at.isoformat() if v.ferme_at else None,
        "resultats": resultats, "total_votants": total,
        "bulletins": [{"user_nom": b.user_nom, "choix": b.choix} for b in bulletins],
    }

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List

from models.building import Room
from routers.auth import get_current_user
from services.rooms_service import RoomsService, get_rooms_service
import services.matrix_service as matrix

router = APIRouter()

class CreerRoom(BaseModel):
    nom:                    str
    type:                   str       = "mixte"
    etage:                  int       = 0
    emoji:                  str       = "💬"
    acces_restreint:        str       = "libre"   # libre | cadenas | cache
    abonnements_requis_ids: List[str] = []

class UpdateRoom(BaseModel):
    nom:                    str       = ""
    type:                   str       = ""
    emoji:                  str       = ""
    acces_restreint:        str       = ""
    abonnements_requis_ids: List[str] = None


def _serialise_room(r: Room) -> dict:
    abonnements = [
        {"id": ra.abonnement.id, "nom": ra.abonnement.nom, "couleur": ra.abonnement.couleur}
        for ra in r.abonnements_requis
    ]
    return {
        "id":                 r.id,
        "nom":                r.nom,
        "type":               r.type,
        "etage":              r.etage,
        "emoji":              r.emoji,
        "building_id":        r.building_id,
        "matrix_room_id":     r.matrix_room_id,
        "acces_restreint":    r.acces_restreint,
        "abonnements_requis": abonnements,
        "status":             r.status or "active",
        "closed_at":          r.closed_at.isoformat() if r.closed_at else None,
        "project_id":         r.project_id,
    }


@router.get("/{room_id}")
def get_room(room_id: str, svc: RoomsService = Depends(get_rooms_service)):
    r = svc.get_room(room_id)
    if not r:
        raise HTTPException(status_code=404, detail="Room introuvable")
    return _serialise_room(r)


@router.get("/{building_id}/rooms")
def lister_rooms(building_id: str, svc: RoomsService = Depends(get_rooms_service)):
    building = svc.get_building(building_id)
    if not building:
        raise HTTPException(status_code=404, detail="Building introuvable")
    return [_serialise_room(r) for r in building.rooms]


@router.post("/{building_id}/rooms")
def creer_room(
    building_id: str,
    data: CreerRoom,
    svc: RoomsService = Depends(get_rooms_service),
    user=Depends(get_current_user),
):
    building = svc.get_building(building_id)
    if not building:
        raise HTTPException(status_code=404, detail="Building introuvable")

    room = svc.create_room(
        building_id=building_id,
        nom=data.nom, type_=data.type, etage=data.etage,
        emoji=data.emoji, acces_restreint=data.acces_restreint,
        abonnements_requis_ids=data.abonnements_requis_ids,
    )

    # Créer la Matrix Room correspondante
    creator = None
    try:
        creator = svc.get_user(user["id"])
    except Exception:
        pass
    creator_mxid = creator.matrix_user_id if creator else None
    if creator_mxid:
        matrix_room_id = matrix.create_room(
            room_id=room.id,
            room_name=f"{data.emoji} {data.nom}",
            creator_mxid=creator_mxid,
            invited_mxids=[],
            encrypt=(data.type in ("texte", "mixte")),
        )
        if matrix_room_id:
            svc.set_matrix_room_id(room, matrix_room_id)

    svc.commit()
    svc.refresh(room)
    return _serialise_room(room)


@router.patch("/{room_id}")
def modifier_room(
    room_id: str,
    data: UpdateRoom,
    svc: RoomsService = Depends(get_rooms_service),
    user=Depends(get_current_user),
):
    r = svc.get_room(room_id)
    if not r:
        raise HTTPException(status_code=404, detail="Room introuvable")
    r = svc.update_room(
        r,
        nom=data.nom, type_=data.type, emoji=data.emoji,
        acces_restreint=data.acces_restreint,
        abonnements_requis_ids=data.abonnements_requis_ids,
    )
    return _serialise_room(r)


@router.delete("/{room_id}")
def supprimer_room(
    room_id: str,
    svc: RoomsService = Depends(get_rooms_service),
    user=Depends(get_current_user),
):
    r = svc.get_room(room_id)
    if not r:
        raise HTTPException(status_code=404, detail="Room introuvable")
    svc.delete_room(r)
    return {"status": "ok"}

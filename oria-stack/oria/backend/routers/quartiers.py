from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from routers.auth import get_current_user
from services.quartiers_service import QuartiersService, get_quartiers_service

router = APIRouter()

class CreerQuartier(BaseModel):
    world_id:    str
    nom:         str
    emoji:       str = "🏘"
    couleur:     str = "#5865F2"
    description: str = ""

class UpdateQuartier(BaseModel):
    nom:         str = ""
    emoji:       str = ""
    couleur:     str = ""
    description: str = ""

@router.post("/")
def creer_quartier(
    data: CreerQuartier,
    svc: QuartiersService = Depends(get_quartiers_service),
    user=Depends(get_current_user),
):
    quartier = svc.create(
        world_id=data.world_id, nom=data.nom,
        emoji=data.emoji, couleur=data.couleur, description=data.description,
    )
    return {"id": quartier.id, "nom": quartier.nom, "emoji": quartier.emoji,
            "couleur": quartier.couleur, "description": quartier.description, "buildings": []}

@router.patch("/{quartier_id}")
def modifier_quartier(
    quartier_id: str,
    data: UpdateQuartier,
    svc: QuartiersService = Depends(get_quartiers_service),
    user=Depends(get_current_user),
):
    q = svc.get(quartier_id)
    if not q:
        raise HTTPException(status_code=404, detail="Quartier introuvable")
    desc = data.description if data.description is not None else None
    q = svc.update(q, nom=data.nom, emoji=data.emoji, couleur=data.couleur, description=desc)
    return {"id": q.id, "nom": q.nom, "emoji": q.emoji, "couleur": q.couleur, "description": q.description}

@router.delete("/{quartier_id}")
def supprimer_quartier(
    quartier_id: str,
    svc: QuartiersService = Depends(get_quartiers_service),
    user=Depends(get_current_user),
):
    q = svc.get(quartier_id)
    if q:
        svc.delete(q)
    return {"status": "ok"}

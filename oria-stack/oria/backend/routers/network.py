from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from models.network import WorldLink
from routers.auth import get_current_user
from services.network_service import NetworkService, get_network_service

router = APIRouter()

TYPES_VALIDES = {"filiale", "partenaire", "client", "fournisseur", "association"}

class CreerLien(BaseModel):
    from_world_id: str
    to_world_id:   str
    type:          str = "partenaire"
    pourcentage:   Optional[float] = None
    visible:       str = "reseau"   # reseau | prive

@router.post("/")
def creer_lien(
    data: CreerLien,
    svc: NetworkService = Depends(get_network_service),
    user=Depends(get_current_user),
):
    if data.type not in TYPES_VALIDES:
        raise HTTPException(status_code=400, detail=f"Type invalide. Valeurs: {TYPES_VALIDES}")
    if data.from_world_id == data.to_world_id:
        raise HTTPException(status_code=400, detail="Un monde ne peut pas se lier à lui-même")
    # Vérifier que l'utilisateur est membre du monde source
    if not svc.get_membre(data.from_world_id, user["id"]):
        raise HTTPException(status_code=403, detail="Tu n'es pas membre de ce monde")
    lien = svc.create_link(
        from_world_id=data.from_world_id, to_world_id=data.to_world_id,
        type_=data.type, pourcentage=data.pourcentage,
        created_by=user["id"], visible=data.visible,
    )
    return _serialise(lien)

@router.get("/{world_id}")
def get_reseau(
    world_id: str,
    svc: NetworkService = Depends(get_network_service),
    user=Depends(get_current_user),
):
    """Retourne tous les liens d'un monde + les mondes accessibles par le user."""
    liens_out = svc.list_links_from(world_id)
    liens_in  = svc.list_links_to(world_id)

    # Mondes où l'user est membre (pour savoir ce qui est accessible)
    mes_worlds = set(svc.list_user_world_ids(user["id"]))

    noeuds = {}
    aretes = []

    def ajouter_noeud(world_id):
        if world_id in noeuds:
            return
        w = svc.get_world(world_id)
        if w:
            noeuds[w.id] = {
                "id": w.id, "nom": w.nom, "emoji": w.emoji,
                "couleur": w.couleur, "accessible": w.id in mes_worlds,
            }

    ajouter_noeud(world_id)
    for l in liens_out + liens_in:
        ajouter_noeud(l.from_world_id)
        ajouter_noeud(l.to_world_id)
        aretes.append(_serialise(l))

    return {"noeuds": list(noeuds.values()), "aretes": aretes}

@router.get("/global/moi")
def get_mon_reseau(
    svc: NetworkService = Depends(get_network_service),
    user=Depends(get_current_user),
):
    """Retourne le graphe complet de tous les mondes de l'utilisateur et leurs liens."""
    mes_worlds = svc.list_user_world_ids(user["id"])
    noeuds = {}
    aretes_vus = set()
    aretes = []

    for wid in mes_worlds:
        w = svc.get_world(wid)
        if w:
            noeuds[w.id] = {"id": w.id, "nom": w.nom, "emoji": w.emoji,
                            "couleur": w.couleur, "accessible": True}
        liens = svc.list_links_involving(wid)
        for l in liens:
            if l.id not in aretes_vus:
                aretes_vus.add(l.id)
                aretes.append(_serialise(l))
            for other_id in [l.from_world_id, l.to_world_id]:
                if other_id not in noeuds:
                    ow = svc.get_world(other_id)
                    if ow:
                        noeuds[ow.id] = {"id": ow.id, "nom": ow.nom, "emoji": ow.emoji,
                                         "couleur": ow.couleur, "accessible": ow.id in mes_worlds}

    return {"noeuds": list(noeuds.values()), "aretes": aretes}

@router.delete("/{lien_id}")
def supprimer_lien(
    lien_id: str,
    svc: NetworkService = Depends(get_network_service),
    user=Depends(get_current_user),
):
    l = svc.get_link(lien_id)
    if not l:
        raise HTTPException(status_code=404, detail="Lien introuvable")
    if l.created_by != user["id"]:
        raise HTTPException(status_code=403, detail="Seul le créateur peut supprimer ce lien")
    svc.delete_link(l)
    return {"status": "ok"}

def _serialise(l: WorldLink):
    return {"id": l.id, "from_world_id": l.from_world_id, "to_world_id": l.to_world_id,
            "type": l.type, "pourcentage": l.pourcentage, "visible": l.visible,
            "created_by": l.created_by}

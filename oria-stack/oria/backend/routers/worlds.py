from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel
from typing import Optional

from routers.auth import get_current_user, _KC
from agent_personnel_shared.keycloak_auth import verify_token_sync
from services.worlds_service import WorldsService, get_worlds_service
import services.matrix_service as matrix

router = APIRouter()

class CreerWorld(BaseModel):
    nom:         str
    description: str = ""
    emoji:       str = "🌍"
    couleur:     str = "#5865F2"

class UpdateWorld(BaseModel):
    nom:         str = ""
    description: str = ""
    emoji:       str = ""
    couleur:     str = ""

def _serialise_membres(membres, svc: WorldsService) -> list:
    """Retourne les membres avec leur matrix_user_id (joint depuis la table users)."""
    user_ids = [m.user_id for m in membres]
    users = svc.get_users_map(user_ids)
    return [
        {
            "user_id": m.user_id,
            "nom": m.nom,
            "avatar_emoji": m.avatar_emoji,
            "role": m.role,
            "matrix_user_id": users.get(m.user_id, {}) and users[m.user_id].matrix_user_id,
        }
        for m in membres
    ]


def get_current_user_optional(authorization: str = Header(None)):
    """Dépendance optionnelle — retourne None si pas de token Keycloak valide."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    try:
        payload = verify_token_sync(authorization[7:], _KC)
        user_id = payload.get("sub")
        nom = payload.get("nom") or payload.get("preferred_username") or payload.get("name")
        return {"id": user_id, "nom": nom} if user_id else None
    except Exception:
        return None


def serialise_room(r, user_abonnement_ids: Optional[set] = None, is_owner: bool = False) -> Optional[dict]:
    """Sérialise une room. Retourne None si la room est cachée pour cet utilisateur."""
    requis = [
        {"id": ra.abonnement.id, "nom": ra.abonnement.nom, "couleur": ra.abonnement.couleur}
        for ra in r.abonnements_requis
    ]
    if is_owner or not requis:
        a_acces = True
    else:
        requis_ids = {ra.abonnement_id for ra in r.abonnements_requis}
        a_acces = bool(requis_ids & (user_abonnement_ids or set()))

    # Rooms cachées : invisibles pour les non-abonnés
    if r.acces_restreint == "cache" and not a_acces:
        return None

    return {
        "id":                 r.id,
        "nom":                r.nom,
        "type":               r.type,
        "etage":              r.etage,
        "emoji":              r.emoji,
        "matrix_room_id":     r.matrix_room_id,
        "acces_restreint":    r.acces_restreint,
        "abonnements_requis": requis,
        "a_acces":            a_acces,
        "status":             r.status or "active",
        "closed_at":          r.closed_at.isoformat() if r.closed_at else None,
        "project_id":         r.project_id,
    }


def serialise_building(b, user_abonnement_ids: Optional[set] = None, is_owner: bool = False):
    rooms = []
    for r in b.rooms:
        serialised = serialise_room(r, user_abonnement_ids, is_owner)
        if serialised is not None:
            rooms.append(serialised)
    return {"id": b.id, "nom": b.nom, "type": b.type, "emoji": b.emoji,
            "couleur": b.couleur, "description": b.description,
            "quartier_id": b.quartier_id, "rooms": rooms}

@router.get("/")
def lister_worlds(
    svc: WorldsService = Depends(get_worlds_service),
    user=Depends(get_current_user),
):
    worlds = svc.list_worlds_for_user(user["id"])
    return [{"id": w.id, "nom": w.nom, "description": w.description,
             "emoji": w.emoji, "couleur": w.couleur, "owner_id": w.owner_id,
             "is_garden": bool(w.is_garden),
             "nb_membres": len(w.members), "nb_buildings": len(w.buildings)} for w in worlds]

@router.post("/")
def creer_world(
    data: CreerWorld,
    svc: WorldsService = Depends(get_worlds_service),
    user=Depends(get_current_user),
):
    world = svc.create_world(
        nom=data.nom, description=data.description,
        emoji=data.emoji, couleur=data.couleur,
        owner_id=user["id"], owner_nom=user["nom"],
        owner_avatar_emoji=user["avatar_emoji"],
    )
    return {"id": world.id, "nom": world.nom, "emoji": world.emoji, "couleur": world.couleur}

@router.get("/{world_id}")
def get_world(
    world_id: str,
    svc: WorldsService = Depends(get_worlds_service),
    user=Depends(get_current_user_optional),
):
    world = svc.get_world(world_id)
    if not world:
        raise HTTPException(status_code=404, detail="Monde introuvable")

    is_owner = user and world.owner_id == user["id"]
    user_abonnement_ids = (
        svc.abonnement_ids_membre(world_id, user["id"])
        if user and not is_owner else set()
    )

    buildings_libres = [
        serialise_building(b, user_abonnement_ids, is_owner)
        for b in world.buildings if b.quartier_id is None
    ]
    quartiers = [
        {
            "id": q.id, "nom": q.nom, "emoji": q.emoji, "couleur": q.couleur,
            "description": q.description,
            "buildings": [serialise_building(b, user_abonnement_ids, is_owner) for b in q.buildings],
        }
        for q in world.quartiers
    ]
    return {"id": world.id, "nom": world.nom, "description": world.description,
            "emoji": world.emoji, "couleur": world.couleur, "owner_id": world.owner_id,
            "buildings": buildings_libres, "quartiers": quartiers,
            "membres": _serialise_membres(world.members, svc)}

@router.patch("/{world_id}")
def modifier_world(
    world_id: str,
    data: UpdateWorld,
    svc: WorldsService = Depends(get_worlds_service),
    user=Depends(get_current_user),
):
    w = svc.get_world(world_id)
    if not w or w.owner_id != user["id"]:
        raise HTTPException(status_code=403, detail="Interdit")
    if w.is_garden:
        raise HTTPException(status_code=403, detail="Le jardin secret ne peut pas être modifié")
    w = svc.update_world(
        w, nom=data.nom,
        description=(data.description if data.description is not None else None),
        emoji=data.emoji, couleur=data.couleur,
    )
    return {"id": w.id, "nom": w.nom, "emoji": w.emoji, "couleur": w.couleur}

@router.delete("/{world_id}")
def supprimer_world(
    world_id: str,
    svc: WorldsService = Depends(get_worlds_service),
    user=Depends(get_current_user),
):
    w = svc.get_world(world_id)
    if not w or w.owner_id != user["id"]:
        raise HTTPException(status_code=403, detail="Interdit")
    if w.is_garden:
        raise HTTPException(status_code=403, detail="Le jardin secret ne peut pas être supprimé")
    svc.delete_world(w)
    return {"status": "ok"}

@router.get("/{world_id}/membres")
def get_membres(
    world_id: str,
    svc: WorldsService = Depends(get_worlds_service),
    user=Depends(get_current_user),
):
    membres = svc.list_membres(world_id)
    return _serialise_membres(membres, svc)

@router.patch("/{world_id}/membres/{user_id}")
def modifier_role(
    world_id: str,
    user_id: str,
    role: str,
    svc: WorldsService = Depends(get_worlds_service),
    user=Depends(get_current_user),
):
    w = svc.get_world(world_id)
    if not w or w.owner_id != user["id"]:
        raise HTTPException(status_code=403, detail="Seul le propriétaire peut changer les rôles")
    m = svc.get_membre(world_id, user_id)
    if m:
        svc.update_membre_role(m, role)
    return {"status": "ok"}

@router.delete("/{world_id}/membres/{user_id}")
def exclure_membre(
    world_id: str,
    user_id: str,
    svc: WorldsService = Depends(get_worlds_service),
    user=Depends(get_current_user),
):
    w = svc.get_world(world_id)
    if not w or w.owner_id != user["id"]:
        raise HTTPException(status_code=403, detail="Interdit")
    m = svc.get_membre(world_id, user_id)
    if m:
        svc.delete_membre(m)
    return {"status": "ok"}

@router.post("/{world_id}/rejoindre")
def rejoindre_world(
    world_id: str,
    user_id: str,
    nom: str,
    avatar_emoji: str = "👤",
    svc: WorldsService = Depends(get_worlds_service),
):
    existe = svc.get_membre(world_id, user_id)
    if not existe:
        svc.add_membre(world_id, user_id, nom, avatar_emoji=avatar_emoji)

        # Inviter le nouveau membre dans toutes les Matrix Rooms du world
        nouveau = svc.get_user(user_id)
        if nouveau and nouveau.matrix_user_id:
            rooms = svc.get_world_matrix_rooms(world_id)
            # Utiliser le premier propriétaire comme invitant
            owner = svc.get_world_owner_member(world_id)
            owner_user = svc.get_user(owner.user_id) if owner else None
            inviter_mxid = owner_user.matrix_user_id if owner_user else None

            if inviter_mxid:
                for room in rooms:
                    matrix.invite_to_room(room.matrix_room_id, nouveau.matrix_user_id, inviter_mxid)

    return {"status": "ok"}

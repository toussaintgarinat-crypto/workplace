"""
Découverte des worlds publics + profils utilisateurs publics.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional

from models.world import World
from models.user import User
from routers.auth import get_current_user
from services.discovery_service import DiscoveryService, get_discovery_service

router = APIRouter()


def _world_preview(w: World, svc: DiscoveryService) -> dict:
    member_count = svc.count_members(w.id)
    agent_count = svc.count_active_agents(w.id)
    owner = svc.get_user(w.owner_id)
    import json as _json
    tags = []
    try:
        tags = _json.loads(w.tags) if w.tags else []
    except Exception:
        pass
    return {
        "id": w.id, "nom": w.nom, "description": w.description,
        "emoji": w.emoji, "couleur": w.couleur,
        "owner_id": w.owner_id,
        "owner_nom": owner.nom if owner else "?",
        "owner_avatar": owner.avatar_emoji if owner else "👤",
        "member_count": member_count,
        "agent_count": agent_count,
        "view_count": w.view_count or 0,
        "tags": tags,
        "created_at": w.created_at.isoformat() if w.created_at else None,
    }


# ── Worlds publics ───────────────────────────────────────────────

@router.get("/worlds")
def list_public_worlds(
    q: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    limit: int = Query(20, le=50),
    offset: int = Query(0),
    svc: DiscoveryService = Depends(get_discovery_service),
):
    worlds = svc.list_public_worlds(q=q, tag=tag, limit=limit, offset=offset)
    return [_world_preview(w, svc) for w in worlds]


@router.get("/worlds/{world_id}")
def get_public_world(world_id: str, svc: DiscoveryService = Depends(get_discovery_service)):
    w = svc.get_public_world(world_id)
    if not w:
        raise HTTPException(404, "World introuvable ou privé")
    # Incrémenter view_count
    w.view_count = (w.view_count or 0) + 1
    svc.commit()
    return _world_preview(w, svc)


@router.patch("/worlds/{world_id}/visibility")
def toggle_world_visibility(
    world_id: str,
    is_public: bool,
    svc: DiscoveryService = Depends(get_discovery_service),
    user=Depends(get_current_user),
):
    w = svc.get_own_world(world_id, user["id"])
    if not w:
        raise HTTPException(404)
    if w.is_garden:
        raise HTTPException(403, "Le jardin secret est toujours privé")
    w.is_public = is_public
    svc.commit()
    return {"id": w.id, "is_public": w.is_public}


class UpdateWorldMeta(BaseModel):
    tags: Optional[list[str]] = None
    map_data: Optional[str] = None


@router.patch("/worlds/{world_id}/meta")
def update_world_meta(
    world_id: str,
    body: UpdateWorldMeta,
    svc: DiscoveryService = Depends(get_discovery_service),
    user=Depends(get_current_user),
):
    import json as _json
    w = svc.get_own_world(world_id, user["id"])
    if not w:
        raise HTTPException(404)
    if body.tags is not None:
        w.tags = _json.dumps(body.tags)
    if body.map_data is not None:
        w.map_data = body.map_data
    svc.commit()
    return {"ok": True}


# ── Utilisateurs publics (suggestions onboarding) ───────────────

@router.get("/users")
def list_public_users(
    limit: int = Query(5, le=20),
    exclude: Optional[str] = Query(None),
    svc: DiscoveryService = Depends(get_discovery_service),
):
    import random as _random
    users = svc.list_public_users(exclude=exclude)
    sample = _random.sample(users, min(limit, len(users)))
    return [
        {"id": u.id, "nom": u.nom, "avatar_emoji": u.avatar_emoji, "bio": u.bio or ""}
        for u in sample
    ]


# ── Profils publics ──────────────────────────────────────────────

@router.get("/profile/{user_id}")
def get_public_profile(user_id: str, svc: DiscoveryService = Depends(get_discovery_service)):
    u = svc.get_public_user(user_id)
    if not u:
        raise HTTPException(404, "Profil introuvable ou privé")

    worlds = svc.list_public_worlds_by_owner(user_id)
    return {
        "id": u.id, "nom": u.nom,
        "avatar_emoji": u.avatar_emoji,
        "bio": u.bio or "",
        "website": u.website or "",
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "worlds": [_world_preview(w, svc) for w in worlds],
    }


@router.patch("/profile/me")
def update_my_profile(
    bio: Optional[str] = None,
    website: Optional[str] = None,
    is_public: Optional[bool] = None,
    svc: DiscoveryService = Depends(get_discovery_service),
    user=Depends(get_current_user),
):
    u = svc.get_user(user["id"])
    if not u:
        raise HTTPException(404)
    if bio is not None:
        u.bio = bio
    if website is not None:
        u.website = website
    if is_public is not None:
        u.is_public = is_public
    svc.commit()
    return {
        "id": u.id, "nom": u.nom, "avatar_emoji": u.avatar_emoji,
        "bio": u.bio, "website": u.website, "is_public": u.is_public,
    }

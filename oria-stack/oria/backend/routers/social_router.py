"""
Réseau social : follow/unfollow, fil d'activité, notifications.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sse_starlette.sse import EventSourceResponse
from jose import JWTError
import asyncio
import json

from routers.auth import get_current_user, _KC
from agent_personnel_shared.keycloak_auth import verify_token_sync
from services.social_service import SocialService, get_social_service

router = APIRouter()

_NOTIF_CHANNEL = "notifs:{user_id}"


async def _publish_notif(user_id: str, count: int):
    from redis_client import redis_client
    if redis_client:
        await redis_client.publish(_NOTIF_CHANNEL.format(user_id=user_id), json.dumps({"count": count}))


# ── Follow ───────────────────────────────────────────────────────

@router.post("/follow/{user_id}")
async def follow_user(
    user_id: str,
    svc: SocialService = Depends(get_social_service),
    user=Depends(get_current_user),
):
    if user_id == user["id"]:
        raise HTTPException(400, "Tu ne peux pas te suivre toi-même")
    if svc.get_follow(user["id"], user_id):
        raise HTTPException(400, "Déjà suivi")
    if not svc.get_user(user_id):
        raise HTTPException(404, "Utilisateur introuvable")

    svc.create_follow(follower_id=user["id"], followed_id=user_id)
    svc.add_notification(
        user_id=user_id,
        type_="new_follower",
        data_dict={
            "follower_id":     user["id"],
            "follower_nom":    user["nom"],
            "follower_avatar": user["avatar_emoji"],
        },
    )
    svc.commit()
    count = svc.count_unread_notifs(user_id)
    await _publish_notif(user_id, count)
    return {"ok": True}


@router.delete("/follow/{user_id}")
def unfollow_user(
    user_id: str,
    svc: SocialService = Depends(get_social_service),
    user=Depends(get_current_user),
):
    follow = svc.get_follow(user["id"], user_id)
    if not follow:
        raise HTTPException(404, "Pas suivi")
    svc.delete_follow(follow)
    return {"ok": True}


@router.get("/check/{user_id}")
def check_follow(
    user_id: str,
    svc: SocialService = Depends(get_social_service),
    user=Depends(get_current_user),
):
    return {"following": bool(svc.get_follow(user["id"], user_id))}


@router.get("/following")
def get_following(
    svc: SocialService = Depends(get_social_service),
    user=Depends(get_current_user),
):
    users = svc.list_following(user["id"])
    return [{"id": u.id, "nom": u.nom, "avatar_emoji": u.avatar_emoji, "bio": u.bio or ""} for u in users]


@router.get("/followers")
def get_followers(
    svc: SocialService = Depends(get_social_service),
    user=Depends(get_current_user),
):
    users = svc.list_followers(user["id"])
    return [{"id": u.id, "nom": u.nom, "avatar_emoji": u.avatar_emoji, "bio": u.bio or ""} for u in users]


# ── Feed ─────────────────────────────────────────────────────────

@router.get("/feed")
def get_feed(
    svc: SocialService = Depends(get_social_service),
    user=Depends(get_current_user),
):
    """Worlds publics récents des utilisateurs suivis."""
    followed_ids = svc.list_followed_ids(user["id"])
    if not followed_ids:
        return []

    worlds = svc.list_public_worlds_by_owners(followed_ids, limit=30)
    owners = svc.get_users_map(followed_ids)
    result = []
    for w in worlds:
        owner = owners.get(w.owner_id)
        result.append({
            "type":          "world",
            "world_id":      w.id,
            "world_nom":     w.nom,
            "world_emoji":   w.emoji,
            "world_couleur": w.couleur,
            "world_desc":    w.description or "",
            "owner_id":      w.owner_id,
            "owner_nom":     owner.nom if owner else "?",
            "owner_avatar":  owner.avatar_emoji if owner else "👤",
            "created_at":    w.created_at.isoformat() if w.created_at else None,
        })
    return result


# ── Notifications ────────────────────────────────────────────────

@router.get("/notifs")
def get_notifs(
    svc: SocialService = Depends(get_social_service),
    user=Depends(get_current_user),
):
    notifs = svc.list_notifs(user["id"], limit=50)
    return [
        {
            "id":         n.id,
            "type":       n.type,
            "data":       json.loads(n.data or "{}"),
            "read":       n.read,
            "created_at": n.created_at.isoformat() if n.created_at else None,
        }
        for n in notifs
    ]


@router.get("/notifs/unread-count")
def unread_count(
    svc: SocialService = Depends(get_social_service),
    user=Depends(get_current_user),
):
    return {"count": svc.count_unread_notifs(user["id"])}


@router.get("/notifs/stream")
async def notifs_stream(
    request: Request,
    token: str = "",
    svc: SocialService = Depends(get_social_service),
):
    # Valide le JWT depuis le query param (EventSource ne supporte pas les headers)
    if not token:
        raise HTTPException(401, "Token manquant")
    try:
        payload = verify_token_sync(token, _KC)
    except JWTError as exc:
        raise HTTPException(401, f"Token invalide: {exc}")
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(401, "Token invalide (sub manquant)")

    from redis_client import redis_client

    async def generator():
        # Envoie le count actuel au démarrage
        count = svc.count_unread_notifs(user_id)
        yield json.dumps({"count": count})

        if redis_client:
            channel = _NOTIF_CHANNEL.format(user_id=user_id)
            pubsub = redis_client.pubsub()
            await pubsub.subscribe(channel)
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        msg = await asyncio.wait_for(pubsub.get_message(ignore_subscribe_messages=True), timeout=25)
                        if msg and msg.get("type") == "message":
                            yield msg["data"]
                        else:
                            yield json.dumps({"type": "ping"})
                    except asyncio.TimeoutError:
                        yield json.dumps({"type": "ping"})
            finally:
                await pubsub.unsubscribe(channel)
                await pubsub.aclose()
        else:
            # Fallback sans Redis : polling toutes les 30s
            while True:
                if await request.is_disconnected():
                    break
                await asyncio.sleep(30)
                count = svc.count_unread_notifs(user_id)
                yield json.dumps({"count": count})

    return EventSourceResponse(generator())


@router.patch("/notifs/{notif_id}/read")
def mark_read(
    notif_id: str,
    svc: SocialService = Depends(get_social_service),
    user=Depends(get_current_user),
):
    n = svc.get_notif(notif_id, user["id"])
    if not n:
        raise HTTPException(404)
    svc.mark_notif_read(n)
    return {"ok": True}


@router.patch("/notifs/read-all")
def mark_all_read(
    svc: SocialService = Depends(get_social_service),
    user=Depends(get_current_user),
):
    svc.mark_all_notifs_read(user["id"])
    return {"ok": True}


# ── Public profile ───────────────────────────────────────────────

@router.get("/profile/{user_id}")
def get_profile(
    user_id: str,
    svc: SocialService = Depends(get_social_service),
    user=Depends(get_current_user),
):
    target = svc.get_user(user_id)
    if not target:
        raise HTTPException(404, "Utilisateur introuvable")
    worlds = svc.get_user_public_worlds(user_id, limit=20)
    return {
        "id":           target.id,
        "nom":          target.nom,
        "avatar_emoji": target.avatar_emoji,
        "bio":          target.bio or "",
        "worlds": [
            {
                "id":          w.id,
                "nom":         w.nom,
                "emoji":       w.emoji,
                "couleur":     w.couleur,
                "description": w.description or "",
            }
            for w in worlds
        ],
    }

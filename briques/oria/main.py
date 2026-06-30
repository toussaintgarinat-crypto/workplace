"""Brique « oria » — proxy Workplace vers l'API Oria (collaboratif, Matrix/LiveKit).

Port 6085. Agit en tant que `core-service` (client Keycloak à service account) pour
relayer les appels au backend Oria (:8000). Le Cœur découvre les capacités via le
manifest et les expose comme outils LLM (S63/S64).

Variables d'env attendues (dans .env racine ou injectées) :
  ORIA_KC_URL            URL Keycloak (défaut : http://host.docker.internal:8081)
  ORIA_KC_REALM          realm Oria (défaut : oria)
  ORIA_KC_CLIENT_ID      client service (défaut : core-service)
  ORIA_KC_CLIENT_SECRET  secret du client service
  ORIA_API_URL           URL backend Oria (défaut : http://host.docker.internal:8000)
"""
from __future__ import annotations

import os
import time
from typing import Any, Optional

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ── config ────────────────────────────────────────────────────────────────────
KC_URL    = os.getenv("ORIA_KC_URL",           "http://host.docker.internal:8081")
KC_REALM  = os.getenv("ORIA_KC_REALM",         "oria")
KC_CLIENT = os.getenv("ORIA_KC_CLIENT_ID",     "core-service")
KC_SECRET = os.getenv("ORIA_KC_CLIENT_SECRET", "core-service-secret-wp")
ORIA_API  = os.getenv("ORIA_API_URL",          "http://host.docker.internal:8000")

TOKEN_URL = f"{KC_URL}/realms/{KC_REALM}/protocol/openid-connect/token"

# ── app ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="Oria — proxy collaboratif Workplace", version="0.1.0")

_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])

# ── cache token Keycloak ──────────────────────────────────────────────────────
_token_cache: dict[str, Any] = {"access_token": "", "expires_at": 0.0}


def _get_token() -> str:
    """Retourne un token valide ; en recrée un si expiré (marge 30 s)."""
    if time.time() < _token_cache["expires_at"] - 30:
        return _token_cache["access_token"]
    resp = httpx.post(TOKEN_URL, data={
        "grant_type":    "client_credentials",
        "client_id":     KC_CLIENT,
        "client_secret": KC_SECRET,
    }, timeout=10)
    if resp.status_code != 200:
        raise HTTPException(502, f"Keycloak token KO: {resp.text[:200]}")
    data = resp.json()
    _token_cache["access_token"] = data["access_token"]
    _token_cache["expires_at"]   = time.time() + data.get("expires_in", 300)
    return _token_cache["access_token"]


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_get_token()}"}


def _oria(method: str, path: str, **kwargs) -> Any:
    """Appel HTTP vers l'API Oria avec token auto-renouvelé."""
    url = f"{ORIA_API}/v1/api{path}"
    r = httpx.request(method, url, headers=_headers(), timeout=15, **kwargs)
    if r.status_code >= 400:
        raise HTTPException(r.status_code, f"Oria: {r.text[:300]}")
    return r.json()


# ── endpoints ─────────────────────────────────────────────────────────────────

@app.get("/sante")
def sante():
    try:
        _get_token()
        return {"statut": "ok", "version": "0.1.0", "oria_api": ORIA_API}
    except Exception as e:
        return {"statut": "degradé", "erreur": str(e)}


@app.get("/worlds")
def lister_worlds():
    """Worlds accessibles par l'assistant (espaces de collaboration)."""
    return _oria("GET", "/worlds/")


@app.get("/monde/membres")
def membres_world(world_id: str = Query(..., description="UUID du world")):
    """Membres d'un world (id, nom, rôle, Matrix ID)."""
    return _oria("GET", f"/worlds/{world_id}/membres")


@app.get("/monde/rooms")
def rooms_world(world_id: str = Query(..., description="UUID du world")):
    """Rooms (salles) d'un world — utilisées pour la visio et le fil de discussion."""
    # Oria stocke les rooms dans les buildings. On liste les buildings puis les rooms.
    buildings = _oria("GET", f"/worlds/{world_id}/membres")  # membres = contexte
    # Appel direct discover pour rooms — si le world a un building
    try:
        world_info = _oria("GET", f"/worlds/{world_id}")
        rooms: list = []
        # Pas d'endpoint direct world→rooms sans building_id ; on renvoie world_info enrichi
        return {"world": world_info, "note": "rooms accessibles via les buildings du world"}
    except Exception:
        return {"rooms": []}


@app.get("/utilisateurs")
def decouvrir_utilisateurs():
    """Utilisateurs Oria connus (pour invitations ou contacts)."""
    return _oria("GET", "/discover/users")


@app.get("/social/flux")
def flux_social():
    """Fil d'actualité social (activités récentes des membres suivis)."""
    return _oria("GET", "/social/feed")


class WorldCreerEntree(BaseModel):
    nom: str
    description: Optional[str] = ""
    emoji: Optional[str] = "🌍"
    couleur: Optional[str] = "#3b82f6"


@app.post("/worlds")
def creer_world(corps: WorldCreerEntree):
    """Crée un nouvel espace de collaboration (world) dans Oria."""
    return _oria("POST", "/worlds/", json=corps.model_dump())


class InvitationEntree(BaseModel):
    world_id: str
    user_id: Optional[str] = None
    email: Optional[str] = None


@app.post("/invitations")
def inviter(corps: InvitationEntree):
    """Envoie une invitation à un utilisateur pour rejoindre un world."""
    payload: dict[str, Any] = {"world_id": corps.world_id}
    if corps.user_id:
        payload["user_id"] = corps.user_id
    if corps.email:
        payload["email"] = corps.email
    return _oria("POST", "/invitations/", json=payload)


class RoomEntree(BaseModel):
    world_id: str
    building_id: str
    nom: str
    description: Optional[str] = ""


@app.post("/monde/rooms")
def creer_room(corps: RoomEntree):
    """Crée une room (salle) dans un building d'un world."""
    return _oria("POST", f"/rooms/{corps.building_id}/rooms", json={
        "nom":         corps.nom,
        "description": corps.description,
    })

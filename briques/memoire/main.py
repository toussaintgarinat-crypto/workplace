"""Brique « memoire » — adaptateur entre Workplace et le projet Memory.

Le projet Memory (backend FastAPI + Postgres/pgvector, graphe de souvenirs avec
stages IPCRa, tiers et recherche hybride) est riche mais multi-espaces et
authentifié par JWT. Cette brique l'enveloppe derrière un **contrat simple** que
le reste de Workplace (le Cœur, Forge, Oria) peut consommer sans rien connaître
des espaces ni des tokens :

    GET    /sante
    POST   /retenir              {contenu, titre?, type?, wing?, room?, hall?, metadata?}
    GET    /rappeler?q=...        recherche hybride (texte+vecteur), avec score
    GET    /souvenirs?type=...    liste (filtrable par type/wing/room)
    GET    /taxonomy             comptes par type (pour les onglets/wings)
    DELETE /souvenir/{id}        supprime un souvenir

L'adaptateur gère une fois pour toutes : compte de service, connexion (JWT) et
**espace par défaut** (« Workplace »). Idempotent et tolérant au démarrage
différé du backend Memory.

Le backend Memory possède un `location` natif (wing/room/drawer) : on l'utilise
pour porter les rangements de Forge (wings IPCRa) et d'Oria (wing_user / salles).
"""

import asyncio
import os

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

MEMORY_API = os.environ.get("MEMORY_API", "http://memoire-backend:8000").rstrip("/")
EMAIL = os.environ.get("MEMOIRE_EMAIL", "service@workplace.local")
MOTDEPASSE = os.environ.get("MEMOIRE_PASSWORD", "workplace-memoire")
ESPACE = os.environ.get("MEMOIRE_ESPACE", "Workplace")

VERSION = "0.2.0"
app = FastAPI(title="Mémoire Workplace", version=VERSION)

# Session résolue paresseusement, protégée par un verrou. Le token de service est partagé ;
# les espaces (« Workplace » = solution, « Perso », …) sont résolus/créés à la demande et
# mémoïsés par nom → cloisonnement réel (le backend Memory isole les nœuds par space).
_session: dict = {"token": None}
_espaces: dict[str, str] = {}   # nom d'espace → espace_id
_verrou = asyncio.Lock()


async def _token(client: httpx.AsyncClient) -> str:
    """Garantit le compte de service et renvoie un JWT (mémoïsé)."""
    if _session["token"]:
        return _session["token"]
    async with _verrou:
        if _session["token"]:
            return _session["token"]
        # 1) Inscription idempotente (400 = déjà inscrit → on ignore).
        try:
            await client.post(
                f"{MEMORY_API}/api/v1/auth/register",
                json={"email": EMAIL, "password": MOTDEPASSE, "display_name": "Workplace"},
            )
        except httpx.HTTPError:
            pass
        # 2) Connexion → JWT.
        r = await client.post(
            f"{MEMORY_API}/api/v1/auth/login",
            json={"email": EMAIL, "password": MOTDEPASSE},
        )
        r.raise_for_status()
        _session["token"] = r.json()["access_token"]
        return _session["token"]


async def _espace_id(client: httpx.AsyncClient, nom: str | None = None) -> str:
    """Renvoie l'id de l'espace `nom` (créé s'il n'existe pas). Défaut = espace solution."""
    nom = (nom or ESPACE).strip() or ESPACE
    if nom in _espaces:
        return _espaces[nom]
    # Résoudre le token AVANT de prendre _verrou (sinon double acquisition = deadlock).
    token = await _token(client)
    async with _verrou:
        if nom in _espaces:
            return _espaces[nom]
        entetes = {"Authorization": f"Bearer {token}"}
        r = await client.get(f"{MEMORY_API}/api/v1/spaces", headers=entetes)
        r.raise_for_status()
        espace = next((e for e in r.json() if e.get("name") == nom), None)
        if espace is None:
            desc = ("Mémoire de la solution Workplace" if nom == ESPACE
                    else f"Espace mémoire « {nom} »")
            r = await client.post(
                f"{MEMORY_API}/api/v1/spaces",
                headers=entetes,
                json={"name": nom, "description": desc},
            )
            r.raise_for_status()
            espace = r.json()
        _espaces[nom] = espace["id"]
        return _espaces[nom]


async def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=20)


# ── Modèles ──────────────────────────────────────────────────────────────────

# Types de nœuds valides côté Memory (enum NodeType). « input » = entrée IPCRa.
TYPES_VALIDES = {"input", "projet", "casquette", "ressource", "archive"}


def _type_valide(t: str | None) -> str:
    return t if t in TYPES_VALIDES else "input"


class Souvenir(BaseModel):
    contenu: str
    titre: str | None = None
    type: str = "input"
    wing: str | None = None          # rangement (défaut : = type) — location.wing côté Memory
    room: str | None = None          # sous-rangement (défaut : « general ») — location.room
    hall: str | None = None          # méta libre (hall_events/hall_facts…) → frontmatter
    metadata: dict | None = None     # méta libre supplémentaire → frontmatter
    espace: str | None = None        # None → espace solution (« Workplace »)


# ── Contrat ──────────────────────────────────────────────────────────────────

@app.get("/sante")
async def sante():
    """OK si le backend Memory répond et que la session de service est résolue."""
    try:
        async with await _client() as client:
            await _espace_id(client)  # résout token + espace solution
        return {"statut": "ok", "service": "memoire", "version": VERSION,
                "espaces": _espaces}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(503, f"Backend Memory indisponible : {e}")


@app.post("/retenir", summary="Mémoriser un souvenir")
async def retenir(s: Souvenir):
    titre = (s.titre or s.contenu[:60] or "souvenir").strip()
    type_ = _type_valide(s.type)
    # Rangement : par défaut le wing reflète le type (vue Forge = wings IPCRa) ;
    # Oria fournit un wing/room explicites (wing_user / salles thématiques).
    wing = (s.wing or type_).strip() or type_
    room = (s.room or "general").strip() or "general"
    frontmatter = dict(s.metadata or {})
    if s.hall:
        frontmatter["hall"] = s.hall
    # Le backend Memory ne persiste pas toujours `location` à la création : on garde
    # donc wing/room AUSSI dans le frontmatter (source de vérité fiable au relire).
    frontmatter["wing"] = wing
    frontmatter["room"] = room
    corps = {
        "type": type_,
        "title": titre,
        "content_md": s.contenu,
        "location": {"wing": wing, "room": room},
        "frontmatter": frontmatter,
    }
    async with await _client() as client:
        espace_id = await _espace_id(client, s.espace)
        r = await client.post(
            f"{MEMORY_API}/api/v1/spaces/{espace_id}/nodes",
            json=corps,
        )
        if r.status_code >= 400:
            raise HTTPException(502, f"Memory: {r.text}")
        n = r.json()
    # wing/room : valeurs envoyées (Memory n'écho pas toujours location dans la réponse).
    return {"retenu": True, "id": n["id"], "titre": n["title"], "type": n["type"],
            "wing": wing, "room": room}


@app.get("/rappeler", summary="Retrouver des souvenirs (recherche hybride)")
async def rappeler(q: str = "", limite: int = 8, type: str | None = None,
                   espace: str | None = None):
    params: dict = {"q": q, "limit": limite}
    if type:
        params["type"] = type
    async with await _client() as client:
        espace_id = await _espace_id(client, espace)
        r = await client.get(
            f"{MEMORY_API}/api/v1/spaces/{espace_id}/search",
            params=params,
        )
        if r.status_code >= 400:
            raise HTTPException(502, f"Memory: {r.text}")
        resultats = r.json()
    souvenirs = [
        {
            "id": x.get("id"),
            "titre": x.get("title"),
            "extrait": (x.get("content_md") or "")[:280],
            "type": x.get("type"),
            "score": x.get("score", 0),
        }
        for x in resultats
    ]
    return {"requete": q, "total": len(souvenirs), "souvenirs": souvenirs}


@app.get("/souvenirs", summary="Lister les souvenirs récents")
async def souvenirs(limite: int = 20, type: str | None = None,
                    wing: str | None = None, room: str | None = None,
                    espace: str | None = None):
    params: dict = {"limit": limite}
    if type:
        params["type"] = type
    if wing:
        params["wing"] = wing
    if room:
        params["room"] = room
    async with await _client() as client:
        espace_id = await _espace_id(client, espace)
        r = await client.get(
            f"{MEMORY_API}/api/v1/spaces/{espace_id}/nodes",
            params=params,
        )
        if r.status_code >= 400:
            raise HTTPException(502, f"Memory: {r.text}")
        noeuds = r.json()

    def _vue(n: dict) -> dict:
        loc = n.get("location") or {}
        fm = n.get("frontmatter") or {}
        return {
            "id": n.get("id"), "titre": n.get("title"),
            "contenu": n.get("content_md"), "type": n.get("type"),
            # location d'abord (si Memory l'a persistée), sinon repli sur le frontmatter.
            "wing": loc.get("wing") or fm.get("wing"),
            "room": loc.get("room") or fm.get("room"),
            "metadata": fm,
            "stage": n.get("ipcra_stage"), "tier": n.get("storage_tier"),
        }

    return {"total": len(noeuds), "souvenirs": [_vue(n) for n in noeuds]}


@app.get("/taxonomy", summary="Comptes par type (pour les onglets/wings)")
async def taxonomy(espace: str | None = None):
    async with await _client() as client:
        espace_id = await _espace_id(client, espace)
        # /stats est protégé (check_space_access) → joindre le JWT de service.
        token = await _token(client)
        r = await client.get(
            f"{MEMORY_API}/api/v1/spaces/{espace_id}/stats",
            headers={"Authorization": f"Bearer {token}"},
        )
        if r.status_code >= 400:
            raise HTTPException(502, f"Memory: {r.text}")
        stats = r.json()
    return {
        "total": stats.get("total_nodes", 0),
        "par_type": stats.get("by_type", {}),
        "par_stage": stats.get("by_stage", {}),
    }


@app.delete("/souvenir/{souvenir_id}", summary="Supprimer un souvenir")
async def supprimer(souvenir_id: str, espace: str | None = None):
    async with await _client() as client:
        espace_id = await _espace_id(client, espace)
        r = await client.delete(
            f"{MEMORY_API}/api/v1/spaces/{espace_id}/nodes/{souvenir_id}"
        )
        if r.status_code >= 400 and r.status_code != 404:
            raise HTTPException(502, f"Memory: {r.text}")
    return {"supprime": True, "id": souvenir_id}

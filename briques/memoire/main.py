"""Brique « memoire » — adaptateur entre Workplace et le projet Memory.

Le projet Memory (backend FastAPI + Postgres/pgvector, graphe de souvenirs avec
stages IPCRa, tiers et recherche hybride) est riche mais multi-espaces et
authentifié par JWT. Cette brique l'enveloppe derrière un **contrat simple** que
le reste de Workplace (et l'assistant du Cœur) peut consommer sans rien connaître
des espaces ni des tokens :

    GET  /sante
    POST /retenir              {contenu, titre?, type?}      → crée un souvenir
    GET  /rappeler?q=...       recherche hybride (texte+vecteur)
    GET  /souvenirs            liste les souvenirs récents

L'adaptateur gère une fois pour toutes : compte de service, connexion (JWT) et
**espace par défaut** (« Workplace »). Idempotent et tolérant au démarrage
différé du backend Memory.
"""

import asyncio
import os

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

MEMORY_API = os.environ.get("MEMORY_API", "http://memoire-backend:8000").rstrip("/")
EMAIL = os.environ.get("MEMOIRE_EMAIL", "service@workplace.local")
MOTDEPASSE = os.environ.get("MEMOIRE_PASSWORD", "workplace-memoire")
ESPACE = os.environ.get("MEMOIRE_ESPACE", "Workplace")

app = FastAPI(title="Mémoire Workplace", version="0.1.0")

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


class Souvenir(BaseModel):
    contenu: str
    titre: str | None = None
    type: str = "input"
    espace: str | None = None   # None → espace solution (« Workplace »)


# ── Contrat ──────────────────────────────────────────────────────────────────

@app.get("/sante")
async def sante():
    """OK si le backend Memory répond et que la session de service est résolue."""
    try:
        async with await _client() as client:
            await _espace_id(client)  # résout token + espace solution
        return {"statut": "ok", "service": "memoire", "version": "0.1.0",
                "espaces": _espaces}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(503, f"Backend Memory indisponible : {e}")


@app.post("/retenir", summary="Mémoriser un souvenir")
async def retenir(s: Souvenir):
    titre = (s.titre or s.contenu[:60] or "souvenir").strip()
    type_ = s.type if s.type in TYPES_VALIDES else "input"
    async with await _client() as client:
        espace_id = await _espace_id(client, s.espace)
        r = await client.post(
            f"{MEMORY_API}/api/v1/spaces/{espace_id}/nodes",
            json={"type": type_, "title": titre, "content_md": s.contenu},
        )
        if r.status_code >= 400:
            raise HTTPException(502, f"Memory: {r.text}")
        n = r.json()
    return {"retenu": True, "id": n["id"], "titre": n["title"], "type": n["type"]}


@app.get("/rappeler", summary="Retrouver des souvenirs (recherche hybride)")
async def rappeler(q: str = "", limite: int = 8, espace: str | None = None):
    async with await _client() as client:
        espace_id = await _espace_id(client, espace)
        r = await client.get(
            f"{MEMORY_API}/api/v1/spaces/{espace_id}/search",
            params={"q": q, "limit": limite},
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
        }
        for x in resultats
    ]
    return {"requete": q, "total": len(souvenirs), "souvenirs": souvenirs}


@app.get("/souvenirs", summary="Lister les souvenirs récents")
async def souvenirs(limite: int = 20, espace: str | None = None):
    async with await _client() as client:
        espace_id = await _espace_id(client, espace)
        r = await client.get(
            f"{MEMORY_API}/api/v1/spaces/{espace_id}/nodes",
            params={"limit": limite},
        )
        if r.status_code >= 400:
            raise HTTPException(502, f"Memory: {r.text}")
        noeuds = r.json()
    return {
        "total": len(noeuds),
        "souvenirs": [
            {"id": n.get("id"), "titre": n.get("title"), "type": n.get("type"),
             "stage": n.get("ipcra_stage"), "tier": n.get("storage_tier")}
            for n in noeuds
        ],
    }

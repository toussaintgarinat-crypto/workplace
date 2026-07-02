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
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

MEMORY_API = os.environ.get("MEMORY_API", "http://memoire-backend:8000").rstrip("/")
EMAIL = os.environ.get("MEMOIRE_EMAIL", "service@workplace.local")
MOTDEPASSE = os.environ.get("MEMOIRE_PASSWORD", "workplace-memoire")
ESPACE = os.environ.get("MEMOIRE_ESPACE", "Workplace")

# Front React buildé (memory/frontend → /app/ui par le Dockerfile multi-stage).
# Absent en test/dev local : tout le service du front est alors gracieusement inerte.
UI_DIR = Path(os.environ.get("UI_DIR", "/app/ui"))

VERSION = "0.3.0"
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


def _normaliser_espace(espace: str | None) -> str | None:
    """Normalise l'espace envoyé par le manifest : 'solution'→None (défaut), 'perso'→'Perso'."""
    if not espace:
        return None
    low = espace.strip().lower()
    if low == "solution":
        return None
    if low == "perso":
        return "Perso"
    return espace  # valeur brute pour les espaces custom


@app.post("/retenir", summary="Mémoriser un souvenir")
async def retenir(s: Souvenir):
    s = s.model_copy(update={"espace": _normaliser_espace(s.espace)})
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
    espace = _normaliser_espace(espace)
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
    espace = _normaliser_espace(espace)
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


# ── Front React (S108) ─────────────────────────────────────────────────────────
# La brique sert le vrai front du projet Memory (memory/frontend, buildé dans /app/ui)
# et reverse-proxy /api/v1 vers le backend Memory interne. Le front parle à /api/v1 en
# relatif → tout est same-origin (pas de CORS). L'auth est injectée côté serveur : le
# proxy force le JWT de service sur chaque appel, et l'index pré-remplit localStorage
# (auth_token + active_space_id) pour passer le garde RequireAuth sans écran de connexion.

# En-têtes hop-by-hop : ne JAMAIS recopier de/vers le client (gérés par le transport).
_HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "content-encoding",
    "content-length", "host",
}


@app.api_route(
    "/api/v1/{chemin:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_api(chemin: str, request: Request):
    """Relaie /api/v1/* vers le backend Memory interne en forçant l'auth de service.

    On IGNORE l'Authorization éventuel du front (jeton injecté, peut-être périmé) et on
    pose toujours un JWT de service frais : la brique est mono-locataire (compte unique).
    """
    corps = await request.body()
    entetes = {
        k: v for k, v in request.headers.items()
        if k.lower() not in _HOP_BY_HOP and k.lower() != "authorization"
    }
    async with await _client() as client:
        entetes["Authorization"] = f"Bearer {await _token(client)}"
        amont = await client.request(
            request.method,
            f"{MEMORY_API}/api/v1/{chemin}",
            params=dict(request.query_params),
            content=corps,
            headers=entetes,
        )
    sortie = {
        k: v for k, v in amont.headers.items() if k.lower() not in _HOP_BY_HOP
    }
    return Response(content=amont.content, status_code=amont.status_code,
                    headers=sortie, media_type=amont.headers.get("content-type"))


# Assets statiques du build Vite (montés seulement si le front est présent).
if (UI_DIR / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=str(UI_DIR / "assets")), name="assets")


def _type_mime(nom: str) -> str:
    import mimetypes
    return mimetypes.guess_type(nom)[0] or "application/octet-stream"


async def _index_injecte() -> str:
    """index.html du front avec un <script> qui pré-remplit localStorage (auth + espace)."""
    index = UI_DIR / "index.html"
    if not index.is_file():
        return ("<!doctype html><meta charset=utf-8><title>Mémoire</title>"
                "<p>Front non buildé (image construite sans le stage Node ?).</p>")
    html = index.read_text(encoding="utf-8")
    async with await _client() as client:
        token = await _token(client)
        espace_id = await _espace_id(client)
    boot = (
        "<script>try{"
        f"localStorage.setItem('auth_token',{token!r});"
        f"localStorage.setItem('active_space_id',{espace_id!r});"
        "}catch(e){}</script>"
    )
    return html.replace("</head>", boot + "</head>", 1)


@app.get("/", include_in_schema=False)
async def racine():
    return RedirectResponse("/memory")


@app.get("/{chemin:path}", include_in_schema=False)
async def spa(chemin: str):
    """Fallback SPA : toute route front (/memory, /memory/graph, …) rend l'index injecté.

    Déclaré en DERNIER : le contrat (/sante, /retenir…) et /api/v1 sont matchés avant.
    Un fichier statique racine présent (favicon.svg…) est servi tel quel.
    """
    if chemin and UI_DIR.is_dir():
        cible = UI_DIR / chemin
        if cible.is_file() and cible.resolve().is_relative_to(UI_DIR.resolve()):
            return Response(content=cible.read_bytes(), media_type=_type_mime(cible.name))
    return HTMLResponse(await _index_injecte())

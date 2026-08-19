"""Brique « atelier-veille » — front unique de la famille veille.

Quasi uniquement du front (front.html) : compose geo (carte, iframe navigateur direct) et
veille-info (sources RSS, digests, audio ; proxy HTTP serveur→serveur) sans dupliquer leur
code ni leur état. Motif de composition identique à briques/studio/main.py (appel HTTP +
repli honnête si la brique composée est injoignable). Aucune capacité LLM (`capacites: []`
dans le manifest) : cette brique est une SURFACE HUMAINE, pas un outil de l'assistant.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field

app = FastAPI(title="Atelier Veille", version="0.1.0")

_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])

# GEO_PUBLIC_URL : surcharge EXPLICITE seulement (déploiement particulier / SSO). Laissée
# vide par défaut : une valeur figée type "http://localhost:6110/" casse la carte dès que
# l'atelier est ouvert depuis autre chose que la machine hôte (LAN, mesh, téléphone) — même
# piège que S128 (cf. core/urls_ui.py). Par défaut on dérive donc l'URL de l'hôte de la
# requête courante dans /config, exactement comme url_brique() côté Cœur.
GEO_PUBLIC_URL = os.getenv("GEO_PUBLIC_URL", "").strip()
GEO_PORT = int(os.getenv("GEO_PORT", "6110"))
VEILLE_INFO_URL = os.getenv("VEILLE_INFO_URL", "http://host.docker.internal:6120")
VEILLE_PROSPECTION_URL = os.getenv("VEILLE_PROSPECTION_URL", "http://host.docker.internal:6140")
GEO_URL = os.getenv("GEO_URL", "http://host.docker.internal:6110")
FORGE_URL = os.getenv("FORGE_URL", "http://host.docker.internal:5700")
MAIL_URL = os.getenv("MAIL_URL", "http://host.docker.internal:6030")

# MESH_HOST / MESH_PORT_OFFSET : même convention que core/urls_ui.py::url_brique. Caddy
# termine le TLS du mesh et reverse-proxy en HTTP vers ce conteneur, donc `request.url.scheme`
# vaut toujours "http" ici — jamais fiable pour reconstruire l'URL vue par le NAVIGATEUR.
# Sans ce garde-fou, la carte (servie en clair sur GEO_PORT) est bloquée en mixed content
# dès que l'atelier est ouvert en HTTPS via le mesh.
MESH_HOST = os.getenv("MESH_HOST", "").strip()
MESH_PORT_OFFSET = int(os.getenv("MESH_PORT_OFFSET", "10000"))


def _hote_sans_port(host: str) -> str:
    """Renvoie l'hôte de l'en-tête `Host` sans le `:port` éventuel — même logique que
    `core/urls_ui.py::_hote_sans_port` (S128), dupliquée ici car cette brique est un
    service Docker autonome sans dépendance au code du Cœur."""
    host = (host or "localhost").strip()
    if host.startswith("["):
        return host.split("]", 1)[0] + "]"
    return host.rsplit(":", 1)[0] if ":" in host else host

_FRONT = Path(__file__).parent / "front.html"
# no-cache (pas no-store) : le navigateur revalide sur l'ETag à chaque chargement au lieu
# de garder une copie en cache heuristique — sans ça, un correctif poussé sur front.html
# reste invisible tant que l'utilisateur ne force pas un rechargement complet.
_ENTETES_FRONT = {"Cache-Control": "no-cache"}


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def racine():
    return FileResponse(_FRONT, media_type="text/html", headers=_ENTETES_FRONT)


@app.get("/atelier", response_class=HTMLResponse, include_in_schema=False)
def alias_atelier():
    return FileResponse(_FRONT, media_type="text/html", headers=_ENTETES_FRONT)


@app.get("/workplace.css", include_in_schema=False)
def css():
    return FileResponse(Path(__file__).parent / "workplace.css", media_type="text/css")


def _entetes_aval(x_user_id: Optional[str], x_api_key: Optional[str]) -> dict:
    """Relaie tels quels les en-têtes d'identité reçus du navigateur vers veille-info —
    l'atelier ne fabrique jamais lui-même une identité (pass-through pur)."""
    entetes: dict = {}
    if x_user_id:
        entetes["X-User-Id"] = x_user_id
    if x_api_key:
        entetes["X-API-Key"] = x_api_key
    return entetes


class CreerSource(BaseModel):
    nom: str = Field(min_length=1)
    url: str = Field(min_length=1)
    thematique: str = ""


class RetaggerSource(BaseModel):
    thematique: str = ""


class GenererAudioGlobal(BaseModel):
    ordre_thematiques: list[int] = Field(min_length=1)


class CreerCampagneProspection(BaseModel):
    zone_id: str = Field(min_length=1)
    type: str = "b2b"


class EnvoyerAudioGlobal(BaseModel):
    destinataires: list[str] = Field(min_length=1)
    sujet: Optional[str] = None
    message: Optional[str] = None


class PreparerDemarchage(BaseModel):
    campagne_id: int
    prospect_ids: list[str] = Field(min_length=1)
    expediteur: str = Field(min_length=1)
    sujet: str = Field(min_length=1)
    message: str = Field(min_length=1)
    compte: str = ""


_RE_COMMUNE = re.compile(r"Commune\s*:\s*([^·]+)")


def _ville_depuis_notes(notes: str | None) -> str:
    """Best-effort : extrait la commune du format `notes` posé par
    `briques/forge/main.py::_prospect_vers_lead` (« NAF : … · Commune : X · … »). Un
    format qui change côté Forge casse cette extraction SILENCIEUSEMENT (regex, pas un
    contrat) — acceptable : {ville} reste juste vide, jamais une erreur (cf. spec
    2026-08-19)."""
    if not notes:
        return ""
    m = _RE_COMMUNE.search(notes)
    return m.group(1).strip() if m else ""


@app.get("/sante", tags=["système"])
def sante():
    return {"statut": "ok"}


@app.get("/config", tags=["système"])
def config(request: Request, x_forwarded_host: Optional[str] = Header(None),
          x_forwarded_proto: Optional[str] = Header(None)):
    """URL publique (navigateur) de la carte geo — injectée dans l'onglet Carte du front.

    Dérivée par défaut du scheme + hôte de LA REQUÊTE COURANTE (celle que le navigateur
    vient d'utiliser pour joindre l'atelier), pour rester juste en LAN comme sur le mesh
    sans repointer une IP figée. `GEO_PUBLIC_URL` reste une surcharge possible.

    Derrière le proxy du Cœur (`core/routers/atelier_veille_proxy.py`), la requête HTTP
    reçue ICI vient du Cœur lui-même (httpx serveur→serveur) : son en-tête `Host` vaut
    l'hôte INTERNE du conteneur atelier-veille, jamais celui vu par le navigateur. Le
    proxy forwarde donc `X-Forwarded-Host`/`X-Forwarded-Proto` (motif déjà utilisé par
    `core/routers/dashboard.py::u()` pour la même raison) — on les préfère s'ils sont
    présents, sinon on retombe sur `Host` brut (accès direct, LAN, inchangé)."""
    if GEO_PUBLIC_URL:
        return {"geo_url": GEO_PUBLIC_URL}
    hote_brut = x_forwarded_host or request.headers.get("host", "localhost")
    scheme = x_forwarded_proto or request.url.scheme
    hote = _hote_sans_port(hote_brut)
    if MESH_HOST and hote == MESH_HOST:
        return {"geo_url": f"https://{hote}:{GEO_PORT + MESH_PORT_OFFSET}/"}
    return {"geo_url": f"{scheme}://{hote}:{GEO_PORT}/"}


@app.get("/veille/sources", tags=["veille"])
async def lister_sources(x_user_id: Optional[str] = Header(None),
                         x_api_key: Optional[str] = Header(None)):
    entetes = _entetes_aval(x_user_id, x_api_key)
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"{VEILLE_INFO_URL}/sources", headers=entetes)
        corps = r.json()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"veille-info injoignable ({VEILLE_INFO_URL}) : {str(e)[:150]}")
    if r.status_code >= 400:
        detail = corps.get("detail") if isinstance(corps, dict) else None
        raise HTTPException(r.status_code, detail or f"veille-info a refusé la requête ({r.status_code}).")
    return corps


@app.post("/veille/sources", tags=["veille"])
async def creer_source(body: CreerSource, x_user_id: Optional[str] = Header(None),
                       x_api_key: Optional[str] = Header(None)):
    entetes = _entetes_aval(x_user_id, x_api_key)
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(f"{VEILLE_INFO_URL}/sources", headers=entetes,
                             json=body.model_dump())
        corps = r.json()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"veille-info injoignable ({VEILLE_INFO_URL}) : {str(e)[:150]}")
    if r.status_code >= 400:
        detail = corps.get("detail") if isinstance(corps, dict) else None
        raise HTTPException(r.status_code, detail or f"veille-info a refusé la requête ({r.status_code}).")
    return JSONResponse(content=corps, status_code=r.status_code)


@app.delete("/veille/sources/{source_id}", tags=["veille"])
async def supprimer_source(source_id: int, x_user_id: Optional[str] = Header(None),
                           x_api_key: Optional[str] = Header(None)):
    entetes = _entetes_aval(x_user_id, x_api_key)
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.delete(f"{VEILLE_INFO_URL}/sources/{source_id}", headers=entetes)
        corps = r.json()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"veille-info injoignable ({VEILLE_INFO_URL}) : {str(e)[:150]}")
    if r.status_code == 404:
        raise HTTPException(404, "Source introuvable.")
    if r.status_code >= 400:
        detail = corps.get("detail") if isinstance(corps, dict) else None
        raise HTTPException(r.status_code, detail or f"veille-info a refusé la requête ({r.status_code}).")
    return corps


@app.get("/veille/digests", tags=["veille"])
async def lister_digests(x_user_id: Optional[str] = Header(None),
                         x_api_key: Optional[str] = Header(None)):
    entetes = _entetes_aval(x_user_id, x_api_key)
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"{VEILLE_INFO_URL}/digests", headers=entetes)
        corps = r.json()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"veille-info injoignable ({VEILLE_INFO_URL}) : {str(e)[:150]}")
    if r.status_code >= 400:
        detail = corps.get("detail") if isinstance(corps, dict) else None
        raise HTTPException(r.status_code, detail or f"veille-info a refusé la requête ({r.status_code}).")
    return corps


@app.patch("/veille/sources/{source_id}/thematique", tags=["veille"])
async def retagger_source(source_id: int, body: RetaggerSource,
                          x_user_id: Optional[str] = Header(None),
                          x_api_key: Optional[str] = Header(None)):
    entetes = _entetes_aval(x_user_id, x_api_key)
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.patch(f"{VEILLE_INFO_URL}/sources/{source_id}/thematique",
                              headers=entetes, json=body.model_dump())
        corps = r.json()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"veille-info injoignable ({VEILLE_INFO_URL}) : {str(e)[:150]}")
    if r.status_code >= 400:
        detail = corps.get("detail") if isinstance(corps, dict) else None
        raise HTTPException(r.status_code, detail or f"veille-info a refusé la requête ({r.status_code}).")
    return corps


class ModifierUrlSource(BaseModel):
    url: str


@app.patch("/veille/sources/{source_id}/url", tags=["veille"])
async def modifier_url_source(source_id: int, body: ModifierUrlSource,
                              x_user_id: Optional[str] = Header(None),
                              x_api_key: Optional[str] = Header(None)):
    """Corrige l'URL d'une source (S203) — pass-through, isolation faite en aval."""
    entetes = _entetes_aval(x_user_id, x_api_key)
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.patch(f"{VEILLE_INFO_URL}/sources/{source_id}/url",
                              headers=entetes, json=body.model_dump())
        corps = r.json()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"veille-info injoignable ({VEILLE_INFO_URL}) : {str(e)[:150]}")
    if r.status_code >= 400:
        detail = corps.get("detail") if isinstance(corps, dict) else None
        raise HTTPException(r.status_code, detail or f"veille-info a refusé la requête ({r.status_code}).")
    return corps


class BasculerSourceActive(BaseModel):
    active: bool


@app.patch("/veille/sources/{source_id}/actif", tags=["veille"])
async def basculer_source_active(source_id: int, body: BasculerSourceActive,
                                 x_user_id: Optional[str] = Header(None),
                                 x_api_key: Optional[str] = Header(None)):
    """Allume/éteint UNE source (S203) — pass-through, l'isolation par personne est faite
    en aval par veille-info sur l'identité relayée."""
    entetes = _entetes_aval(x_user_id, x_api_key)
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.patch(f"{VEILLE_INFO_URL}/sources/{source_id}/actif",
                              headers=entetes, json=body.model_dump())
        corps = r.json()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"veille-info injoignable ({VEILLE_INFO_URL}) : {str(e)[:150]}")
    if r.status_code >= 400:
        detail = corps.get("detail") if isinstance(corps, dict) else None
        raise HTTPException(r.status_code, detail or f"veille-info a refusé la requête ({r.status_code}).")
    return corps


class BasculerPauseThematique(BaseModel):
    thematique: str
    en_pause: bool


@app.get("/veille/thematiques", tags=["veille"])
async def lister_thematiques(x_user_id: Optional[str] = Header(None),
                             x_api_key: Optional[str] = Header(None)):
    entetes = _entetes_aval(x_user_id, x_api_key)
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"{VEILLE_INFO_URL}/thematiques", headers=entetes)
        corps = r.json()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"veille-info injoignable ({VEILLE_INFO_URL}) : {str(e)[:150]}")
    if r.status_code >= 400:
        detail = corps.get("detail") if isinstance(corps, dict) else None
        raise HTTPException(r.status_code, detail or f"veille-info a refusé la requête ({r.status_code}).")
    return corps


@app.patch("/veille/thematiques/pause", tags=["veille"])
async def basculer_pause_thematique(body: BasculerPauseThematique,
                                    x_user_id: Optional[str] = Header(None),
                                    x_api_key: Optional[str] = Header(None)):
    entetes = _entetes_aval(x_user_id, x_api_key)
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.patch(f"{VEILLE_INFO_URL}/thematiques/pause",
                              headers=entetes, json=body.model_dump())
        corps = r.json()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"veille-info injoignable ({VEILLE_INFO_URL}) : {str(e)[:150]}")
    if r.status_code >= 400:
        detail = corps.get("detail") if isinstance(corps, dict) else None
        raise HTTPException(r.status_code, detail or f"veille-info a refusé la requête ({r.status_code}).")
    return corps


@app.post("/veille/audio-global/generer", tags=["veille"])
async def generer_audio_global(body: GenererAudioGlobal, x_user_id: Optional[str] = Header(None),
                               x_api_key: Optional[str] = Header(None)):
    entetes = _entetes_aval(x_user_id, x_api_key)
    try:
        async with httpx.AsyncClient(timeout=300) as c:
            r = await c.post(f"{VEILLE_INFO_URL}/audio-global/generer", headers=entetes,
                             json=body.model_dump())
        corps = r.json()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"veille-info injoignable ({VEILLE_INFO_URL}) : {str(e)[:150]}")
    if r.status_code >= 400:
        detail = corps.get("detail") if isinstance(corps, dict) else None
        raise HTTPException(r.status_code, detail or f"veille-info a refusé la requête ({r.status_code}).")
    return corps


@app.get("/veille/audio-global", tags=["veille"])
async def lister_audio_global(x_user_id: Optional[str] = Header(None),
                              x_api_key: Optional[str] = Header(None)):
    entetes = _entetes_aval(x_user_id, x_api_key)
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"{VEILLE_INFO_URL}/audio-global", headers=entetes)
        corps = r.json()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"veille-info injoignable ({VEILLE_INFO_URL}) : {str(e)[:150]}")
    if r.status_code >= 400:
        detail = corps.get("detail") if isinstance(corps, dict) else None
        raise HTTPException(r.status_code, detail or f"veille-info a refusé la requête ({r.status_code}).")
    return corps


@app.get("/veille/audio-global/{jeton}.mp3", include_in_schema=False, tags=["veille"])
async def fichier_audio_global(jeton: str):
    """Sert le fichier mp3 de l'audio global — proxy BINAIRE (pas JSON) vers veille-info,
    même motif pass-through que les autres routes `/veille/*` de ce fichier. Nécessaire car
    VEILLE_INFO_URL pointe vers `host.docker.internal` (joignable seulement depuis CE
    conteneur), jamais depuis le navigateur — contrairement à la carte geo (`/config`), il
    n'existe pas de port hôte dédié à dériver ici : le navigateur ne parle qu'à l'atelier."""
    try:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.get(f"{VEILLE_INFO_URL}/audio-global/{jeton}.mp3")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"veille-info injoignable ({VEILLE_INFO_URL}) : {str(e)[:150]}")
    if r.status_code >= 400:
        raise HTTPException(r.status_code, "Audio introuvable ou lien expiré.")
    return Response(content=r.content, media_type=r.headers.get("content-type", "audio/mpeg"))


@app.post("/veille/audio-global/{audio_id}/envoyer", tags=["veille"])
async def envoyer_audio_global(audio_id: int, body: EnvoyerAudioGlobal,
                               x_user_id: Optional[str] = Header(None),
                               x_api_key: Optional[str] = Header(None)):
    entetes = _entetes_aval(x_user_id, x_api_key)
    try:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(f"{VEILLE_INFO_URL}/audio-global/{audio_id}/envoyer",
                             headers=entetes, json=body.model_dump())
        corps = r.json()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"veille-info injoignable ({VEILLE_INFO_URL}) : {str(e)[:150]}")
    if r.status_code >= 400:
        detail = corps.get("detail") if isinstance(corps, dict) else None
        raise HTTPException(r.status_code, detail or f"veille-info a refusé la requête ({r.status_code}).")
    return corps


class ExecuterDigest(BaseModel):
    thematique: str | None = None


@app.post("/veille/digest/executer", tags=["veille"])
async def executer_digest(body: ExecuterDigest | None = None):
    """Déclenche le digest quotidien pour TOUT le foyer (motif horloge, pas un compte
    personnel) — gardé côté veille-info par un jeton de SERVICE, jamais l'identité du
    navigateur. `body.thematique` (S200), si fourni, cible une seule thématique, y compris
    en pause (fetch forcé côté veille-info)."""
    jeton = os.environ.get("VEILLE_INFO_KEY", "")
    entetes = {"Authorization": f"Bearer {jeton}"}
    try:
        # 300 s (et non 60) : la synthèse LLM du digest sur toutes les sources d'une thématique
        # dépasse couramment la minute. Même palier que /veille/audio-global/generer.
        async with httpx.AsyncClient(timeout=300) as c:
            r = await c.post(f"{VEILLE_INFO_URL}/digest/executer", headers=entetes,
                             json=body.model_dump() if body else None)
        corps = r.json()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"veille-info injoignable ({VEILLE_INFO_URL}) : {str(e)[:150]}")
    if r.status_code >= 400:
        detail = corps.get("detail") if isinstance(corps, dict) else None
        raise HTTPException(r.status_code, detail or f"veille-info a refusé la requête ({r.status_code}).")
    return corps


@app.get("/prospection/campagnes", tags=["prospection"])
async def lister_campagnes_prospection(x_user_id: Optional[str] = Header(None),
                                       x_api_key: Optional[str] = Header(None)):
    entetes = _entetes_aval(x_user_id, x_api_key)
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"{VEILLE_PROSPECTION_URL}/campagnes", headers=entetes)
        corps = r.json()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"veille-prospection injoignable ({VEILLE_PROSPECTION_URL}) : {str(e)[:150]}")
    if r.status_code >= 400:
        detail = corps.get("detail") if isinstance(corps, dict) else None
        raise HTTPException(r.status_code, detail or f"veille-prospection a refusé la requête ({r.status_code}).")
    return corps


@app.post("/prospection/campagnes", tags=["prospection"], status_code=201)
async def creer_campagne_prospection(body: CreerCampagneProspection,
                                     x_user_id: Optional[str] = Header(None),
                                     x_api_key: Optional[str] = Header(None)):
    entetes = _entetes_aval(x_user_id, x_api_key)
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(f"{VEILLE_PROSPECTION_URL}/campagnes", headers=entetes,
                             json=body.model_dump())
        corps = r.json()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"veille-prospection injoignable ({VEILLE_PROSPECTION_URL}) : {str(e)[:150]}")
    if r.status_code >= 400:
        detail = corps.get("detail") if isinstance(corps, dict) else None
        raise HTTPException(r.status_code, detail or f"veille-prospection a refusé la requête ({r.status_code}).")
    return JSONResponse(content=corps, status_code=r.status_code)


@app.delete("/prospection/campagnes/{campagne_id}", tags=["prospection"])
async def supprimer_campagne_prospection(campagne_id: int,
                                         x_user_id: Optional[str] = Header(None),
                                         x_api_key: Optional[str] = Header(None)):
    entetes = _entetes_aval(x_user_id, x_api_key)
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.delete(f"{VEILLE_PROSPECTION_URL}/campagnes/{campagne_id}", headers=entetes)
        corps = r.json()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"veille-prospection injoignable ({VEILLE_PROSPECTION_URL}) : {str(e)[:150]}")
    if r.status_code == 404:
        raise HTTPException(404, "Campagne introuvable.")
    if r.status_code >= 400:
        detail = corps.get("detail") if isinstance(corps, dict) else None
        raise HTTPException(r.status_code, detail or f"veille-prospection a refusé la requête ({r.status_code}).")
    return corps


@app.post("/prospection/campagnes/{campagne_id}/executer", tags=["prospection"])
async def executer_campagne_prospection(campagne_id: int,
                                        x_user_id: Optional[str] = Header(None),
                                        x_api_key: Optional[str] = Header(None)):
    entetes = _entetes_aval(x_user_id, x_api_key)
    try:
        # 200s (pas 30) : l'appel geo sous-jacent (enrichir-lot) peut prendre jusqu'à 180s.
        async with httpx.AsyncClient(timeout=200) as c:
            r = await c.post(f"{VEILLE_PROSPECTION_URL}/campagnes/{campagne_id}/executer",
                             headers=entetes)
        corps = r.json()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"veille-prospection injoignable ({VEILLE_PROSPECTION_URL}) : {str(e)[:150]}")
    if r.status_code == 404:
        raise HTTPException(404, "Campagne introuvable ou inactive.")
    if r.status_code >= 400:
        detail = corps.get("detail") if isinstance(corps, dict) else None
        raise HTTPException(r.status_code, detail or f"veille-prospection a refusé la requête ({r.status_code}).")
    return corps


@app.get("/prospection/zones", tags=["prospection"])
async def lister_zones_prospection(x_user_id: Optional[str] = Header(None),
                                   x_api_key: Optional[str] = Header(None)):
    """Peuple le sélecteur de zone du formulaire de création de campagne — proxy vers
    `geo GET /zones` (jamais dupliqué, geo reste la seule source de vérité des zones)."""
    entetes = _entetes_aval(x_user_id, x_api_key)
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"{GEO_URL}/zones", headers=entetes)
        corps = r.json()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"geo injoignable ({GEO_URL}) : {str(e)[:150]}")
    if r.status_code >= 400:
        detail = corps.get("detail") if isinstance(corps, dict) else None
        raise HTTPException(r.status_code, detail or f"geo a refusé la requête ({r.status_code}).")
    return corps


async def _get_json_ou_erreur(url: str, service: str, entetes: dict | None = None) -> dict | list:
    """Petit helper local aux routes `/prospection/*` qui chaînent 2 appels amont — les
    routes `/veille/*` existantes n'en ont pas besoin (un seul appel chacune)."""
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(url, headers=entetes or {})
        corps = r.json()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"{service} injoignable ({url}) : {str(e)[:150]}")
    if r.status_code >= 400:
        detail = corps.get("detail") if isinstance(corps, dict) else None
        raise HTTPException(r.status_code, detail or f"{service} a refusé la requête ({r.status_code}).")
    return corps


@app.get("/prospection/prospects", tags=["prospection"])
async def prospects_campagne(campagne_id: int, x_user_id: Optional[str] = Header(None),
                             x_api_key: Optional[str] = Header(None)):
    """Prospects CRM rattachables à cette campagne — filtrés par le tag `"Zone : <nom>"`
    posé dans les notes à l'export (cf. veille-prospection orchestration.py, Task 2).
    Limite ASSUMÉE (spec 2026-08-19) : un filtrage texte, pas une vraie clé étrangère —
    si `zone_nom` est `None` (jamais résolu à la création), on renvoie une liste VIDE
    plutôt que tout le CRM (mieux vaut rien qu'une vue trompeuse)."""
    entetes = _entetes_aval(x_user_id, x_api_key)
    campagnes = await _get_json_ou_erreur(f"{VEILLE_PROSPECTION_URL}/campagnes",
                                          "veille-prospection", entetes)
    campagne = next((c for c in campagnes if c.get("id") == campagne_id), None)
    if campagne is None:
        raise HTTPException(404, "Campagne introuvable.")
    zone_nom = campagne.get("zone_nom")
    if not zone_nom:
        return {"campagne_id": campagne_id, "zone_nom": None, "prospects": []}
    crm = await _get_json_ou_erreur(f"{FORGE_URL}/crm", "forge", entetes)
    tag = f"Zone : {zone_nom}"
    prospects = [p for p in crm.get("prospects", []) if tag in (p.get("notes") or "")]
    return {"campagne_id": campagne_id, "zone_nom": zone_nom, "prospects": prospects}


@app.post("/prospection/demarchage", tags=["prospection"], status_code=201)
async def preparer_demarchage(body: PreparerDemarchage, x_user_id: Optional[str] = Header(None),
                              x_api_key: Optional[str] = Header(None)):
    """Prépare des brouillons de démarchage (mail, jamais envoyés) pour la sélection de
    prospects d'UNE campagne. Les infos (nom/entreprise/email/ville) sont re-dérivées ICI
    depuis le CRM — jamais celles envoyées par le navigateur — pour que la campagne et le
    tag de zone restent la source de vérité, pas une saisie cliente."""
    entetes = _entetes_aval(x_user_id, x_api_key)
    campagnes = await _get_json_ou_erreur(f"{VEILLE_PROSPECTION_URL}/campagnes",
                                          "veille-prospection", entetes)
    campagne = next((c for c in campagnes if c.get("id") == body.campagne_id), None)
    if campagne is None:
        raise HTTPException(404, "Campagne introuvable.")
    zone_nom = campagne.get("zone_nom")
    leads_par_id: dict = {}
    if zone_nom:
        crm = await _get_json_ou_erreur(f"{FORGE_URL}/crm", "forge", entetes)
        tag = f"Zone : {zone_nom}"
        leads_par_id = {p["id"]: p for p in crm.get("prospects", [])
                        if tag in (p.get("notes") or "")}
    prospects = [
        {"nom": leads_par_id[pid].get("nom"), "entreprise": leads_par_id[pid].get("entreprise"),
         "email": leads_par_id[pid].get("email"),
         "ville": _ville_depuis_notes(leads_par_id[pid].get("notes"))}
        for pid in body.prospect_ids if pid in leads_par_id
    ]
    if not prospects:
        raise HTTPException(422, "Aucun des prospects sélectionnés n'appartient à cette campagne.")
    corps_aval = {"prospects": prospects, "sujet": body.sujet, "message": body.message,
                 "expediteur": body.expediteur, "compte": body.compte}
    try:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(f"{MAIL_URL}/demarchage/preparer", json=corps_aval, headers=entetes)
        corps = r.json()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"mail injoignable ({MAIL_URL}) : {str(e)[:150]}")
    if r.status_code >= 400:
        detail = corps.get("detail") if isinstance(corps, dict) else None
        raise HTTPException(r.status_code, detail or f"mail a refusé la requête ({r.status_code}).")
    return JSONResponse(content=corps, status_code=r.status_code)

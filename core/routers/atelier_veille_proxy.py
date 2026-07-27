"""Proxy « atelier-veille » du Cœur : vue native de la tuile Atelier Veille, isolée PAR
PERSONNE.

Même motif que core/routers/studio_proxy.py et atelier_images_video_proxy.py, avec une
nuance : le frontend autoporté (`briques/atelier-veille/front.html`) proxifie lui-même vers
`veille-info` (pass-through pur, cf. `briques/atelier-veille/main.py::_entetes_aval`) — donc
l'identité qu'on injecte ICI doit être celle attendue par `veille-info` (X-User-Id +
VEILLE_INFO_KEY), PAS une clé « ATELIER_VEILLE_KEY » qui n'existe pas (atelier-veille est un
service ouvert, sans authentification propre). Sans ce détour, la session web retombait sur
le tenant anonyme `public` côté veille-info (aucune en-tête d'identité à relayer), trou
identique à S183/S190 jamais porté sur cette brique.

`/config` (URL publique de la carte geo) dérive normalement l'hôte de la requête COURANTE :
une fois proxifiée, cette requête vient du Cœur lui-même (httpx serveur→serveur), donc son
`Host` vaudrait l'hôte interne du conteneur — on forwarde `X-Forwarded-Host`/
`X-Forwarded-Proto` (motif déjà utilisé par `core/routers/dashboard.py::u()`) pour que
`briques/atelier-veille/main.py::config` reconstruise la bonne URL.

Sécurité : toute en-tête d'identité envoyée par le navigateur (X-API-Key, X-User-Id,
Authorization) est ignorée — seule l'identité de la session Cœur (cookie, `exiger_session` +
`lire_contexte_tenant` posés sur ce router dans `main.py`) compte.
"""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

import orchestrateur
import outils_communs
from etat import registre

router = APIRouter()

_PREFIXE = "/atelier-veille-app"
_TIMEOUT = 60.0

# Deux routes d'atelier-veille déclenchent un travail LONG côté veille-info (synthèse LLM du
# digest, synthèse vocale de l'audio global) : elles dépassent couramment 60 s. Sans ce palier,
# le Cœur coupait la connexion en `httpx.ReadTimeout` → 500 rendu à l'utilisateur ALORS QUE le
# travail aboutissait côté brique (constaté en prod : 500 dans les logs du Cœur, 200 OK dans
# ceux de veille-info pour le même appel). Aligné sur le timeout de `briques/atelier-veille`.
_TIMEOUT_LONG = 300.0
_CHEMINS_LENTS = ("veille/digest/executer", "veille/audio-global/generer")


def _timeout_pour(chemin: str) -> float:
    return _TIMEOUT_LONG if chemin.strip("/") in _CHEMINS_LENTS else _TIMEOUT


def _base() -> str:
    return orchestrateur._brique_base(registre, "atelier-veille")


def _entetes(request: Request) -> dict:
    entetes = dict(outils_communs._entetes_brique("veille-info"))
    entetes["X-Forwarded-Host"] = request.headers.get("host", "")
    entetes["X-Forwarded-Proto"] = request.headers.get("x-forwarded-proto") or request.url.scheme
    type_contenu = request.headers.get("content-type")
    if type_contenu:
        entetes["Content-Type"] = type_contenu
    return entetes


async def _page(chemin_brique: str, request: Request) -> HTMLResponse:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.get(f"{_base()}{chemin_brique}", headers=_entetes(request))
    page = (r.text
            .replace('href="/workplace.css"', f'href="{_PREFIXE}/workplace.css"')
            .replace("</head>", f"<script>window.ATELIER_VEILLE_API_BASE='{_PREFIXE}';</script></head>"))
    return HTMLResponse(page, status_code=r.status_code)


@router.get(_PREFIXE + "/", response_class=HTMLResponse)
async def atelier_veille_app_racine(request: Request):
    return await _page("/", request)


@router.get(_PREFIXE + "/atelier", response_class=HTMLResponse)
async def atelier_veille_app_atelier(request: Request):
    return await _page("/atelier", request)


@router.api_route(_PREFIXE + "/{chemin:path}", methods=["GET", "POST", "DELETE", "PATCH", "PUT"])
async def atelier_veille_app_proxy(chemin: str, request: Request):
    """Proxy générique du reste des routes (API `/veille/*`, `/config`, `/workplace.css`)."""
    corps = await request.body()
    async with httpx.AsyncClient(timeout=_timeout_pour(chemin)) as client:
        r = await client.request(
            request.method, f"{_base()}/{chemin}",
            params=request.query_params, headers=_entetes(request),
            content=corps or None,
        )
    return Response(content=r.content, status_code=r.status_code,
                    media_type=r.headers.get("content-type"))

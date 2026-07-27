"""Proxy « studio » du Cœur (S187) : vue native de la tuile Créations, isolée PAR PERSONNE.

Le frontend autoporté de la brique studio (`briques/studio/front.html`) fait ses appels via
une fonction JS unique `api(path, method, body)`, préfixée d'une variable `STUDIO_API_BASE`
posée côté page (vide en usage autoporté). On sert cette MÊME page sous `/studio-app/*` avec
`STUDIO_API_BASE` posé à ce préfixe, et on proxy chaque appel vers la vraie brique en y
injectant l'identité de la SESSION Cœur courante (`outils_communs._entetes_brique("studio")`
→ X-User-Id, motif agenda S182 / mail S185 / memoire S186) — au lieu de laisser le navigateur
appeler la brique en direct avec une STUDIO_KEY statique partagée par tout le foyer (trou S183).

Sécurité : toute en-tête d'identité envoyée par le navigateur (X-API-Key, X-User-Id,
Authorization) est ignorée — seule l'identité de la session Cœur (cookie, `exiger_session` +
`lire_contexte_tenant` posés sur ce router dans `main.py`) compte, pour qu'un onglet ne
puisse pas usurper un autre utilisateur en trafiquant sa requête.
"""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

import orchestrateur
import outils_communs
from etat import registre

router = APIRouter()

_PREFIXE = "/studio-app"
_TIMEOUT = outils_communs.TIMEOUT_PROXY_COURT

# Routes de PRODUCTION du studio : elles font tourner un rendu (image, vidéo, synthèse
# vocale) et la brique s'accorde bien plus que 60 s pour les mener à bien —
# `briques/studio/studio.py::_appeler_video` attend jusqu'à 600 s. Un `_TIMEOUT` unique de
# 60 s côté Cœur coupait donc AVANT la brique et rendait un 500 alors que le rendu
# aboutissait : exactement le 500 fantôme du digest de veille. Valeurs recopiées de la
# brique, pas inventées ici.
_ROUTES_LENTES = (
    ("/animer", 600.0),      # studio.py::_appeler_video  (timeout=600)
    ("/teaser", 600.0),      # idem
    ("/portrait", 200.0),    # studio.py::_appeler_images (timeout=200)
    ("/couverture", 200.0),  # idem
    ("/audio", 180.0),       # main.py:1021, rendu voix   (timeout=180)
)


def _timeout_pour(chemin: str) -> float:
    return outils_communs.timeout_proxy(chemin, _ROUTES_LENTES)


def _base() -> str:
    return orchestrateur._brique_base(registre, "studio")


def _entetes(request: Request) -> dict:
    entetes = dict(outils_communs._entetes_brique("studio"))
    type_contenu = request.headers.get("content-type")
    if type_contenu:
        entetes["Content-Type"] = type_contenu
    return entetes


async def _page(chemin_brique: str, request: Request) -> HTMLResponse:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.get(f"{_base()}{chemin_brique}", headers=_entetes(request))
    page = (r.text
            .replace('src="/manipulation_directe.js"', f'src="{_PREFIXE}/manipulation_directe.js"')
            .replace("</head>", f"<script>window.STUDIO_API_BASE='{_PREFIXE}';</script></head>"))
    return HTMLResponse(page, status_code=r.status_code)


@router.get(_PREFIXE + "/", response_class=HTMLResponse)
async def studio_app_racine(request: Request):
    return await _page("/", request)


@router.get(_PREFIXE + "/atelier", response_class=HTMLResponse)
async def studio_app_atelier(request: Request):
    return await _page("/atelier", request)


@router.api_route(_PREFIXE + "/{chemin:path}", methods=["GET", "POST", "DELETE", "PATCH", "PUT"])
async def studio_app_proxy(chemin: str, request: Request):
    """Proxy générique du reste des routes studio (API + `/manipulation_directe.js` +
    `/workplace.css`)."""
    corps = await request.body()
    async with httpx.AsyncClient(timeout=_timeout_pour(chemin)) as client:
        r = await client.request(
            request.method, f"{_base()}/{chemin}",
            params=request.query_params, headers=_entetes(request),
            content=corps or None,
        )
    return Response(content=r.content, status_code=r.status_code,
                    media_type=r.headers.get("content-type"))

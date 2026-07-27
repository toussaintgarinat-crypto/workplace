"""Proxy « atelier-images-video » du Cœur : vue native du front de l'atelier créatif.

Même motif que core/routers/studio_proxy.py : le frontend autoporté de la brique
`briques/atelier-images-video` (`front.html`) fait ses appels via `API_BASE + path`, où
`API_BASE` vaut `window.ATELIER_IV_API_BASE` (vide en usage autoporté). On sert cette MÊME
page sous `/atelier-images-video-app/*` avec `ATELIER_IV_API_BASE` posé à ce préfixe, et on
proxy chaque appel vers la vraie brique en y injectant l'identité de la SESSION Cœur
courante (`outils_communs._entetes_brique("atelier-images-video")` → X-User-Id +
X-API-Key: ATELIER_IMAGES_VIDEO_KEY).

Sécurité : toute en-tête d'identité envoyée par le navigateur (X-API-Key, X-User-Id,
Authorization) est ignorée — seule l'identité de la session Cœur (cookie, `exiger_session`
+ `lire_contexte_tenant` posés sur ce router dans `main.py`) compte. Sans ce garde-fou, un
appel direct sur le port 6160 pourrait forger X-User-Id et emprunter STUDIO_KEY/MEMOIRE_KEY
(que la brique atelier-images-video détient) pour usurper une autre personne sur les
synergies Studio ou la galerie — même trou que S183, un cran plus loin dans la chaîne de
composition (cf. briques/atelier-images-video/main.py::_identite_service).
"""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

import orchestrateur
import outils_communs
from etat import registre

router = APIRouter()

_PREFIXE = "/atelier-images-video-app"
_TIMEOUT = outils_communs.TIMEOUT_PROXY_COURT

# Génération et synergies Studio : un rendu d'image ou de vidéo dépasse couramment la minute
# (les fournisseurs de `briques/video` pollent jusqu'à 120 s + attente, et le studio leur
# accorde 200/600 s). Voir `outils_communs.timeout_proxy` pour la règle. Valeurs alignées sur
# `briques/atelier-images-video/main.py::_relayer`, relevé en même temps que ce proxy — les
# deux couches plafonnaient à 60 s, donc relever la seule ici n'aurait rien changé.
_ROUTES_LENTES = (
    ("/video/generer", 600.0),
    ("/animer", 600.0),
    ("/teaser", 600.0),
    ("/images/generer", 200.0),
    ("/portrait", 200.0),
    ("/couverture", 200.0),
)


def _timeout_pour(chemin: str) -> float:
    return outils_communs.timeout_proxy(chemin, _ROUTES_LENTES)


def _base() -> str:
    return orchestrateur._brique_base(registre, "atelier-images-video")


def _entetes(request: Request) -> dict:
    entetes = dict(outils_communs._entetes_brique("atelier-images-video"))
    type_contenu = request.headers.get("content-type")
    if type_contenu:
        entetes["Content-Type"] = type_contenu
    return entetes


async def _page(chemin_brique: str, request: Request) -> HTMLResponse:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.get(f"{_base()}{chemin_brique}", headers=_entetes(request))
    page = r.text.replace(
        "</head>", f"<script>window.ATELIER_IV_API_BASE='{_PREFIXE}';</script></head>")
    return HTMLResponse(page, status_code=r.status_code)


@router.get(_PREFIXE + "/", response_class=HTMLResponse)
async def atelier_iv_racine(request: Request):
    return await _page("/", request)


@router.get(_PREFIXE + "/atelier", response_class=HTMLResponse)
async def atelier_iv_atelier(request: Request):
    return await _page("/atelier", request)


@router.api_route(_PREFIXE + "/{chemin:path}", methods=["GET", "POST", "DELETE", "PATCH", "PUT"])
async def atelier_iv_proxy(chemin: str, request: Request):
    """Proxy générique du reste des routes (API + `/workplace.css`)."""
    corps = await request.body()
    async with httpx.AsyncClient(timeout=_timeout_pour(chemin)) as client:
        r = await client.request(
            request.method, f"{_base()}/{chemin}",
            params=request.query_params, headers=_entetes(request),
            content=corps or None,
        )
    return Response(content=r.content, status_code=r.status_code,
                    media_type=r.headers.get("content-type"))

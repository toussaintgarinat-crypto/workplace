"""Proxy « mail » du Cœur (S185) : vue native de l'onglet Mail, isolée PAR PERSONNE.

Le frontend autoporté de la brique mail (`briques/mail/main.py::_PAGE`) fait ses appels
fetch() en chemin absolu, préfixé d'une variable `MAIL_API_BASE` posée côté page (vide en
usage autoporté). On sert cette MÊME page sous `/mail-app/*` avec `MAIL_API_BASE` posé à ce
préfixe, et on proxy chaque appel vers la vraie brique en y injectant l'identité de la
SESSION Cœur courante (`outils_communs._entetes_brique("mail")` → X-User-Id, motif agenda
S182 / ecoute S184) — au lieu de laisser le navigateur appeler la brique en direct, ce qui
retomberait sur le tenant « public » partagé par tout le foyer (trou S183).

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

_PREFIXE = "/mail-app"
_TIMEOUT = 30.0


def _base() -> str:
    return orchestrateur._brique_base(registre, "mail")


def _entetes(request: Request) -> dict:
    entetes = dict(outils_communs._entetes_brique("mail"))
    type_contenu = request.headers.get("content-type")
    if type_contenu:
        entetes["Content-Type"] = type_contenu
    return entetes


@router.get(_PREFIXE + "/", response_class=HTMLResponse)
async def mail_app_racine(request: Request):
    """Page mail, avec `MAIL_API_BASE` posé pour que TOUS ses appels passent par ce proxy."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.get(f"{_base()}/", headers=_entetes(request))
    page = (r.text
            .replace('src="/static/purify.min.js"', f'src="{_PREFIXE}/static/purify.min.js"')
            .replace("</head>", f"<script>window.MAIL_API_BASE='{_PREFIXE}';</script></head>"))
    return HTMLResponse(page, status_code=r.status_code)


@router.api_route(_PREFIXE + "/{chemin:path}", methods=["GET", "POST", "DELETE", "PATCH", "PUT"])
async def mail_app_proxy(chemin: str, request: Request):
    """Proxy générique du reste des routes mail (API + `/static/purify.min.js`)."""
    corps = await request.body()
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.request(
            request.method, f"{_base()}/{chemin}",
            params=request.query_params, headers=_entetes(request),
            content=corps or None,
        )
    return Response(content=r.content, status_code=r.status_code,
                    media_type=r.headers.get("content-type"))

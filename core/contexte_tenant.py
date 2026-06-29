"""Contexte de tenant par requête — prépa multi-tenant (S121).

Le Cœur est historiquement mono-utilisateur (« perso » codé en dur). Pour préparer le
multi-tenant [[roadmap-deploiement-multiutilisateur]], on porte l'identité de l'appelant
le long d'un tour de requête **sans changer la signature des fonctions** : trois
``contextvars`` (utilisateur, organisation, token JWT) posés à l'entrée par une
dépendance FastAPI et lus par les clients S2S au moment de l'appel sortant.

Motif repris verbatim de l'adaptateur Forge (``briques/forge/main.py`` :
``_JETON_UTILISATEUR`` + middleware ``_capter_jeton_utilisateur``) — ContextVar par
requête, reset en ``finally``, aucune signature de route à modifier.

Rétrocompatible par construction : sans en-tête, l'utilisateur retombe sur ``"perso"``
(comportement actuel de ``core/agenda.py``) et l'organisation sur ``"defaut"`` côté
``donnees`` — l'instance de dev ouverte et les bundles existants ne changent pas.

Granularité (décision S121) : ``donnees`` est scopé par **organisation**
(``X-Org-ID`` / claim ``org_id``), ``agenda`` par **utilisateur** (``X-User-Id``).
"""
from __future__ import annotations

import contextvars
from typing import NamedTuple, Optional

from fastapi import Header, Request

# Valeur par défaut de l'utilisateur quand aucune identité n'est fournie. Aligne le
# comportement historique de core/agenda.py (USER_ID = "perso").
UTILISATEUR_DEFAUT = "perso"
# Tenant de repli côté donnees (les lignes pré-S121 y sont rétro-remplies).
ORG_DEFAUT = "defaut"

_utilisateur: contextvars.ContextVar[str] = contextvars.ContextVar(
    "tenant_utilisateur", default=UTILISATEUR_DEFAUT
)
_org_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "tenant_org_id", default=None
)
_user_token: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "tenant_user_token", default=None
)


class Contexte(NamedTuple):
    utilisateur: str
    org_id: Optional[str]
    user_token: Optional[str]


def contexte_actuel() -> Contexte:
    """Instantané du contexte du tour de requête courant."""
    return Contexte(_utilisateur.get(), _org_id.get(), _user_token.get())


class _Jetons(NamedTuple):
    utilisateur: object
    org_id: object
    user_token: object


def definir_contexte(
    *,
    utilisateur: Optional[str] = None,
    org_id: Optional[str] = None,
    user_token: Optional[str] = None,
) -> _Jetons:
    """Pose les valeurs fournies (les ``None`` laissent la valeur courante intacte).

    Renvoie des jetons de reset à passer à :func:`reinitialiser` — utile en test et
    pour la symétrie ``set``/``reset`` du middleware. Une chaîne vide est ignorée
    (en-tête présent mais vide ⇒ on garde le défaut).
    """
    ju = _utilisateur.set(utilisateur) if utilisateur else _utilisateur.set(_utilisateur.get())
    jo = _org_id.set(org_id) if org_id else _org_id.set(_org_id.get())
    jt = _user_token.set(user_token) if user_token else _user_token.set(_user_token.get())
    return _Jetons(ju, jo, jt)


def reinitialiser(jetons: _Jetons) -> None:
    """Restaure le contexte d'avant :func:`definir_contexte` (reset des ContextVars)."""
    _utilisateur.reset(jetons.utilisateur)
    _org_id.reset(jetons.org_id)
    _user_token.reset(jetons.user_token)


# ── En-têtes sortants S2S ────────────────────────────────────────────────────────

def entetes_agenda() -> dict:
    """Identité pour la brique agenda : ``X-User-Id`` (scope par utilisateur)."""
    return {"X-User-Id": _utilisateur.get() or UTILISATEUR_DEFAUT}


def entetes_donnees() -> dict:
    """Tenant pour la brique donnees : ``X-Org-ID`` (scope par organisation)."""
    return {"X-Org-ID": _org_id.get() or ORG_DEFAUT}


def entetes_forge() -> dict:
    """Token utilisateur pour l'adaptateur Forge, s'il y en a un (sinon dict vide :
    l'adaptateur retombe sur son token de service, flux S17/S24 inchangé)."""
    token = _user_token.get()
    return {"X-Forge-User-Token": f"Bearer {token}"} if token else {}


# ── Capture entrante (dépendance FastAPI) ────────────────────────────────────────

def _token_depuis_request(request: Request) -> Optional[str]:
    """Extrait le JWT utilisateur : en-tête dédié ``X-User-Token`` (préféré, pour ne
    pas confondre avec l'``Authorization`` du Cœur lui-même), sinon ``Authorization:
    Bearer``. Tolère le préfixe ``Bearer``."""
    brut = request.headers.get("X-User-Token") or request.headers.get("Authorization") or ""
    brut = brut.strip()
    if brut.lower().startswith("bearer "):
        brut = brut.split(" ", 1)[1].strip()
    return brut or None


async def lire_contexte_tenant(
    request: Request,
    x_org_id: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None),
) -> None:
    """Dépendance posée sur les routers déclenchant des appels S2S : lit l'identité de
    la requête entrante et la dépose dans le contexte du tour.

    Sources, par priorité : en-têtes ``X-User-Id`` / ``X-Org-ID`` / ``X-User-Token``.
    Absentes ⇒ défauts (perso / defaut / pas de token) ⇒ comportement mono-user actuel.
    Le champ ``utilisateur`` du corps du chat (S78) reste géré par le routeur assistant
    qui appelle :func:`definir_contexte` lui-même.
    """
    definir_contexte(
        utilisateur=x_user_id,
        org_id=x_org_id,
        user_token=_token_depuis_request(request),
    )
    # Pas de reset ici : la dépendance vit le temps de la requête, et chaque requête
    # s'exécute dans son propre contexte copié (Starlette) — les défauts reviennent
    # naturellement au tour suivant.

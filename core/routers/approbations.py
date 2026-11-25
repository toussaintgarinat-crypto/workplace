"""Routes d'approbation (S245). Deux publics, deux garde-fous :

- la brique `connexion` (relais Telegram) : clé partagée `X-Approbations-Cle`, comparée en temps
  constant, FAIL CLOSED (clé non configurée => 503, mauvaise clé => 401) ;
- le tableau de bord (liste, affichage du code destructif) : session obligatoire.

Modèle de confiance : les routes `decision`, `code/armer` et `code` font CONFIANCE au champ `par`
envoyé par la brique `connexion`. C'est la brique — pas le Cœur — qui vérifie que l'expéditeur
Telegram est un approbateur autorisé ; le Cœur ne voit que la clé partagée.

Le `code` d'un destructif n'apparaît QUE dans `GET /approbations/en_attente` (session). Aucune
réponse des routes à clé ne le contient, et il n'est jamais transmis au canal de notification.

`/approbations/relancer` est appelé par l'horloge S29, qui ne sait poser qu'un en-tête
`Authorization: Bearer <variable d'env>` (`entete_token_env` du manifest ; le secret ne figure
jamais dans le manifest). La clé est donc acceptée soit en `X-Approbations-Cle`, soit en Bearer.
"""
from __future__ import annotations

import hmac
import logging
import os
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Path
from pydantic import BaseModel

import approbations
import approbations_canal
import auth
from etat import registre

log = logging.getLogger(__name__)

router = APIRouter(prefix="/approbations", tags=["approbations"])

_ID_RE = r"^[0-9a-f]{32}$"


def _verifier_cle(fournie: str | None) -> None:
    attendue = os.getenv("APPROBATIONS_CLE", "")
    if not attendue:
        raise HTTPException(503, "Approbations par Telegram non configurées (APPROBATIONS_CLE).")
    if not hmac.compare_digest((fournie or "").encode(), attendue.encode()):
        raise HTTPException(401, "Clé d'approbation invalide.")


def exiger_cle(x_approbations_cle: str | None = Header(None)) -> None:
    _verifier_cle(x_approbations_cle)


def _sans_code(demande: dict) -> dict:
    """Copie destinée au canal : le code destructif ne quitte jamais l'application."""
    return {k: v for k, v in demande.items() if k != "code"}


class Decision(BaseModel):
    decision: Literal["ok", "ko"]
    par: str
    canal: str = "telegram"


class Armer(BaseModel):
    par: str


class Saisie(BaseModel):
    par: str
    code: str


async def _canal_sans_echec(fonction, id_: str, *args, **kw) -> None:
    """Appel au canal en best-effort : la décision est déjà enregistrée, une panne de la brique
    `connexion` ne doit pas faire échouer la route. Journalise l'id tronqué, jamais le code."""
    try:
        await fonction(registre, *args, **kw)
    except Exception as e:  # noqa: BLE001
        log.warning("approbation %s : canal indisponible (%s)", str(id_)[:8], type(e).__name__)


def _entier_env(nom: str, defaut: int) -> int:
    try:
        return int(os.getenv(nom, str(defaut)))
    except (TypeError, ValueError):
        log.warning("%s invalide, repli sur %s", nom, defaut)
        return defaut


async def _maj(id_: str) -> dict | None:
    lue = approbations.lire(id_)
    if lue:
        await _canal_sans_echec(approbations_canal.mettre_a_jour, id_, _sans_code(lue))
    return lue


@router.post("/{id_}/decision", dependencies=[Depends(exiger_cle)])
async def decision(body: Decision, id_: str = Path(pattern=_ID_RE)):
    agir = approbations.approuver if body.decision == "ok" else approbations.refuser
    ok, raison = agir(id_, body.par, body.canal)
    lue = await _maj(id_)
    return {"ok": ok, "raison": raison, "statut": lue and lue["statut"],
            "sensibilite": lue and lue["sensibilite"]}


@router.post("/{id_}/code/armer", dependencies=[Depends(exiger_cle)])
async def armer(body: Armer, id_: str = Path(pattern=_ID_RE)):
    ok, raison = approbations.armer_saisie_code(id_, body.par)
    return {"ok": ok, "raison": raison}


@router.post("/code", dependencies=[Depends(exiger_cle)])
async def code(body: Saisie):
    r = approbations.valider_code_saisi(body.par, body.code)
    if r is None:
        return {"pris_en_charge": False}
    await _maj(r["approbation_id"])
    return {"pris_en_charge": True, **r}


@router.get("/en_attente", dependencies=[Depends(auth.exiger_session_api)])
async def en_attente():
    """Demandes ouvertes. Le `code` d'un destructif n'est exposé QU'ICI (session obligatoire) :
    c'est le canal distinct de Telegram qui fait sa valeur."""
    return {"approbations": approbations.en_attente()}


@router.post("/relancer")
async def relancer(x_approbations_cle: str | None = Header(None),
                   authorization: str | None = Header(None)):
    """Mode attente : expire les périmées, relance les anciennes. Appelé par l'horloge S29
    (tâche `approbations-relance` du manifest noyau) avec la clé en Bearer ou en X-Approbations-Cle."""
    fournie = x_approbations_cle
    if not fournie and authorization and authorization.lower().startswith("bearer "):
        fournie = authorization[7:].strip()
    _verifier_cle(fournie)
    delai = _entier_env("APPROBATION_RELANCE_MIN", 60) * 60
    maxi = _entier_env("APPROBATION_RELANCE_MAX", 3)
    perimees = approbations.expirer_perimees()
    for id_ in perimees:
        await _maj(id_)
    relancees = []
    for d in approbations.a_relancer(delai, maxi):
        approbations.marquer_relancee(d["id"])  # réclamer d'abord, notifier ensuite
        await _canal_sans_echec(approbations_canal.notifier, d["id"], _sans_code(d), relance=True)
        relancees.append(d["id"])
    return {"expirees": perimees, "relancees": relancees}

"""
Router Application Service Matrix.

Synapse appelle ces endpoints pour notifier FastAPI des événements Matrix
et pour vérifier l'existence de users/rooms gérés par l'AS.

Ces routes sont montées SANS préfixe /api (protocole Matrix AS).
"""

import logging
from typing import Optional
from fastapi import APIRouter, Header, HTTPException, Request

from config import config

logger = logging.getLogger(__name__)

router = APIRouter()


def _verifier_token(authorization: Optional[str]):
    """Vérifie que la requête vient bien de Synapse."""
    if not authorization or authorization != f"Bearer {config.MATRIX_HS_TOKEN}":
        raise HTTPException(status_code=403, detail="Token HS invalide")


@router.put("/_matrix/app/v1/transactions/{txn_id}")
async def transaction(txn_id: str, request: Request, authorization: str = Header(None)):
    """
    Synapse envoie ici les événements Matrix en batch.
    Pour l'instant on accuse réception sans traitement côté FastAPI
    (le frontend écoute directement via matrix-js-sdk).
    """
    _verifier_token(authorization)
    body = await request.json()
    events = body.get("events", [])
    logger.debug(f"Transaction AS {txn_id} : {len(events)} événement(s)")
    return {}


@router.get("/_matrix/app/v1/users/{user_id}")
async def lookup_user(user_id: str, authorization: str = Header(None)):
    """
    Synapse demande si un user géré par l'AS existe.
    On répond 200 pour tous les users @oria_*:oria.local.
    """
    _verifier_token(authorization)
    if user_id.startswith("@oria_"):
        return {}
    raise HTTPException(status_code=404, detail="Utilisateur inconnu")


@router.get("/_matrix/app/v1/rooms/{room_alias}")
async def lookup_room(room_alias: str, authorization: str = Header(None)):
    """
    Synapse demande si un alias de room géré par l'AS existe.
    On répond 200 pour tous les alias #oria_*:oria.local.
    """
    _verifier_token(authorization)
    if room_alias.startswith("#oria_"):
        return {}
    raise HTTPException(status_code=404, detail="Room inconnue")

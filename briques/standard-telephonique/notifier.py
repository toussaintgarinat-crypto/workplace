"""Notification Telegram best-effort via briques/connexion (/pousser).

Motif copié de core/proactif.py::_pousser_messagerie et briques/geo/main.py::_pousser_connexion
(déjà établis dans le monorepo) : le pont /pousser résout LUI-MÊME les canaux liés de
l'utilisateur — best-effort, ne lève jamais."""
import logging
import os

import httpx

logger = logging.getLogger("standard-telephonique.notifier")


def _client() -> httpx.AsyncClient:
    base = os.getenv("CONNEXION_URL", "http://host.docker.internal:5870").rstrip("/")
    return httpx.AsyncClient(base_url=base, timeout=10)


async def notifier(texte: str) -> None:
    """Pousse `texte` vers les messageries liées de l'utilisateur. Ne lève jamais."""
    entetes = {}
    cle = os.getenv("CONNEXION_KEY", "")
    if cle:
        entetes["X-API-Key"] = cle
    utilisateur = os.getenv("STANDARD_TEL_NOTIF_UTILISATEUR", "perso")
    try:
        async with _client() as client:
            await client.post("/pousser", json={"utilisateur": utilisateur, "texte": texte},
                              headers=entetes)
    except Exception as ex:  # noqa: BLE001
        logger.warning("Notification standard-telephonique : %s", ex)

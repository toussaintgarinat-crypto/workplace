"""Envoi de l'audio global par email via la brique Mail (S199). Motif d'appel identique à
digest.py::_pousser_memoire (S193) : `user_id` est le tenant interne (`f"perso:{x}"`), on
retire le préfixe avant de le transmettre en X-User-Id à Mail, qui recompose le même
tenant `perso:{x}` de son côté via son propre dialecte Cœur (`tenant_actuel`)."""
from __future__ import annotations

import os

import httpx

MAIL_URL = os.getenv("MAIL_URL", "http://host.docker.internal:6030")
MAIL_KEY = os.getenv("MAIL_KEY", "")


class EnvoiAudioGlobalError(Exception):
    """Échec d'un envoi (réseau, brouillon non composé, envoi refusé)."""


def envoyer(user_id: str, destinataire: str, lien: str, sujet: str | None,
           message: str | None) -> None:
    identite = user_id.removeprefix("perso:")
    entetes = {"X-User-Id": identite}
    if MAIL_KEY:
        entetes["X-API-Key"] = MAIL_KEY
    corps_dicte = (message or "Voici la veille audio du jour.") + f"\n\nÉcouter : {lien}"
    try:
        r = httpx.post(f"{MAIL_URL}/mail/composer",
                       json={"a": destinataire, "dictee": corps_dicte,
                             "sujet": sujet or "Veille audio"},
                       headers=entetes, timeout=30)
        r.raise_for_status()
        brouillon_id = r.json()["brouillon"]["id"]
        r2 = httpx.post(f"{MAIL_URL}/brouillons/{brouillon_id}/envoyer",
                        headers=entetes, timeout=30)
        r2.raise_for_status()
    except (httpx.HTTPError, KeyError, ValueError) as e:
        raise EnvoiAudioGlobalError(f"Envoi mail impossible ({destinataire}) : {e}") from e

"""Identité de l'appelant pour les commandes de mot-clé sur mesure (S184).

Motif copié de l'agenda (S182, `briques/agenda/backend/auth.py` branche S2S) : `ECOUTE_KEY`
est le gage de confiance du Cœur — seul lui la détient et peut donc forwarder l'identité de
l'utilisateur connecté via `X-User-Id`. Sans clé configurée, la brique reste en mode ouvert
(dev/démo, convention du monorepo) : l'identité retombe sur `X-User-Id` si présent, sinon
`"perso"` (repli mono-user historique).
"""
from __future__ import annotations

import os
from typing import Optional

from fastapi import Header, HTTPException


def _presentee(x_api_key: Optional[str], authorization: Optional[str]) -> Optional[str]:
    return x_api_key or (authorization or "").removeprefix("Bearer ").strip() or None


def identite(x_api_key: Optional[str] = Header(None),
             authorization: Optional[str] = Header(None),
             x_user_id: Optional[str] = Header(None)) -> str:
    """Propriétaire courant pour les routes `/commandes*` : isolation par personne."""
    cle_configuree = os.environ.get("ECOUTE_KEY")
    if not cle_configuree:
        return x_user_id or "perso"
    if _presentee(x_api_key, authorization) != cle_configuree:
        raise HTTPException(401, "Clé API manquante ou invalide (header X-API-Key).")
    return x_user_id or "perso"


def service_key(x_api_key: Optional[str] = Header(None),
                authorization: Optional[str] = Header(None)) -> None:
    """Garde `/entrainement/traiter` : credential de service (l'horloge S29), pas une
    identité personne — cette route traite la file pour tout le monde."""
    cle_configuree = os.environ.get("ECOUTE_KEY")
    if not cle_configuree:
        return
    if _presentee(x_api_key, authorization) != cle_configuree:
        raise HTTPException(401, "Clé API manquante ou invalide (header X-API-Key).")

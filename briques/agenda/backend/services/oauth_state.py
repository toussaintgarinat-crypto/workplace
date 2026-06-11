"""State OAuth opaque et signé (anti-CSRF) pour le pont Google (S35).

Le paramètre `state` d'un flux OAuth doit (1) empêcher un attaquant de forger un callback
— attaque **CSRF** — et (2) ne jamais faire confiance à une identité fournie en clair par
le client. L'implémentation initiale (S27) posait `state = user_id` brut : prévisible et
falsifiable. On émet désormais un state **signé (HMAC-SHA256)** portant l'identité + une
expiration courte + un aléa :

  • **infalsifiable** sans le secret serveur → anti-CSRF (un tiers ne peut pas fabriquer
    un state valide) ;
  • **sans stockage serveur** → survit aux redémarrages et au multi-worker (contrairement
    à un nonce gardé en mémoire) ;
  • **à courte durée de vie** (le consentement dure quelques minutes).

Le callback **vérifie** signature + expiration puis lit le `user_id` du payload — il ne
fait plus confiance à un identifiant transmis tel quel.

Le secret de signature vient de `GOOGLE_STATE_SECRET`, ou à défaut est **dérivé** de
`VAULT_SECRET` (déjà requis dès qu'on stocke un token Google) — aucun nouveau secret
obligatoire à provisionner.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time

from config import settings

TTL_DEFAUT = 600  # 10 minutes — large pour le consentement, court pour le rejeu


class StateError(ValueError):
    """State OAuth invalide, falsifié ou expiré."""


def _cle() -> bytes:
    secret = settings.GOOGLE_STATE_SECRET or settings.VAULT_SECRET
    if not secret:
        raise StateError(
            "Aucun secret pour signer le state OAuth (GOOGLE_STATE_SECRET / VAULT_SECRET)")
    # Dérivation étiquetée : ne réutilise pas tel quel la clé du coffre.
    return hashlib.sha256(b"google-oauth-state:" + secret.encode()).digest()


def _b64(donnees: bytes) -> str:
    return base64.urlsafe_b64encode(donnees).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _signer(corps: str) -> str:
    return _b64(hmac.new(_cle(), corps.encode(), hashlib.sha256).digest())


def emettre(user_id: str, *, ttl: int = TTL_DEFAUT, maintenant: float | None = None) -> str:
    """Émet un state signé liant ce flux à `user_id` (expire dans `ttl` s)."""
    if not user_id:
        raise StateError("user_id requis pour émettre un state")
    base = int(maintenant if maintenant is not None else time.time())
    payload = {"uid": user_id, "exp": base + ttl, "n": _b64(os.urandom(9))}
    corps = _b64(json.dumps(payload, separators=(",", ":")).encode())
    return f"{corps}.{_signer(corps)}"


def verifier(state: str, *, maintenant: float | None = None) -> str:
    """Vérifie signature + expiration et renvoie le `user_id`. Lève `StateError` sinon."""
    if not state or "." not in state:
        raise StateError("state malformé")
    corps, signature = state.split(".", 1)
    if not hmac.compare_digest(signature, _signer(corps)):
        raise StateError("signature du state invalide (CSRF ?)")
    try:
        payload = json.loads(_unb64(corps))
    except Exception as exc:  # noqa: BLE001
        raise StateError(f"payload du state illisible : {exc}")
    now = maintenant if maintenant is not None else time.time()
    if now > payload.get("exp", 0):
        raise StateError("state expiré — relance la connexion")
    uid = payload.get("uid")
    if not uid:
        raise StateError("state sans identité")
    return uid

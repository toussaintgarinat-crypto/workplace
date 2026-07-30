"""Jeton signé Cœur→jeu-factions (S217), miroir de briques/memoire/main.py::_verifier_jeton /
_emettre_jeton — vérifie ici (process brique séparé), même secret `JEU_FACTIONS_KEY` que le
module d'émission côté Cœur (`core/jeu_factions_jeton.py`). HMAC, pas de chiffrement :
l'identité n'est pas confidentielle, seule l'INTÉGRITÉ compte — empêche un utilisateur
connecté de fabriquer le jeton d'un autre en modifiant l'URL."""
import hashlib
import hmac
import os
import time
from typing import Optional

COOKIE_NOM = "jeu_factions_utilisateur"


def _secret() -> bytes:
    return (os.environ.get("JEU_FACTIONS_KEY") or "").encode()


def emettre(utilisateur: str, ttl: int) -> str:
    expire = int(time.time()) + ttl
    message = f"{utilisateur}:{expire}"
    signature = hmac.new(_secret(), message.encode(), hashlib.sha256).hexdigest()
    return f"{message}:{signature}"


def verifier(jeton: Optional[str]) -> Optional[str]:
    if not jeton or not _secret():
        return None
    try:
        utilisateur, expire, signature = jeton.rsplit(":", 2)
        expire_i = int(expire)
    except ValueError:
        return None
    message = f"{utilisateur}:{expire}"
    attendue = hmac.new(_secret(), message.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, attendue) or time.time() > expire_i:
        return None
    return utilisateur

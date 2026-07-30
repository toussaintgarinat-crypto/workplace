"""Jeton signé Cœur→jeu-factions (S217) : dit à la brique jeu-factions QUI ouvre la tuile du
dashboard, sans jamais exposer `JEU_FACTIONS_KEY` au navigateur. Miroir exact de
`core/memoire_jeton.py` (S186) — même motif HMAC, même rôle.

HMAC, pas de chiffrement : l'identité (un id d'utilisateur) n'est pas confidentielle, seule
l'INTÉGRITÉ compte — empêche un utilisateur connecté de fabriquer le jeton d'un autre en
modifiant l'URL. Vérification dupliquée côté brique (`briques/jeu-factions/jeton.py`, process
séparé) : seul le secret `JEU_FACTIONS_KEY` est partagé.

Sans `JEU_FACTIONS_KEY` configurée : `emettre` renvoie ``None`` — le dashboard laisse l'URL de
la tuile telle quelle. CONTRAIREMENT à Mémoire, la brique jeu-factions n'a PAS de repli
mono-tenant dans ce cas (spec S217, Non-objectifs) : la tuile devient simplement inutilisable
tant que la clé n'est pas posée.
"""
import hashlib
import hmac
import os
import time

TTL_DEFAUT = 120  # secondes : juste assez pour charger la page, la brique pose ensuite un cookie


def _secret() -> bytes:
    return (os.environ.get("JEU_FACTIONS_KEY") or "").encode()


def emettre(utilisateur: str, ttl: int = TTL_DEFAUT) -> str | None:
    """Jeton `utilisateur:expiration:signature`, ou ``None`` si JEU_FACTIONS_KEY n'est pas posée."""
    secret = _secret()
    if not secret:
        return None
    expire = int(time.time()) + ttl
    message = f"{utilisateur}:{expire}"
    signature = hmac.new(secret, message.encode(), hashlib.sha256).hexdigest()
    return f"{message}:{signature}"

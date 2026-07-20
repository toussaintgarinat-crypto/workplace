"""Jeton signé Cœur→mémoire (S186) : dit à la brique memoire QUI ouvre la tuile Mémoire du
dashboard, sans jamais exposer `MEMOIRE_KEY` au navigateur.

HMAC, pas de chiffrement : l'identité (un id d'utilisateur) n'est pas confidentielle, seule
l'INTÉGRITÉ compte — empêche un utilisateur connecté de fabriquer le jeton d'un autre en
modifiant l'URL. Vérification dupliquée côté brique (`briques/memoire/main.py`, process
séparé) : seul le secret `MEMOIRE_KEY` est partagé, comme AGENDA_KEY/MAIL_KEY/ECOUTE_KEY.

Sans `MEMOIRE_KEY` configurée : `emettre` renvoie ``None`` — le dashboard laisse l'URL de
la tuile telle quelle, la brique retombe sur le compte de service (comportement historique,
mono-tenant), exactement comme les autres briques « cercle privé » sans leur clé posée.
"""
import hashlib
import hmac
import os
import time

TTL_DEFAUT = 120  # secondes : juste assez pour charger la page, la brique pose ensuite un cookie


def _secret() -> bytes:
    return (os.environ.get("MEMOIRE_KEY") or "").encode()


def emettre(utilisateur: str, ttl: int = TTL_DEFAUT) -> str | None:
    """Jeton `utilisateur:expiration:signature`, ou ``None`` si MEMOIRE_KEY n'est pas posée."""
    secret = _secret()
    if not secret:
        return None
    expire = int(time.time()) + ttl
    message = f"{utilisateur}:{expire}"
    signature = hmac.new(secret, message.encode(), hashlib.sha256).hexdigest()
    return f"{message}:{signature}"
